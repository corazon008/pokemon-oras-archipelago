"""Exact-OR native registration/read experiment. No save hook or delivery ledger."""

import hashlib
from pathlib import Path
import secrets
import struct

from oras_archive import capture_stable_archive, tree_digest
from oras_code_research import address_offset
from oras_profiles import sync_directory, write_synced
from oras_save import SAVE_SIZE
from oras_save_lifecycle import require_words
from oras_save_registration import analyze_registration


NAME = "aptest"
FILE_SIZE = 512
PREFIX = b"ORAS-AP-LOAD-TEST\0"
BASE_METADATA = struct.pack("<4I", 0x40000, 1, 1, 1)
TEST_METADATA = struct.pack("<4I", 0x40000, 1, 2, 1)
REG_SITE, REGISTER = 0x108E54, 0x115A84
READ = 0x45DACC
READ_PUSH = 0xE92D4FF8
READ_CALLERS = (0x45D3D4, 0x124D7C)  # First, then second, on the verified boot path.
STATUS_SIZE = 36


def stage_fixture(target: Path):
    """Only a probe-owned copy reaches here. Never native-format any archive."""
    files, metadata, tree = capture_stable_archive(target)
    if set(files) != {"main"} or tree["directories"] or metadata != BASE_METADATA:
        raise ValueError("Sidecar experiment requires the known one-file Encore archive")
    # Random file content cannot be reproduced by the patch or by a zeroed BSS.
    payload = PREFIX + secrets.token_bytes(FILE_SIZE - len(PREFIX))
    write_synced(target.parent / NAME, payload)
    temp = target.parent.with_suffix(".probe-metadata")
    write_synced(temp, TEST_METADATA)
    temp.replace(target.parent.with_suffix(".metadata"))
    sync_directory(target.parent)
    sync_directory(target.parent.parent)
    return payload


def verify_fixture(target, expected):
    files, metadata, tree = capture_stable_archive(target)
    if set(files) != {"main", NAME} or tree["directories"] or metadata != TEST_METADATA:
        raise ValueError("Unexpected sidecar experiment archive layout")
    if len(expected) != FILE_SIZE or not expected.startswith(PREFIX) or files[NAME] != expected:
        raise ValueError("Missing or altered sidecar experiment payload")
    return tree_digest(tree)


class Stub:
    """Small A32 layout helper for fixed instructions and in-range branches."""

    def __init__(self, address):
        self.address = address
        self.words = []
        self.labels = {}
        self.fixups = []

    def label(self, name):
        self.labels[name] = self.address + len(self.words) * 4

    def emit(self, *words):
        self.words.extend(words)

    def branch(self, target, *, link=False, condition=14):
        self.fixups.append((len(self.words), target, link, condition))
        self.emit(0)

    def literal(self, register, target):
        self.fixups.append((len(self.words), target, register, None))
        self.emit(0)

    def finish(self):
        from oras_bootstrap_patch import arm_branch
        for index, target, arg, condition in self.fixups:
            if isinstance(target, str):
                target = self.labels[target]
            pc = self.address + index * 4
            if condition is None:
                offset = target - pc - 8
                if not 0 <= offset <= 4095:
                    raise ValueError("Sidecar literal outside bounded A32 load")
                word = 0xE59F0000 | (arg << 12) | offset
            else:
                word = (arm_branch(pc, target, arg) & 0x0FFFFFFF) | (condition << 28)
            self.words[index] = word
        return struct.pack(f"<{len(self.words)}I", *self.words)


def build_sidecar(info, image, start, owned_page):
    from oras_bootstrap_patch import arm_branch

    analyze_registration(info, image)
    require_words(info, image, READ, [READ_PUSH, 0xE1A04001, 0xE1A05000, 0xE1A06002])
    for site in READ_CALLERS:
        require_words(info, image, site, [arm_branch(site, READ, link=True)])
    require_words(info, image, 0x45D8C4, [0xE5980008, 0xE59D1000, 0xE1500001, 0x059D0004, 0x03500001])
    # BSS layout is independent of native heap/manager layouts.
    manager, block, status, buffer = (owned_page + n for n in (0x20, 0x24, 0x30, 0x200))
    s = Stub(start)
    s.label("register")
    s.emit(0xE92D4070, 0xE1A04000, 0xE1A05001)  # push r4-r6,lr; save controller/main
    s.branch(REGISTER, link=True)
    s.emit(0xE1A06000, 0xE3500001)              # preserve original return; require count 1
    s.branch("register_exit", condition=1)
    s.emit(0xE5940008, 0xE3500002)              # require allocated capacity 2
    s.branch("register_exit", condition=1)
    s.literal(1, "manager_address")
    s.literal(2, "manager_table_address")
    s.emit(0xE5812000)                          # initialize AP manager vptr
    s.literal(3, "block_address")
    s.literal(2, "block_table_address")
    s.emit(0xE5832000, 0xE1A00004)              # AP block vptr; controller argument
    s.literal(2, "filename_address")
    s.branch(REGISTER, link=True)
    s.emit(0xE3500002)
    s.branch("register_exit", condition=1)
    s.literal(1, "status_address")
    s.emit(0xE5814000, 0xE5815004, 0xE5810008)  # controller, main manager, registered count
    s.label("register_exit")
    s.emit(0xE1A00006, 0xE8BD8070)              # original return; pop r4-r6,pc

    # Wrap the generic reader only for the specific registered controller/main
    # pair. The original read closes its file before the second read reuses
    # the same backend. Preserve original result for the game's caller.
    s.label("read")
    s.literal(12, "status_address")
    s.emit(0xE59CC000, 0xE150000C)              # r0 == registered controller?
    s.branch("native_read", condition=1)
    s.emit(0xE3500000, 0x13510000)              # controller/backend both nonnull
    s.branch("native_read", condition=0)
    s.literal(12, "status_address")
    s.emit(0xE59CC004, 0xE152000C)              # r2 == main manager?
    s.branch("native_read", condition=1)
    s.emit(0xE92D40F0, 0xE24DD004, 0xE1A04000, 0xE1A05001, 0xE1A06003)  # aligned SP
    s.branch("native_read", link=True)
    s.emit(0xE1A07000, 0xE3500000)
    s.branch("read_exit", condition=1)
    s.emit(0xE1A00004, 0xE1A01005)
    s.literal(2, "manager_address")
    s.emit(0xE1A03006)
    s.branch("native_read", link=True)
    s.literal(12, "status_address")
    s.emit(0xE58C000C, 0xE59C1010, 0xE3510002)  # native sidecar result, calls, bounded trace
    s.branch("count_read", condition=2)         # hs: do not write past two entries
    s.emit(0xE08C2181, 0xE59D3014, 0xE5823014, 0xE5820018)  # caller LR and result
    s.label("count_read")
    s.emit(0xE2811001, 0xE58C1010)
    s.label("read_exit")
    s.emit(0xE1A00007, 0xE28DD004, 0xE8BD80F0)
    s.label("native_read")
    s.emit(READ_PUSH)
    s.branch(READ + 4)

    # Interfaces used by the exact-build align/register/read paths. No native
    # heap allocation or save callbacks installed for this test object.
    for name, instruction in (
        ("noop", 0xE3A00000), ("one", 0xE3A00001), ("size", 0xE3A00C02),
    ):
        s.label(name)
        s.emit(instruction, 0xE12FFF1E)
    for name, literal in (("block", "block_address"), ("data", "buffer_address")):
        s.label(name)
        s.literal(0, literal)
        s.emit(0xE12FFF1E)
    s.label("manager_table")
    s.emit(*(s.labels[name] for name in ("noop", "noop", "one", "block", "size",
                                         "noop", "noop", "noop", "noop", "noop", "noop")))
    s.label("block_table")
    s.emit(*(s.labels[name] for name in ("noop", "noop", "noop", "data", "size", "noop")))
    s.label("filename")
    filename = (NAME + "\0").encode("utf-16le")
    filename += bytes(-len(filename) % 4)
    s.emit(*struct.unpack(f"<{len(filename)//4}I", filename))
    for name, address in (
        ("manager_address", manager), ("block_address", block),
        ("status_address", status), ("buffer_address", buffer),
        ("filename_address", s.labels["filename"]),
        ("manager_table_address", s.labels["manager_table"]),
        ("block_table_address", s.labels["block_table"]),
    ):
        s.label(name)
        s.emit(address)
    records = [
        (address_offset(info, 0x108E3C, 4), struct.pack("<I", 0xE3A02002)),
        (address_offset(info, REG_SITE, 4), struct.pack("<I", arm_branch(REG_SITE, s.labels["register"], True))),
        (address_offset(info, READ, 4), struct.pack("<I", arm_branch(READ, s.labels["read"]))),
    ]
    return records, s.finish(), {
        "manager": manager, "block": block, "status": status, "buffer": buffer,
        "register_hook": s.labels["register"], "read_hook": s.labels["read"],
        "manager_table": s.labels["manager_table"], "block_table": s.labels["block_table"],
        "path": f"data:/{NAME}", "size": FILE_SIZE,
    }


def parse_status(data):
    if len(data) != STATUS_SIZE:
        raise ValueError("Incomplete native sidecar status")
    controller, main, count, status, calls, caller1, result1, caller2, result2 = struct.unpack("<9I", data)
    if count != 2 or status != 0 or calls != 2:
        raise ValueError(f"Native sidecar load not corroborated: count={count}, result={status}, calls={calls}")
    if any(address % 4 or not 0x08000000 <= address <= 0x0FFFFFF0 for address in (controller, main)):
        raise ValueError("Native sidecar controller/main pointer outside aligned heap")
    if result1 or result2 or (caller1 - 4, caller2 - 4) != READ_CALLERS:
        raise ValueError("Native sidecar read caller or result differs")
    return controller, main, (caller1, caller2)


def verify_records(records, main, plan):
    if len(records) != 96:
        raise ValueError("Incomplete native sidecar records")
    for offset, manager, size, path in (
        (0, main, SAVE_SIZE, "data:/main"), (48, plan["manager"], FILE_SIZE, plan["path"]),
    ):
        if (struct.unpack_from("<I", records, offset)[0] != manager
                or struct.unpack_from("<Q", records, offset + 8)[0] != size
                or records[offset+16:offset+48].decode("utf-16le").split("\0", 1)[0] != path):
            raise ValueError("Wrong native sidecar record manager/size/path")


async def read_sidecar(api, context, plan, expected, audit):
    async def read(*ranges):
        audit["memory_read_requests"] += len(ranges)
        values = await api.read(context, [(address, size, "System Bus") for address, size in ranges])
        if len(values) != len(ranges) or any(len(v) != n for v, (_, n) in zip(values, ranges)):
            raise ValueError("Incomplete native sidecar readback")
        return values

    status, payload, vptrs = await read(
        (plan["status"], STATUS_SIZE), (plan["buffer"], FILE_SIZE), (plan["manager"], 8),
    )
    audit["sidecar_last_status_hex"] = status.hex()
    controller, main, callers = parse_status(status)
    if payload != expected:
        raise ValueError("Native sidecar RAM differs from host-only challenge")
    if struct.unpack("<2I", vptrs) != (plan["manager_table"], plan["block_table"]):
        raise ValueError("Native sidecar dispatch pointers differ")
    header, = await read((controller, 16))
    _, registered, capacity, records = struct.unpack("<4I", header)
    if registered != 2 or capacity != 2 or records % 4 or not 0x08000000 <= records <= 0x10000000 - 96:
        raise ValueError("Invalid expanded native sidecar controller")
    rows, = await read((records, 96))
    verify_records(rows, main, plan)
    return {
        "controller": controller, "main_manager": main, "records": records,
        "registered_count": registered, "capacity": capacity, "native_read_result": 0,
        "native_read_calls": len(callers), "native_read_return_addresses": list(callers),
        "payload_sha256": hashlib.sha256(payload).hexdigest(),
        "records_sha256": hashlib.sha256(rows).hexdigest(),
        "sidecar_registered_and_loaded": True, "next_delivery_index": None,
        "live_delivery_authorized": False,
    }

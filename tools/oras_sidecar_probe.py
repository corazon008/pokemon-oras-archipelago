"""Exact-OR native sidecar experiments. No delivery ledger."""

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
WRITE = 0x45DC38
WRITE_CALLERS = (0x45D23C, 0x124E50, 0x124F34)
WRITE_STATUS_SIZE = 16
SAVE_MARKER = b"ASV1"
MARKER_OFFSET = FILE_SIZE - len(SAVE_MARKER)


def stage_fixture(target: Path, *, save_trial=False, footer=False, index_trial=False):
    """Only a probe-owned copy reaches here. Never native-format any archive."""
    files, metadata, tree = capture_stable_archive(target)
    if set(files) != {"main"} or tree["directories"] or metadata != BASE_METADATA:
        raise ValueError("Sidecar experiment requires the known one-file Encore archive")
    if index_trial:
        from oras_index_probe import new_index_payload
        payload = new_index_payload(files["main"])
    elif footer:
        from oras_footer_binding import footer_payload
        payload = footer_payload(files["main"], saved=False)
    else:
        # Random file content cannot be reproduced by the patch or a zeroed BSS.
        payload = PREFIX + secrets.token_bytes(FILE_SIZE - len(PREFIX))
        if save_trial:
            payload = payload[:MARKER_OFFSET] + bytes(len(SAVE_MARKER))
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


def load_saved_fixture(target):
    """Read only from an already verified archive copy, never create a file."""
    files, _, _ = capture_stable_archive(target)
    payload = files.get(NAME, b"")
    verify_fixture(target, payload)
    if payload[MARKER_OFFSET:] != SAVE_MARKER:
        raise ValueError("Sidecar reload requires the saved test marker")
    return payload


def after_save_payload(payload):
    if len(payload) != FILE_SIZE or not payload.startswith(PREFIX) or any(payload[MARKER_OFFSET:]):
        raise ValueError("Sidecar SAVE fixture must start with a clear test marker")
    return payload[:MARKER_OFFSET] + SAVE_MARKER


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


def build_sidecar(info, image, start, owned_page, *, save_trial=False, interrupt=False, footer=False,
                  index_trial=False):
    from oras_bootstrap_patch import arm_branch

    analyze_registration(info, image)
    if interrupt and not save_trial:
        raise ValueError("Interruption requires the native SAVE variant")
    if index_trial and not footer:
        raise ValueError("Synthetic index requires native footer capture")
    if footer:
        if not save_trial or interrupt:
            raise ValueError("Footer experiment requires its own native SAVE variant")
        from oras_footer_binding import verify_footer_getter
        verify_footer_getter(info, image)
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

    write_status = owned_page + 0x60
    if save_trial:
        emit_save_stub(s, interrupt, footer)

    # Interfaces used by the exact-build align/register/read paths. No native
    # manager mutation/validation callbacks installed for this test object.
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
    literals = [
        ("manager_address", manager), ("block_address", block),
        ("status_address", status), ("buffer_address", buffer),
        ("filename_address", s.labels["filename"]),
        ("manager_table_address", s.labels["manager_table"]),
        ("block_table_address", s.labels["block_table"]),
    ]
    if save_trial:
        if index_trial:
            from oras_index_probe import INDEX_OFFSET
        literals += [
            ("write_status_address", write_status),
            ("marker_address", buffer + (INDEX_OFFSET if index_trial else MARKER_OFFSET)),
            ("marker_word", 1 if index_trial else int.from_bytes(SAVE_MARKER, "little")),
        ]
    if footer:
        from oras_footer_binding import footer_literals
        literals.extend(footer_literals(buffer))
    for name, address in literals:
        s.label(name)
        s.emit(address)
    records = [
        (address_offset(info, 0x108E3C, 4), struct.pack("<I", 0xE3A02002)),
        (address_offset(info, REG_SITE, 4), struct.pack("<I", arm_branch(REG_SITE, s.labels["register"], True))),
        (address_offset(info, READ, 4), struct.pack("<I", arm_branch(READ, s.labels["read"]))),
    ]
    plan = {
        "manager": manager, "block": block, "status": status, "buffer": buffer,
        "register_hook": s.labels["register"], "read_hook": s.labels["read"],
        "manager_table": s.labels["manager_table"], "block_table": s.labels["block_table"],
        "path": f"data:/{NAME}", "size": FILE_SIZE,
    }
    if save_trial:
        require_words(info, image, WRITE, [0xE92D4FF8, 0xE1A04001, 0xE1A05000, 0xE1A07002])
        for site in WRITE_CALLERS:
            require_words(info, image, site, [arm_branch(site, WRITE, link=True)])
            records.append((
                address_offset(info, site, 4),
                struct.pack("<I", arm_branch(site, s.labels["write"], link=True)),
            ))
        plan.update({"write_hook": s.labels["write"], "write_status": write_status})
        if interrupt:
            plan["interrupt_barrier"] = s.labels["park"]
        if footer:
            plan["footer_binding"] = True
        if index_trial:
            plan["synthetic_index_trial"] = True
    return records, s.finish(), plan


def emit_save_stub(s, interrupt=False, footer=False):
    """Run once after main's writer returns 0. Preserve main's result."""
    s.label("write")
    s.literal(12, "status_address")
    s.emit(0xE59CC000, 0xE150000C)             # registered controller?
    s.branch(WRITE, condition=1)
    s.emit(0xE3500000, 0x13510000)             # controller/backend both nonnull
    s.branch(WRITE, condition=0)
    s.literal(12, "status_address")
    s.emit(0xE59CC004, 0xE152000C)             # native main manager?
    s.branch(WRITE, condition=1)
    s.literal(12, "status_address")
    s.emit(0xE59CC010, 0xE35C0002)             # both boot reads ran
    s.branch(WRITE, condition=1)
    s.literal(12, "write_status_address")
    s.emit(0xE59CC000, 0xE35C0000)             # never retry an attempted write
    s.branch(WRITE, condition=1)
    s.literal(12, "marker_address")
    s.emit(0xE59CC000, 0xE35C0000)             # only replace a clear test marker
    s.branch(WRITE, condition=1)
    s.emit(0xE92D40F0, 0xE24DD004, 0xE1A04000, 0xE1A05001, 0xE1A06003)
    s.branch(WRITE, link=True)
    s.emit(0xE1A07000, 0xE3500000)
    s.branch("write_exit", condition=1)

    s.literal(12, "write_status_address")
    s.emit(0xE3A00001, 0xE58C0000, 0xE59D1014, 0xE58C1004)  # attempt, caller LR
    s.emit(0xE3E00000, 0xE58C0008)             # sentinel until writer returns
    if interrupt:
        # Experiment only: widen the inter-file window. No sidecar mutation
        # or second writer call can run after this acknowledgement.
        s.emit(0xE3A00002, 0xE58C000C)         # returned field = parked (not success)
        s.label("park")
        s.branch("park")
    if footer:
        from oras_footer_binding import emit_footer_copy
        emit_footer_copy(s)
    s.literal(12, "marker_address")
    s.literal(0, "marker_word")
    s.emit(0xE58C0000, 0xE1A00004, 0xE1A01005)
    s.literal(2, "manager_address")
    s.emit(0xE1A03006)
    s.branch(WRITE, link=True)
    s.literal(12, "write_status_address")
    s.emit(0xE58C0008, 0xE3A00001, 0xE58C000C)  # actual result, returned flag
    s.label("write_exit")
    s.emit(0xE1A00007, 0xE28DD004, 0xE8BD80F0)


def parse_write_status(data):
    if len(data) != WRITE_STATUS_SIZE:
        raise ValueError("Incomplete native sidecar write status")
    attempts, caller, result, returned = struct.unpack("<4I", data)
    if (attempts, result, returned) != (1, 0, 1) or caller - 4 not in WRITE_CALLERS:
        raise ValueError(
            f"Native sidecar SAVE not corroborated: attempts={attempts}, LR={caller:#x}, "
            f"result={result}, returned={returned}"
        )
    return caller


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
    if "write_status" in plan:
        write_status, = await read((plan["write_status"], WRITE_STATUS_SIZE))
        if any(write_status):
            raise ValueError("Native sidecar writer ran before preflight completed")
    return {
        "controller": controller, "main_manager": main, "records": records,
        "registered_count": registered, "capacity": capacity, "native_read_result": 0,
        "native_read_calls": len(callers), "native_read_return_addresses": list(callers),
        "payload_sha256": hashlib.sha256(payload).hexdigest(),
        "records_sha256": hashlib.sha256(rows).hexdigest(),
        "sidecar_registered_and_loaded": True, "next_delivery_index": None,
        "live_delivery_authorized": False,
    }


async def read_saved_sidecar(api, context, plan, expected, audit):
    audit["memory_read_requests"] += 2
    values = await api.read(context, [
        (plan["write_status"], WRITE_STATUS_SIZE, "System Bus"),
        (plan["buffer"], FILE_SIZE, "System Bus"),
    ])
    if len(values) != 2:
        raise ValueError("Incomplete native sidecar SAVE readback")
    status, payload = values
    audit["sidecar_write_status_hex"] = status.hex()
    caller = parse_write_status(status)
    if plan.get("synthetic_index_trial"):
        from oras_index_probe import parse_index_payload
        before, initial_index = parse_index_payload(expected)
        after, saved_index = parse_index_payload(payload)
        if (initial_index, saved_index) != (0, 1) or before != after:
            raise ValueError("Native synthetic index or binding differs in RAM")
    elif plan.get("footer_binding"):
        from oras_footer_binding import HEADER
        if (len(payload) != FILE_SIZE or not payload.startswith(HEADER)
                or payload[MARKER_OFFSET:] != SAVE_MARKER or payload == expected):
            raise ValueError("Missing changed native footer payload in RAM")
    elif payload != after_save_payload(expected):
        raise ValueError("Native sidecar RAM doesn't match the changed test marker")
    return {"return_address": caller, "native_write_result": 0,
            "payload_sha256": hashlib.sha256(payload).hexdigest()}

"""Exact-OR registration analysis and opt-in native trace, not a file writer."""

import hashlib
from pathlib import Path
import struct

from oras_code_research import address_offset
from oras_save import SAVE_SIZE
from oras_save_lifecycle import require_words
from oras_save_serialization import branch_target


SLOT_SIZE = 64
SLOT_OFFSETS = (64, 128, 192)


def analyze_registration(info, image):
    checks = {
        0x108E3C: [0xE3A02001, 0xE1A01007],
        0x108E4C: [0xE5941000, 0xE28F2FE7],
        0x115A84: [0xE92D5FF0, 0xE1A06000, 0xE1A07001, 0xE1A0B002],
        0x115A94: [0xE1C600D4, 0xE1500001],
        0x115B28: [0xE5962004, 0xE596300C],
        0x115B38: [0xE0822082, 0xE3A04010, 0xE7837202],
        0x115B5C: [0xE5810004, 0xE5815000],
        0x115BA0: [0xE5960004, 0xE2800001, 0xE5860004, 0xE8BD9FF0],
        0x115BF4: [0xE92D4070],
        0x115C28: [0xE5842008],
        0x115C40: [0xE5940008, 0xE1A01005, 0xE0800080, 0xE1A00200],
        0x115C54: [0xE5941008, 0xE584000C, 0xE0811081, 0xE1A01201],
    }
    for address, words in checks.items():
        require_words(info, image, address, words)
    for site, target in ((0x108E44, 0x115BF4), (0x108E54, 0x115A84)):
        at = address_offset(info, site, 4)
        word = struct.unpack_from("<I", image, at)[0]
        if word >> 24 != 0xEB or branch_target(word, site) != target:
            raise ValueError("Native registration caller changed")
    for address, value in ((0x1091F4, "main\0"), (0x115BB0, "data:/\0")):
        expected = value.encode("utf-16le")
        at = address_offset(info, address, len(expected))
        if at is None or image[at:at + len(expected)] != expected:
            raise ValueError("Native registration name/prefix changed")
    return {
        "constructor": 0x115BF4, "register": 0x115A84, "register_return": 0x115BAC,
        "constructor_caller_return": 0x108E48, "register_caller_return": 0x108E58,
        "name_address": 0x1091F4, "registered_count_offset": 4,
        "capacity_offset": 8, "records_pointer_offset": 12, "record_stride": 48,
        "native_requested_capacity": 1, "registering_second_record_authorized": False,
        "write_allowed": False,
    }


def build_trace(info, image, start_address, owned_page):
    """Emit fixed-slot loggers; log stores use the added page, scratch stack is restored."""
    from oras_bootstrap_patch import align, arm_branch
    analysis = analyze_registration(info, image)
    payload, records, hooks = bytearray(), [], []
    # The entry/return instructions are position-independent PUSH/POP only.
    sites = (
        ("constructor", analysis["constructor"], 0xE92D4070, None),
        ("register_entry", analysis["register"], 0xE92D5FF0, 0),
        ("register_return", analysis["register_return"], 0xE8BD9FF0, 6),
    )
    for (role, site, displaced, controller_register), slot_offset in zip(sites, SLOT_OFFSETS):
        address = align(start_address + len(payload), 16)
        payload.extend(bytes(address - start_address - len(payload)))
        slot = owned_page + slot_offset
        words = [
            0xE92D500F,  # push {r0-r3,r12,lr}; 24 bytes
            0xE10FC000,  # mrs r12,cpsr
            0xE92D1010,  # push {r4,r12}; total 32, keep SP aligned
            0,           # ldr r12,=slot, fixed below
            0xE59C4000,  # ldr r4,[r12]
            0xE2844001,  # add r4,r4,#1 (no flags)
            0xE58C4000,  # str r4,[r12]
            0xE28C4004,  # add r4,r12,#4
            0xE884000F,  # stm r4,{r0-r3}
            0xE58CE014,  # str lr,[r12,#20]
            0xE59D4004,  # ldr r4,[sp,#4] -> saved CPSR
            0xE58C4018,  # str r4,[r12,#24]
        ]
        if controller_register is not None:
            words.extend([
                0xE890000F | (controller_register << 16),  # ldm controller,{r0-r3}
                0xE28C4020,  # add r4,r12,#32
                0xE884000F,  # stm r4,{r0-r3}
            ])
        words.extend([
            0xE8BD1010,  # pop {r4,r12}; r12 = saved CPSR
            0xE128F00C,  # msr CPSR_f,r12
            0xE8BD500F,  # pop {r0-r3,r12,lr}
            displaced,
        ])
        if role != "register_return":
            words.append(arm_branch(address + len(words) * 4, site + 4))
        literal_index = len(words)
        words.append(slot)
        delta = (literal_index - 3) * 4 - 8
        if not 0 <= delta <= 0xFFF:
            raise ValueError("Trace literal outside bounded A32 load")
        words[3] = 0xE59FC000 | delta
        payload.extend(struct.pack(f"<{len(words)}I", *words))
        at = address_offset(info, site, 4)
        require_words(info, image, site, [displaced])
        records.append((at, struct.pack("<I", arm_branch(site, address))))
        hooks.append({
            "role": role, "site": site, "trampoline": address,
            "log_address": slot, "log_length": SLOT_SIZE,
        })
    return records, bytes(payload), {**analysis, "hooks": hooks}


def inspect_trace_slots(payloads, plan):
    if len(payloads) != 3 or any(len(p) != SLOT_SIZE for p in payloads):
        raise ValueError("Incomplete native registration trace")
    slots = [struct.unpack("<16I", payload) for payload in payloads]
    ctor, before, after = slots
    if any(slot[0] != 1 for slot in slots):
        raise ValueError("Expected exactly one call at each registration trace site")
    controller, manager = before[1:3]
    if (controller % 4 or manager % 4 or not 0x08000000 <= controller <= 0x10000000 - 32
            or not 0x08000000 <= manager < 0x10000000):
        raise ValueError("Registration arguments outside verified aligned application heap")
    if (ctor[1] != controller or ctor[3] != 1 or ctor[5] != plan["constructor_caller_return"]
            or before[5] != plan["register_caller_return"] or before[3] != plan["name_address"]):
        raise ValueError("Native registration call arguments differ")
    if before[9:11] != (0, 1) or after[9:11] != (1, 1) or before[8] != after[8] or after[1] != 1:
        raise ValueError("Native registered-count/capacity transition differs")
    if after[8] % 4 or not 0x08000000 <= after[8] <= 0x10000000 - 4:
        raise ValueError("Native backend pointer outside verified aligned application heap")
    record = after[11]
    if before[11] != record or record % 4 or not 0x08000000 <= record <= 0x10000000 - 48:
        raise ValueError("Native registration record pointer differs")
    return {
        "controller": controller, "manager": manager, "record": record,
        "backend": after[8], "constructor_calls": 1, "register_entry_calls": 1, "register_return_calls": 1,
        "registered_before": 0, "registered_after": 1, "capacity": 1,
        "constructor_caller_return": ctor[5], "register_caller_return": before[5],
        "name_address": before[3], "slot_sha256": [hashlib.sha256(p).hexdigest() for p in payloads],
        "second_record_registered": False, "persistent_ap_storage_allocated": False,
        "live_delivery_authorized": False,
    }


async def read_registration_trace(api, context, plan, audit):
    audit["memory_read_requests"] += 3
    payloads = await api.read(context, [
        (hook["log_address"], SLOT_SIZE, "System Bus") for hook in plan["hooks"]
    ])
    capture = None
    if audit.get("registration_trace_capture"):
        capture = Path(audit["registration_trace_capture"]) / f"connection-{len(audit['exchanges']) + 1:02d}"
        capture.mkdir(parents=True, exist_ok=False)
        for index, data in enumerate(payloads, 1):
            (capture / f"slot-{index:02d}.bin").write_bytes(data)
    result = inspect_trace_slots(payloads, plan)
    audit["memory_read_requests"] += 1
    records = await api.read(context, [(result["record"], 48, "System Bus")])
    if capture is not None:
        for index, data in enumerate(records, 1):
            (capture / f"record-{index:02d}.bin").write_bytes(data)
    if len(records) != 1 or len(records[0]) != 48:
        raise ValueError("Incomplete registered native save record")
    record = records[0]
    if (struct.unpack_from("<I", record)[0] != result["manager"]
            or struct.unpack_from("<Q", record, 8)[0] != SAVE_SIZE
            or record[16:48].decode("utf-16le").split("\0", 1)[0] != "data:/main"):
        raise ValueError("Registered native record manager/size/path differs")
    result.update({"record_sha256": hashlib.sha256(record).hexdigest(),
                   "declared_file_size": SAVE_SIZE, "path": "data:/main"})
    return result

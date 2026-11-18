"""Read-only static serialization leads for the exact verified OR executable.

Callsite syntax and file layout are checked, not instruction execution, pointer
ownership, native method purity or filesystem crash atomicity.
"""

import argparse
import hashlib
import json
from pathlib import Path
import struct

from oras_code_research import address_offset, arm_constant_return, image_address, load_code
from oras_save import BLOCKS, METADATA_OFFSET, SAVE_SIZE
from oras_save_objects import OR_HASH
from rom_identity import sha256_file


def aligned_layout(lengths, alignment):
    if (not isinstance(alignment, int) or isinstance(alignment, bool)
            or alignment < 1 or alignment > 4096 or alignment & (alignment - 1)):
        raise ValueError("Alignment must be a bounded power of two")
    offset, result = 0, []
    for length in lengths:
        if not isinstance(length, int) or isinstance(length, bool) or not 0 < length <= 64 * 1024 * 1024:
            raise ValueError("Invalid bounded block length")
        padded = (length + alignment - 1) & ~(alignment - 1)
        if offset + padded > 64 * 1024 * 1024:
            raise ValueError("Aligned file exceeds research bound")
        result.append({"offset": offset, "length": length, "padded_length": padded})
        offset += padded
    return result, offset


def branch_target(word, address):
    if address % 4 or not 0 <= address <= 0xFFFFFFFC:
        raise ValueError("Invalid A32 branch address")
    if word >> 28 == 15 or word & 0x0E000000 != 0x0A000000:
        return None  # BLX-immediate has different semantics and is not accepted.
    displacement = word & 0xFFFFFF
    if displacement & 0x800000:
        displacement -= 1 << 24
    return (address + 8 + displacement * 4) & 0xFFFFFFFF


def direct_references(info, image, targets):
    text = next(s for s in info["code_segments"] if s["name"] == "text")
    found = []
    for offset in range(text["image_offset"], text["image_offset"] + text["size"] - 3, 4):
        word = struct.unpack_from("<I", image, offset)[0]
        address = image_address(info, offset, 4)
        target = branch_target(word, address)
        if target in targets:
            found.append({
                "instruction": address, "target": target,
                "kind": "BL" if word & 0x01000000 else "B", "condition": word >> 28,
            })
    return found


def verify_slot_call(info, image, load, slot, call):
    """Verify LDR method,[register,#slot], MOV-only gap, BLX same method.

    Does not claim the register contains any particular object's vtable.
    """
    if load % 4 or call % 4 or not 4 <= call - load <= 16:
        raise ValueError("Invalid bounded virtual-call range")
    at = address_offset(info, load, call - load + 4)
    if at is None or at + call - load + 4 > len(image):
        raise ValueError("Virtual-call range outside executable")
    word = struct.unpack_from("<I", image, at)[0]
    if word & 0xFFF00FFF != 0xE5900000 | slot:
        raise ValueError("Method-slot load changed")
    method = (word >> 12) & 15
    if method == 15:
        raise ValueError("PC is not an indirect-call register")
    for offset in range(at + 4, at + call - load, 4):
        move = struct.unpack_from("<I", image, offset)[0]
        # MOV register without shifts or flags; must not replace method or PC.
        if move & 0xFFFF0FF0 != 0xE1A00000 or (move >> 12) & 15 in (method, 15):
            raise ValueError("Unsupported or clobbered virtual-call gap")
    if struct.unpack_from("<I", image, at + call - load)[0] != 0xE12FFF30 | method:
        raise ValueError("Indirect call does not use loaded method")
    return {"method_load": load, "slot": slot, "indirect_call": call}


def analyze_serialization(info, image):
    sites = [
        ("entry_count", 0x45DB1C, 8, 0x45DB24),
        ("alignment", 0x45DB30, 16, 0x45DB38),
        ("indexed_block", 0x45DB60, 12, 0x45DB68),
        ("block_size", 0x45DB74, 16, 0x45DB7C),
        ("block_data", 0x45DB88, 12, 0x45DB90),
        ("backend_read", 0x45DBD0, 16, 0x45DBD8),
        ("write_seek", 0x45DD10, 24, 0x45DD18),
        ("backend_write", 0x45DD40, 72, 0x45DD4C),
    ]
    calls = [{"role_lead": role, **verify_slot_call(info, image, load, slot, call)}
             for role, load, slot, call in sites]
    metadata_provider = address_offset(info, 0x4630C4, 4)
    result = arm_constant_return(info, image, metadata_provider)
    if result is None or result[0] != 488:
        raise ValueError("Metadata payload length not corroborated")
    for address, expected in ((0x4EA990, 512), (0x4EA998, 59)):
        value = arm_constant_return(info, image, address_offset(info, address, 4))
        if value is None or value[0] != expected:
            raise ValueError("Manager alignment or entry count not corroborated")
    layout, total = aligned_layout([length for _, length in BLOCKS] + [result[0]], 512)
    if any(row["offset"] != expected[0] for row, expected in zip(layout, BLOCKS)):
        raise ValueError("Aligned layout differs from saved block offsets")
    if layout[-1]["offset"] != METADATA_OFFSET or total != SAVE_SIZE:
        raise ValueError("Footer or total save size differs")
    return {
        "read_loop": 0x45DACC, "write_loop": 0x45DC38,
        "checked_callsite_syntax": calls,
        "direct_branch_candidates": direct_references(info, image, {0x45DACC, 0x45DC38}),
        "regular_offsets_matching_file_layout": len(BLOCKS),
        "alignment": 512, "layout": layout, "total_size": total,
        "manager_entry_count": 59,
        "metadata_payload_length": 488,
        "size_inputs_source": "Documented BLOCKS layout; no native methods invoked",
        "size_helper_has_special_cases_for_blocks_56_57": True,
        "size_helper_special_cases_applied_to_this_full_layout": False,
        "instruction_execution_traced": False,
        "crash_atomicity_proven": False, "write_allowed": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("rom", type=Path)
    args = parser.parse_args()
    try:
        if sha256_file(args.rom) != OR_HASH:
            raise ValueError("Serialization research requires the verified OR build")
        info, image = load_code(args.rom)
        report = analyze_serialization(info, image)
        report.update({"rom_sha256": OR_HASH, "expanded_code_sha256": hashlib.sha256(image).hexdigest()})
    except (OSError, ValueError) as error:
        parser.exit(1, f"Serialization research failed: {error}\n")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

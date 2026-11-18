"""Bounded, read-only A32 save-manager research; never an execution emulator.

Only straight-line word operations used by the selected constructor fragment
are accepted. Values are constants or affine offsets from the input r4 base.
Unknown stack loads stay unknown. No game code is executed or patched.
"""

import argparse
import hashlib
import json
from pathlib import Path
import struct

from oras_code_research import address_offset, arm_constant_return, image_address, load_code
from oras_save import BLOCKS, METADATA_OFFSET, validate_save
from oras_save_objects import OR_HASH
from rom_identity import sha256_file


ASSIGNMENTS_START = 0x00116AC4
ASSIGNMENTS_END = 0x00116EDC
TABLE_OFFSET = 0x722D0  # Corroborated by the separately checked native accessor.


def immediate(word):
    value, rotate = word & 255, ((word >> 8) & 15) * 2
    return ((value >> rotate) | (value << ((32 - rotate) % 32))) & 0xFFFFFFFF


def shifted(value, shift, amount):
    if value is None:
        return None
    if amount == 0 and shift == 0:
        return value
    coefficient, number = value
    if coefficient:
        return None  # Shifting a symbolic address is deliberately unsupported.
    if shift == 0:
        result = number << amount
    elif shift == 1:
        result = number >> (amount or 32)
    elif shift == 2:
        signed = number if number < 0x80000000 else number - (1 << 32)
        result = signed >> (amount or 32)
    elif amount:
        result = (number >> amount) | (number << (32 - amount))
    else:
        return None  # RRX depends on unknown carry.
    return (0, result & 0xFFFFFFFF)


def combine(left, right, subtract=False):
    if left is None or right is None:
        return None
    coefficient = left[0] + (-right[0] if subtract else right[0])
    if coefficient not in (0, 1):
        return None
    return coefficient, (left[1] + (-right[1] if subtract else right[1])) & 0xFFFFFFFF


def trace_assignments(info, image, start, end):
    """Trace supported instructions only; return base-relative word stores.

    r4 denotes an unknown manager base; no initial value is invented for other
    registers. Conditional instructions, calls and unsupported forms abort.
    """
    if start % 4 or end % 4 or end <= start or end - start > 4096:
        raise ValueError("Invalid bounded assignment fragment")
    offset = address_offset(info, start, end - start)
    if offset is None or offset + end - start > len(image):
        raise ValueError("Assignment fragment outside executable")
    registers = [None] * 16
    registers[4] = (1, 0)
    stores = {}
    for index, pc in enumerate(range(start, end, 4)):
        word = struct.unpack_from("<I", image, offset + index * 4)[0]
        if word >> 28 != 0xE:
            raise ValueError(f"Conditional instruction in assignment fragment at {pc:#x}")
        registers[15] = (0, pc + 8)
        if word & 0x0E000000 == 0x08000000:
            # Only LDMIA sp without writeback: these stack values are unknown.
            if word & 0x0FFF0000 != 0x089D0000 or word & 0xA000:
                raise ValueError("Unsupported multiple transfer")
            for register in range(15):
                if word & (1 << register):
                    registers[register] = None
            continue
        if word & 0x0C000000 == 0x04000000:
            # Word LDR/STR, pre-index, no writeback.
            if word & 0x01600000 != 0x01000000:
                raise ValueError("Unsupported memory addressing")
            source, target = (word >> 16) & 15, (word >> 12) & 15
            if target == 15:
                raise ValueError("PC transfer is not straight-line analysis")
            if word & 0x02000000:
                if word & 0x10:
                    raise ValueError("Register-controlled memory shift")
                displacement = shifted(registers[word & 15], (word >> 5) & 3, (word >> 7) & 31)
            else:
                displacement = (0, word & 4095)
            address = combine(registers[source], displacement, not bool(word & 0x00800000))
            if word & 0x00100000:
                registers[target] = None
                if source == 15 and address is not None and address[0] == 0:
                    at = address_offset(info, address[1], 4)
                    if at is None or at + 4 > len(image) or address[1] % 4:
                        raise ValueError("Unmapped or unaligned literal")
                    registers[target] = (0, struct.unpack_from("<I", image, at)[0])
            elif address is not None and address[0] == 1:
                if address[1] % 4:
                    raise ValueError("Unaligned base-relative store")
                stores[address[1]] = {"instruction": pc, "value": registers[target]}
            continue
        if word & 0x0C000000 == 0:
            if word & 0x00100000:
                raise ValueError("Flag-setting operation in assignment fragment")
            opcode, source, target = (word >> 21) & 15, (word >> 16) & 15, (word >> 12) & 15
            if target == 15 or opcode not in (2, 4, 12, 13):
                raise ValueError("Unsupported data-processing instruction")
            if word & 0x02000000:
                operand = (0, immediate(word))
            else:
                if word & 0x10:
                    raise ValueError("Register-controlled shift")
                operand = shifted(registers[word & 15], (word >> 5) & 3, (word >> 7) & 31)
            if opcode == 13:
                value = operand
            elif opcode in (2, 4):
                value = combine(registers[source], operand, opcode == 2)
            else:
                left = registers[source]
                value = (0, left[1] | operand[1]) if left and operand and left[0] == operand[0] == 0 else None
            registers[target] = value
            continue
        raise ValueError(f"Unsupported assignment instruction at {pc:#x}")
    return stores


def analyze_manager(info, image):
    stores = trace_assignments(info, image, ASSIGNMENTS_START, ASSIGNMENTS_END)
    table = {}
    for block_id in range(len(BLOCKS)):
        store = stores.get(TABLE_OFFSET + block_id * 4)
        if store and store["value"] is not None and store["value"][0] == 1:
            table[block_id] = {
                "object_offset": store["value"][1], "assignment_instruction": store["instruction"],
            }
    if any(block_id not in table for block_id in (1, 19, 47)):
        raise ValueError("Selected manager slots not derived from constructor assignments")
    # Exact independent A32 accessor: base + index*4 + 0x72000, LDR +0x2D0.
    at = address_offset(info, 0x004652B0, 16)
    if at is None or struct.unpack_from("<4I", image, at) != (
        0xE0840105, 0xE2800A72, 0xE59002D0, 0xE8BD8070,
    ):
        raise ValueError("Native indexed accessor changed; table offset is not verified")
    return {
        "assignment_range": [ASSIGNMENTS_START, ASSIGNMENTS_END],
        "table_offset": TABLE_OFFSET, "slot_count": len(BLOCKS),
        "derived_slots": table,
        "unknown_slot_ids": [i for i in range(len(BLOCKS)) if i not in table],
        "execution_observed": False, "write_allowed": False,
    }


def inspect_manager_capture(capture, rom, prediction, save_reference=None):
    """Inspect private captures, not a trace of instruction execution."""
    info, image = load_code(rom)
    pointers = (capture / "manager-table.bin").read_bytes()
    headers = (capture / "manager-headers.bin").read_bytes()
    root = (capture / "manager-root.bin").read_bytes()
    metadata = (capture / "manager-metadata.bin").read_bytes()
    if len(pointers) != 232 or len(headers) != 232 or len(root) != 8 or len(metadata) != 504:
        raise ValueError("Incomplete manager capture")
    base = prediction["predicted_base"]
    derived = prediction["derived_slots"]
    rows, descriptor_matches = [], []
    text = next(s for s in info["code_segments"] if s["name"] == "text")
    for block_id, (_, expected_length) in enumerate(BLOCKS):
        address = struct.unpack_from("<I", pointers, block_id * 4)[0]
        slot = derived.get(block_id)
        if slot is not None and address != base + slot["object_offset"]:
            raise ValueError(f"Manager object differs from constructor prediction: {block_id}")
        dispatch = struct.unpack_from("<I", headers, block_id * 4)[0]
        offset = address_offset(info, dispatch, 24)
        if offset is None or dispatch % 4:
            raise ValueError(f"Manager dispatch outside executable: {block_id}")
        words = struct.unpack_from("<6I", image, offset)
        if any(word % 4 or not text["address"] <= word < text["address"] + text["size"] for word in words):
            raise ValueError(f"Manager dispatch has an unverified code pointer: {block_id}")
        provider = address_offset(info, words[4], 4)
        result = arm_constant_return(info, image, provider)
        row = {
            "block_id": block_id, "object_address": address, "dispatch_address": dispatch,
            "size_provider": words[4], "recognized_size": result[0] if result else None,
            "size_matches_file_layout": result[0] == expected_length if result else None,
        }
        rows.append(row)
        length, identifier = struct.unpack_from("<IH", metadata, 28 + block_id * 8)
        descriptor_matches.append((length, identifier) == (expected_length, block_id))
    dispatch = struct.unpack_from("<I", root)[0]
    offset = address_offset(info, dispatch, 44)
    if offset is None:
        raise ValueError("Manager dispatch lies outside executable")
    methods = struct.unpack_from("<11I", image, offset)
    if any(word % 4 or not text["address"] <= word < text["address"] + text["size"] for word in methods):
        raise ValueError("Manager dispatch has an unverified code pointer")
    count_offset = address_offset(info, methods[2], 4)
    count_result = arm_constant_return(info, image, count_offset)
    if count_result is None or count_result[0] != 59:
        raise ValueError("Manager slot-count provider not corroborated")
    report = {
        "manager_dispatch": dispatch,
        "manager_slot_count": count_result[0],
        "regular_slot_count": 58, "metadata_slot_index": 58,
        "indexed_accessor": methods[3], "reset_loop": methods[5],
        "descriptor_builder": methods[7],
        "captured_table_sha256": hashlib.sha256(pointers).hexdigest(),
        "constructor_offsets_matched": len(derived),
        "objects": rows,
        "metadata_object": struct.unpack_from("<I", root, 4)[0],
        "metadata_descriptors_matching_file_layout": sum(descriptor_matches),
        "size_matches": sum(row["size_matches_file_layout"] is True for row in rows),
        "size_mismatch_ids": [row["block_id"] for row in rows if row["size_matches_file_layout"] is False],
        "unrecognized_size_ids": [row["block_id"] for row in rows if row["recognized_size"] is None],
        "instruction_execution_traced": False, "serialization_timing_proven": False,
        "write_allowed": False,
    }
    if save_reference is not None:
        validate_save(save_reference)
        report.update({
            "metadata_source_save_sha256": hashlib.sha256(save_reference).hexdigest(),
            "metadata_payload_matches_saved_footer": metadata[8:496] == save_reference[METADATA_OFFSET:METADATA_OFFSET + 488],
            "metadata_descriptors_with_matching_crc": sum(
                metadata[28 + i * 8:36 + i * 8] == save_reference[METADATA_OFFSET + 20 + i * 8:METADATA_OFFSET + 28 + i * 8]
                for i in range(58)
            ),
        })
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("rom", type=Path)
    args = parser.parse_args()
    try:
        if sha256_file(args.rom) != OR_HASH:
            raise ValueError("Save-manager research requires the verified OR build")
        info, image = load_code(args.rom)
        report = analyze_manager(info, image)
        report.update({"rom_sha256": OR_HASH, "expanded_code_sha256": hashlib.sha256(image).hexdigest()})
    except (OSError, ValueError) as error:
        parser.exit(1, f"Save-manager research failed: {error}\n")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

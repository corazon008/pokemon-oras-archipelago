"""Read-only native reset/load and source-record binding research, exact OR build.

Static callsites and captured pointer relationships do not prove runtime call
arguments, an idle/safe-write state, exclusive AP storage or crash recovery.
"""

import argparse
import json
from pathlib import Path
import struct

from oras_code_research import address_offset, arm_constant_return, load_code
from oras_save import SAVE_SIZE
from oras_save_objects import OR_HASH
from oras_save_references import inspect_reference_capture
from oras_save_serialization import branch_target, verify_slot_call
from rom_identity import sha256_file


def require_words(info, image, address, expected):
    offset = address_offset(info, address, len(expected) * 4)
    if offset is None or offset + len(expected) * 4 > len(image):
        raise ValueError("Lifecycle signature outside executable")
    if struct.unpack_from(f"<{len(expected)}I", image, offset) != tuple(expected):
        raise ValueError(f"Native lifecycle signature changed at {address:#x}")


def analyze_lifecycle(info, image):
    # Independent source-record lookup: count at +8, records pointer at +12,
    # index*3 followed by index<<4 => 48-byte records.
    require_words(info, image, 0x45D66C, [0xE5903008])
    require_words(info, image, 0x45D684, [0xC59C400C])
    require_words(info, image, 0x45D690, [0xE0805080, 0xE7945205])
    require_words(info, image, 0x45D244, [0xE5C40018])
    require_words(info, image, 0x45E180, [0xE2800004, 0xE12FFF1E])
    require_words(info, image, 0x15EBCC, [0xE3A02000])
    for address in (0x116864, 0x45E17C):
        offset = address_offset(info, address, 4)
        if offset is None or branch_target(struct.unpack_from("<I", image, offset)[0], address) != 0x15EBCC:
            raise ValueError("Reserved-object zero-fill target changed")
    result = arm_constant_return(info, image, address_offset(info, 0x45E13C, 4))
    if result is None or result[0] != 2000:
        raise ValueError("Reserved-object payload length changed")
    calls = [
        verify_slot_call(info, image, 0x45E150, 12, 0x45E158),
        verify_slot_call(info, image, 0x45E164, 16, 0x45E16C),
        verify_slot_call(info, image, 0x45DBD0, 16, 0x45DBD8),
    ]
    # Reader's arguments: R1 = data getter result saved in r5, R2 = size in r8.
    require_words(info, image, 0x45DBC8, [0xE1A02008, 0xE1A01005])
    return {
        "source_record_lookup": 0x45D664,
        "controller_record_count_offset": 8, "controller_records_pointer_offset": 12,
        "source_record_stride": 48,
        "raw_io_result_store": 0x45D244, "raw_io_result_offset": 24,
        "raw_result_is_safe_write_flag_proven": False,
        "reserved_payload_offset": 4, "reserved_payload_length": 2000,
        "constructor_zero_call": 0x116864, "reset_tail_branch": 0x45E17C,
        "zero_fill_target": 0x15EBCC, "reset_getter_and_reader_call_syntax": calls,
        "loader_reads_into_data_getter_result": True,
        "nonzero_reserved_payload_roundtrip_tested": False,
        "exclusive_ap_ownership_proven": False, "runtime_instruction_trace": False,
        "live_delivery_authorized": False,
    }


def bind_controller_capture(capture, references, manager_base):
    records = references["main_save_record_candidates"]
    if len(records) != 1:
        raise ValueError("Controller binding requires one main-file record")
    record = records[0]
    data = None
    for index, row in enumerate(references["manager_backrefs"], 1):
        if row["reference_address"] == record:
            context = (capture / f"manager-backref-{index:02d}.bin").read_bytes()
            offset = record - row["context_start"]
            if offset < 0 or offset + 48 > len(context):
                raise ValueError("Incomplete 48-byte source record")
            data = context[offset:offset + 48]
    if data is None or struct.unpack_from("<I", data)[0] != manager_base:
        raise ValueError("Source-record manager pointer differs")
    if struct.unpack_from("<Q", data, 8)[0] != SAVE_SIZE:
        raise ValueError("Source-record file size differs")
    path = data[16:48].decode("utf-16le").split("\0", 1)[0]
    if path != "data:/main":
        raise ValueError("Source-record path differs")
    candidates = []
    for index, row in enumerate(references["save_record_referrers"], 1):
        context = (capture / f"save-record-referrer-{index:02d}.bin").read_bytes()
        controller = row["reference_address"] - 12
        offset = controller - row["context_start"]
        if offset < 0 or offset + 32 > len(context):
            continue
        engine, _, count, pointer = struct.unpack_from("<4I", context, offset)
        types = [entry for entry in row["context_type_candidates"]
                 if entry["context_address"] == engine
                 and entry["static_mangled_type_name"] == "N3gfl2fs12BackupSystemE"]
        if len(types) != 1:
            continue
        if pointer != record or count != 1:
            raise ValueError("Captured source-record controller differs from lookup layout")
        candidates.append({
            "controller_prefix": controller, "backup_system_pointer": engine,
            "source_record_count": count, "source_records_pointer": pointer,
            "source_record": record, "source_manager_pointer": manager_base,
            "declared_file_size": SAVE_SIZE, "path": path,
            "raw_result_byte_address": controller + 24, "raw_result_byte": context[offset + 24],
            "pointer_relationships_corroborated": True,
            "runtime_call_arguments_traced": False, "safe_to_write_proven": False,
        })
    if len(candidates) != 1:
        raise ValueError("Expected one captured controller binding")
    return candidates[0]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("rom", type=Path)
    parser.add_argument("--probe-result", type=Path, help="Private completed manager/reference probe result")
    args = parser.parse_args()
    try:
        if sha256_file(args.rom) != OR_HASH:
            raise ValueError("Lifecycle research requires the verified OR build")
        info, image = load_code(args.rom)
        report = {"rom_sha256": OR_HASH, "static": analyze_lifecycle(info, image)}
        if args.probe_result:
            probe = json.loads(args.probe_result.read_text())
            if probe["status"] != "complete" or probe["rom_identity"]["rom_sha256"] != OR_HASH:
                raise ValueError("Incomplete or wrong-build probe")
            manager = probe["save_objects"]["manager"]
            capture = args.probe_result.parent / "objects"
            references = inspect_reference_capture(capture, args.rom, manager["predicted_base"])
            report["controller_capture"] = bind_controller_capture(capture, references, manager["predicted_base"])
    except (OSError, ValueError, KeyError) as error:
        parser.exit(1, f"Lifecycle research failed: {error}\n")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

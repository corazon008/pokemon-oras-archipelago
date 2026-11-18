"""Inspect bounded private pointer contexts. Adjacency is not ownership proof."""

import hashlib
import struct

from oras_code_research import address_offset, load_code


def context_types(info, image, context, start):
    ro = next(s for s in info["code_segments"] if s["name"] == "ro")
    text = next(s for s in info["code_segments"] if s["name"] == "text")
    found = []
    for offset in range(0, len(context) - 3, 4):
        dispatch = struct.unpack_from("<I", context, offset)[0]
        if dispatch % 4 or not ro["address"] + 8 <= dispatch <= ro["address"] + ro["size"] - 8:
            continue
        at = address_offset(info, dispatch - 8, 16)
        if at is None:
            continue
        top, typeinfo, first, second = struct.unpack_from("<4I", image, at)
        if top != 0 or any(word % 4 or not text["address"] <= word < text["address"] + text["size"]
                           for word in (first, second)):
            continue
        at = address_offset(info, typeinfo, 8)
        if at is None:
            continue
        name_address = struct.unpack_from("<I", image, at + 4)[0]
        at = address_offset(info, name_address, 1)
        if at is None:
            continue
        end = image.find(b"\0", at, min(at + 192, len(image)))
        if end < 0:
            continue
        name = image[at:end]
        if len(name) < 5 or not all(32 <= byte < 127 for byte in name):
            continue
        found.append({
            "context_address": start + offset, "dispatch": dispatch,
            "static_mangled_type_name": name.decode("ascii"),
            "is_owner_of_nearby_reference_proven": False,
        })
    return found


def inspect_reference_capture(capture, rom, manager_base):
    info, image = load_code(rom)

    def context(fields, filename, expected):
        reference, start, length = fields
        if (reference % 4 or start % 4 or not 0x08000000 <= start <= reference
                or reference + 4 > start + length or start + length > 0x10000000
                or not 4 <= length <= 512):
            raise ValueError("Invalid bounded reference context")
        data = (capture / filename).read_bytes()
        if len(data) != length or struct.unpack_from("<I", data, reference - start)[0] != expected:
            raise ValueError("Captured pointer does not match reference relationship")
        return data, {
            "reference_address": reference, "context_start": start,
            "context_length": length, "context_sha256": hashlib.sha256(data).hexdigest(),
            "context_type_candidates": context_types(info, image, data, start),
        }

    lines = (capture / "manager-backrefs.txt").read_text().splitlines()
    if len(lines) > 16:
        raise ValueError("Too many manager references")
    backrefs, record_data = [], {}
    for index, line in enumerate(lines, 1):
        fields = [int(word, 0) for word in line.split()]
        if len(fields) != 3:
            raise ValueError("Invalid manager reference manifest")
        data, row = context(fields, f"manager-backref-{index:02d}.bin", manager_base)
        backrefs.append(row)
        record_data[fields[0]] = (data, fields[0] - fields[1])
    records = []
    for line in (capture / "save-records.txt").read_text().splitlines():
        address = int(line, 0)
        if address not in record_data or address in records:
            raise ValueError("Save record is not a unique manager reference")
        data, offset = record_data[address]
        if (offset + 36 > len(data) or struct.unpack_from("<I", data, offset + 8)[0] != 0x76000
                or data[offset + 16:offset + 36] != "data:/main".encode("utf-16le")):
            raise ValueError("Save-record size/path does not match captured bytes")
        records.append(address)
    lines = (capture / "save-record-referrers.txt").read_text().splitlines()
    if len(lines) > 16 * len(records):
        raise ValueError("Too many save-record references")
    referrers = []
    for index, line in enumerate(lines, 1):
        fields = [int(word, 0) for word in line.split()]
        if len(fields) != 4 or fields[0] not in records:
            raise ValueError("Unknown save record in referrer manifest")
        _, row = context(fields[1:], f"save-record-referrer-{index:02d}.bin", fields[0])
        referrers.append({"record_address": fields[0], **row})
    return {
        "manager_backrefs": backrefs,
        "main_save_record_candidates": records,
        "save_record_referrers": referrers,
        "context_adjacency_proves_ownership": False,
        "instruction_execution_traced": False, "write_allowed": False,
    }

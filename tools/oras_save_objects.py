"""Build a private read-only object-search plan from executable evidence, never guessed RAM."""

import hashlib
import struct

from oras_code_research import (
    address_offset, arm_constant_return, find_provider_tables, image_address, load_code,
)
from oras_save import BLOCKS, validate_save
from rom_identity import CodeReference, sha256_file


OR_HASH = "d76faafacd746fdcc5ec04a60b8b82ceb9678c3ad937b374234a506c50c417e4"


def load_object_observation(capture, report: dict) -> CodeReference:
    """Require completed, unique, aligned heap observation before AP rechecks."""
    if (capture / "complete").read_text() != "read-only\n":
        raise ValueError("Object search did not complete")
    matches = (capture / "matches.txt").read_text().splitlines()
    report["object_matches"] = matches
    if len(matches) != 1:
        raise ValueError("Object search did not produce one unambiguous match")
    address = int(matches[0], 16)
    if address % 4 or not 0x08000000 <= address <= 0x10000000 - 2004:
        raise ValueError("Object match lies outside aligned application heap")
    plan = (capture / "references.bin").read_bytes()
    if hashlib.sha256(plan).hexdigest() != report["plan_sha256"]:
        raise ValueError("Object plan changed after preparation")
    if len(plan) < 2008 or struct.unpack_from("<I", plan, len(plan) - 2008)[0] != 2004:
        raise ValueError("Invalid object pattern trailer")
    reads = (capture / "read-requests.txt").read_text().splitlines()
    expected_reads = len(report["reference_ranges"]) + 128 + 1 + (61 if "manager" in report else 0)
    if len(reads) != expected_reads:
        raise ValueError("Unexpected object-search read count")
    report.update({
        "lua_memory_read_requests": len(reads),
        "payload_candidates": [f"0x{address + 4:08X}"],
        "static_references_and_known_headers_matched": True,
        "unique_heap_match_rechecked": True,
    })
    return CodeReference(address, plan[-2004:])


def object_candidates(info: dict, image: bytes) -> list[dict]:
    providers, _ = find_provider_tables(info, image, tuple(length for _, length in BLOCKS))
    results = []
    text = next(s for s in info["code_segments"] if s["name"] == "text")
    ro = next(s for s in info["code_segments"] if s["name"] == "ro")
    for block_id in (1, 19, 47):
        length = BLOCKS[block_id][1]
        for provider in sorted(providers[length]):
            cursor = ro["image_offset"]
            end = cursor + ro["size"]
            needle = struct.pack("<I", provider)
            while (at := image.find(needle, cursor, end)) >= 0:
                cursor = at + 1
                if at % 4 or at - 16 < ro["image_offset"] or at + 8 > end:
                    continue
                words = struct.unpack_from("<6I", image, at - 16)
                if not all(text["address"] <= word < text["address"] + text["size"] and word % 4 == 0
                           for word in words):
                    continue
                getter = address_offset(info, words[3], 8)
                # Exact A32 ADD r0,r0,#4; BX LR. No generic object layout is assumed.
                if getter is None or struct.unpack_from("<II", image, getter) != (0xE2800004, 0xE12FFF1E):
                    continue
                results.append({
                    "block_id": block_id, "payload_length": length,
                    "dispatch_address": image_address(info, at - 16, 24),
                    "size_provider_address": provider, "data_getter_address": words[3],
                    "payload_offset_from_object": 4,
                })
    return results


def build_plan(rom, rom_hash: str, save: bytes, profile: dict, manager=False) -> tuple[bytes, dict]:
    if (rom_hash != OR_HASH or profile["program_id"] != "000400000011C400"
            or profile["domain"] != "System Bus"):
        raise ValueError("Save-object research is restricted to the verified OR build")
    if sha256_file(rom) != rom_hash:
        raise ValueError("ROM hash does not match object-search build")
    validate_save(save)
    info, image = load_code(rom)
    if info["program_id"] != profile["program_id"]:
        raise ValueError("ROM program ID does not match object-search profile")
    candidates = object_candidates(info, image)
    chosen = {}
    for block_id in (1, 19, 47):
        matches = [row for row in candidates if row["block_id"] == block_id]
        if len(matches) != 1:
            raise ValueError(f"Expected one static dispatch candidate for block {block_id}, got {len(matches)}")
        chosen[block_id] = matches[0]
    references = {}

    def reference(address, length):
        offset = address_offset(info, address, length)
        if offset is None:
            raise ValueError("Static object reference lies outside declared executable segments")
        references[address] = image[offset:offset + length]

    reference(info["code_segments"][0]["address"], 64)
    for row in chosen.values():
        reference(row["dispatch_address"], 24)
        reference(row["data_getter_address"], 8)
        offset = address_offset(info, row["size_provider_address"])
        result = arm_constant_return(info, image, offset)
        if result is None:
            raise ValueError("Size provider no longer recognized")
        value, instructions = result
        if value != row["payload_length"]:
            raise ValueError("Size provider changed during plan construction")
        reference(row["size_provider_address"], instructions * 4)
        # Include any literal used by the bounded size-return recognizer.
        for i in range(instructions):
            at = offset + i * 4
            word = struct.unpack_from("<I", image, at)[0]
            if word & 0x0F7FF000 == 0x051F0000:
                pc = image_address(info, at, 4)
                literal = pc + 8 + ((word & 0xFFF) if word & 0x800000 else -(word & 0xFFF))
                reference(literal, 4)
    # Payload offsets come from the exact decoded getter, corroborated below in live RAM.
    for block_id, payload in (
        (1, int(profile["inventory_address"], 16)),
        (19, int(profile["event_work"]["address"], 16)),
    ):
        if payload % 4 or not 0x08000004 <= payload <= 0x10000000 - BLOCKS[block_id][1]:
            raise ValueError("Known payload reference lies outside the application heap")
        references[payload - 4] = struct.pack("<I", chosen[block_id]["dispatch_address"])
    manager_report = None
    if manager:
        from oras_save_manager import analyze_manager
        manager_report = analyze_manager(info, image)
        slots = manager_report["derived_slots"]
        base = int(profile["inventory_address"], 16) - 4 - slots[1]["object_offset"]
        if int(profile["event_work"]["address"], 16) - 4 - slots[19]["object_offset"] != base:
            raise ValueError("Known object headers disagree about manager base")
        table = base + manager_report["table_offset"]
        if base % 4 or not 0x08000000 <= base < table <= 0x10000000 - 232:
            raise ValueError("Predicted manager lies outside the application heap")
        manager_report.update({"predicted_base": base, "predicted_table": table})
        start, end = manager_report["assignment_range"]
        for address in range(start, end, 256):
            reference(address, min(256, end - address))
        for address, length in (
            (0x00465284, 60), (0x00116EE0, 80), (0x004654F4, 80),
            (0x004652D4, 152), (0x00116824, 68), (0x0045E144, 60), (0x0015EBCC, 64),
            (0x005E0B24, 44), (0x004EA998, 8),
        ):
            reference(address, length)
        for block_id in (1, 19, 47):
            references[table + block_id * 4] = struct.pack("<I", base + slots[block_id]["object_offset"])
    offset, length = BLOCKS[47]
    pattern = struct.pack("<I", chosen[47]["dispatch_address"]) + save[offset:offset + length]
    plan = bytearray(struct.pack("<I", len(references)))
    for address, data in sorted(references.items()):
        plan.extend(struct.pack("<II", address, len(data)))
        plan.extend(data)
    plan.extend(struct.pack("<I", len(pattern)))
    plan.extend(pattern)
    report = {
        "static_candidates": list(chosen.values()),
        "source_save_sha256": hashlib.sha256(save).hexdigest(),
        "expanded_code_sha256": hashlib.sha256(image).hexdigest(),
        "target_block_id": 47, "pattern_length": len(pattern),
        "reference_ranges": [{"address": f"0x{address:08X}", "length": len(data)}
                             for address, data in sorted(references.items())],
        "ownership_proven": False, "write_allowed": False,
    }
    if manager_report is not None:
        report["manager"] = manager_report
    return bytes(plan), report

"""Plan and inspect frame-level native-save observations on seeded copies only."""

import hashlib
import json
from pathlib import Path
import struct

from oras_save import BLOCKS, METADATA_OFFSET, validate_save
from oras_events import event_bytes, event_flag, event_work


def digest(data):
    return hashlib.sha256(data).hexdigest()


def prepare_observation(capture, objects, target, source_save, object_report):
    validate_save(source_save)
    manager = object_report["manager"]
    refs = manager["references"]
    config = {
        "schema_version": 1, "capture": str(capture), "save_path": str(target),
        "max_ticks": 4000, "ranges": [],
    }

    def add(name, address, reference, stable=None):
        path = capture / f"reference-{name}.bin"
        path.write_bytes(reference)
        row = {"name": name, "address": address, "length": len(reference), "reference_path": str(path)}
        if stable:
            row["stable_prefix"] = stable
        config["ranges"].append(row)

    base = manager["predicted_base"]
    root = (objects / "manager-root.bin").read_bytes()
    if len(root) != 8:
        raise ValueError("Incomplete manager root")
    add("manager_root", base, root, 8)
    add("manager_table", manager["predicted_table"], (objects / "manager-table.bin").read_bytes(), 232)
    add("metadata", struct.unpack_from("<I", root, 4)[0], (objects / "manager-metadata.bin").read_bytes(), 4)
    slots = manager["derived_slots"]
    for name, block_id in (("inventory", 1), ("events", 19)):
        offset, length = BLOCKS[block_id]
        add(name, base + slots[block_id]["object_offset"] + 4, source_save[offset:offset + length],
            length if block_id == 1 else None)
    pattern = (objects / "references.bin").read_bytes()[-2004:]
    add("reserved_object", base + slots[47]["object_offset"], pattern, 4)
    records = refs["main_save_record_candidates"]
    if len(records) != 1:
        raise ValueError("Native-save observation requires one verified main-file record")
    for index, row in enumerate(refs["manager_backrefs"], 1):
        if row["reference_address"] == records[0]:
            data = (objects / f"manager-backref-{index:02d}.bin").read_bytes()
            at = records[0] - row["context_start"]
            add("main_record", records[0], data[at:at + 36], 4)
    if not any(row["name"] == "main_record" for row in config["ranges"]):
        raise ValueError("Main-file record has no checked capture")
    (capture / "observer.json").write_text(json.dumps(config, indent=2) + "\n")
    return config


def inspect_observation(capture, before, after):
    validate_save(before)
    validate_save(after)
    config = json.loads((capture / "observer.json").read_text())
    ranges = config["ranges"]
    names = [row["name"] for row in ranges]
    if names != ["manager_root", "manager_table", "metadata", "inventory", "events", "reserved_object", "main_record"]:
        raise ValueError("Unexpected native-save sample ranges")
    lines = (capture / "timeline.tsv").read_text().splitlines()
    ticks = int((capture / "observation-complete").read_text())
    if not 1 <= ticks <= 4000 or len(lines) != ticks:
        raise ValueError("Incomplete native-save timeline")
    rows = [[int(value) for value in line.split("\t")] for line in lines]
    if any(len(row) != len(ranges) + 4 for row in rows):
        raise ValueError("Malformed native-save timeline")
    for index, row in enumerate(rows):
        if index and row[0] != rows[index - 1][0] + 1:
            raise ValueError("Nonconsecutive observation frames")
        for column in range(2, 3 + len(ranges)):
            previous = rows[index - 1][column] if index else 0
            if row[column] not in (previous, previous + 1) or row[column] < 1:
                raise ValueError("Invalid observation version sequence")
    reads = (capture / "reads.tsv").read_text().splitlines()
    if len(reads) != ticks * len(ranges):
        raise ValueError("Unexpected frame-sampler read count")
    for index, line in enumerate(reads):
        fields = line.split("\t")
        sample = ranges[index % len(ranges)]
        if (len(fields) != 3 or int(fields[0]) != rows[index // len(ranges)][0]
                or int(fields[1], 0) != sample["address"] or int(fields[2]) != sample["length"]):
            raise ValueError("Frame-sampler read journal differs from configured ranges")
    versions = {}
    final = {}
    for column, sample in enumerate(ranges, 2):
        name, length = sample["name"], sample["length"]
        last_version = rows[-1][column]
        reference = Path(sample["reference_path"]).read_bytes()
        buffers = [(capture / f"{name}-{version:04d}.bin").read_bytes()
                   for version in range(1, last_version + 1)]
        if any(len(data) != length for data in buffers) or buffers[0] != reference:
            raise ValueError(f"Invalid initial sample/length for {name}")
        prefix = sample.get("stable_prefix")
        if prefix and any(data[:prefix] != reference[:prefix] for data in buffers):
            raise ValueError(f"Stable reference changed for {name}")
        final[name] = buffers[-1]
        versions[name] = {"versions": last_version, "last_sha256": digest(buffers[-1])}
    for name, block_id in (("inventory", 1), ("events", 19)):
        offset, length = BLOCKS[block_id]
        if final[name] != after[offset:offset + length]:
            raise ValueError(f"Final RAM {name} differs from native save")
    offset, length = BLOCKS[47]
    if final["reserved_object"][4:] != after[offset:offset + length]:
        raise ValueError("Final reserved payload differs from native save")
    if final["metadata"][8:496] != after[METADATA_OFFSET:METADATA_OFFSET + 488]:
        raise ValueError("Final RAM metadata differs from native footer")
    file_states = []
    for version in range(1, rows[-1][-2] + 1):
        path = capture / f"file-{version:04d}.bin"
        data = path.read_bytes() if path.exists() else None
        valid = False
        if data is not None:
            try:
                validate_save(data)
                valid = True
            except ValueError:
                pass
        file_states.append({"version": version, "present": data is not None,
                            "size": len(data) if data is not None else -1,
                            "sha256": digest(data) if data is not None else None,
                            "all_58_crcs_valid": valid})
        observed = [row for row in rows if row[-2] == version]
        file_states[-1].update({"first_frame": observed[0][0], "last_frame": observed[-1][0]})
    for row in rows:
        if row[-1] != file_states[row[-2] - 1]["size"]:
            raise ValueError("Sampled file size differs from timeline")
    if (capture / "file-0001.bin").read_bytes() != before:
        raise ValueError("Initial sampled file differs from seed")
    last_file = capture / f"file-{rows[-1][-2]:04d}.bin"
    if not last_file.exists() or last_file.read_bytes() != after:
        raise ValueError("Final sampled file differs from post-exit save")
    if before == after:
        raise ValueError("No saved-file change observed; native SAVE not demonstrated")
    initial_events, final_events = event_bytes(before), event_bytes(after)
    if (event_flag(initial_events, 2722) != event_flag(final_events, 2722)
            or event_work(initial_events, 130) != event_work(final_events, 130)):
        raise ValueError("Observed progression controls changed during native-save UI")
    changed = [i for i, (offset, length) in enumerate(BLOCKS)
               if before[offset:offset + length] != after[offset:offset + length]]
    return {
        "ticks": ticks, "first_frame": rows[0][0], "last_frame": rows[-1][0],
        "lua_memory_read_requests": len(reads), "sample_versions": versions,
        "file_states": file_states, "file_changed": True,
        "crc_invalid_file_sample_frames": [
            row[0] for row in rows if not file_states[row[-2] - 1]["all_58_crcs_valid"]
        ],
        "metadata_version_frames": [
            {"frame": row[0], "version": row[4]}
            for index, row in enumerate(rows) if not index or row[4] != rows[index - 1][4]
        ],
        "changed_save_block_ids": changed, "final_ram_matches_native_file": True,
        "pokedex_and_clock_controls_unchanged": True,
        "before_save_sha256": digest(before), "after_save_sha256": digest(after),
        "instruction_execution_traced": False, "direct_memory_writes": 0,
        "sampling_proves_crash_atomicity": False,
    }

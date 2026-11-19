"""Compare a quiet OR test archive with a trusted local native-SAVE observation.

This external witness is for the aptest experiment only. It is not a signed
receipt, an automatic rollback decision, a delivery journal, or a repair tool.
"""

import argparse
from dataclasses import dataclass
import json
from pathlib import Path

from oras_archive import capture_stable_archive, tree_digest
from oras_events import event_bytes
from oras_profiles import digest, validate_snapshot
from oras_save import inventory_bytes, validate_save
from oras_save_objects import OR_HASH
from oras_sidecar_probe import NAME, TEST_METADATA, after_save_payload, parse_write_status


OR_TITLE = "000400000011C400"


@dataclass(frozen=True)
class Checkpoint:
    snapshot: Path
    main_sha256: str
    sidecar_sha256: str
    tree_sha256: str


@dataclass(frozen=True)
class SaveWitness:
    before: Checkpoint
    after: Checkpoint
    metadata_sha256: str


def load_checkpoint(path):
    path = Path(path)
    manifest = validate_snapshot(path, OR_HASH)
    if manifest["program_id"] != OR_TITLE or manifest["schema_version"] != 2:
        raise ValueError("Sidecar witness requires exact OR and v2 snapshot")
    files, metadata, tree = capture_stable_archive(path / "00000001/main")
    tree_hash = tree_digest(tree)
    if (set(files) != {"main", NAME} or tree["directories"] or metadata != TEST_METADATA
            or tree_hash != manifest["archive_tree_sha256"]
            or digest(metadata) != manifest["metadata_sha256"]):
        raise ValueError("Wrong or changed sidecar witness archive")
    return Checkpoint(path, digest(files["main"]), digest(files[NAME]), tree_hash), files


def verify_witness(report):
    """Bind report, writer telemetry and both full checkpoints; no path is inferred."""
    identity = report.get("rom_identity", {})
    if (report.get("schema_version") != 1 or report.get("status") != "complete"
            or report.get("exit_code") != 0 or report.get("forced_shutdown")
            or report.get("memory_write_requests") != 0
            or identity.get("rom_sha256") != OR_HASH or identity.get("program_id") != OR_TITLE
            or report.get("bootstrap", {}).get("mode") != "sidecar-save"
            or report.get("native_save_macro_completed") is not True
            or report.get("full_archive_source_unchanged") is not True
            or report.get("save_unchanged") is not False):
        raise ValueError("Expected a completed exact-OR native sidecar SAVE result")
    caller = parse_write_status(bytes.fromhex(report["sidecar_write_status_hex"]))
    before, old = load_checkpoint(report["backup_before_launch"])
    after, new = load_checkpoint(report["backup_after_exit"])
    if (before.main_sha256 == after.main_sha256 or after_save_payload(old[NAME]) != new[NAME]
            or inventory_bytes(old["main"]) != inventory_bytes(new["main"])
            or event_bytes(old["main"]) != event_bytes(new["main"])):
        raise ValueError("Checkpoints are not the experimental marker-only transition")
    fixture = report["sidecar_fixture"]
    if (fixture.get("native_save_tested") is not True or fixture.get("host_seeded") is not True
            or fixture.get("archive_tree_before_boot") != before.tree_sha256
            or fixture.get("archive_tree_after_exit") != after.tree_sha256
            or fixture.get("sha256") != before.sidecar_sha256
            or report.get("save_sha256_before_launch") != before.main_sha256
            or report.get("resulting_save", {}).get("save_sha256") != after.main_sha256
            or report["sidecar_save"] != {"return_address": caller, "native_write_result": 0,
                                         "payload_sha256": after.sidecar_sha256}):
        raise ValueError("SAVE report does not bind both observed checkpoints")
    return SaveWitness(before, after, digest(TEST_METADATA))


def load_witness(result: Path):
    if result.is_symlink() or not result.is_file():
        raise ValueError("Expected a local SAVE result file")
    with result.open("rb") as source:
        encoded = source.read(1024 * 1024 + 1)
    if len(encoded) > 1024 * 1024:
        raise ValueError("SAVE result exceeds research bound")
    try:
        report = json.loads(encoded)
        if not isinstance(report, dict):
            raise ValueError("Expected an object in SAVE result")
        return verify_witness(report)
    except (AttributeError, KeyError, TypeError) as error:
        raise ValueError("Incomplete or malformed SAVE result") from error


def inspect_pair(candidate: Path, witness: SaveWitness):
    outcome = {
        "candidate": str(candidate), "classification": "unreadable",
        "main_crc_valid": None, "main_matches": None, "sidecar_matches": None,
        "fork_anchor_after": str(witness.after.snapshot),
        "restore_in_place": False, "journal_reset_or_replay_authorized": False,
        "next_delivery_index": None, "live_delivery_authorized": False,
    }
    try:
        files, metadata, tree = capture_stable_archive(candidate)
    except (OSError, ValueError) as error:
        return {**outcome, "detail": str(error)}

    outcome["archive_tree_sha256"] = tree_digest(tree)

    def match(hash_value, before, after):
        if hash_value == before:
            return "before"
        if hash_value == after:
            return "after"
        return "unknown"

    main = outcome["main_matches"] = match(
        digest(files["main"]), witness.before.main_sha256, witness.after.main_sha256,
    )
    side = outcome["sidecar_matches"] = (
        match(digest(files[NAME]), witness.before.sidecar_sha256, witness.after.sidecar_sha256)
        if NAME in files else "missing"
    )
    try:
        validate_save(files["main"])
    except ValueError as error:
        return {**outcome, "classification": "invalid-main", "main_crc_valid": False, "detail": str(error)}
    outcome["main_crc_valid"] = True
    if digest(metadata) != witness.metadata_sha256 or tree["directories"] or set(files) - {"main", NAME}:
        state = "unexpected-archive-layout"
    elif side == "missing":
        state = "missing-sidecar"
    elif main == side and main != "unknown":
        anchor = witness.before if main == "before" else witness.after
        state = f"observed-{main}" if outcome["archive_tree_sha256"] == anchor.tree_sha256 else "unknown-pair"
    elif main != "unknown" and side != "unknown":
        state = f"split-main-{main}-sidecar-{side}"
    else:
        state = "unknown-pair"
    outcome["classification"] = state
    return outcome


def require_observed_after(result):
    if result["classification"] != "observed-after":
        raise ValueError(f"Sidecar reload refused: {result['classification']}; expected observed-after")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--save-result", type=Path, required=True, help="Trusted local sidecar-save result.json")
    parser.add_argument("--archive-main", type=Path, required=True, help="Candidate archive's 00000001/main")
    args = parser.parse_args()
    try:
        result = inspect_pair(args.archive_main, load_witness(args.save_result))
    except (OSError, ValueError) as error:
        parser.exit(1, f"Sidecar inspection failed: {error}\n")
    print(json.dumps(result, indent=2))
    return 0 if result["classification"] in ("observed-before", "observed-after") else 1


if __name__ == "__main__":
    raise SystemExit(main())

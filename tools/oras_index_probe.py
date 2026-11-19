"""Synthetic two-checkpoint index fixture. Never an AP delivery ledger."""

from pathlib import Path
import secrets
import struct

from oras_archive import capture_stable_archive, tree_digest
from oras_footer_binding import FOOTER_SIZE
from oras_profiles import digest, validate_snapshot
from oras_save import METADATA_OFFSET, inventory_bytes, validate_save
from oras_save_objects import OR_HASH
from oras_sidecar_probe import FILE_SIZE, MARKER_OFFSET, NAME, TEST_METADATA


INDEX_MAGIC = b"ORASIDX1"
INDEX_OFFSET = 16
INDEX_TAG = b"TIDX"


def index_payload(main, binding, index):
    validate_save(main)
    if len(binding) != 8 or not any(binding) or type(index) is not int or index not in (0, 1):
        raise ValueError("Invalid synthetic index fixture")
    return (INDEX_MAGIC + binding + struct.pack("<I", index)
            + main[METADATA_OFFSET:METADATA_OFFSET + FOOTER_SIZE] + INDEX_TAG)


def new_index_payload(main):
    binding = (1 + secrets.randbelow((1 << 64) - 1)).to_bytes(8, "little")
    return index_payload(main, binding, 0)


def parse_index_payload(payload):
    if len(payload) != FILE_SIZE or not payload.startswith(INDEX_MAGIC) or payload[MARKER_OFFSET:] != INDEX_TAG:
        raise ValueError("Not a complete synthetic index sidecar")
    binding = payload[8:INDEX_OFFSET]
    index, = struct.unpack_from("<I", payload, INDEX_OFFSET)
    if not any(binding) or index not in (0, 1):
        raise ValueError("Synthetic index or binding outside experiment")
    return binding, index


def _capture_index_archive(target: Path):
    files, metadata, tree = capture_stable_archive(target)
    if set(files) != {"main", NAME} or tree["directories"] or metadata != TEST_METADATA:
        raise ValueError("Unexpected synthetic index archive layout")
    payload = files[NAME]
    binding, index = parse_index_payload(payload)
    matches = payload == index_payload(files["main"], binding, index)
    return files["main"], payload, {
        "binding": binding.hex(), "synthetic_index": index, "footer_matches": matches,
        "main_sha256": digest(files["main"]), "payload_sha256": digest(payload),
        "footer_sha256": digest(payload[20:MARKER_OFFSET]), "metadata_sha256": digest(metadata),
        "archive_tree_sha256": tree_digest(tree),
        "next_delivery_index": None, "live_delivery_authorized": False,
    }


def inspect_index_archive(target: Path):
    _, payload, report = _capture_index_archive(target)
    if not report["footer_matches"]:
        raise ValueError("Synthetic index sidecar does not match main's footer")
    return payload, report


def inspect_interrupted_index(target: Path, before, expected_inventory):
    """Require the observed main-only advance; never treat it as an anchor."""
    main, _, report = _capture_index_archive(target)
    inventory = inventory_bytes(main)
    if (before["synthetic_index"] != 0 or report["synthetic_index"] != 0
            or report["binding"] != before["binding"] or report["footer_matches"]
            or report["payload_sha256"] != before["payload_sha256"]
            or inventory != expected_inventory):
        raise ValueError("Expected updated main inventory with the exact pre-SAVE index-0 sidecar")
    return {
        **report, "inventory_sha256": digest(inventory),
        "classification": "inventory-advanced-index-stale",
        "main_crc_valid": True, "reload_authorized": False, "replay_authorized": False,
    }


def load_index_anchor(snapshot: Path):
    manifest = validate_snapshot(snapshot, OR_HASH)
    if manifest["schema_version"] != 2 or manifest["program_id"] != "000400000011C400":
        raise ValueError("Synthetic index anchor requires an exact OR snapshot v2")
    _, anchor = inspect_index_archive(snapshot / "00000001/main")
    if anchor["synthetic_index"] != 1 or anchor["archive_tree_sha256"] != manifest["archive_tree_sha256"]:
        raise ValueError("Synthetic index anchor must match an intact index-1 snapshot")
    return anchor


def require_index_anchor(candidate, anchor):
    if candidate["binding"] != anchor["binding"]:
        raise ValueError("Synthetic index archive has a different trial binding")
    if candidate["synthetic_index"] < anchor["synthetic_index"]:
        raise ValueError("Coherent rollback: synthetic index is older than pinned checkpoint")
    if candidate != anchor:
        raise ValueError("Synthetic index archive differs from pinned checkpoint")


def verify_index_transition(before, after, ram_sha256):
    if (before["synthetic_index"] != 0 or after["synthetic_index"] != 1
            or before["binding"] != after["binding"]
            or before["footer_sha256"] == after["footer_sha256"]
            or after["payload_sha256"] != ram_sha256):
        raise ValueError("Synthetic native index transition not corroborated")

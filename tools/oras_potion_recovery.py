"""Preview a read-only fork of the last intact checkpoint of one interrupted Potion trial."""

import argparse
import json
from pathlib import Path
import signal

from oras_index_probe import inspect_index_archive, inspect_interrupted_index
from oras_profiles import digest
from oras_save import BLOCKS, inventory_bytes, inventory_entries
from oras_save_interruption import barrier_caller
from oras_sidecar_recovery import OR_HASH, OR_TITLE, load_checkpoint
from run_bizhawk_save_probe import save_destination


def recovery_plan(seed: Path, result: Path):
    if result.is_symlink() or not result.is_file() or result.stat().st_size > 1024 * 1024:
        raise ValueError("Expected a bounded local interruption result")
    report = json.loads(result.read_bytes())
    try:
        return verify_interruption(seed, result.parent, report)
    except (KeyError, TypeError, AttributeError) as error:
        raise ValueError("Incomplete Potion interruption result") from error


def verify_interruption(seed, profile, report):
    """The local witness is trusted; both referenced archives must still match it."""
    stop = report["interruption"]
    caller = barrier_caller(bytes.fromhex(stop["barrier_hex"]))
    if (report["schema_version"] != 1 or report["status"] != "complete"
            or report["bootstrap"]["mode"] != "sidecar-index-potion-interrupt"
            or report["rom_identity"]["rom_sha256"] != OR_HASH or report["rom_identity"]["program_id"] != OR_TITLE
            or report["exit_code"] != -signal.SIGKILL or not caller or caller != stop["caller_return"]
            or stop["sigkill_confirmed"] is not True or stop["sidecar_ram_unchanged"] is not True
            or report["memory_write_requests"] != 1 or report.get("backup_after_exit") is not None
            or report["full_archive_source_unchanged"] is not True
            or report["potion_experiment"]["status"] != "full_inventory_readback_verified"):
        raise ValueError("Expected a verified interrupted Potion SAVE")
    snapshot = Path(report["backup_before_launch"])
    if seed.resolve() != (snapshot / "00000001/main").resolve():
        raise ValueError("Expected the interrupted run's explicit pre-SAVE snapshot")
    forensic = save_destination(profile.resolve() / "runtime", OR_TITLE)
    if Path(report["forensic_archive"]).resolve() != forensic.parent.resolve():
        raise ValueError("Forensic archive is not the interrupted profile's archive")
    checkpoint, files = load_checkpoint(snapshot)
    _, anchor = inspect_index_archive(seed)
    if (anchor != report["sidecar_index_before"] or checkpoint.tree_sha256 != anchor["archive_tree_sha256"]
            or anchor["synthetic_index"] != 0):
        raise ValueError("Pre-SAVE checkpoint differs from interruption witness")
    inventory = bytearray(inventory_bytes(files["main"]))
    if (inventory[0x970:0x974] != b"\x11\x00\x01\x00"
            or sum(row["item_id"] == 17 for row in inventory_entries(inventory)) != 1):
        raise ValueError("Expected one Potion in the witnessed pre-SAVE slot")
    inventory[0x972] = 2
    split = inspect_interrupted_index(forensic, anchor, bytes(inventory))
    if (split != report["interrupted_pair"] or split["inventory_sha256"] !=
            report["potion_experiment"]["readback"]["sha256"]):
        raise ValueError("Interrupted archive differs from its recorded split")
    main = forensic.read_bytes()
    if digest(main) != split["main_sha256"]:
        raise ValueError("Interrupted main changed while inspecting progress")
    return {
        "anchor": anchor, "interrupted_tree_sha256": split["archive_tree_sha256"],
        "fork_snapshot": str(snapshot.resolve()), "interrupted_main": str(forensic),
        "potion_quantity_in_interrupted_main": 2, "potion_quantity_in_fork": 1,
        "changed_main_block_ids_not_carried_into_fork": [
            i for i, (offset, length) in enumerate(BLOCKS)
            if main[offset:offset + length] != files["main"][offset:offset + length]
        ],
        "restore_in_place": False, "delivery_replay_authorized": False,
        "next_delivery_index": None, "live_delivery_authorized": False,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed-save", required=True, type=Path)
    parser.add_argument("--interrupted-potion-result", required=True, type=Path)
    args = parser.parse_args()
    try:
        print(json.dumps(recovery_plan(args.seed_save, args.interrupted_potion_result), indent=2))
    except (OSError, ValueError) as error:
        parser.exit(1, f"Potion recovery refused: {error}\n")

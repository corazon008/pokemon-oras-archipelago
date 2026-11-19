"""Offline mismatch controls using synthetic saves; no emulator or AP journal."""

from pathlib import Path
import json
import struct
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from oras_profiles import digest, snapshot_save, validate_snapshot
from oras_save import BLOCKS
from oras_sidecar_probe import FILE_SIZE, NAME, PREFIX, TEST_METADATA, WRITE_CALLERS, after_save_payload
from oras_sidecar_recovery import (
    OR_HASH, OR_TITLE, inspect_pair, load_witness, require_observed_after, verify_witness,
)
from save_fixtures import synthetic_save, update_fixture_crcs


def write_archive(root, main, sidecar, metadata=TEST_METADATA):
    path = root / "00000001/main"
    path.parent.mkdir(parents=True)
    path.write_bytes(main)
    if sidecar is not None:
        (path.parent / NAME).write_bytes(sidecar)
    path.parent.with_suffix(".metadata").write_bytes(metadata)
    return path


def fixture(root):
    old_main = bytes(synthetic_save())
    new_main = bytearray(old_main)
    new_main[BLOCKS[3][0]] ^= 1
    update_fixture_crcs(new_main)
    old_sidecar = PREFIX.ljust(FILE_SIZE, b"\0")
    new_sidecar = after_save_payload(old_sidecar)
    mains, sidecars = (old_main, bytes(new_main)), (old_sidecar, new_sidecar)
    snapshots = [
        snapshot_save(write_archive(root / label, m, s), OR_TITLE, OR_HASH, label, root / "backups")
        for label, m, s in zip(("before", "after"), mains, sidecars, strict=True)
    ]
    hashes = [validate_snapshot(snapshot)["archive_tree_sha256"] for snapshot in snapshots]
    caller = WRITE_CALLERS[0] + 4
    report = {
        "schema_version": 1, "status": "complete", "exit_code": 0, "memory_write_requests": 0,
        "rom_identity": {"rom_sha256": OR_HASH, "program_id": OR_TITLE},
        "bootstrap": {"mode": "sidecar-save"}, "native_save_macro_completed": True,
        "full_archive_source_unchanged": True, "save_unchanged": False,
        "sidecar_write_status_hex": struct.pack("<4I", 1, caller, 0, 1).hex(),
        "backup_before_launch": str(snapshots[0]), "backup_after_exit": str(snapshots[1]),
        "sidecar_fixture": {
            "native_save_tested": True, "host_seeded": True, "sha256": digest(old_sidecar),
            "archive_tree_before_boot": hashes[0], "archive_tree_after_exit": hashes[1],
        },
        "save_sha256_before_launch": digest(old_main), "resulting_save": {"save_sha256": digest(new_main)},
        "sidecar_save": {"return_address": caller, "native_write_result": 0, "payload_sha256": digest(new_sidecar)},
    }
    return report, mains, sidecars


class SidecarRecoveryTests(unittest.TestCase):
    def test_self_consistent_snapshots_of_split_pairs_are_blocked(self):
        with tempfile.TemporaryDirectory(dir="/tmp/opencode") as tmp:
            root = Path(tmp)
            report, main, sidecar = fixture(root)
            witness = verify_witness(report)
            for index, (m, s, expected) in enumerate((
                (0, 0, "observed-before"), (1, 1, "observed-after"),
                (1, 0, "split-main-after-sidecar-before"), (0, 1, "split-main-before-sidecar-after"),
            )):
                with self.subTest(classification=expected):
                    raw = write_archive(root / f"candidate-{index}", main[m], sidecar[s])
                    snap = snapshot_save(raw, OR_TITLE, OR_HASH, "capture", root / "backups")
                    validate_snapshot(snap, OR_HASH)
                    archive = snap / "00000001/main"
                    result = inspect_pair(archive, witness)
                    self.assertEqual(result["classification"], expected)
                    self.assertTrue(result["main_crc_valid"])
                    self.assertFalse(result["restore_in_place"])
                    self.assertFalse(result["journal_reset_or_replay_authorized"])
                    self.assertFalse(result["live_delivery_authorized"])
                    self.assertIsNone(result["next_delivery_index"])
                    self.assertEqual(archive.read_bytes(), main[m])
                    if m == s == 1:
                        require_observed_after(result)
                    else:
                        with self.assertRaisesRegex(ValueError, expected):
                            require_observed_after(result)

    def test_corrupt_unknown_missing_and_extra_data_classifications(self):
        with tempfile.TemporaryDirectory(dir="/tmp/opencode") as tmp:
            root = Path(tmp)
            report, main, sidecar = fixture(root)
            witness = verify_witness(report)
            damaged = bytearray(main[1])
            damaged[BLOCKS[3][0]] ^= 2
            wrong_metadata = b"\0" * len(TEST_METADATA)
            for m, s, md, expected in (
                (damaged, sidecar[1], TEST_METADATA, "invalid-main"),
                (main[1], sidecar[1][:-1], TEST_METADATA, "unknown-pair"),
                (main[1], None, TEST_METADATA, "missing-sidecar"),
                (main[1], sidecar[1], wrong_metadata, "unexpected-archive-layout"),
            ):
                candidate = write_archive(root / expected, m, s, md)
                self.assertEqual(inspect_pair(candidate, witness)["classification"], expected)
            candidate = write_archive(root / "extra", main[1], sidecar[1])
            (candidate.parent / "extra").mkdir()
            self.assertEqual(inspect_pair(candidate, witness)["classification"], "unexpected-archive-layout")
            self.assertEqual(inspect_pair(root / "missing/main", witness)["classification"], "unreadable")

    def test_witness_refuses_incomplete_write_wrong_identity_or_rebound_snapshot(self):
        with tempfile.TemporaryDirectory(dir="/tmp/opencode") as tmp:
            root = Path(tmp)
            report, main, sidecar = fixture(root)
            wrong = snapshot_save(write_archive(root / "mixed", main[0], sidecar[1]),
                                  OR_TITLE, OR_HASH, "mixed", root / "backups")
            for change in (
                {"status": "failed"}, {"forced_shutdown": True}, {"memory_write_requests": 1},
                {"rom_identity": {"rom_sha256": OR_HASH, "program_id": "000400000011C500"}},
                {"sidecar_write_status_hex": bytes(16).hex()}, {"backup_after_exit": str(wrong)},
                {"resulting_save": {"save_sha256": digest(main[0])}},
            ):
                with self.subTest(change=change), self.assertRaises(ValueError):
                    verify_witness({**report, **change})
            path = root / "result.json"
            path.write_text(json.dumps(report))
            self.assertEqual(load_witness(path).after.snapshot, Path(report["backup_after_exit"]))
            path.write_text("{}")
            with self.assertRaises(ValueError):
                load_witness(path)

    def test_reload_cli_requires_witness_and_other_modes_reject_it(self):
        for mode, extra in (("sidecar-reload", []), ("sidecar-load", ["--sidecar-save-result", "result.json"])):
            run = subprocess.run(
                [sys.executable, str(ROOT / "tools/run_bizhawk_connector_probe.py"), "--rom", "unused",
                 "--seed-save", "unused", "--experimental-bootstrap", mode, *extra],
                capture_output=True, text=True, timeout=10,
            )
            self.assertEqual(run.returncode, 2)
            self.assertIn("--sidecar-save-result is required", run.stderr)


if __name__ == "__main__":
    unittest.main()

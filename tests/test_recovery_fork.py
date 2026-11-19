"""Synthetic recovery snapshots only; no archive is restored in place."""

from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from oras_profiles import snapshot_save
from run_bizhawk_connector_probe import recovery_snapshot_reference
from save_fixtures import synthetic_save


ROM = "a" * 64
IDENTITY = {"rom_sha256": ROM, "program_id": "000400000011C400"}


class RecoveryForkTests(unittest.TestCase):
    def snapshot(self, root):
        source = root / "source/00000001"
        source.mkdir(parents=True)
        (source / "main").write_bytes(synthetic_save())
        source.with_suffix(".metadata").write_bytes(bytes(16))
        return snapshot_save(source / "main", IDENTITY["program_id"], ROM, "synthetic", root / "snapshots")

    def test_verified_snapshot_does_not_authorize_delivery_or_inplace_restore(self):
        with tempfile.TemporaryDirectory(dir="/tmp/opencode") as directory:
            root = Path(directory)
            snapshot = self.snapshot(root)
            before = {p: p.read_bytes() for p in snapshot.rglob("*") if p.is_file()}
            reference = recovery_snapshot_reference(snapshot, IDENTITY)
            self.assertFalse(reference["restore_in_place"])
            self.assertFalse(reference["live_delivery_authorized"])
            self.assertFalse(reference["journal_reset_or_replay_authorized"])
            self.assertIsNone(reference["next_delivery_index"])
            self.assertEqual(before, {p: p.read_bytes() for p in before})

    def test_wrong_rom_title_or_corrupt_snapshot_fails(self):
        with tempfile.TemporaryDirectory(dir="/tmp/opencode") as directory:
            snapshot = self.snapshot(Path(directory))
            for identity in ({**IDENTITY, "rom_sha256": "b" * 64},
                             {**IDENTITY, "program_id": "000400000011C500"}):
                with self.assertRaises(ValueError):
                    recovery_snapshot_reference(snapshot, identity)
            (snapshot / "00000001/main").write_bytes(b"partial")
            with self.assertRaises(ValueError):
                recovery_snapshot_reference(snapshot, IDENTITY)

    def test_cli_refuses_live_profile_or_write_modes(self):
        for options in (["--session", "existing"], ["--seed-save", "source"],
                        ["--observe-native-save"], ["--experimental-potion-1-to-2"],
                        ["--steps", "1:A"]):
            result = subprocess.run(
                [sys.executable, str(ROOT / "tools/run_bizhawk_connector_probe.py"),
                 "--rom", "synthetic.3ds", "--recover-from-snapshot", "snapshot", *options],
                text=True, capture_output=True, timeout=10,
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("new read-only profile", result.stderr)


if __name__ == "__main__":
    unittest.main()

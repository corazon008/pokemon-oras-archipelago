"""Durable snapshots tested only with synthetic saves, never real game data."""

import json
import contextlib
import io
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from oras_profiles import PROFILE_ROOT, backup_existing_save, snapshot_save, validate_profile_path, validate_snapshot
from save_fixtures import synthetic_save
import run_bizhawk_save_probe as runner

TITLE = "000400000011C400"
ROM = "a" * 64


def make_save(root):
    source = root / "00000001/main"
    source.parent.mkdir(parents=True)
    source.write_bytes(synthetic_save(fill=1))
    source.parent.with_suffix(".metadata").write_bytes(bytes(range(16)))
    return source


class ProfileTests(unittest.TestCase):
    def test_durable_snapshot_survives_loss_of_temporary_source(self):
        with tempfile.TemporaryDirectory(dir="/tmp/opencode") as directory:
            durable = Path(directory) / "durable"
            with tempfile.TemporaryDirectory(dir="/tmp/opencode") as transient:
                source = make_save(Path(transient))
                expected = source.read_bytes()
                snapshot = snapshot_save(source, TITLE, ROM, "before-test", durable)
                self.assertEqual(source.read_bytes(), expected)
            self.assertFalse(source.exists())
            manifest = validate_snapshot(snapshot, ROM)
            self.assertEqual(manifest["validated_crc_blocks"], 58)
            self.assertEqual((snapshot / "00000001/main").read_bytes(), expected)
            self.assertFalse(snapshot.name.startswith(".partial-"))
            self.assertEqual(os.stat(snapshot).st_mode & 0o777, 0o700)
            self.assertEqual(os.stat(snapshot / "00000001/main").st_mode & 0o777, 0o600)

    def test_snapshots_never_replace_previous_copy(self):
        with tempfile.TemporaryDirectory(dir="/tmp/opencode") as directory:
            root = Path(directory)
            source = make_save(root / "source")
            first = snapshot_save(source, TITLE, ROM, "test", root / "backups")
            second = snapshot_save(source, TITLE, ROM, "test", root / "backups")
            self.assertNotEqual(first, second)
            self.assertEqual(validate_snapshot(first, ROM)["save_sha256"],
                             validate_snapshot(second, ROM)["save_sha256"])

    def test_extra_archive_entries_preserved_but_raw_import_still_refused(self):
        for kind in ("file", "directory"):
            with tempfile.TemporaryDirectory(dir="/tmp/opencode") as directory:
                root = Path(directory)
                source = make_save(root / "source")
                extra = source.parent / "ap-ledger"
                if kind == "file":
                    extra.write_bytes(b"must preserve")
                else:
                    extra.mkdir()
                before = source.read_bytes()
                snapshot = snapshot_save(source, TITLE, ROM, "test", root / "backups")
                self.assertTrue((snapshot / "00000001/ap-ledger").exists())
                target = root / "target/00000001/main"
                with self.assertRaisesRegex(ValueError, "multi-file archive"):
                    runner.seed_archive(source, target)
                self.assertFalse(target.parent.exists())
                self.assertEqual(validate_snapshot(snapshot, ROM)["schema_version"], 2)
                self.assertEqual(source.read_bytes(), before)
                self.assertTrue(extra.exists())

    def test_snapshot_with_unmanifested_sidecar_is_not_recoverable(self):
        with tempfile.TemporaryDirectory(dir="/tmp/opencode") as directory:
            root = Path(directory)
            source = make_save(root / "source")
            snapshot = snapshot_save(source, TITLE, ROM, "test", root / "backups")
            (snapshot / "00000001/ap-ledger").write_bytes(b"unmanifested")
            with self.assertRaisesRegex(ValueError, "inventory/integrity"):
                validate_snapshot(snapshot, ROM)

    def test_invalid_save_does_not_publish_backup(self):
        with tempfile.TemporaryDirectory(dir="/tmp/opencode") as directory:
            root = Path(directory)
            source = make_save(root / "source")
            bad = bytearray(source.read_bytes())
            bad[0x400] ^= 1
            source.write_bytes(bad)
            with self.assertRaisesRegex(ValueError, "checksum"):
                snapshot_save(source, TITLE, ROM, "test", root / "backups")
            self.assertFalse((root / "backups").exists())

    def test_missing_or_invalid_metadata_refused(self):
        with tempfile.TemporaryDirectory(dir="/tmp/opencode") as directory:
            root = Path(directory)
            source = make_save(root / "source")
            metadata = source.parent.with_suffix(".metadata")
            metadata.unlink()
            with self.assertRaises(FileNotFoundError):
                snapshot_save(source, TITLE, ROM, "test", root / "backups")
            metadata.write_bytes(b"invalid")
            with self.assertRaisesRegex(ValueError, "16-byte"):
                snapshot_save(source, TITLE, ROM, "test", root / "backups")

    def test_corruption_wrong_rom_and_tampered_metadata_refused(self):
        with tempfile.TemporaryDirectory(dir="/tmp/opencode") as directory:
            root = Path(directory)
            source = make_save(root / "source")
            snapshot = snapshot_save(source, TITLE, ROM, "test", root / "backups")
            with self.assertRaisesRegex(ValueError, "identity mismatch"):
                validate_snapshot(snapshot, "b" * 64)
            (snapshot / "00000001.metadata").write_bytes(b"x" * 16)
            with self.assertRaisesRegex(ValueError, "integrity"):
                validate_snapshot(snapshot, ROM)
            (snapshot / "00000001/main").write_bytes(bytes(0x76000))
            with self.assertRaisesRegex(ValueError, "footer"):
                validate_snapshot(snapshot, ROM)

    def test_failed_publication_is_not_a_completed_snapshot(self):
        with tempfile.TemporaryDirectory(dir="/tmp/opencode") as directory:
            root = Path(directory)
            source = make_save(root / "source")
            with patch("oras_profiles.validate_snapshot", side_effect=ValueError("copy failed")):
                with self.assertRaisesRegex(ValueError, "copy failed"):
                    snapshot_save(source, TITLE, ROM, "test", root / "backups")
            self.assertTrue(all(p.name.startswith(".partial-") for p in (root / "backups").iterdir()))
            self.assertEqual(source.read_bytes(), synthetic_save(fill=1))

    def test_changing_source_is_rejected_before_copy(self):
        with tempfile.TemporaryDirectory(dir="/tmp/opencode") as directory:
            root = Path(directory)
            source = make_save(root / "source")
            from oras_archive import capture_archive, tree_manifest
            first = capture_archive(source.parent)
            changed = {"main": synthetic_save(fill=2)}
            second = (changed, tree_manifest(changed, []))
            with patch("oras_archive.capture_archive", side_effect=[first, second]):
                with self.assertRaisesRegex(ValueError, "Source changed"):
                    snapshot_save(source, TITLE, ROM, "test", root / "backups")
            self.assertFalse((root / "backups").exists())

    def test_bad_identity_and_labels_refused(self):
        for title, rom, label in [(TITLE, ROM, "../bad"), ("0" * 16, ROM, "test"), (TITLE, "bad", "test")]:
            with self.subTest(title=title, label=label), self.assertRaises(ValueError):
                snapshot_save(Path("unused"), title, rom, label)

    def test_missing_save_has_no_backup(self):
        with tempfile.TemporaryDirectory(dir="/tmp/opencode") as directory:
            self.assertIsNone(backup_existing_save(Path(directory) / "missing", TITLE, ROM, "test"))

    def test_persistent_and_legacy_paths_supported_but_roots_rejected(self):
        for root in (PROFILE_ROOT, Path("/tmp/opencode")):
            self.assertEqual(validate_profile_path(root / "session"), (root / "session").resolve())
            with self.assertRaisesRegex(ValueError, "private children"):
                validate_profile_path(root)
        with self.assertRaises(ValueError):
            validate_profile_path(Path("/home"))

    def test_snapshot_manifest_is_not_authenticity_or_trusted_path_input(self):
        with tempfile.TemporaryDirectory(dir="/tmp/opencode") as directory:
            root = Path(directory)
            snapshot = snapshot_save(make_save(root / "source"), TITLE, ROM, "test", root / "backups")
            manifest = json.loads((snapshot / "snapshot.json").read_text())
            manifest["rom_sha256"] = "invalid"
            (snapshot / "snapshot.json").write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, "identity"):
                validate_snapshot(snapshot)

    def test_native_runner_backs_up_before_and_after_emulator(self):
        with tempfile.TemporaryDirectory(dir="/tmp/opencode") as directory:
            root = Path(directory)
            session = root / "session"
            runtime = session / "runtime"
            runtime.mkdir(parents=True)
            (runtime / "config.ini").write_text("{}")
            (session / "profile.json").write_text(json.dumps({
                "kind": "oras_native_save_probe", "rom_sha256": ROM,
                "seed_source": None, "archive_metadata_source": None,
            }))
            target = runner.save_destination(runtime, TITLE)
            target.parent.mkdir(parents=True)
            target.write_bytes(synthetic_save(fill=1))
            target.parent.with_suffix(".metadata").write_bytes(bytes(range(16)))
            backup_root = root / "durable/backups"

            def backup(source, title, rom, label):
                return str(snapshot_save(source, title, rom, label, backup_root))

            def emulate(*args, **kwargs):
                published = list(backup_root.glob("before-launch-*"))
                self.assertEqual(len(published), 1)
                self.assertEqual((published[0] / "00000001/main").read_bytes(), synthetic_save(fill=1))
                target.write_bytes(synthetic_save(fill=2))
                return type("Result", (), {"returncode": 0})()

            with (
                patch.object(sys, "argv", ["probe", "--rom", "unused", "--session", str(session), "--interactive"]),
                patch.object(runner, "PROFILE_ROOT", root / "durable/profiles"),
                patch.object(runner, "inspect_rom", return_value=({"edition_from_program_id": "OR", "program_id": TITLE}, None)),
                patch.object(runner, "sha256_file", return_value=ROM),
                patch.object(runner.shutil, "which", return_value="mono"),
                patch.object(runner, "backup_existing_save", side_effect=backup),
                patch.object(runner.subprocess, "run", side_effect=emulate),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(runner.main(), 0)
            attempt = next(session.glob("attempt-*"))
            report = json.loads((attempt / "result.json").read_text())
            self.assertEqual((Path(report["backup_after_exit"]) / "00000001/main").read_bytes(),
                             synthetic_save(fill=2))
            validate_snapshot(Path(report["backup_before_launch"]), ROM)
            validate_snapshot(Path(report["backup_after_exit"]), ROM)


if __name__ == "__main__":
    unittest.main()

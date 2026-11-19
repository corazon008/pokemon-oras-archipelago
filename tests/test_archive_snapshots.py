"""Synthetic full archives. Sidecars are transport fixtures, not AP ledgers."""

import json
import os
import shutil
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from oras_archive import capture_archive, safe_archive_path, source_archive_unchanged
from oras_profiles import snapshot_save, validate_snapshot
from run_bizhawk_save_probe import seed_archive
from run_bizhawk_connector_probe import recovery_snapshot_reference
from save_fixtures import synthetic_save


TITLE, ROM = "000400000011C400", "a" * 64


def make_archive(root, extras=True):
    source = root / "source/00000001/main"
    source.parent.mkdir(parents=True)
    source.write_bytes(synthetic_save())
    source.parent.with_suffix(".metadata").write_bytes(bytes(16))
    if extras:
        (source.parent / "empty").mkdir()
        (source.parent / "proof").mkdir()
        (source.parent / "proof/sentinel.bin").write_bytes(b"NOT AN AP LEDGER")
        (source.parent / "extra").write_bytes(b"\0\xff\0")
    return source


class FullArchiveTests(unittest.TestCase):
    def test_v2_roundtrip_preserves_files_empty_directories_and_sources(self):
        with tempfile.TemporaryDirectory(dir="/tmp/opencode") as directory:
            root = Path(directory)
            source = make_archive(root)
            before = capture_archive(source.parent)
            snapshot = snapshot_save(source, TITLE, ROM, "full", root / "snapshots")
            manifest = validate_snapshot(snapshot, ROM)
            self.assertEqual(manifest["schema_version"], 2)
            self.assertEqual(len(manifest["archive_tree"]["files"]), 3)
            target = root / "fork/00000001/main"
            imported = seed_archive(snapshot / "00000001/main", target, TITLE, ROM)
            self.assertEqual(before, capture_archive(target.parent))
            self.assertEqual(before, capture_archive(source.parent))
            self.assertEqual(imported["archive_file_count"], 3)
            self.assertTrue(source_archive_unchanged(imported))
            identity = {"program_id": TITLE, "rom_sha256": ROM}
            receipt = recovery_snapshot_reference(snapshot, identity)
            self.assertEqual(receipt["source_archive_tree_sha256"], manifest["archive_tree_sha256"])
            self.assertIsNone(receipt["next_delivery_index"])
            self.assertFalse(receipt["journal_reset_or_replay_authorized"])
            self.assertEqual(os.stat(target.parent / "empty").st_mode & 0o777, 0o700)
            self.assertEqual(os.stat(target.parent / "extra").st_mode & 0o777, 0o600)

    def test_missing_changed_added_or_renamed_file_and_empty_directory_rejected(self):
        for change in ("missing", "changed", "added", "renamed", "empty_directory"):
            with tempfile.TemporaryDirectory(dir="/tmp/opencode") as directory:
                root = Path(directory)
                snapshot = snapshot_save(make_archive(root), TITLE, ROM, "full", root / "snapshots")
                archive = snapshot / "00000001"
                if change == "missing":
                    (archive / "extra").unlink()
                elif change == "changed":
                    (archive / "extra").write_bytes(b"changed")
                elif change == "added":
                    (archive / "added").write_bytes(b"unmanifested")
                elif change == "renamed":
                    (archive / "extra").rename(archive / "other")
                else:
                    (archive / "empty").rmdir()
                target = root / "fork/00000001/main"
                with self.subTest(change=change), self.assertRaises(ValueError):
                    seed_archive(archive / "main", target, TITLE, ROM)
                self.assertFalse(target.parent.exists())

    def test_v1_compatibility_and_unknown_schema_refusal(self):
        with tempfile.TemporaryDirectory(dir="/tmp/opencode") as directory:
            root = Path(directory)
            snapshot = snapshot_save(make_archive(root, False), TITLE, ROM, "old", root / "snapshots")
            path = snapshot / "snapshot.json"
            manifest = json.loads(path.read_text())
            manifest.pop("archive_tree")
            manifest.pop("archive_tree_sha256")
            manifest["schema_version"] = 1
            path.write_text(json.dumps(manifest))
            self.assertEqual(validate_snapshot(snapshot)["schema_version"], 1)
            seed_archive(snapshot / "00000001/main", root / "fork/00000001/main", TITLE, ROM)
            for version in (True, None, 0, 3, "2"):
                manifest["schema_version"] = version
                path.write_text(json.dumps(manifest))
                with self.subTest(version=version), self.assertRaisesRegex(ValueError, "schema version"):
                    validate_snapshot(snapshot)

    def test_multi_file_import_requires_manifest_and_matching_explicit_identity(self):
        with tempfile.TemporaryDirectory(dir="/tmp/opencode") as directory:
            root = Path(directory)
            source = make_archive(root)
            with self.assertRaisesRegex(ValueError, "multi-file archive"):
                seed_archive(source, root / "raw/00000001/main", TITLE, ROM)
            snapshot = snapshot_save(source, TITLE, ROM, "full", root / "snapshots")
            for title, rom in ((None, None), (TITLE, "b" * 64), ("000400000011C500", ROM)):
                target = root / "fork/00000001/main"
                with self.subTest(title=title, rom=rom), self.assertRaises(ValueError):
                    seed_archive(snapshot / "00000001/main", target, title, rom)
                self.assertFalse(target.parent.exists())

    def test_manifest_path_traversal_duplicate_and_wrong_types_rejected(self):
        for change in ("traversal", "absolute", "duplicate", "bool_size"):
            with tempfile.TemporaryDirectory(dir="/tmp/opencode") as directory:
                root = Path(directory)
                snapshot = snapshot_save(make_archive(root), TITLE, ROM, "full", root / "snapshots")
                path = snapshot / "snapshot.json"
                manifest = json.loads(path.read_text())
                rows = manifest["archive_tree"]["files"]
                if change == "traversal":
                    rows[0]["path"] = "../escape"
                elif change == "absolute":
                    rows[0]["path"] = "/etc/passwd"
                elif change == "duplicate":
                    rows.append(rows[0])
                else:
                    rows[0]["size"] = True
                path.write_text(json.dumps(manifest))
                with self.subTest(change=change), self.assertRaises(ValueError):
                    validate_snapshot(snapshot)
                self.assertFalse((root / "escape").exists())

    def test_links_special_files_and_unsafe_names_rejected_before_publication(self):
        for kind in ("symlink", "directory_symlink", "hardlink", "fifo", "bad_name"):
            with tempfile.TemporaryDirectory(dir="/tmp/opencode") as directory:
                root = Path(directory)
                source = make_archive(root, False)
                extra = source.parent / "extra"
                if kind == "symlink":
                    extra.symlink_to(source)
                elif kind == "directory_symlink":
                    extra.symlink_to(root, target_is_directory=True)
                elif kind == "hardlink":
                    os.link(source, extra)
                elif kind == "fifo":
                    os.mkfifo(extra)
                else:
                    (source.parent / "bad:name").write_bytes(b"unsupported")
                with self.subTest(kind=kind), self.assertRaises((ValueError, OSError)):
                    snapshot_save(source, TITLE, ROM, "bad", root / "snapshots")
                self.assertFalse((root / "snapshots").exists())

    def test_bounds_and_path_validation(self):
        for name in ("../main", "/main", "a//b", "a\\b", "a/./b", "a/../b", "a:b", "é", "/".join(["d"] * 9)):
            with self.subTest(name=name), self.assertRaises(ValueError):
                safe_archive_path(name)
        with tempfile.TemporaryDirectory(dir="/tmp/opencode") as directory:
            source = make_archive(Path(directory))
            for bound, value in (("MAX_FILES", 1), ("MAX_DIRECTORIES", 1), ("MAX_FILE_BYTES", 8),
                                 ("MAX_ARCHIVE_BYTES", 16)):
                with patch(f"oras_archive.{bound}", value):
                    with self.subTest(bound=bound), self.assertRaisesRegex(ValueError, "limit exceeded"):
                        capture_archive(source.parent)

    def test_existing_archive_or_metadata_never_overwritten(self):
        for collision in ("directory", "metadata"):
            with tempfile.TemporaryDirectory(dir="/tmp/opencode") as directory:
                root = Path(directory)
                snapshot = snapshot_save(make_archive(root), TITLE, ROM, "full", root / "snapshots")
                target = root / "fork/00000001/main"
                target.parent.parent.mkdir()
                existing = target.parent if collision == "directory" else target.parent.with_suffix(".metadata")
                if collision == "directory":
                    existing.mkdir()
                else:
                    existing.write_bytes(b"untouched")
                with self.assertRaises(FileExistsError):
                    seed_archive(snapshot / "00000001/main", target, TITLE, ROM)
                self.assertFalse(target.exists())
                if collision == "metadata":
                    self.assertEqual(existing.read_bytes(), b"untouched")

    def test_extra_source_file_change_detected_after_import(self):
        with tempfile.TemporaryDirectory(dir="/tmp/opencode") as directory:
            root = Path(directory)
            snapshot = snapshot_save(make_archive(root), TITLE, ROM, "full", root / "snapshots")
            imported = seed_archive(snapshot / "00000001/main", root / "fork/00000001/main", TITLE, ROM)
            (snapshot / "00000001/extra").write_bytes(b"changed")
            self.assertFalse(source_archive_unchanged(imported))

    def test_snapshot_destination_cannot_be_inside_source_archive(self):
        with tempfile.TemporaryDirectory(dir="/tmp/opencode") as directory:
            root = Path(directory)
            source = make_archive(root)
            with self.assertRaisesRegex(ValueError, "outside source archive"):
                snapshot_save(source, TITLE, ROM, "bad", source.parent / "backups")
            self.assertFalse((source.parent / "backups").exists())
            snapshot = snapshot_save(source, TITLE, ROM, "full", root / "snapshots")
            with self.assertRaisesRegex(ValueError, "outside source archive"):
                seed_archive(snapshot / "00000001/main", snapshot / "00000001/fork/main", TITLE, ROM)
            self.assertFalse((snapshot / "00000001/fork").exists())
            validate_snapshot(snapshot, ROM)

    def test_unpublished_snapshot_never_authorizes_import(self):
        with tempfile.TemporaryDirectory(dir="/tmp/opencode") as directory:
            root = Path(directory)
            snapshot = snapshot_save(make_archive(root), TITLE, ROM, "full", root / "snapshots")
            partial = root / ".partial-unpublished"
            shutil.copytree(snapshot, partial)
            with self.assertRaisesRegex(ValueError, "Unpublished partial"):
                seed_archive(partial / "00000001/main", root / "fork/00000001/main", TITLE, ROM)
            self.assertFalse((root / "fork").exists())


if __name__ == "__main__":
    unittest.main()

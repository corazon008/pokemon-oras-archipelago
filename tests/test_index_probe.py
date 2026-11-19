"""Synthetic fixtures for the one-SAVE native index experiment."""

from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from oras_index_probe import (
    INDEX_OFFSET, INDEX_TAG, index_payload, inspect_index_archive, load_index_anchor,
    parse_index_payload, require_index_anchor, verify_index_transition,
)
from oras_profiles import snapshot_save
from oras_save import BLOCKS, validate_save
from oras_save_objects import OR_HASH
from oras_sidecar_probe import NAME, TEST_METADATA, build_sidecar
from save_fixtures import synthetic_save, update_fixture_crcs


class IndexProbeTests(unittest.TestCase):
    def setUp(self):
        root = tempfile.TemporaryDirectory(dir="/tmp/opencode")
        self.addCleanup(root.cleanup)
        self.root = Path(root.name)
        self.token = b"test0001"
        self.old = bytes(synthetic_save())
        new = bytearray(self.old)
        new[BLOCKS[3][0]] ^= 1
        update_fixture_crcs(new)
        self.new = bytes(new)

    def make_archive(self, label, main, index, token=None):
        path = self.root / label / "00000001/main"
        path.parent.mkdir(parents=True)
        path.write_bytes(main)
        (path.parent / NAME).write_bytes(index_payload(main, self.token if token is None else token, index))
        path.parent.with_suffix(".metadata").write_bytes(TEST_METADATA)
        return path

    def test_coherent_rollback_is_distinct_from_a_corrupt_or_split_pair(self):
        old = self.make_archive("old", self.old, 0)
        new = self.make_archive("new", self.new, 1)
        snapshot = snapshot_save(new, "000400000011C400", OR_HASH, "new", self.root / "snapshots")
        anchor = load_index_anchor(snapshot)
        _, before = inspect_index_archive(old)
        _, after = inspect_index_archive(new)
        require_index_anchor(after, anchor)
        self.assertTrue(before["footer_matches"])
        self.assertIsNone(before["next_delivery_index"])
        self.assertFalse(after["live_delivery_authorized"])
        with self.assertRaisesRegex(ValueError, "Coherent rollback"):
            require_index_anchor(before, anchor)
        self.assertEqual((old.parent / NAME).read_bytes(), index_payload(self.old, self.token, 0))
        (old.parent / NAME).write_bytes((new.parent / NAME).read_bytes())
        with self.assertRaisesRegex(ValueError, "footer"):
            inspect_index_archive(old)

    def test_index_alone_cannot_substitute_for_pinned_archive(self):
        main = self.make_archive("pinned", self.new, 1)
        _, anchor = inspect_index_archive(main)
        for flag, token, save, error in (
            ("foreign", b"test0002", self.new, "trial binding"),
            ("same index", self.token, self.old, "differs from pinned"),
        ):
            candidate = self.make_archive(flag, save, 1, token)
            _, observed = inspect_index_archive(candidate)
            with self.subTest(flag=flag), self.assertRaisesRegex(ValueError, error):
                require_index_anchor(observed, anchor)

    def test_invalid_saved_index_and_corrupted_main_fail(self):
        payload = index_payload(self.new, self.token, 1)
        self.assertEqual(parse_index_payload(payload), (self.token, 1))
        self.assertEqual(payload[-4:], INDEX_TAG)
        for invalid in (payload[:INDEX_OFFSET] + struct.pack("<I", 2) + payload[20:],
                        payload[:8] + bytes(8) + payload[16:], payload[:-1]):
            with self.subTest(invalid=invalid[:20]), self.assertRaises(ValueError):
                parse_index_payload(invalid)
        target = self.make_archive("invalid", self.new, 1)
        corrupted = bytearray(self.new)
        corrupted[BLOCKS[3][0]] ^= 2
        target.write_bytes(corrupted)
        with self.assertRaisesRegex(ValueError, "checksum"):
            inspect_index_archive(target)
        with self.assertRaises(ValueError):
            validate_save(corrupted)

    def test_anchor_cannot_be_created_from_index_zero_or_wrong_title(self):
        for label, index, title in (("before", 0, "000400000011C400"), ("wrong-title", 1, "000400000011C500")):
            target = self.make_archive(label, self.old, index)
            snapshot = snapshot_save(target, title, OR_HASH, label, self.root / "snapshots")
            with self.subTest(label=label), self.assertRaises(ValueError):
                load_index_anchor(snapshot)

    def test_transition_cross_checks_footer_binding_and_entire_ram_payload(self):
        _, before = inspect_index_archive(self.make_archive("start", self.old, 0))
        _, after = inspect_index_archive(self.make_archive("end", self.new, 1))
        verify_index_transition(before, after, after["payload_sha256"])
        for replacement in ({"synthetic_index": 0}, {"binding": "0" * 16},
                            {"footer_sha256": before["footer_sha256"]}, {"payload_sha256": "0" * 64}):
            with self.subTest(replacement=replacement), self.assertRaises(ValueError):
                verify_index_transition(before, {**after, **replacement}, after["payload_sha256"])

    def test_patch_targets_numeric_index_not_format_tag(self):
        info = {"code_segments": [{"address": 0x100000, "image_offset": 0, "size": 0x500000}]}
        with patch("oras_sidecar_probe.analyze_registration"), patch("oras_sidecar_probe.require_words"), \
                patch("oras_footer_binding.verify_footer_getter"):
            _, code, plan = build_sidecar(
                info, b"", 0x579640, 0x6AF000, save_trial=True, footer=True, index_trial=True,
            )
        self.assertIn(struct.pack("<2I", plan["buffer"] + INDEX_OFFSET, 1), code)
        self.assertIn(struct.pack("<I", plan["buffer"] + 20), code)
        self.assertNotIn(self.token, code)

    def test_reload_cli_requires_explicit_anchor(self):
        run = subprocess.run(
            [sys.executable, str(ROOT / "tools/run_bizhawk_connector_probe.py"), "--rom", "unused",
             "--seed-save", "unused", "--experimental-bootstrap", "sidecar-index-reload"],
            capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(run.returncode, 2)
        self.assertIn("--synthetic-index-anchor is required", run.stderr)


if __name__ == "__main__":
    unittest.main()

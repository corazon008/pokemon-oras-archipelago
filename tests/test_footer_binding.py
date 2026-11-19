"""Synthetic experimental footer fixtures; no ROM or personal save needed."""

from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from oras_footer_binding import FOOTER_SIZE, HEADER, METADATA_ACCESSOR, footer_payload, inspect_footer_archive
from oras_save import BLOCKS, METADATA_OFFSET, validate_save
from oras_save_serialization import branch_target
from oras_sidecar_probe import NAME, TEST_METADATA, WRITE, build_sidecar
from save_fixtures import synthetic_save, update_fixture_crcs


class FooterBindingTests(unittest.TestCase):
    def setUp(self):
        root = tempfile.TemporaryDirectory(dir="/tmp/opencode")
        self.addCleanup(root.cleanup)
        self.main = Path(root.name) / "00000001/main"
        self.main.parent.mkdir()
        self.main.parent.with_suffix(".metadata").write_bytes(TEST_METADATA)
        self.sidecar = self.main.parent / NAME
        self.old = bytes(synthetic_save())
        new = bytearray(self.old)
        new[BLOCKS[3][0]] ^= 1
        update_fixture_crcs(new)
        self.new = bytes(new)

    def test_exact_footer_and_marker_required(self):
        payload = footer_payload(self.new, saved=True)
        self.assertEqual(len(payload), 512)
        self.assertEqual(payload[20:508], self.new[METADATA_OFFSET:METADATA_OFFSET + FOOTER_SIZE])
        self.main.write_bytes(self.new)
        self.sidecar.write_bytes(payload)
        got, result = inspect_footer_archive(self.main)
        self.assertEqual(got, payload)
        self.assertIsNone(result["next_delivery_index"])
        self.assertFalse(result["live_delivery_authorized"])
        for changed in (b"!" + payload[1:], payload[:-1], payload[:-4] + bytes(4)):
            self.sidecar.write_bytes(changed)
            with self.assertRaisesRegex(ValueError, "footer differs"):
                inspect_footer_archive(self.main)

    def test_independently_valid_mixed_pair_is_rejected_without_history(self):
        for main, side in ((self.old, self.new), (self.new, self.old)):
            validate_save(main)
            self.main.write_bytes(main)
            self.sidecar.write_bytes(footer_payload(side, saved=True))
            with self.assertRaisesRegex(ValueError, "footer differs"):
                inspect_footer_archive(self.main)

    def test_matching_footer_does_not_override_an_invalid_block(self):
        self.sidecar.write_bytes(footer_payload(self.new, saved=True))
        corrupt = bytearray(self.new)
        corrupt[BLOCKS[3][0]] ^= 2
        self.main.write_bytes(corrupt)
        with self.assertRaisesRegex(ValueError, "checksum"):
            inspect_footer_archive(self.main)

    def test_clear_marker_accepted_only_in_explicit_precapture(self):
        self.main.write_bytes(self.old)
        self.sidecar.write_bytes(footer_payload(self.old, saved=False))
        self.assertFalse(inspect_footer_archive(self.main, saved=False)[1]["marker_saved"])
        with self.assertRaisesRegex(ValueError, "marker"):
            inspect_footer_archive(self.main)

    def test_footer_reader_between_writers_and_bounded_to_488_bytes(self):
        start, page = 0x579640, 0x6AF000
        info = {"code_segments": [{"address": 0x100000, "image_offset": 0, "size": 0x500000}]}
        with patch("oras_sidecar_probe.analyze_registration"), patch("oras_sidecar_probe.require_words"), \
                patch("oras_footer_binding.verify_footer_getter"):
            _, code, plan = build_sidecar(info, b"", start, page, save_trial=True, footer=True)
        calls = [(start + i * 4, branch_target(word, start + i * 4))
                 for i, (word,) in enumerate(struct.iter_unpack("<I", code)) if word >> 24 == 0xEB]
        targets = [target for _, target in calls if target in (WRITE, METADATA_ACCESSOR)]
        self.assertEqual(targets, [WRITE, METADATA_ACCESSOR, WRITE])
        self.assertIn(struct.pack("<4I", 0xE3A0207A, 0xE4903004, 0xE4813004, 0xE2522001), code)
        self.assertIn(struct.pack("<I", plan["buffer"] + len(HEADER)), code)


if __name__ == "__main__":
    unittest.main()

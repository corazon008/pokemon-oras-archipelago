"""Synthetic layout and A32 callsite fixtures only."""

from pathlib import Path
import struct
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from oras_save import BLOCKS, METADATA_OFFSET, SAVE_SIZE
from oras_save_serialization import aligned_layout, branch_target, direct_references, verify_slot_call


class SerializationTests(unittest.TestCase):
    def test_full_layout_matches_all_documented_offsets(self):
        rows, total = aligned_layout([n for _, n in BLOCKS] + [488], 512)
        self.assertEqual([row["offset"] for row in rows[:-1]], [offset for offset, _ in BLOCKS])
        self.assertEqual(rows[47]["offset"], 0x20600)
        self.assertEqual(rows[-1]["offset"], METADATA_OFFSET)
        self.assertEqual(total, SAVE_SIZE)

    def test_invalid_alignment_lengths_and_overflow_fail(self):
        for alignment in (0, 3, 8192, True):
            with self.assertRaises(ValueError):
                aligned_layout([1], alignment)
        for lengths in ((0,), (-1,), (True,), (64 * 1024 * 1024, 1)):
            with self.assertRaises(ValueError):
                aligned_layout(lengths, 512)

    def test_branch_sign_conditions_and_blx_exclusion(self):
        self.assertEqual(branch_target(0xEB000002, 0x100000), 0x100010)
        self.assertEqual(branch_target(0xBAFFFFFC, 0x100010), 0x100008)
        self.assertIsNone(branch_target(0xFA000002, 0x100000))
        self.assertIsNone(branch_target(0xE12FFF31, 0x100000))
        with self.assertRaises(ValueError):
            branch_target(0xEB000000, 0x100001)

    def test_direct_references_only_scan_text(self):
        image = struct.pack("<4I", 0xEB000002, 0xE12FFF1E, 0xEB000000, 0xE12FFF1E)
        info = {"code_segments": [
            {"name": "text", "address": 0x100000, "image_offset": 0, "size": 8},
            {"name": "ro", "address": 0x900000, "image_offset": 8, "size": 8},
        ]}
        rows = direct_references(info, image, {0x100010, 0x900010})
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["target"], 0x100010)

    def callsite(self, middle=0xE1A00004, last=0xE12FFF31, slot=28):
        image = struct.pack("<III", 0xE590101C, middle, last)
        info = {"code_segments": [{"address": 0x100000, "image_offset": 0, "size": len(image)}]}
        return verify_slot_call(info, image, 0x100000, slot, 0x100008)

    def test_method_load_move_this_and_indirect_call(self):
        row = self.callsite()
        self.assertEqual(row["slot"], 28)
        self.assertEqual(row["indirect_call"], 0x100008)

    def test_clobbers_shifts_wrong_slots_and_calls_fail(self):
        for kwargs in ({"middle": 0xE1A01004}, {"middle": 0xE1A00084},
                       {"last": 0xE12FFF32}, {"slot": 24}):
            with self.assertRaises(ValueError):
                self.callsite(**kwargs)


if __name__ == "__main__":
    unittest.main()

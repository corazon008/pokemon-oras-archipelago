"""Synthetic EventWork6 layout tests, not game-event validation."""

from pathlib import Path
import struct
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from oras_events import (
    EVENT_LENGTH, FLAG_COUNT, FLAG_OFFSET, TAIL_OFFSET, WORK_COUNT,
    compare_events, event_bytes, event_flag, event_work,
)
from save_fixtures import synthetic_save


class EventTests(unittest.TestCase):
    def test_extract_requires_all_save_crcs(self):
        save = synthetic_save(fill=1)
        self.assertEqual(len(event_bytes(save)), EVENT_LENGTH)
        corrupt = bytearray(save)
        corrupt[0x14A00] ^= 1
        with self.assertRaisesRegex(ValueError, "checksum"):
            event_bytes(corrupt)

    def test_word_and_flag_indices_do_not_mix(self):
        before = bytes(EVENT_LENGTH)
        after = bytearray(before)
        struct.pack_into("<H", after, 118 * 2, 3)
        after[FLAG_OFFSET + 2722 // 8] |= 1 << (2722 % 8)
        result = compare_events(before, after)
        self.assertEqual(result["work_changes"], [{"index": 118, "before": 0, "after": 3}])
        self.assertEqual(result["flag_changes"], [{"index": 2722, "before": False, "after": True}])
        self.assertEqual(result["unknown_tail_changed_offsets"], [])
        self.assertEqual(event_work(after, 118), 3)
        self.assertTrue(event_flag(after, 2722))

    def test_unknown_tail_has_no_invented_flag_semantics(self):
        before = bytes(EVENT_LENGTH)
        after = bytearray(before)
        after[TAIL_OFFSET] = 1
        result = compare_events(before, after)
        self.assertFalse(result["matches_reference"])
        self.assertEqual(result["work_changes"], [])
        self.assertEqual(result["flag_changes"], [])
        self.assertEqual(result["unknown_tail_changed_offsets"], [f"0x{TAIL_OFFSET:03X}"])

    def test_bounds_and_truncation_fail(self):
        for function, limit in ((event_work, WORK_COUNT), (event_flag, FLAG_COUNT)):
            for index in (-1, limit):
                with self.subTest(function=function, index=index), self.assertRaises(ValueError):
                    function(bytes(EVENT_LENGTH), index)
            with self.assertRaises(ValueError):
                function(bytes(EVENT_LENGTH - 1), 0)
        with self.assertRaises(ValueError):
            compare_events(bytes(EVENT_LENGTH), bytes(EVENT_LENGTH + 1))

    def test_identical_blocks_and_flag_clear(self):
        block = bytes(EVENT_LENGTH)
        self.assertTrue(compare_events(block, block)["matches_reference"])
        before = bytearray(block)
        before[FLAG_OFFSET] = 0x80
        self.assertEqual(compare_events(before, block)["flag_changes"],
                         [{"index": 7, "before": True, "after": False}])


if __name__ == "__main__":
    unittest.main()

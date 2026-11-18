"""Synthetic straight-line instructions and manager captures only."""

from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from oras_save import BLOCKS
import oras_save_manager as manager
from save_fixtures import synthetic_save


class AssignmentTests(unittest.TestCase):
    def trace(self, *words, literal=None):
        image = struct.pack(f"<{len(words)}I", *words)
        end = 0x100000 + len(image)
        if literal is not None:
            image += struct.pack("<I", literal)
        info = {"code_segments": [
            {"name": "text", "address": 0x100000, "image_offset": 0, "size": len(image)},
        ]}
        return manager.trace_assignments(info, image, 0x100000, end)

    def test_affine_add_sub_and_store(self):
        stores = self.trace(0xE2840008, 0xE2400004, 0xE5840010)
        self.assertEqual(stores[16], {"instruction": 0x100008, "value": (1, 4)})

    def test_literal_and_shifted_register_store(self):
        # LDR r0,[pc,#4]; ADD r1,r4,#8; STR r1,[r4,r0]; literal 32.
        stores = self.trace(0xE59F0004, 0xE2841008, 0xE7841000, literal=32)
        self.assertEqual(stores[32]["value"], (1, 8))

    def test_unknown_stack_load_invalidates_prior_value(self):
        stores = self.trace(0xE2849008, 0xE89D0200, 0xE5849010)
        self.assertIsNone(stores[16]["value"])
        stores = self.trace(0xE284E008, 0xE89D4000, 0xE584E010)
        self.assertIsNone(stores[16]["value"])

    def test_unknown_memory_and_symbolic_shift_stay_unknown(self):
        stores = self.trace(0xE5940000, 0xE5840010, 0xE1A01084, 0xE5841014)
        self.assertIsNone(stores[16]["value"])
        self.assertIsNone(stores[20]["value"])

    def test_constant_orr_and_rotated_immediate(self):
        stores = self.trace(0xE3A00001, 0xE3800101, 0xE5840010)
        self.assertEqual(stores[16]["value"], (0, 0x40000001))
        self.assertEqual(manager.shifted((0, 0x80000000), 2, 0), (0, 0xFFFFFFFF))
        self.assertIsNone(manager.shifted((0, 1), 3, 0))

    def test_conditional_calls_writeback_and_flag_operations_abort(self):
        for instruction in (0x12840008, 0xEB000000, 0xE5A40004, 0xE2940008,
                            0xE1A00114, 0xE8BD0010, 0xE5840001):
            with self.subTest(instruction=hex(instruction)), self.assertRaises(ValueError):
                self.trace(instruction)

    def test_invalid_fragment_bounds_abort(self):
        info = {"code_segments": [{"address": 0x100000, "image_offset": 0, "size": 4}]}
        for start, end in ((0x100001, 0x100004), (0x100000, 0x100000), (0x100000, 0x100008)):
            with self.assertRaises(ValueError):
                manager.trace_assignments(info, bytes(4), start, end)


def capture_fixture(path, mismatch=None):
    image = bytearray(8192)
    info = {"code_segments": [
        {"name": "text", "address": 0x100000, "image_offset": 0, "size": 58 * 24 + 8},
        {"name": "ro", "address": 0x500000, "image_offset": 4096, "size": 58 * 24 + 44},
    ]}
    pointers, headers = bytearray(), bytearray()
    metadata = bytearray(504)
    save = synthetic_save()
    metadata[8:496] = save[manager.METADATA_OFFSET:manager.METADATA_OFFSET + 488]
    for index, (_, length) in enumerate(BLOCKS):
        at = index * 24
        provider, getter = 0x100000 + at, 0x100000 + at + 12
        struct.pack_into("<5I", image, at, 0xE59F0000, 0xE12FFF1E,
                         length + (4 if mismatch == index else 0), 0xE2800004, 0xE12FFF1E)
        struct.pack_into("<6I", image, 4096 + at, getter, getter, getter, getter, provider, getter)
        pointers.extend(struct.pack("<I", 0x08001000 + index * 0x100))
        headers.extend(struct.pack("<I", 0x500000 + at))
    struct.pack_into("<II", image, 58 * 24, 0xE3A0003B, 0xE12FFF1E)
    struct.pack_into("<11I", image, 4096 + 58 * 24, *([0x100000 + 58 * 24] * 11))
    (path / "manager-root.bin").write_bytes(struct.pack("<II", 0x500000 + 58 * 24, 0x08090000))
    (path / "manager-table.bin").write_bytes(pointers)
    (path / "manager-headers.bin").write_bytes(headers)
    (path / "manager-metadata.bin").write_bytes(metadata)
    prediction = {"predicted_base": 0x08000000, "derived_slots": {
        index: {"object_offset": 0x1000 + index * 0x100} for index in range(58)
    }}
    return info, bytes(image), prediction


class ManagerCaptureTests(unittest.TestCase):
    def test_cli_requires_profile_and_refuses_potion_combination(self):
        root = Path(__file__).resolve().parents[1]
        for options, message in (
            ([], "requires a validated profile"),
            (["--seed-save", "synthetic-main", "--experimental-potion-1-to-2"], "read-only"),
        ):
            result = subprocess.run(
                [sys.executable, str(root / "tools/run_bizhawk_connector_probe.py"),
                 "--rom", "synthetic.3ds", "--trace-save-manager", *options],
                capture_output=True, text=True, timeout=10,
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn(message, result.stderr)

    def inspect(self, mismatch=None, change=None):
        with tempfile.TemporaryDirectory(dir="/tmp/opencode") as directory:
            path = Path(directory)
            info, image, prediction = capture_fixture(path, mismatch)
            if change:
                change(path, prediction)
            with patch.object(manager, "load_code", return_value=(info, image)):
                return manager.inspect_manager_capture(path, Path("synthetic.3ds"), prediction)

    def test_complete_synthetic_descriptors_and_sizes(self):
        report = self.inspect()
        self.assertEqual(report["constructor_offsets_matched"], 58)
        self.assertEqual(report["metadata_descriptors_matching_file_layout"], 58)
        self.assertEqual(report["size_matches"], 58)
        self.assertFalse(report["instruction_execution_traced"])
        self.assertFalse(report["write_allowed"])
        self.assertEqual(report["manager_slot_count"], 59)
        self.assertEqual(report["metadata_slot_index"], 58)

    def test_size_mismatch_reported_not_hidden(self):
        report = self.inspect(mismatch=35)
        self.assertEqual(report["size_matches"], 57)
        self.assertEqual(report["size_mismatch_ids"], [35])

    def test_bad_constructor_pointer_or_partial_capture_aborts(self):
        def wrong_pointer(path, prediction):
            prediction["derived_slots"][47]["object_offset"] += 4
        with self.assertRaisesRegex(ValueError, "constructor prediction"):
            self.inspect(change=wrong_pointer)
        def truncate(path, prediction):
            (path / "manager-table.bin").write_bytes(b"")
        with self.assertRaisesRegex(ValueError, "Incomplete"):
            self.inspect(change=truncate)

    def test_native_footer_compared_to_crc_valid_reference(self):
        with tempfile.TemporaryDirectory(dir="/tmp/opencode") as directory:
            path = Path(directory)
            info, image, prediction = capture_fixture(path)
            with patch.object(manager, "load_code", return_value=(info, image)):
                report = manager.inspect_manager_capture(path, Path("synthetic.3ds"), prediction, synthetic_save())
            self.assertTrue(report["metadata_payload_matches_saved_footer"])
            self.assertEqual(report["metadata_descriptors_with_matching_crc"], 58)

    def test_regular_block_count_is_not_total_manager_count(self):
        with tempfile.TemporaryDirectory(dir="/tmp/opencode") as directory:
            path = Path(directory)
            info, fixture_image, prediction = capture_fixture(path)
            image = bytearray(fixture_image)
            struct.pack_into("<I", image, 58 * 24, 0xE3A0003A)
            with patch.object(manager, "load_code", return_value=(info, image)), \
                    self.assertRaisesRegex(ValueError, "slot-count provider"):
                manager.inspect_manager_capture(path, Path("synthetic.3ds"), prediction)


if __name__ == "__main__":
    unittest.main()

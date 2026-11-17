import binascii
from pathlib import Path
import struct
import sys
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from oras_save import BLOCKS, METADATA_OFFSET, inspect_save, validate_save, compare_medicine_change
from save_fixtures import synthetic_save, update_fixture_crcs


class OrasSaveTests(unittest.TestCase):
    @staticmethod
    def potion_inventory():
        data = bytearray(0xB90)
        struct.pack_into("<HH", data, 0x970, 17, 1)
        return data

    def test_native_quantity_removal(self):
        reference = self.potion_inventory()
        result = compare_medicine_change(reference, reference, bytes(0xB90), 17, 0)
        self.assertTrue(result["passed"])
        self.assertEqual(result["before_quantity"], 1)
        self.assertEqual(result["observed_quantity"], 0)

    def test_wrong_baseline_cannot_pass_a_zero_quantity(self):
        reference = self.potion_inventory()
        result = compare_medicine_change(reference, bytes(0xB90), bytes(0xB90), 17, 0)
        self.assertFalse(result["passed"])

    def test_unchanged_quantity_is_not_a_differential_proof(self):
        reference = self.potion_inventory()
        self.assertFalse(compare_medicine_change(reference, reference, reference, 17, 1)["passed"])

    def test_unrelated_medicine_change_fails(self):
        reference = self.potion_inventory()
        after = bytearray(0xB90)
        struct.pack_into("<HH", after, 0x974, 99, 2)
        self.assertFalse(compare_medicine_change(reference, reference, after, 17, 0)["passed"])

    def test_other_pouch_padding_change_fails(self):
        reference = self.potion_inventory()
        after = bytearray(0xB90)
        after[0x600] = 1
        self.assertFalse(compare_medicine_change(reference, reference, after, 17, 0)["passed"])

    def test_zero_quantity_with_retained_id_is_supported(self):
        reference = self.potion_inventory()
        after = reference.copy()
        struct.pack_into("<H", after, 0x972, 0)
        self.assertTrue(compare_medicine_change(reference, reference, after, 17, 0)["passed"])

    def test_ccitt_reference_vector(self):
        self.assertEqual(binascii.crc_hqx(b"123456789", 0xFFFF), 0x29B1)

    def test_valid_synthetic_save_and_inventory(self):
        data = synthetic_save()
        struct.pack_into("<HH", data, 0x400 + 0x970, 17, 1)
        struct.pack_into("<I", data, 0x4208, 3000)
        update_fixture_crcs(data)
        original = bytes(data)
        result = inspect_save(data)
        self.assertEqual(result["validated_block_count"], 58)
        self.assertEqual(result["money"], 3000)
        self.assertEqual(result["inventory"], [
            {"pouch": "medicine", "slot": 0, "item_id": 17, "quantity": 1},
        ])
        self.assertEqual(data, original)

    def test_corrupt_inventory_is_rejected(self):
        data = synthetic_save()
        data[0x400] ^= 1
        with self.assertRaisesRegex(ValueError, "checksum mismatch: 1"):
            validate_save(data)

    def test_forged_block_descriptor_is_rejected(self):
        data = synthetic_save()
        struct.pack_into("<I", data, METADATA_OFFSET + 0x14, 0)
        with self.assertRaisesRegex(ValueError, "descriptor 0"):
            validate_save(data)

    def test_bad_footer_and_size_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "0x76000"):
            validate_save(b"short")
        data = synthetic_save()
        data[METADATA_OFFSET + 0x10] ^= 1
        with self.assertRaisesRegex(ValueError, "footer marker"):
            validate_save(data)

    def test_layout_blocks_do_not_overlap_footer(self):
        for (offset, length), (next_offset, _) in zip(BLOCKS, BLOCKS[1:]):
            self.assertLessEqual(offset + length, next_offset)
        self.assertLess(BLOCKS[-1][0] + BLOCKS[-1][1], METADATA_OFFSET)


if __name__ == "__main__":
    unittest.main()

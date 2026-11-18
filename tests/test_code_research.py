"""Synthetic BLZ and executable fixtures only; no proprietary code is included."""

from pathlib import Path
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from oras_code_research import (
    address_offset, arm_constant_return, decompress_blz, find_provider_tables,
    find_size_tables, image_address, load_code,
)
from test_rom_identity import fixture


def blz_fixture(prefix=b"PFX!"):
    # Backwards tokens: literals C,B,A; copies of 18 and 15 bytes at distance 3.
    tokens = struct.pack("<HH", 0xC000, 0xF000) + b"ABC" + b"\x18"
    packed = prefix + tokens
    suffix = len(tokens) + 8
    return packed + struct.pack("<II", (8 << 24) | suffix, 20)


class BlzTests(unittest.TestCase):
    def test_overlapping_backreferences_and_prefix(self):
        self.assertEqual(decompress_blz(blz_fixture()), b"PFX!" + b"ABC" * 12)

    def test_empty_prefix(self):
        self.assertEqual(decompress_blz(blz_fixture(b"")), b"ABC" * 12)

    def test_missing_or_invalid_footer(self):
        for data in (b"", b"short", b"\0" * 8):
            with self.subTest(data=data), self.assertRaises(ValueError):
                decompress_blz(data)
        data = bytearray(blz_fixture())
        struct.pack_into("<I", data, len(data) - 8, (7 << 24) | 16)
        with self.assertRaisesRegex(ValueError, "footer"):
            decompress_blz(data)

    def test_output_limit(self):
        data = bytearray(blz_fixture())
        struct.pack_into("<I", data, len(data) - 4, 0xFFFFFFFF)
        with self.assertRaisesRegex(ValueError, "bound"):
            decompress_blz(data)

    def test_reference_to_unwritten_end_is_rejected(self):
        data = bytearray(blz_fixture())
        data[-9] = 0x80  # First token is now a backreference, without literal seeds.
        with self.assertRaises(ValueError):
            decompress_blz(data)

    def test_truncated_token_is_rejected(self):
        data = b"\0\x80" + struct.pack("<II", (8 << 24) | 10, 20)
        with self.assertRaisesRegex(ValueError, "Truncated"):
            decompress_blz(data)

    def test_underfilled_output_is_rejected(self):
        data = bytearray(blz_fixture())
        struct.pack_into("<I", data, len(data) - 4, 21)
        with self.assertRaises(ValueError):
            decompress_blz(data)


class TableTests(unittest.TestCase):
    def test_complete_table_at_multiple_strides(self):
        sizes = (0x2C8, 0xB90, 0x2C, 0x38)
        for stride in (4, 8, 12, 16):
            image = bytearray(16 + stride * len(sizes))
            for index, value in enumerate(sizes):
                struct.pack_into("<I", image, 16 + index * stride, value)
            self.assertIn({"image_offset": 16, "stride": stride, "count": 4},
                          find_size_tables(image, sizes))

    def test_partial_match_and_unaligned_match_not_promoted(self):
        sizes = (1, 2, 3, 4)
        self.assertEqual(find_size_tables(struct.pack("<IIII", 1, 2, 3, 5), sizes), [])
        self.assertEqual(find_size_tables(b"x" + struct.pack("<IIII", *sizes), sizes), [])

    def test_multiple_tables_retained(self):
        sizes = (1, 2, 3, 4)
        image = struct.pack("<IIII", *sizes) + b"\0" * 16 + struct.pack("<IIII", *sizes)
        self.assertEqual(len(find_size_tables(image, sizes)), 2)

    def test_invalid_search_parameters(self):
        for sizes, strides in (((0, 0, 0, 0), (4,)), ((1, 2), (4,)), ((1, 2, 3, 4), (5,))):
            with self.assertRaises(ValueError):
                find_size_tables(b"", sizes, strides)

    def test_virtual_mapping_uses_segment_headers_not_flat_base(self):
        info = {"code_segments": [
            {"image_offset": 0, "address": 0x100000, "size": 16},
            {"image_offset": 4096, "address": 0x900000, "size": 16},
        ]}
        self.assertEqual(image_address(info, 4100, 4), 0x900004)
        self.assertIsNone(image_address(info, 4092, 8))
        self.assertIsNone(image_address(info, 17))
        with self.assertRaises(ValueError):
            image_address(info, -1)

    def test_load_uncompressed_synthetic_image(self):
        data, _, exheader, exefs = fixture(cartridge=False)
        data.extend(bytes(0x4000 - len(data)))
        struct.pack_into("<I", data, 0x104, 0x20)
        struct.pack_into("<I", data, 0x1A4, 0x10)
        data[exheader + 0x0D] = 0
        struct.pack_into("<III", data, exheader + 0x10, 0x100000, 1, 4096)
        struct.pack_into("<I", data, exefs + 12, 4096)
        with tempfile.TemporaryDirectory(dir="/tmp/opencode") as directory:
            path = Path(directory) / "fixture.3ds"
            path.write_bytes(data)
            info, image = load_code(path)
            self.assertEqual(len(image), 4096)
            self.assertEqual(image[:64], bytes(range(1, 65)))
            self.assertEqual(image_address(info, 64), 0x100040)
            self.assertEqual(path.read_bytes(), data)


class ArmProviderTests(unittest.TestCase):
    def recognize(self, *words):
        image = struct.pack(f"<{len(words)}I", *words)
        info = {"code_segments": [
            {"name": "text", "address": 0x100000, "image_offset": 0, "size": len(image)},
        ]}
        return arm_constant_return(info, image, 0)

    def test_immediate_rotation_and_return_forms(self):
        self.assertEqual(self.recognize(0xE3A00EB9, 0xE12FFF1E), (2960, 2))
        self.assertEqual(self.recognize(0xE3A00E7D, 0xE1A0F00E), (2000, 2))

    def test_constant_arithmetic_and_three_operation_limit(self):
        self.assertEqual(self.recognize(0xE3A00001, 0xE2800003, 0xE2400002, 0xE12FFF1E), (2, 4))
        self.assertEqual(self.recognize(0xE3A00001, 0xE3800004, 0xE3C00001, 0xE12FFF1E), (4, 4))
        self.assertIsNone(self.recognize(0xE3A00001, 0xE2800001, 0xE2800001, 0xE2800001, 0xE12FFF1E))

    def test_pc_relative_literals_both_directions(self):
        self.assertEqual(self.recognize(0xE59F0000, 0xE12FFF1E, 1284), (1284, 2))
        image = struct.pack("<III", 1284, 0xE51F000C, 0xE12FFF1E)
        info = {"code_segments": [
            {"name": "text", "address": 0x100000, "image_offset": 0, "size": len(image)},
        ]}
        self.assertEqual(arm_constant_return(info, image, 4), (1284, 2))

    def test_conditional_state_changing_and_unknown_source_rejected(self):
        for instruction in (0x13A00001, 0xE3B00001, 0xE2810001, 0xE5BF0000, 0xE5DF0000, 0xEB000000):
            with self.subTest(instruction=hex(instruction)):
                self.assertIsNone(self.recognize(instruction, 0xE12FFF1E, 0))
        self.assertIsNone(self.recognize(0xE2800001, 0xE12FFF1E))
        self.assertIsNone(self.recognize(0xE12FFF1E))

    def test_truncated_unaligned_unmapped_literals_and_ranges(self):
        self.assertIsNone(self.recognize(0xE59F0100, 0xE12FFF1E))
        self.assertIsNone(self.recognize(0xE59F0001, 0xE12FFF1E, 1284))
        image = struct.pack("<II", 0xE3A00001, 0xE12FFF1E)
        info = {"code_segments": [{"name": "text", "address": 0x100000, "image_offset": 0, "size": 8}]}
        for offset in (-4, 1, 8):
            self.assertIsNone(arm_constant_return(info, image, offset))
        self.assertIsNone(arm_constant_return(info, image[:4], 0))

    def test_reverse_mapping_and_padding(self):
        info = {"code_segments": [
            {"image_offset": 0, "address": 0x100000, "size": 16},
            {"image_offset": 4096, "address": 0x900000, "size": 16},
        ]}
        self.assertEqual(address_offset(info, 0x900004, 4), 4100)
        self.assertIsNone(address_offset(info, 0x10000C, 8))
        self.assertIsNone(address_offset(info, 0x100010))
        for address, length in ((-1, 1), (0x100000, 0)):
            with self.assertRaises(ValueError):
                address_offset(info, address, length)

    def test_provider_pointer_tables_complete_partial_and_unmapped(self):
        sizes = (101, 102, 103, 104, 105)
        image = bytearray(0x1100)
        for index, size in enumerate(sizes):
            struct.pack_into("<II", image, index * 8, 0xE3A00000 | size, 0xE12FFF1E)
            struct.pack_into("<I", image, 0x1000 + index * 4, 0x100000 + index * 8)
        info = {"code_segments": [
            {"name": "text", "address": 0x100000, "image_offset": 0, "size": 40},
            {"name": "ro", "address": 0x500000, "image_offset": 0x1000, "size": 20},
        ]}
        providers, tables = find_provider_tables(info, image, sizes)
        self.assertEqual(providers[103], {0x100010})
        self.assertEqual(len(tables), 1)
        self.assertTrue(tables[0]["exact_provider_match"])
        struct.pack_into("<I", image, 0x1008, 0)
        _, tables = find_provider_tables(info, image, sizes)
        self.assertEqual(tables[0]["unrecognized_block_ids"], [2])
        self.assertFalse(tables[0]["exact_provider_match"])
        struct.pack_into("<I", image, 0x100C, 0)
        self.assertEqual(find_provider_tables(info, image, sizes)[1], [])
        with self.assertRaises(ValueError):
            find_provider_tables(info, image, ())


if __name__ == "__main__":
    unittest.main()

"""Synthetic NCSD/NCCH fixtures only; no proprietary ROM data."""

import hashlib
from pathlib import Path
import struct
import sys
import tempfile
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from rom_identity import inspect_rom, sha256_file


def fixture(cartridge=True):
    base = 0x200 if cartridge else 0
    data = bytearray(base + 0x2000)
    if cartridge:
        data[0x100:0x104] = b"NCSD"
        struct.pack_into("<II", data, 0x120, 1, 0x10)
    data[base + 0x100:base + 0x104] = b"NCCH"
    struct.pack_into("<I", data, base + 0x104, 0x10)
    struct.pack_into("<H", data, base + 0x112, 2)
    struct.pack_into("<Q", data, base + 0x118, 0x000400000011C400)
    data[base + 0x150:base + 0x160] = b"CTR-P-TEST".ljust(16, b"\0")
    struct.pack_into("<I", data, base + 0x180, 0x400)
    data[base + 0x18F] = 4
    struct.pack_into("<II", data, base + 0x1A0, 8, 4)
    exheader = base + 0x200
    data[exheader + 0x0D] = 1
    struct.pack_into("<H", data, exheader + 0x0E, 3)
    struct.pack_into("<III", data, exheader + 0x10, 0x100000, 1, 64)
    struct.pack_into("<Q", data, exheader + 0x200, 0x000400000011C400)
    exefs = base + 0x1000
    data[exefs:exefs + 8] = b".code\0\0\0"
    struct.pack_into("<II", data, exefs + 8, 0, 128)
    data[exefs + 0x200:exefs + 0x240] = bytes(range(1, 65))
    struct.pack_into("<II", data, exefs + 0x200 + 120, (8 << 24) | 56, 4096)
    return data, base, exheader, exefs


class IdentityTests(unittest.TestCase):
    def inspect_fixture(self, data):
        with tempfile.TemporaryDirectory(dir="/tmp/opencode") as directory:
            path = Path(directory) / "fixture.3ds"
            path.write_bytes(data)
            original = hashlib.sha256(data).hexdigest()
            result = inspect_rom(path)
            self.assertEqual(sha256_file(path), original)
            return result

    def test_ncsd_and_reference_are_derived_without_modification(self):
        data, _, _, _ = fixture()
        info, reference = self.inspect_fixture(data)
        self.assertEqual(info["program_id"], "000400000011C400")
        self.assertEqual(info["exheader_remaster_version"], 3)
        self.assertIsNone(info["commercial_update_version"])
        self.assertFalse(info["region_verified"])
        self.assertEqual(info["code_uncompressed_prefix_size_bytes"], 72)
        self.assertEqual(reference.address, 0x100000)
        self.assertEqual(reference.expected, bytes(range(1, 65)))
        self.assertNotIn("expected=", repr(reference))

    def test_raw_ncch(self):
        data, _, _, _ = fixture(cartridge=False)
        info, reference = self.inspect_fixture(data)
        self.assertEqual(info["container"], "NCCH")
        self.assertEqual(info["ncch_offset_bytes"], 0)
        self.assertIsNotNone(reference)

    def test_encrypted_metadata_does_not_attempt_exheader_parse(self):
        data, base, exheader, _ = fixture()
        data[base + 0x18F] = 0
        data[exheader:exheader + 0x400] = b"\xff" * 0x400
        info, reference = self.inspect_fixture(data)
        self.assertFalse(info["code_reference_available"])
        self.assertIsNone(reference)

    def test_truncated_header_and_out_of_bounds_partition_fail(self):
        with self.assertRaises(ValueError):
            self.inspect_fixture(b"short")
        data, _, _, _ = fixture()
        struct.pack_into("<I", data, 0x120, 0xFFFFFFFF)
        with self.assertRaisesRegex(ValueError, "partition"):
            self.inspect_fixture(data)

    def test_mismatched_exheader_identity_fails(self):
        data, _, exheader, _ = fixture()
        struct.pack_into("<Q", data, exheader + 0x200, 0)
        with self.assertRaisesRegex(ValueError, "program ID"):
            self.inspect_fixture(data)

    def test_code_section_must_fit_exefs(self):
        data, _, _, exefs = fixture()
        struct.pack_into("<I", data, exefs + 8, 0xFFFFFFFF)
        with self.assertRaisesRegex(ValueError, "section range"):
            self.inspect_fixture(data)

    def test_short_uncompressed_prefix_does_not_produce_reference(self):
        data, _, _, exefs = fixture()
        struct.pack_into("<I", data, exefs + 0x200 + 120, (8 << 24) | 80)
        info, reference = self.inspect_fixture(data)
        self.assertFalse(info["code_reference_available"])
        self.assertIsNone(reference)

    def test_invalid_footer_fails(self):
        data, _, _, exefs = fixture()
        struct.pack_into("<I", data, exefs + 0x200 + 120, (200 << 24) | 56)
        with self.assertRaisesRegex(ValueError, "footer"):
            self.inspect_fixture(data)

    def test_zero_reference_is_rejected(self):
        data, _, _, exefs = fixture()
        data[exefs + 0x200:exefs + 0x240] = b"\0" * 64
        with self.assertRaisesRegex(ValueError, "All-zero"):
            self.inspect_fixture(data)

    def test_text_range_must_fit_32_bit_bus(self):
        data, _, exheader, _ = fixture()
        struct.pack_into("<II", data, exheader + 0x10, 0xFFFFF000, 2)
        with self.assertRaisesRegex(ValueError, "virtual address"):
            self.inspect_fixture(data)


if __name__ == "__main__":
    unittest.main()

"""Synthetic pointer contexts and type-name chains only."""

from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import oras_save_references as refs


def fixture(path):
    image = bytearray(8192)
    info = {"code_segments": [
        {"name": "text", "address": 0x100000, "image_offset": 0, "size": 64},
        {"name": "ro", "address": 0x500000, "image_offset": 4096, "size": 512},
    ]}
    struct.pack_into("<4I", image, 0x1038, 0, 0x500100, 0x100000, 0x100004)
    struct.pack_into("<2I", image, 0x1100, 0x500180, 0x500140)
    name = b"N7fixture10SaveWorkerE\0"
    image[0x1140:0x1140 + len(name)] = name
    parent = bytearray(320)
    struct.pack_into("<I", parent, 256, 0x08C6A9A8)
    struct.pack_into("<I", parent, 264, 0x76000)
    parent[272:292] = "data:/main".encode("utf-16le")
    child = bytearray(512)
    struct.pack_into("<I", child, 256, 0x08001100)
    struct.pack_into("<I", child, 320, 0x500040)
    (path / "manager-backrefs.txt").write_text("0x08001100 0x08001000 320\n")
    (path / "manager-backref-01.bin").write_bytes(parent)
    (path / "save-records.txt").write_text("0x08001100\n")
    (path / "save-record-referrers.txt").write_text("0x08001100 0x08002100 0x08002000 512\n")
    (path / "save-record-referrer-01.bin").write_bytes(child)
    return info, bytes(image)


class ReferenceTests(unittest.TestCase):
    def inspect(self, change=None):
        with tempfile.TemporaryDirectory(dir="/tmp/opencode") as directory:
            path = Path(directory)
            info, image = fixture(path)
            if change:
                change(path)
            with patch.object(refs, "load_code", return_value=(info, image)):
                return refs.inspect_reference_capture(path, Path("synthetic.3ds"), 0x08C6A9A8)

    def test_pointer_relationships_and_type_candidates(self):
        report = self.inspect()
        self.assertEqual(report["main_save_record_candidates"], [0x08001100])
        candidates = report["save_record_referrers"][0]["context_type_candidates"]
        self.assertEqual(candidates[0]["context_address"], 0x08002140)
        self.assertEqual(candidates[0]["static_mangled_type_name"], "N7fixture10SaveWorkerE")
        self.assertFalse(candidates[0]["is_owner_of_nearby_reference_proven"])
        self.assertFalse(report["write_allowed"])

    def test_pointer_and_path_mismatch_fail(self):
        for offset in (256, 264, 272):
            def change(path):
                data = bytearray((path / "manager-backref-01.bin").read_bytes())
                data[offset] ^= 1
                (path / "manager-backref-01.bin").write_bytes(data)
            with self.subTest(offset=offset), self.assertRaises(ValueError):
                self.inspect(change)

    def test_unlisted_record_or_incomplete_context_fails(self):
        with self.assertRaises(ValueError):
            self.inspect(lambda p: (p / "save-records.txt").write_text("0x08001104\n"))
        with self.assertRaises(ValueError):
            self.inspect(lambda p: (p / "save-record-referrer-01.bin").write_bytes(b""))


if __name__ == "__main__":
    unittest.main()

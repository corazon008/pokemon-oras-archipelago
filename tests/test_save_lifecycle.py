"""Synthetic controller/source records; no proprietary executable bytes."""

from pathlib import Path
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from oras_save_lifecycle import bind_controller_capture, require_words
from oras_save import SAVE_SIZE


def fixture(path):
    manager, record, controller, engine = 0x08000000, 0x08001100, 0x08002100, 0x08002200
    source = bytearray(320)
    struct.pack_into("<I", source, 256, manager)
    struct.pack_into("<Q", source, 264, SAVE_SIZE)
    source[272:292] = "data:/main".encode("utf-16le")
    parent = bytearray(512)
    struct.pack_into("<4I", parent, 256, engine, 1, 1, record)
    (path / "manager-backref-01.bin").write_bytes(source)
    (path / "save-record-referrer-01.bin").write_bytes(parent)
    references = {
        "main_save_record_candidates": [record],
        "manager_backrefs": [{"reference_address": record, "context_start": record - 256}],
        "save_record_referrers": [{
            "reference_address": controller + 12, "context_start": controller - 256,
            "context_type_candidates": [{
                "context_address": engine, "static_mangled_type_name": "N3gfl2fs12BackupSystemE",
            }],
        }],
    }
    return manager, references


class LifecycleBindingTests(unittest.TestCase):
    def test_static_signatures_reject_modified_or_unmapped_code(self):
        info = {"code_segments": [{"address": 0x100000, "image_offset": 0, "size": 4}]}
        image = struct.pack("<I", 0xE3A02000)
        require_words(info, image, 0x100000, [0xE3A02000])
        with self.assertRaises(ValueError):
            require_words(info, bytes(4), 0x100000, [0xE3A02000])
        with self.assertRaises(ValueError):
            require_words(info, image, 0x100004, [0xE3A02000])

    def bind(self, change=None):
        with tempfile.TemporaryDirectory(dir="/tmp/opencode") as directory:
            path = Path(directory)
            manager, references = fixture(path)
            if change:
                change(path, references)
            return bind_controller_capture(path, references, manager)

    def test_binding_is_not_safe_write_approval(self):
        result = self.bind()
        self.assertEqual(result["controller_prefix"], 0x08002100)
        self.assertEqual(result["declared_file_size"], SAVE_SIZE)
        self.assertEqual(result["raw_result_byte"], 0)
        self.assertTrue(result["pointer_relationships_corroborated"])
        self.assertFalse(result["safe_to_write_proven"])
        self.assertFalse(result["runtime_call_arguments_traced"])

    def test_wrong_record_manager_size_or_path_fails(self):
        for offset in (256, 264, 272):
            def change(path, references):
                data = bytearray((path / "manager-backref-01.bin").read_bytes())
                data[offset] ^= 1
                (path / "manager-backref-01.bin").write_bytes(data)
            with self.subTest(offset=offset), self.assertRaises(ValueError):
                self.bind(change)

    def test_pointer_to_wrong_type_or_ambiguous_binding_fails(self):
        def wrong_type(path, references):
            references["save_record_referrers"][0]["context_type_candidates"][0]["static_mangled_type_name"] = "Unknown"
        with self.assertRaises(ValueError):
            self.bind(wrong_type)
        def duplicate(path, references):
            references["save_record_referrers"] *= 2
            (path / "save-record-referrer-02.bin").write_bytes((path / "save-record-referrer-01.bin").read_bytes())
        with self.assertRaises(ValueError):
            self.bind(duplicate)


if __name__ == "__main__":
    unittest.main()

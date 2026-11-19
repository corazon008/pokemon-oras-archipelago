"""Synthetic executable/ExHeader only. No game bytes or save data."""

from pathlib import Path
import struct
import subprocess
import sys
import unittest
from unittest.mock import patch
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from oras_bootstrap_patch import MAGIC, MARKER, arm_branch, build_bootstrap, encode_ips, install_bootstrap
from oras_save_serialization import branch_target


def fixture():
    segments = [
        {"name": "text", "address": 0x100000, "size": 64, "pages": 1, "image_offset": 0},
        {"name": "ro", "address": 0x101000, "size": 64, "pages": 1, "image_offset": 0x1000},
        {"name": "data", "address": 0x102000, "size": 64, "pages": 1, "image_offset": 0x2000},
    ]
    info = {"code_segments": segments, "bss_size_bytes": 123}
    image = bytearray(0x3000)
    struct.pack_into("<I", image, 0, arm_branch(0x100000, 0x100024, True))
    header = bytearray(0x800)
    for segment, offset in zip(segments, (0x10, 0x20, 0x30)):
        struct.pack_into("<III", header, offset, segment["address"], segment["pages"], segment["size"])
    struct.pack_into("<I", header, 0x3C, 123)
    return info, image, header


def apply_test_ips(patch, original):
    image, cursor = bytearray(original), 5
    while patch[cursor:cursor + 3] != b"EOF":
        offset = int.from_bytes(patch[cursor:cursor + 3], "big")
        length = int.from_bytes(patch[cursor + 3:cursor + 5], "big")
        cursor += 5
        image[offset:offset + length] = patch[cursor:cursor + length]
        cursor += length
    return image


class BootstrapPatchTests(unittest.TestCase):
    def test_new_page_and_explicit_text_extent_not_borrowed_padding(self):
        info, image, header = fixture()
        before = bytes(image), bytes(header)
        ips, changed, prefix, refs, report = build_bootstrap(info, image, header)
        self.assertEqual(before, (bytes(image), bytes(header)))
        self.assertEqual(report["owned_volatile_page"], 0x104000)
        self.assertEqual(struct.unpack_from("<I", changed, 0x3C)[0], 0x2000)
        self.assertEqual(struct.unpack_from("<I", changed, 0x18)[0], 104)
        for offset in range(len(header)):
            if not (0x18 <= offset < 0x1C or 0x3C <= offset < 0x40):
                self.assertEqual(header[offset], changed[offset])
        modified = apply_test_ips(ips, image)
        self.assertEqual(modified[:64], prefix.expected)
        self.assertEqual(modified[64:104], refs[0].expected)
        self.assertEqual(modified[104:], image[104:])
        self.assertEqual(refs[1].expected, MARKER)
        self.assertFalse(report["persistent_storage_allocated"])
        self.assertFalse(report["live_delivery_authorized"])
        self.assertIsNone(report["next_delivery_index"])

    def test_trampoline_link_tail_and_literals(self):
        info, image, header = fixture()
        _, _, prefix, refs, report = build_bootstrap(info, image, header)
        entry = report["entry_address"]
        stub = report["stub_address"]
        self.assertEqual(branch_target(struct.unpack_from("<I", prefix.expected)[0], entry), stub)
        words = struct.unpack("<10I", refs[0].expected)
        self.assertEqual(branch_target(words[6], stub + 24), entry + 0x24)
        self.assertEqual(words[0], 0xE92D4007)  # paired push/pop, no flag modifications
        self.assertEqual(words[5], 0xE8BD4007)
        for index in (1, 2):
            literal_address = stub + index * 4 + 8 + (words[index] & 0xFFF)
            self.assertEqual(literal_address, stub + (index + 7) * 4)
        self.assertEqual(words[8:], (0x104000, MAGIC))

    def test_allocation_only_has_no_code_or_marker_write(self):
        info, image, header = fixture()
        ips, _, prefix, refs, report = build_bootstrap(info, image, header, False)
        self.assertEqual(ips, b"PATCHEOF")
        self.assertEqual(prefix.expected, image[:64])
        self.assertEqual(len(refs), 1)
        self.assertEqual(refs[0].expected, bytes(8))
        self.assertFalse(report["native_marker_store_enabled"])

    def test_changed_mapping_occupied_tail_or_wrong_entry_rejected(self):
        for kind in ("mapping", "bss", "tail", "entry", "target", "capacity", "truncated"):
            info, image, header = fixture()
            if kind == "mapping":
                header[0x10] ^= 1
            elif kind == "bss":
                header[0x3C] ^= 1
            elif kind == "tail":
                image[64] = 1
            elif kind == "entry":
                image[:4] = bytes(4)
            elif kind == "target":
                struct.pack_into("<I", image, 0, arm_branch(0x100000, 0x101000, True))
            elif kind == "capacity":
                info["code_segments"][0]["size"] = 0x1000
                struct.pack_into("<I", header, 0x18, 0x1000)
            else:
                header = header[:0x400]
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                build_bootstrap(info, image, header)

    def test_branch_and_ips_reject_unsafe_ranges(self):
        for source, target in ((1, 4), (4, 5), (0, 1 << 26)):
            with self.assertRaises(ValueError):
                arm_branch(source, target)
        for records in ([(0, b"")], [(0, b"abc"), (2, b"a")],
                        [(int.from_bytes(b"EOF", "big"), b"a")], [((1 << 24) - 1, b"ab")]):
            with self.assertRaises(ValueError):
                encode_ips(records)

    def test_cli_refuses_nonisolated_or_write_combinations(self):
        for options in ([], ["--session", "old"], ["--seed-save", "seed", "--observe-native-save"],
                        ["--seed-save", "seed", "--experimental-potion-1-to-2"],
                        ["--seed-save", "seed", "--recover-from-snapshot", "backup"],
                        ["--seed-save", "seed", "--scan-save-objects"],
                        ["--seed-save", "seed", "--steps", "1:A"]):
            result = subprocess.run(
                [sys.executable, str(ROOT / "tools/run_bizhawk_connector_probe.py"),
                 "--rom", "synthetic.3ds", "--experimental-bootstrap", "hook", *options],
                text=True, capture_output=True, timeout=10,
            )
            self.assertEqual(result.returncode, 2)

    def test_wrong_rom_or_adjacent_overlays_refused_before_install(self):
        with tempfile.TemporaryDirectory(dir="/tmp/opencode") as directory:
            root = Path(directory)
            rom, runtime = root / "game.3ds", root / "runtime"
            rom.write_bytes(b"synthetic")
            with self.assertRaisesRegex(ValueError, "exact verified OR"):
                install_bootstrap(rom, runtime, "hook")
            for suffix in (".exheader", ".exefsdir", ".romfs"):
                overlay = Path(str(rom) + suffix)
                overlay.write_bytes(b"untouched")
                with patch("oras_bootstrap_patch.sha256_file", return_value=
                           "d76faafacd746fdcc5ec04a60b8b82ceb9678c3ad937b374234a506c50c417e4"):
                    with self.assertRaisesRegex(ValueError, "adjacent ROM overlays"):
                        install_bootstrap(rom, runtime, "hook")
                self.assertEqual(overlay.read_bytes(), b"untouched")
                overlay.unlink()
            self.assertEqual(rom.read_bytes(), b"synthetic")
            self.assertFalse(runtime.exists())


if __name__ == "__main__":
    unittest.main()

"""Synthetic, no game executable bytes or game saves."""

import asyncio
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from oras_save import SAVE_SIZE
from oras_save_serialization import branch_target
from oras_sidecar_probe import (
    BASE_METADATA, FILE_SIZE, NAME, PREFIX, READ, READ_CALLERS, READ_PUSH, REG_SITE, REGISTER, TEST_METADATA,
    MARKER_OFFSET, SAVE_MARKER, WRITE, WRITE_CALLERS, after_save_payload, build_sidecar, load_saved_fixture,
    parse_status, parse_write_status, read_saved_sidecar, read_sidecar, stage_fixture, verify_fixture,
    verify_records,
)


PAGE = 0x006AF000
START = 0x00579640
CONTROLLER = 0x08001000
MAIN = 0x08002000
RECORDS = 0x08003000
CALLERS = tuple(address + 4 for address in READ_CALLERS)
STATUS = (CONTROLLER, MAIN, 2, 0, 2, CALLERS[0], 0, CALLERS[1], 0)


def artifacts(*, save_trial=False, interrupt=False):
    info = {"code_segments": [{"address": 0x100000, "image_offset": 0, "size": 0x500000}]}
    with patch("oras_sidecar_probe.analyze_registration"), patch("oras_sidecar_probe.require_words"):
        return build_sidecar(info, b"", START, PAGE, save_trial=save_trial, interrupt=interrupt)


def records_fixture(plan):
    data = bytearray(96)
    for offset, pointer, size, name in (
        (0, MAIN, SAVE_SIZE, "data:/main"), (48, plan["manager"], FILE_SIZE, plan["path"]),
    ):
        struct.pack_into("<I4xQ", data, offset, pointer, size)
        encoded = name.encode("utf-16le")
        data[offset + 16:offset + 16 + len(encoded)] = encoded
    return bytes(data)


class SidecarTests(unittest.TestCase):
    def test_patch_sites_and_dispatch_are_bounded(self):
        records, code, plan = artifacts()
        self.assertEqual([0x100000 + offset for offset, _ in records], [0x108E3C, REG_SITE, READ])
        capacity, reg, read = [struct.unpack("<I", data)[0] for _, data in records]
        self.assertEqual(capacity, 0xE3A02002)
        self.assertEqual(reg >> 24, 0xEB)
        self.assertEqual(read >> 24, 0xEA)
        self.assertEqual(branch_target(reg, REG_SITE), plan["register_hook"])
        self.assertEqual(branch_target(read, READ), plan["read_hook"])
        self.assertEqual(START + len(code), plan["block_table"] + 24 + 16 + 28)
        words = struct.unpack(f"<{len(code)//4}I", code)
        idx = words.index(READ_PUSH)
        self.assertEqual(branch_target(words[idx + 1], START + (idx + 1) * 4), READ + 4)
        registration_calls = [word for i, word in enumerate(words)
                              if branch_target(word, START + i * 4) == REGISTER]
        self.assertEqual(len(registration_calls), 2)
        self.assertGreaterEqual(plan["buffer"], PAGE)
        self.assertLessEqual(plan["buffer"] + FILE_SIZE, PAGE + 4096)
        self.assertNotIn(PREFIX, code)

    def test_fixture_changes_only_copy_and_rejects_missing_or_modified_payload(self):
        with tempfile.TemporaryDirectory(dir="/tmp/opencode") as directory:
            archive = Path(directory) / "00000001"
            archive.mkdir()
            main = archive / "main"
            main.write_bytes(b"unchanged test")
            metadata = archive.with_suffix(".metadata")
            metadata.write_bytes(BASE_METADATA)
            payload = stage_fixture(main)
            self.assertEqual(len(payload), FILE_SIZE)
            self.assertTrue(payload.startswith(PREFIX))
            self.assertEqual(metadata.read_bytes(), TEST_METADATA)
            self.assertEqual(main.read_bytes(), b"unchanged test")
            verify_fixture(main, payload)
            with self.assertRaisesRegex(ValueError, "one-file"):
                stage_fixture(main)
            side = archive / NAME
            side.write_bytes(bytes(FILE_SIZE))
            with self.assertRaisesRegex(ValueError, "altered"):
                verify_fixture(main, payload)
            side.unlink()
            with self.assertRaisesRegex(ValueError, "layout"):
                verify_fixture(main, payload)

    def test_save_variant_redirects_only_known_writer_callers(self):
        records, code, plan = artifacts(save_trial=True)
        self.assertEqual(len(records), 6)
        for (offset, data), site in zip(records[3:], WRITE_CALLERS, strict=True):
            self.assertEqual(offset + 0x100000, site)
            word, = struct.unpack("<I", data)
            self.assertEqual(word >> 24, 0xEB)
            self.assertEqual(branch_target(word, site), plan["write_hook"])
        self.assertGreaterEqual(plan["write_status"], plan["status"] + 36)
        self.assertLessEqual(plan["write_status"] + 16, plan["buffer"])
        calls = [
            index for index, (word,) in enumerate(struct.iter_unpack("<I", code[plan["write_hook"] - START:]))
            if word >> 24 == 0xEB and branch_target(word, plan["write_hook"] + index * 4) == WRITE
        ]
        self.assertEqual(len(calls), 2)
        self.assertNotIn(SAVE_MARKER, artifacts()[1])

    def test_reload_never_manufactures_marker_or_reseeds_fixture(self):
        with tempfile.TemporaryDirectory(dir="/tmp/opencode") as directory:
            archive = Path(directory) / "00000001"
            archive.mkdir()
            main = archive / "main"
            main.write_bytes(b"unchanged test")
            archive.with_suffix(".metadata").write_bytes(BASE_METADATA)
            initial = stage_fixture(main, save_trial=True)
            self.assertEqual(initial[MARKER_OFFSET:], bytes(4))
            with self.assertRaisesRegex(ValueError, "saved test marker"):
                load_saved_fixture(main)
            saved = after_save_payload(initial)
            self.assertEqual(saved[:MARKER_OFFSET], initial[:MARKER_OFFSET])
            self.assertEqual(saved[MARKER_OFFSET:], SAVE_MARKER)
            (archive / NAME).write_bytes(saved)
            self.assertEqual(load_saved_fixture(main), saved)
            self.assertEqual((archive / NAME).read_bytes(), saved)
            with self.assertRaisesRegex(ValueError, "clear test marker"):
                after_save_payload(saved)

    def test_interruption_barrier_is_between_native_writers(self):
        _, code, plan = artifacts(save_trial=True, interrupt=True)
        barrier = plan["interrupt_barrier"]
        self.assertEqual(struct.unpack_from("<I", code, barrier - START)[0], 0xEAFFFFFE)
        calls = [START + i * 4 for i, (w,) in enumerate(struct.iter_unpack("<I", code))
                 if w >> 24 == 0xEB and branch_target(w, START + i * 4) == WRITE]
        self.assertEqual(len(calls), 2)
        self.assertLess(calls[0], barrier)
        self.assertGreater(calls[1], barrier)
        self.assertNotIn("interrupt_barrier", artifacts(save_trial=True)[2])

    def test_write_verifier_requires_completed_attempt_and_entire_changed_payload(self):
        _, _, plan = artifacts(save_trial=True)
        expected = PREFIX.ljust(FILE_SIZE, b"\0")
        status = (1, WRITE_CALLERS[0] + 4, 0, 1)

        class API:
            def __init__(self, words, payload):
                self.words, self.payload = words, payload

            async def read(self, _context, ranges):
                self.ranges = ranges
                return [struct.pack("<4I", *self.words), self.payload]

        changed = after_save_payload(expected)
        audit = {"memory_read_requests": 0}
        api = API(status, changed)
        result = asyncio.run(read_saved_sidecar(api, None, plan, expected, audit))
        self.assertEqual(result["return_address"], status[1])
        self.assertEqual(audit["memory_read_requests"], 2)
        self.assertEqual(api.ranges[1], (plan["buffer"], FILE_SIZE, "System Bus"))
        for index, bad_value in ((0, 2), (1, 0), (2, 0xFFFFFFFF), (3, 0)):
            bad = list(status)
            bad[index] = bad_value
            with self.subTest(index=index), self.assertRaises(ValueError):
                parse_write_status(struct.pack("<4I", *bad))
        for bad in (expected, changed[:-1], changed[:-5] + b"!" + SAVE_MARKER):
            with self.assertRaisesRegex(ValueError, "changed test marker"):
                asyncio.run(read_saved_sidecar(API(status, bad), None, plan, expected, audit))

    def test_status_and_record_parser_fail_closed(self):
        _, _, plan = artifacts()
        good = struct.pack("<9I", *STATUS)
        self.assertEqual(parse_status(good), (CONTROLLER, MAIN, CALLERS))
        for index, value in ((0, 1), (1, 0), (2, 1), (3, 4), (4, 0), (5, 0), (6, 1), (7, CALLERS[0]), (8, 4)):
            bad = list(STATUS)
            bad[index] = value
            with self.subTest(index=index), self.assertRaises(ValueError):
                parse_status(struct.pack("<9I", *bad))
        records = records_fixture(plan)
        verify_records(records, MAIN, plan)
        for offset in (0, 8, 16, 48, 56, 64):
            changed = bytearray(records)
            changed[offset] ^= 1
            with self.subTest(offset=offset), self.assertRaises(ValueError):
                verify_records(changed, MAIN, plan)
        with self.assertRaises(ValueError):
            verify_records(records[:48], MAIN, plan)

    def test_connector_verifies_challenge_without_writes(self):
        _, _, plan = artifacts()
        expected = PREFIX + b"x" * (FILE_SIZE - len(PREFIX))

        class API:
            def __init__(self, challenge):
                self.memory = {
                    plan["status"]: struct.pack("<9I", *STATUS),
                    plan["buffer"]: challenge,
                    plan["manager"]: struct.pack("<2I", plan["manager_table"], plan["block_table"]),
                    CONTROLLER: struct.pack("<4I", 0x08004000, 2, 2, RECORDS),
                    RECORDS: records_fixture(plan),
                }

            async def read(self, context, ranges):
                return [self.memory[address] for address, _, _ in ranges]

        audit = {"memory_read_requests": 0}
        result = asyncio.run(read_sidecar(API(expected), None, plan, expected, audit))
        self.assertEqual(audit["memory_read_requests"], 5)
        self.assertTrue(result["sidecar_registered_and_loaded"])
        self.assertFalse(result["live_delivery_authorized"])
        self.assertIsNone(result["next_delivery_index"])
        for challenge in (bytes(FILE_SIZE), b"truncated"):
            with self.assertRaises(ValueError):
                asyncio.run(read_sidecar(API(challenge), None, plan, expected, audit))

    def test_cli_disallows_other_save_modes_and_reuse_with_sidecar_modes(self):
        for mode in ("sidecar-load", "sidecar-save", "sidecar-reload", "sidecar-interrupt", "sidecar-rollback",
                      "sidecar-footer-save", "sidecar-footer-reload", "sidecar-index-save", "sidecar-index-reload"):
            for options in (
                [], ["--session", "old"], ["--seed-save", "seed", "--observe-native-save"],
                ["--seed-save", "seed", "--experimental-potion-1-to-2"],
                ["--seed-save", "seed", "--steps", "30:A"],
            ):
                with self.subTest(mode=mode, options=options):
                    r = subprocess.run(
                        [sys.executable, str(ROOT / "tools/run_bizhawk_connector_probe.py"), "--rom", "unused",
                         "--experimental-bootstrap", mode, *options],
                        text=True, capture_output=True, timeout=10,
                    )
                    self.assertEqual(r.returncode, 2)
                    self.assertIn("requires a fresh seed", r.stderr)


if __name__ == "__main__":
    unittest.main()

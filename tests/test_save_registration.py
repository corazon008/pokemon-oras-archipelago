"""Synthetic trace slots and A32 logger layout. No game save or executable."""

import asyncio
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from oras_save_registration import (
    SLOT_SIZE, analyze_registration, build_trace, inspect_trace_slots, read_registration_trace,
)
from oras_save_serialization import branch_target
from oras_save import SAVE_SIZE


def fixture():
    plan = {
        "constructor": 0x100010, "register": 0x100020, "register_return": 0x100030,
        "constructor_caller_return": 0x100104, "register_caller_return": 0x100114,
        "name_address": 0x101000,
    }
    controller, manager, backend, record = 0x08001000, 0x08002000, 0x08003000, 0x08004000
    ctor, before, after = [[0] * 16 for _ in range(3)]
    for slot in (ctor, before, after):
        slot[0] = 1
    ctor[1:6] = [controller, 0x08005000, 1, 0, plan["constructor_caller_return"]]
    before[1:6] = [controller, manager, plan["name_address"], 0, plan["register_caller_return"]]
    after[1] = 1
    before[8:12] = [backend, 0, 1, record]
    after[8:12] = [backend, 1, 1, record]
    return plan, [struct.pack("<16I", *s) for s in (ctor, before, after)]


class RegistrationTraceTests(unittest.TestCase):
    def test_distinguishes_registered_count_from_capacity(self):
        plan, slots = fixture()
        result = inspect_trace_slots(slots, plan)
        self.assertEqual(result["registered_before"], 0)
        self.assertEqual(result["registered_after"], 1)
        self.assertEqual(result["capacity"], 1)
        self.assertFalse(result["second_record_registered"])
        self.assertFalse(result["persistent_ap_storage_allocated"])
        self.assertFalse(result["live_delivery_authorized"])

    def test_missing_partial_or_repeated_calls_fail(self):
        plan, slots = fixture()
        for payloads in (slots[:2], [slots[0][:32], *slots[1:]],
                         [struct.pack("<I", 2) + slots[0][4:], *slots[1:]]):
            with self.assertRaises(ValueError):
                inspect_trace_slots(payloads, plan)

    def test_bad_callers_arguments_and_transitions_fail(self):
        for slot_index, word in ((0, 1), (0, 3), (0, 5), (1, 1), (1, 2), (1, 3),
                                 (1, 5), (1, 9), (1, 10), (2, 1), (2, 8), (2, 9), (2, 10), (2, 11)):
            plan, slots = fixture()
            data = bytearray(slots[slot_index])
            data[word * 4] ^= 1
            slots[slot_index] = bytes(data)
            with self.subTest(slot=slot_index, word=word), self.assertRaises(ValueError):
                inspect_trace_slots(slots, plan)

    def test_generated_hooks_preserve_link_and_relocate_only_push_pop(self):
        plan, _ = fixture()
        info = {"code_segments": [{"address": 0x100000, "image_offset": 0, "size": 64}]}
        image = bytearray(64)
        for at, word in ((16, 0xE92D4070), (32, 0xE92D5FF0), (48, 0xE8BD9FF0)):
            struct.pack_into("<I", image, at, word)
        with patch("oras_save_registration.analyze_registration", return_value=plan):
            records, payload, result = build_trace(info, image, 0x102000, 0x104000)
        hooks = result["hooks"]
        for index, (record, hook) in enumerate(zip(records, hooks)):
            at, patch_bytes = record
            self.assertEqual(at, hook["site"] - 0x100000)
            word = struct.unpack("<I", patch_bytes)[0]
            self.assertEqual(word >> 24, 0xEA)  # B, never BL; preserve original caller LR.
            self.assertEqual(branch_target(word, hook["site"]), hook["trampoline"])
            offset = hook["trampoline"] - 0x102000
            words = struct.unpack_from("<12I", payload, offset)
            self.assertEqual(words[:3], (0xE92D500F, 0xE10FC000, 0xE92D1010))
            literal = offset + 3 * 4 + 8 + (words[3] & 0xFFF)
            self.assertEqual(struct.unpack_from("<I", payload, literal)[0], 0x104040 + index * SLOT_SIZE)
            self.assertEqual(hook["log_length"], SLOT_SIZE)

    def test_static_registration_signatures_fail_closed(self):
        info = {"code_segments": [{"address": 0x100000, "image_offset": 0, "size": 0x20000}]}
        with self.assertRaisesRegex(ValueError, "signature changed"):
            analyze_registration(info, bytes(0x20000))

    def test_async_reads_bind_record_and_never_write(self):
        plan, slots = fixture()
        plan["hooks"] = [{"log_address": 0x104040 + i * 64} for i in range(3)]
        record = bytearray(48)
        struct.pack_into("<I", record, 0, 0x08002000)
        struct.pack_into("<Q", record, 8, SAVE_SIZE)
        record[16:36] = "data:/main".encode("utf-16le")

        class API:
            def __init__(self, bad=None):
                self.calls = []
                self.bad = bad

            async def read(self, context, requests):
                self.calls.append(requests)
                if len(requests) == 3:
                    return slots
                if self.bad == "missing":
                    return []
                if self.bad == "partial":
                    return [bytes(47)]
                if self.bad == "wrong_manager":
                    return [bytes(4) + record[4:]]
                return [bytes(record)]

        api, audit = API(), {"memory_read_requests": 0}
        result = asyncio.run(read_registration_trace(api, None, plan, audit))
        self.assertEqual(result["path"], "data:/main")
        self.assertEqual(audit["memory_read_requests"], 4)
        self.assertEqual(api.calls[-1], [(0x08004000, 48, "System Bus")])
        for bad in ("missing", "partial", "wrong_manager"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                asyncio.run(read_registration_trace(API(bad), None, plan, {"memory_read_requests": 0}))

    def test_raw_failed_trace_is_preserved_in_private_capture(self):
        plan, slots = fixture()
        plan["hooks"] = [{"log_address": 0x104040 + i * 64} for i in range(3)]

        class API:
            async def read(self, context, requests):
                return slots if len(requests) == 3 else [b"partial"]

        with tempfile.TemporaryDirectory(dir="/tmp/opencode") as directory:
            audit = {"memory_read_requests": 0, "exchanges": [{}], "registration_trace_capture": directory}
            with self.assertRaisesRegex(ValueError, "Incomplete registered"):
                asyncio.run(read_registration_trace(API(), None, plan, audit))
            capture = Path(directory) / "connection-02"
            self.assertEqual((capture / "record-01.bin").read_bytes(), b"partial")
            for index, data in enumerate(slots, 1):
                self.assertEqual((capture / f"slot-{index:02d}.bin").read_bytes(), data)


if __name__ == "__main__":
    unittest.main()

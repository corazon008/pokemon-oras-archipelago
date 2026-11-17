"""Offline guard/reference tests; real emulator results are recorded separately."""

import asyncio
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import oras_connector_inventory as inventory
import run_bizhawk_connector_probe as probe
from run_bizhawk_save_probe import seed_archive
from rom_identity import CodeReference
from save_fixtures import synthetic_save
from test_bizhawk_connector import RESPONSES


class Writer:
    async def wait_closed(self):
        pass


class API:
    class BizHawkContext:
        streams = None
        _port = 43055

    def __init__(self, data):
        self.data = data
        self.reads = []

    async def connect(self, context):
        context.streams = (None, Writer())
        return True

    async def get_script_version(self, context):
        return 1

    async def send_requests(self, context, requests):
        return copy.deepcopy(RESPONSES)

    async def read(self, context, requests):
        self.reads.append(requests)
        return [bytes(range(64)) if request[0] == 0x100000 else self.data for request in requests]

    def disconnect(self, context):
        context.streams = None


class Process:
    def poll(self):
        return None


class InventoryTests(unittest.TestCase):
    def test_inventory_rechecked_after_reconnect(self):
        data = bytes([17]) + bytes(0xB90 - 1)
        api = API(data)
        audit = {"memory_read_requests": 0, "memory_write_requests": 0}
        reference = inventory.InventoryReference(0x08C6AC80, data)
        exchanges = asyncio.run(probe.exercise_connector(
            api, Process(), 1, CodeReference(0x100000, bytes(range(64))), audit, reference,
        ))
        self.assertEqual(audit["memory_read_requests"], 4)
        self.assertEqual(audit["memory_write_requests"], 0)
        self.assertEqual(api.reads[1::2], [[(0x08C6AC80, 0xB90, "System Bus")]] * 2)
        self.assertTrue(all(exchange["inventory_read"]["matches_validated_save"] for exchange in exchanges))

    def test_inventory_mismatch_fails_and_counts_attempt(self):
        audit = {"memory_read_requests": 0}
        with self.assertRaisesRegex(ValueError, "does not match"):
            asyncio.run(inventory.read_inventory(
                API(bytes(0xB90)), None, inventory.InventoryReference(1, b"\x11" + bytes(0xB90 - 1)), audit,
            ))
        self.assertEqual(audit["memory_read_requests"], 1)

    def test_reference_requires_exact_build_and_valid_crc(self):
        profiles = json.loads(inventory.Path(inventory.__file__).with_name("oras_memory_candidates.json").read_text())
        rom_hash, profile = next(iter(profiles["profiles"].items()))
        with tempfile.TemporaryDirectory(dir="/tmp/opencode") as directory:
            save = Path(directory) / "main"
            save.write_bytes(synthetic_save(fill=1))
            reference = inventory.load_inventory_reference(rom_hash, profile["program_id"], save)
            self.assertEqual(len(reference.expected), 0xB90)
            for wrong_hash, program in [("0" * 64, profile["program_id"]), (rom_hash, "000400000011C500")]:
                with self.assertRaisesRegex(ValueError, "exact ROM"):
                    inventory.load_inventory_reference(wrong_hash, program, save)
            corrupt = bytearray(save.read_bytes())
            corrupt[0x400] ^= 1
            save.write_bytes(corrupt)
            with self.assertRaisesRegex(ValueError, "checksum"):
                inventory.load_inventory_reference(rom_hash, profile["program_id"], save)

    def test_archive_copy_checks_metadata_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory(dir="/tmp/opencode") as directory:
            root = Path(directory)
            source, target = root / "original/00000001/main", root / "copy/00000001/main"
            source.parent.mkdir(parents=True)
            source.write_bytes(synthetic_save(fill=1))
            with self.assertRaisesRegex(ValueError, "metadata"):
                seed_archive(source, target)
            self.assertFalse(target.exists())
            metadata = source.parent.with_suffix(".metadata")
            metadata.write_bytes(bytes(range(16)))
            manifest = seed_archive(source, target)
            self.assertEqual(source.read_bytes(), target.read_bytes())
            self.assertEqual(metadata.read_bytes(), target.parent.with_suffix(".metadata").read_bytes())
            self.assertEqual(manifest["seed_source"], str(source))
            with self.assertRaises(FileExistsError):
                seed_archive(source, target)


class PotionTests(unittest.TestCase):
    def setUp(self):
        data = bytearray(0xB90)
        data[0x970:0x974] = b"\x11\x00\x01\x00"
        self.reference = inventory.InventoryReference(0x08C6AC80, bytes(data))
        self.code = CodeReference(0x100000, bytes(range(64)))
        # Synthetic code only in offline tests, never bypass production's verified hash.
        self.code_patch = patch.object(
            inventory, "EXPERIMENT_CODE_SHA256", hashlib.sha256(self.code.expected).hexdigest(),
        )
        self.code_patch.start()
        self.addCleanup(self.code_patch.stop)

    def test_only_verified_build_slot_and_transition_are_allowed(self):
        after = inventory.potion_transition(inventory.EXPERIMENT_ROM_SHA256, self.code, self.reference)
        differences = [i for i, (old, new) in enumerate(zip(self.reference.expected, after.expected)) if old != new]
        self.assertEqual(differences, [0x972])
        self.assertEqual(after.expected[0x970:0x974], b"\x11\x00\x02\x00")
        with self.assertRaises(ValueError):
            inventory.potion_transition("0" * 64, self.code, self.reference)
        with self.assertRaises(ValueError):
            inventory.potion_transition(inventory.EXPERIMENT_ROM_SHA256, CodeReference(1, self.code.expected), self.reference)
        for bad in [
            after,
            inventory.InventoryReference(0x08C6AC84, self.reference.expected),
            inventory.InventoryReference(0x08C6AC80, self.reference.expected, "FCRAM"),
            inventory.InventoryReference(0x08C6AC80, bytes(0xB90)),
            inventory.InventoryReference(0x08C6AC80, self.reference.expected + b"\0"),
        ]:
            with self.subTest(reference=bad), self.assertRaises(ValueError):
                inventory.potion_transition(inventory.EXPERIMENT_ROM_SHA256, self.code, bad)

    def api(self, accepted=True, lost=False):
        class WriteAPI(API):
            submissions = []

            async def guarded_write(api, context, writes, guards):
                api.submissions.append((writes, guards))
                if lost:
                    raise ConnectionError("response lost")
                if accepted:
                    data = bytearray(api.data)
                    data[0x972:0x974] = b"\x02\x00"
                    api.data = bytes(data)
                return accepted
        return WriteAPI(self.reference.expected)

    def test_one_write_full_guard_readback_and_post_write_reconnect(self):
        api = self.api()
        audit = {"memory_read_requests": 0, "memory_write_requests": 0}
        exchanges = asyncio.run(probe.exercise_connector(
            api, Process(), 1, self.code, audit, self.reference, inventory.EXPERIMENT_ROM_SHA256,
        ))
        self.assertEqual(len(exchanges), 3)
        self.assertEqual(audit["memory_read_requests"], 7)
        self.assertEqual(audit["memory_write_requests"], 1)
        self.assertEqual(audit["memory_guard_requests"], 2)
        self.assertEqual(len(api.submissions), 1)
        writes, guards = api.submissions[0]
        self.assertEqual(writes, [(0x08C6B5F2, b"\x02\x00", "System Bus")])
        self.assertEqual(guards, [
            (self.code.address, self.code.expected, "System Bus"),
            (self.reference.address, self.reference.expected, "System Bus"),
        ])
        self.assertEqual(exchanges[2]["inventory_read"]["entries"][0]["quantity"], 2)
        self.assertFalse(exchanges[2]["inventory_read"]["matches_validated_save"])
        self.assertTrue(exchanges[2]["inventory_read"]["matches_reference"])

    def test_rejected_or_unknown_write_never_retried(self):
        for accepted, lost, error, status in [
            (False, False, ValueError, "guard_rejected"),
            (True, True, ConnectionError, "submitted_outcome_unknown"),
        ]:
            api = self.api(accepted, lost)
            audit = {"memory_read_requests": 0, "memory_write_requests": 0}
            with self.subTest(status=status), self.assertRaises(error):
                asyncio.run(probe.exercise_connector(
                    api, Process(), 1, self.code, audit, self.reference, inventory.EXPERIMENT_ROM_SHA256,
                ))
            self.assertEqual(len(api.submissions), 1)
            self.assertEqual(audit["potion_experiment"]["status"], status)

    def test_write_readback_failure_aborts(self):
        api = self.api()
        async def stale_read(context, requests):
            return [self.reference.expected]
        api.read = stale_read
        audit = {"memory_read_requests": 0, "memory_write_requests": 0}
        with self.assertRaisesRegex(ValueError, "does not match"):
            asyncio.run(inventory.add_experimental_potion(
                api, None, inventory.EXPERIMENT_ROM_SHA256, self.code, self.reference, audit,
            ))
        self.assertEqual(audit["potion_experiment"]["status"], "acknowledged")
        self.assertEqual(len(api.submissions), 1)

    def test_reconnect_mismatch_prevents_write(self):
        for bad_code in (False, True):
            api = self.api()
            original_read = api.read
            reads = 0
            async def read(context, requests):
                nonlocal reads
                reads += 1
                if (bad_code and reads == 3) or (not bad_code and reads == 4):
                    return [b"\0" * requests[0][1]]
                return await original_read(context, requests)
            api.read = read
            audit = {"memory_read_requests": 0, "memory_write_requests": 0}
            with self.subTest(bad_code=bad_code), self.assertRaisesRegex(ValueError, "does not match"):
                asyncio.run(probe.exercise_connector(
                    api, Process(), 1, self.code, audit, self.reference, inventory.EXPERIMENT_ROM_SHA256,
                ))
            self.assertEqual(api.submissions, [])
            self.assertEqual(audit["memory_write_requests"], 0)

    def test_unknown_code_prefix_is_rejected_before_io(self):
        api = self.api()
        audit = {"memory_read_requests": 0, "memory_write_requests": 0}
        with self.assertRaisesRegex(ValueError, "code reference"):
            asyncio.run(inventory.add_experimental_potion(
                api, None, inventory.EXPERIMENT_ROM_SHA256,
                CodeReference(0x100000, bytes(64)), self.reference, audit,
            ))
        self.assertEqual(api.submissions, [])
        self.assertEqual(audit["memory_write_requests"], 0)


if __name__ == "__main__":
    unittest.main()

"""Synthetic transport/candidate-state tests, not evidence of game progression."""

import asyncio
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from oras_connector_events import (
    OR_ROM_SHA256, EventReference, clock_scene_observation, load_event_reference, read_events,
)
from oras_events import EVENT_LENGTH
from rom_identity import CodeReference
from run_bizhawk_connector_probe import exercise_connector, reuse_profile
from run_bizhawk_save_probe import keyboard_only_config
from save_fixtures import synthetic_save
from test_connector_inventory import API, Process


def clock_block(value):
    block = bytearray(EVENT_LENGTH)
    struct.pack_into("<H", block, 130 * 2, value)
    return bytes(block)


class EventTransportTests(unittest.TestCase):
    def test_only_observed_states_are_classified(self):
        for value, completed in ((2, False), (3, True), (4, True), (0, None), (1, None), (5, None), (65535, None)):
            result = clock_scene_observation(clock_block(value), OR_ROM_SHA256)
            self.assertIs(result["completed_in_observed_states"], completed)
            self.assertFalse(result["production_location_approved"])
            if completed is None:
                self.assertEqual(result["state"], "unknown")

    def test_wrong_build_and_truncation_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "verified OR"):
            clock_scene_observation(clock_block(4), "0" * 64)
        with self.assertRaisesRegex(ValueError, "length"):
            clock_scene_observation(bytes(EVENT_LENGTH - 1), OR_ROM_SHA256)

    def test_reference_requires_profile_and_crc(self):
        with tempfile.TemporaryDirectory(dir="/tmp/opencode") as directory:
            save = Path(directory) / "main"
            save.write_bytes(synthetic_save(fill=1))
            reference = load_event_reference(OR_ROM_SHA256, "000400000011C400", save)
            self.assertEqual(reference.address, 0x08C7DAEC)
            self.assertEqual(len(reference.expected), EVENT_LENGTH)
            for rom_hash, title in ((OR_ROM_SHA256, "000400000011C500"), ("0" * 64, "000400000011C400")):
                with self.assertRaisesRegex(ValueError, "exact ROM"):
                    load_event_reference(rom_hash, title, save)
            data = bytearray(save.read_bytes())
            data[0x14A00] ^= 1
            save.write_bytes(data)
            with self.assertRaisesRegex(ValueError, "checksum"):
                load_event_reference(OR_ROM_SHA256, "000400000011C400", save)

    def test_full_event_block_rechecked_after_reconnect(self):
        data = clock_block(4)
        api = API(data)
        audit = {"memory_read_requests": 0, "memory_write_requests": 0}
        exchanges = asyncio.run(exercise_connector(
            api, Process(), 1, CodeReference(0x100000, bytes(range(64))), audit,
            event_reference=EventReference(0x08C7DAEC, data, OR_ROM_SHA256),
        ))
        self.assertEqual(len(exchanges), 2)
        self.assertEqual(audit["memory_read_requests"], 4)
        self.assertEqual(audit["memory_write_requests"], 0)
        self.assertEqual(api.reads[1::2], [[(0x08C7DAEC, EVENT_LENGTH, "System Bus")]] * 2)
        self.assertTrue(all(exchange["event_read"]["clock_scene"]["completed_in_observed_states"] for exchange in exchanges))

    def test_event_mismatch_fails_and_counts_attempt(self):
        audit = {"memory_read_requests": 0}
        with self.assertRaisesRegex(ValueError, "do not match"):
            asyncio.run(read_events(
                API(clock_block(5)), None, EventReference(0x08C7DAEC, clock_block(4), OR_ROM_SHA256), audit,
            ))
        self.assertEqual(audit["memory_read_requests"], 1)

    def test_event_observations_require_code_guard(self):
        api = API(clock_block(4))
        with self.assertRaisesRegex(ValueError, "code guard"):
            asyncio.run(exercise_connector(
                api, Process(), 1, audit={"memory_read_requests": 0},
                event_reference=EventReference(0x08C7DAEC, clock_block(4), OR_ROM_SHA256),
            ))
        self.assertEqual(api.reads, [])


class ReuseTests(unittest.TestCase):
    def test_reuse_isolated_matching_profile_keeps_keyboard_bindings(self):
        with tempfile.TemporaryDirectory(dir="/tmp/opencode") as directory:
            path = Path(directory)
            runtime = path / "runtime"
            runtime.mkdir()
            (path / "profile.json").write_text(json.dumps({
                "kind": "oras_native_save_probe", "rom_sha256": OR_ROM_SHA256,
            }))
            (runtime / "config.ini").write_text(json.dumps(keyboard_only_config({"SpeedPercent": 400})))
            reused, manifest = reuse_profile(path, OR_ROM_SHA256)
            self.assertEqual(reused, runtime)
            self.assertEqual(manifest["rom_sha256"], OR_ROM_SHA256)
            config = json.loads((runtime / "config.ini").read_text())
            self.assertEqual(config["SpeedPercent"], 100)
            self.assertEqual(config["AllTrollers"]["3DS Controller"]["A"], "X")

    def test_reuse_requires_matching_manifest_and_private_path(self):
        for path in (Path("/tmp/opencode"), Path("/home")):
            with self.subTest(path=path), self.assertRaisesRegex(ValueError, "private children"):
                reuse_profile(path, OR_ROM_SHA256)
        with tempfile.TemporaryDirectory(dir="/tmp/opencode") as directory:
            path = Path(directory)
            (path / "profile.json").write_text(json.dumps({
                "kind": "oras_native_save_probe", "rom_sha256": "0" * 64,
            }))
            with self.assertRaisesRegex(ValueError, "identity mismatch"):
                reuse_profile(path, OR_ROM_SHA256)

    def test_reuse_rejects_symlinked_runtime(self):
        with tempfile.TemporaryDirectory(dir="/tmp/opencode") as directory:
            path = Path(directory)
            (path / "profile.json").write_text(json.dumps({
                "kind": "oras_native_save_probe", "rom_sha256": OR_ROM_SHA256,
            }))
            (path / "runtime").symlink_to(path, target_is_directory=True)
            with self.assertRaisesRegex(ValueError, "inside"):
                reuse_profile(path, OR_ROM_SHA256)


if __name__ == "__main__":
    unittest.main()

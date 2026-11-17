"""Offline tests for the metadata harness; no emulator or game is simulated as validated."""

import asyncio
import copy
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))
import ap_connector_bundle as bundle
import run_bizhawk_connector_probe as probe
from run_bizhawk_probe import prepare_runtime
from rom_identity import CodeReference


RESPONSES = [
    {"type": "PONG"},
    {"type": "SYSTEM_RESPONSE", "value": "3DS"},
    {"type": "MEMORY_SIZE_RESPONSE", "value": 268435456},
    {"type": "MEMORY_SIZE_RESPONSE", "value": 0},
]


class BundleTests(unittest.TestCase):
    def test_lock_is_pinned_and_contains_linux_library_and_license(self):
        lock = bundle.read_lock()
        paths = {entry["path"] for entry in lock["files"]}
        self.assertIn("x64/socket-linux-5-4.so", paths)
        self.assertIn("x64/luasocket.LICENSE.txt", paths)
        self.assertIn("bizhawk_api.py", paths)

    def test_corrupt_bundle_is_rejected_before_import(self):
        with tempfile.TemporaryDirectory(dir="/tmp/opencode") as directory:
            path = Path(directory)
            (path / "bizhawk_api.py").write_text("raise AssertionError('must not execute')")
            lock = {"files": [{"path": "bizhawk_api.py", "sha256": "0" * 64}]}
            with self.assertRaisesRegex(ValueError, "checksum mismatch"):
                bundle.load_upstream_api(path, lock)

    def test_fetch_verifies_before_writing(self):
        data = b"verified data"
        lock = {
            "repository": "ArchipelagoMW/Archipelago",
            "commit": "a" * 40,
            "files": [{"path": "test.lua", "upstream_path": "data/lua/test.lua",
                       "sha256": hashlib.sha256(data).hexdigest()}],
        }
        with tempfile.TemporaryDirectory(dir="/tmp/opencode") as directory:
            target = Path(directory) / "bundle"
            with patch.object(bundle, "read_lock", return_value=lock):
                with patch.object(bundle.urllib.request, "urlopen", return_value=io.BytesIO(data)):
                    bundle.fetch_bundle(target)
            self.assertEqual((target / "test.lua").read_bytes(), data)

    def test_bad_download_is_not_written(self):
        lock = {
            "repository": "ArchipelagoMW/Archipelago",
            "commit": "a" * 40,
            "files": [{"path": "test.lua", "upstream_path": "data/lua/test.lua",
                       "sha256": "0" * 64}],
        }
        with tempfile.TemporaryDirectory(dir="/tmp/opencode") as directory:
            target = Path(directory) / "bundle"
            with patch.object(bundle, "read_lock", return_value=lock):
                with patch.object(bundle.urllib.request, "urlopen", return_value=io.BytesIO(b"wrong")):
                    with self.assertRaisesRegex(ValueError, "checksum mismatch"):
                        bundle.fetch_bundle(target)
            self.assertFalse((target / "test.lua").exists())

    def test_private_runtime_excludes_existing_3ds_data(self):
        with tempfile.TemporaryDirectory(dir="/tmp/opencode") as directory:
            root = Path(directory)
            source = root / "source"
            (source / "3DS/User").mkdir(parents=True)
            (source / "3DS/User/personal-save").write_text("untouched")
            (source / "EmuHawk.exe").write_bytes(b"fixture")
            (source / "config.ini").write_text(json.dumps({"RecentRoms": {"AutoLoad": True}}))
            session = root / "session"
            runtime = prepare_runtime(source, session)
            self.assertFalse((runtime / "3DS").exists())
            self.assertTrue((runtime / "EmuHawk.exe").exists())
            self.assertEqual((source / "3DS/User/personal-save").read_text(), "untouched")
            self.assertTrue(json.loads((source / "config.ini").read_text())["RecentRoms"]["AutoLoad"])


class ProtocolTests(unittest.TestCase):
    def test_requests_are_metadata_only(self):
        self.assertEqual({request["type"] for request in probe.REQUESTS},
                         {"PING", "SYSTEM", "MEMORY_SIZE"})
        probe.validate_responses(RESPONSES)

    def test_wrong_system_and_changed_bus_behavior_fail(self):
        responses = copy.deepcopy(RESPONSES)
        responses[1]["value"] = "NULL"
        with self.assertRaisesRegex(ValueError, "3DS"):
            probe.validate_responses(responses)
        responses = copy.deepcopy(RESPONSES)
        responses[3]["value"] = 4294967296
        with self.assertRaisesRegex(ValueError, "changed"):
            probe.validate_responses(responses)

    def test_disconnect_and_reconnect_use_upstream_api(self):
        class Context:
            streams = None
            _port = 43055

        class Writer:
            async def wait_closed(self):
                pass

        class API:
            BizHawkContext = Context
            connections = 0

            async def connect(self, context):
                self.connections += 1
                context.streams = (None, Writer())
                return True

            async def get_script_version(self, context):
                return 1

            async def send_requests(self, context, requests):
                self.asserted_requests = requests
                return copy.deepcopy(RESPONSES)

            def disconnect(self, context):
                context.streams = None

        class Process:
            def poll(self):
                return None

        api = API()
        exchanges = asyncio.run(probe.exercise_connector(api, Process(), 1))
        self.assertEqual(api.connections, 2)
        self.assertEqual(len(exchanges), 2)
        self.assertEqual(api.asserted_requests, list(probe.REQUESTS))

    def test_mismatched_code_read_fails_and_records_attempt(self):
        class Context:
            streams = None
            _port = 43055

        class API:
            BizHawkContext = Context

            async def connect(self, context):
                return True

            async def get_script_version(self, context):
                return 1

            async def send_requests(self, context, requests):
                return copy.deepcopy(RESPONSES)

            async def read(self, context, requests):
                return [b"\0" * 64]

            def disconnect(self, context):
                pass

        class Process:
            def poll(self):
                return None

        audit = {"memory_read_requests": 0}
        with self.assertRaisesRegex(ValueError, "does not match"):
            asyncio.run(probe.exercise_connector(
                API(), Process(), 1, CodeReference(0x100000, bytes(range(64))), audit
            ))
        self.assertEqual(audit["memory_read_requests"], 1)

    def test_matching_code_is_read_only_and_rechecked_after_reconnect(self):
        expected = bytes(range(64))
        reads = []

        class Writer:
            async def wait_closed(self):
                pass

        class Context:
            streams = None
            _port = 43055

        class API:
            BizHawkContext = Context

            async def connect(self, context):
                context.streams = (None, Writer())
                return True

            async def get_script_version(self, context):
                return 1

            async def send_requests(self, context, requests):
                return copy.deepcopy(RESPONSES)

            async def read(self, context, requests):
                reads.append(requests)
                return [expected]

            def disconnect(self, context):
                context.streams = None

        class Process:
            def poll(self):
                return None

        audit = {"memory_read_requests": 0}
        exchanges = asyncio.run(probe.exercise_connector(
            API(), Process(), 1, CodeReference(0x100000, expected), audit
        ))
        self.assertEqual(audit["memory_read_requests"], 2)
        self.assertEqual(reads, [[(0x100000, 64, "System Bus")]] * 2)
        self.assertTrue(all(exchange["code_read"]["matches_rom_prefix"] for exchange in exchanges))
        self.assertNotIn("expected", json.dumps(exchanges))


if __name__ == "__main__":
    unittest.main()

"""Offline checks for strict-mode readiness and response validation; no game writes."""

import asyncio
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import run_bizhawk_connector_probe as probe
from rom_identity import CodeReference


class StrictProtocolTests(unittest.TestCase):
    def test_guard_tests_send_no_write_and_count_skipped_read(self):
        class API:
            requests = []

            async def send_requests(self, context, requests):
                self.requests.append(requests)
                response = {"type": "GUARD_RESPONSE", "address": 0x100000, "value": len(self.requests) == 1}
                return [response] * len(requests)

        api = API()
        audit = {"memory_read_requests": 0, "memory_write_requests": 0}
        result = asyncio.run(probe.test_strict_guard(api, None, CodeReference(0x100000, bytes(range(64))), audit))
        self.assertTrue(result["following_read_skipped"])
        self.assertEqual([r["type"] for batch in api.requests for r in batch], ["GUARD", "GUARD", "READ"])
        self.assertEqual(audit["memory_guard_requests"], 2)
        self.assertEqual(audit["memory_read_requests"], 1)
        self.assertEqual(audit["read_requests_blocked_by_guard"], 1)
        self.assertEqual(audit["memory_write_requests"], 0)

    def test_fallback_that_permits_read_is_not_a_success(self):
        class API:
            calls = 0

            async def send_requests(self, context, requests):
                self.calls += 1
                result = [{"type": "GUARD_RESPONSE", "address": 0x100000, "value": True}]
                if self.calls == 2:
                    result.append({"type": "READ_RESPONSE", "value": "not recorded"})
                return result

        audit = {"memory_read_requests": 0, "memory_write_requests": 0}
        with self.assertRaisesRegex(ValueError, "did not skip"):
            asyncio.run(probe.test_strict_guard(API(), None, CodeReference(0x100000, bytes(range(64))), audit))
        self.assertNotIn("read_requests_blocked_by_guard", audit)

    def test_missing_installation_blocks_before_connect(self):
        class API:
            class BizHawkContext:
                pass

            async def connect(self, context):
                raise AssertionError("Must not connect before shim readiness")

            def disconnect(self, context):
                pass

        class Exited:
            def poll(self):
                return 0

        with tempfile.TemporaryDirectory(dir="/tmp/opencode") as directory:
            with self.assertRaisesRegex(RuntimeError, "before strict GUARD"):
                asyncio.run(probe.exercise_connector(
                    API(), Exited(), 1, CodeReference(0x100000, bytes(range(64))),
                    {"memory_read_requests": 0, "memory_write_requests": 0},
                    strict_ready=Path(directory) / "missing-ready",
                ))

    def object_exchange(self, changed=False):
        class Writer:
            async def wait_closed(self):
                pass

        class API:
            class BizHawkContext:
                _port = 43055
                streams = (None, Writer())

            async def get_script_version(self, context):
                return 1

            async def send_requests(self, context, requests):
                if requests != list(probe.REQUESTS):
                    raise AssertionError("Unexpected metadata requests")
                return [
                    {"type": "PONG"}, {"type": "SYSTEM_RESPONSE", "value": "3DS"},
                    {"type": "MEMORY_SIZE_RESPONSE", "value": 268435456},
                    {"type": "MEMORY_SIZE_RESPONSE", "value": 0},
                ]

            async def read(self, context, requests):
                address, size, domain = requests[0]
                if address == 0x100000:
                    return [bytes(64)]
                assert (address, size, domain) == (0x08004000, 2004, "System Bus")
                return [bytes(2004) if not changed else b"x" * 2004]

            def disconnect(self, context):
                pass

        audit = {"memory_read_requests": 0, "memory_write_requests": 0, "save_objects": {}}
        with tempfile.TemporaryDirectory(dir="/tmp/opencode") as directory:
            ready = Path(directory) / "ready"
            ready.touch()
            with patch.object(probe, "connect_until_ready", new=AsyncMock()), \
                    patch.object(probe, "test_strict_guard", new=AsyncMock(return_value={})), \
                    patch("oras_save_objects.load_object_observation",
                          return_value=CodeReference(0x08004000, bytes(2004))):
                exchanges = asyncio.run(probe.exercise_connector(
                    API(), None, 1, CodeReference(0x100000, bytes(64)), audit,
                    strict_ready=ready, object_capture=Path(directory),
                ))
        return exchanges, audit

    def test_full_object_rechecked_across_two_connections(self):
        exchanges, audit = self.object_exchange()
        self.assertEqual(len(exchanges), 2)
        self.assertTrue(all(row["save_object_read"]["matches_private_plan"] for row in exchanges))
        self.assertEqual(audit["memory_read_requests"], 4)
        self.assertEqual(audit["memory_write_requests"], 0)

    def test_changed_object_aborts_connection(self):
        with self.assertRaisesRegex(ValueError, "Save-object bytes changed"):
            self.object_exchange(changed=True)


if __name__ == "__main__":
    unittest.main()

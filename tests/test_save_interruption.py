"""Interruption orchestration tests: fake owned child; no real process signals."""

import asyncio
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from oras_save_interruption import interrupt_at_barrier


class InterruptionTests(unittest.TestCase):
    def run_script(self, responses, exit_code=-9):
        expected = bytes(512)
        api = Mock(read=AsyncMock(side_effect=responses))
        child = Mock()
        child.poll.return_value = None
        child.wait.return_value = exit_code
        report = {"memory_read_requests": 0}
        with tempfile.TemporaryDirectory(dir="/tmp/opencode") as root:
            signal = Path(root) / "finish-ui"
            try:
                asyncio.run(interrupt_at_barrier(
                    api, None, child, {"interrupt_barrier": 4, "write_status": 8, "buffer": 32},
                    expected, signal, report,
                ))
            except (ValueError, RuntimeError) as error:
                return child, report, str(error), signal.exists()
            return child, report, None, signal.exists()

    def test_only_confirmed_boundary_may_issue_the_interruption(self):
        idle = bytes(16)
        parked = struct.pack("<4I", 1, 0x124E54, 0xFFFFFFFF, 2)
        child, audit, error, signalled = self.run_script([[idle], [parked], [parked, bytes(512)]])
        self.assertIsNone(error)
        self.assertTrue(signalled)
        child.kill.assert_called_once_with()
        self.assertTrue(audit["interruption"]["sigkill_confirmed"])
        for responses in (
            [[parked]], [[idle], []], [[idle], [struct.pack("<4I", 1, 0x124E54, 0, 1)]],
            [[idle], [struct.pack("<4I", 1, 12, 0xFFFFFFFF, 2)]],
            [[idle], [parked], [idle, bytes(512)]], [[idle], [parked], [parked, bytes([1]) * 512]],
        ):
            child, audit, error, signalled = self.run_script(responses)
            self.assertIsNotNone(error)
            child.kill.assert_not_called()
            self.assertEqual(signalled, responses[0] == [idle])
            self.assertNotIn("sigkill_confirmed", audit["interruption"])

    def test_clean_exit_does_not_count_as_interruption(self):
        parked = struct.pack("<4I", 1, 0x124E54, 0xFFFFFFFF, 2)
        _, audit, error, _ = self.run_script([[bytes(16)], [parked], [parked, bytes(512)]], exit_code=0)
        self.assertIn("SIGKILL", error)
        self.assertNotIn("sigkill_confirmed", audit["interruption"])

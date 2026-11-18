"""Strict GUARD tests use synthetic bytes and mock memory only."""

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from ap_connector_bundle import read_lock, verify_bundle

LUA = shutil.which("lua5.4")
FACTORY = ROOT / "tools/strict_bizhawk_guard.lua"


@unittest.skipUnless(LUA, "Lua 5.4 is required")
class StrictGuardTests(unittest.TestCase):
    def run_case(self, body):
        script = f"""
local raw_factory = dofile({str(FACTORY)!r})
local function factory(read, decode)
    return raw_factory(read, decode, function(address, size, domain)
        return domain == "System Bus"
    end)
end
local request = {{type="GUARD", address=16, domain="System Bus", expected_data="fixture"}}
local function decode() return {{1,2,3,4}} end
{body}
"""
        result = subprocess.run([LUA, "-"], input=script, text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_exact_match_and_mismatch(self):
        self.run_case("""
local guard = factory(function() return {1,2,3,4} end, decode)
assert(guard(request).value == true)
guard = factory(function() return {1,2,3,5} end, decode)
assert(guard(request).value == false)
""")

    def test_read_exception_is_guard_failure_not_error(self):
        self.run_case("""
local guard = factory(function() error("invalid domain") end, decode)
local result = guard(request)
assert(result.type == "GUARD_RESPONSE" and result.value == false and result.address == 16)
""")

    def test_short_empty_or_wrong_type_read_fails(self):
        self.run_case("""
for _, value in ipairs({{}, {1,2}, {1,2,3,4,5}, "bad", false}) do
    local result = factory(function() return value end, decode)(request)
    assert(result.type == "GUARD_RESPONSE" and result.value == false)
end
""")

    def test_decode_exception_and_empty_guard_fail(self):
        self.run_case("""
local reads = 0
for _, decode_bad in ipairs({
    function() error("bad base64") end,
    function() return {} end,
    function() return false end,
    function() local t={} for i=1,65537 do t[i]=0 end return t end,
}) do
    assert(factory(function() reads=reads+1; return {} end, decode_bad)(request).value == false)
end
assert(reads == 0)
""")

    def test_invalid_requests_fail_before_read(self):
        self.run_case("""
local reads = 0
local guard = factory(function() reads=reads+1; return {1,2,3,4} end, decode)
assert(guard(nil).value == false)
assert(guard(false).value == false)
for _, address in ipairs({-1, 1.5, 0x100000000, 0xFFFFFFFE}) do
    request.address = address
    assert(guard(request).value == false)
end
request.address = 16; request.domain = false
assert(guard(request).value == false)
assert(reads == 0)
""")

    def test_domain_validator_prevents_fallback_and_overflow_reads(self):
        self.run_case("""
local reads = 0
local guard = raw_factory(function() reads=reads+1; return {1,2,3,4} end, decode,
    function(address, size, domain) return domain == "System Bus" and address + size <= 64 end)
request.domain = "missing"
assert(guard(request).value == false)
request.domain = "System Bus"; request.address = 63
assert(guard(request).value == false)
assert(reads == 0)
""")

    def test_invalid_bytes_fail(self):
        self.run_case("""
for _, bad in ipairs({256, -1, 2.5, "3", false}) do
    assert(factory(function() return {1,2,bad,4} end, decode)(request).value == false)
    assert(factory(function() return {1,2,3,4} end,
                   function() return {1,2,bad,4} end)(request).value == false)
end
""")

    def test_pinned_dispatcher_control_and_strict_mode(self):
        # Optional integration against an already verified bundle. No downloads.
        bundles = sorted((ROOT / "local/oras/profiles").glob("*/connector-attempt-*/connector"))
        if not bundles:
            self.skipTest("No cached pinned AP connector bundle")
        bundle = bundles[0]
        verify_bundle(bundle, read_lock())
        with tempfile.TemporaryDirectory(dir="/tmp/opencode") as directory:
            for strict in (False, True):
                env = os.environ.copy()
                for name in ("ORAS_CONNECTOR_BOOT", "ORAS_CONNECTOR_POST_SCRIPT",
                             "ORAS_CONNECTOR_STRICT_GUARD_SCRIPT", "ORAS_CONNECTOR_STRICT_GUARD_READY"):
                    env.pop(name, None)
                env.update({
                    "ORAS_CONNECTOR_DIRECTORY": str(bundle),
                    "ORAS_CONNECTOR_STOP": str(Path(directory) / "stop"),
                    "ORAS_CONNECTOR_TIMEOUT": "60", "ORAS_FIXTURE_STRICT": str(int(strict)),
                    "ORAS_FIXTURE_WRAPPER": str(ROOT / "tools/bizhawk_connector_probe.lua"),
                })
                if strict:
                    env.update({
                        "ORAS_CONNECTOR_STRICT_GUARD_SCRIPT": str(FACTORY),
                        "ORAS_CONNECTOR_STRICT_GUARD_READY": str(Path(directory) / "ready"),
                    })
                result = subprocess.run(
                    [LUA, str(ROOT / "tests/strict_guard_dispatcher_fixture.lua")],
                    env=env, text=True, capture_output=True, timeout=10,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn("STRICT_GUARD_FIXTURE_PASS", result.stdout)


if __name__ == "__main__":
    unittest.main()

from pathlib import Path
import shutil
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
LUA = shutil.which("lua5.4") or shutil.which("lua")


def literal(data):
    return '"' + "".join(f"\\x{byte:02x}" for byte in data) + '"'


@unittest.skipUnless(LUA, "Lua is not installed")
class InventorySearchTests(unittest.TestCase):
    def search(self, data, pattern, truncate=False):
        script = f"""
local search = dofile({str(ROOT / 'tools/inventory_search.lua')!r})
local blob, pattern = {literal(data)}, {literal(pattern)}
local calls = 0
local found, reads = search(function(address, size)
    calls = calls + 1
    local result = blob:sub(address + 1, address + size)
    if {str(truncate).lower()} then result = result:sub(2) end
    return result
end, 0, #blob, pattern, 32)
assert(calls == reads)
for _, address in ipairs(found) do print(address) end
"""
        return subprocess.run([LUA, "-"], input=script, text=True, capture_output=True, timeout=10)

    def test_match_crosses_chunk_boundary(self):
        pattern = b"\0" * 4 + b"\x11\0\1\0" + b"\0" * 4
        result = self.search(b"\0" * 29 + pattern + b"\0" * 80, pattern)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["29"])

    def test_multiple_copies_are_not_silently_selected(self):
        pattern = b"\1\0\2\0" + b"\0" * 8
        result = self.search(b"x" * 17 + pattern + b"x" * 51 + pattern + b"x" * 40, pattern)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["17", "80"])

    def test_anchor_without_full_pattern_is_not_a_match(self):
        pattern = b"\x11\0\1\0" + b"\0" * 8
        result = self.search(b"\x11\0\1\0" + b"x" * 80, pattern)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")

    def test_all_zero_reference_fails(self):
        result = self.search(b"\0" * 80, b"\0" * 12)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("All-zero", result.stderr)

    def test_incomplete_read_fails(self):
        result = self.search(b"x" * 80, b"\1\0\2\0" + b"\0" * 8, truncate=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Incomplete", result.stderr)

    def test_match_limit_fails_closed(self):
        pattern = b"\1\0\2\0" + b"\0" * 8
        result = self.search((pattern + b"x") * 20, pattern)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ambiguous", result.stderr)


if __name__ == "__main__":
    unittest.main()

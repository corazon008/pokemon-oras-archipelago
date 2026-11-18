"""Synthetic dispatch, plan and Lua memory fixtures; no proprietary game data."""

import hashlib
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from oras_save import BLOCKS, SAVE_SIZE
import oras_save_objects as objects


def executable_fixture():
    image = bytearray(0x1100)
    info = {"program_id": "000400000011C400", "code_segments": [
        {"name": "text", "address": 0x100000, "image_offset": 0, "size": 0x200},
        {"name": "ro", "address": 0x500000, "image_offset": 0x1000, "size": 0x100},
    ]}
    for index, instruction in enumerate((0xE3A00EB9, 0xE59F0000, 0xE3A00E7D)):
        provider = 0x40 + index * 0x40
        getter = provider + 0x20
        struct.pack_into("<III", image, provider, instruction, 0xE12FFF1E, (2960, 1284, 2000)[index])
        struct.pack_into("<II", image, getter, 0xE2800004, 0xE12FFF1E)
        struct.pack_into("<6I", image, 0x1000 + index * 24,
                         *([0x100000 + getter] * 4), 0x100000 + provider, 0x100000 + getter)
    return info, bytes(image)


PROFILE = {
    "program_id": "000400000011C400", "domain": "System Bus",
    "inventory_address": "0x08001004", "event_work": {"address": "0x08003004"},
}


class ObjectPlanTests(unittest.TestCase):
    def build(self, image=None, profile=PROFILE, hash_value=objects.OR_HASH):
        info, fixture_image = executable_fixture()
        with patch.object(objects, "load_code", return_value=(info, fixture_image if image is None else image)), \
                patch.object(objects, "sha256_file", return_value=hash_value), \
                patch.object(objects, "validate_save") as validate:
            result = objects.build_plan(Path("synthetic.3ds"), objects.OR_HASH, bytes(SAVE_SIZE), profile)
        validate.assert_called_once()
        return result

    def test_three_distinct_dispatches(self):
        info, image = executable_fixture()
        candidates = objects.object_candidates(info, image)
        self.assertEqual([row["block_id"] for row in candidates], [1, 19, 47])
        self.assertEqual([row["dispatch_address"] for row in candidates], [0x500000, 0x500018, 0x500030])
        self.assertTrue(all(row["payload_offset_from_object"] == 4 for row in candidates))

    def test_rejects_wrong_getter_and_nontext_dispatch_entry(self):
        info, fixture_image = executable_fixture()
        for offset, value in ((0x60, 0xE2800008), (0x1000, 0x500000), (0x1000, 0x100061)):
            image = bytearray(fixture_image)
            struct.pack_into("<I", image, offset, value)
            self.assertEqual([row["block_id"] for row in objects.object_candidates(info, image)], [19, 47])

    def test_missing_and_ambiguous_candidates_abort(self):
        _, fixture_image = executable_fixture()
        image = bytearray(fixture_image)
        image[0x1048:0x1060] = image[0x1030:0x1048]
        with self.assertRaisesRegex(ValueError, "got 2"):
            self.build(image)
        image[0x1030:0x1060] = bytes(48)
        with self.assertRaisesRegex(ValueError, "got 0"):
            self.build(image)

    def test_plan_contains_literal_known_headers_and_nonzero_pattern(self):
        plan, report = self.build()
        count = struct.unpack_from("<I", plan)[0]
        cursor, refs = 4, {}
        for _ in range(count):
            address, length = struct.unpack_from("<II", plan, cursor)
            cursor += 8
            refs[address] = plan[cursor:cursor + length]
            cursor += length
        self.assertEqual(refs[0x100088], struct.pack("<I", 1284))
        self.assertEqual(refs[0x08001000], struct.pack("<I", 0x500000))
        self.assertEqual(refs[0x08003000], struct.pack("<I", 0x500018))
        self.assertEqual(struct.unpack_from("<I", plan, cursor)[0], 2004)
        self.assertEqual(plan[cursor + 4:], struct.pack("<I", 0x500030) + bytes(2000))
        self.assertEqual(report["source_save_sha256"], hashlib.sha256(bytes(SAVE_SIZE)).hexdigest())
        self.assertFalse(report["write_allowed"])
        self.assertFalse(report["ownership_proven"])

    def test_wrong_rom_hash_domain_and_heap_rejected(self):
        with self.assertRaisesRegex(ValueError, "ROM hash"):
            self.build(hash_value="0" * 64)
        with self.assertRaisesRegex(ValueError, "verified OR"):
            self.build(profile={**PROFILE, "domain": "missing"})
        with self.assertRaisesRegex(ValueError, "outside"):
            self.build(profile={**PROFILE, "inventory_address": "0x10000000"})


class ObjectObservationTests(unittest.TestCase):
    def observation(self, matches="0x08004000\n", modified_plan=False, reads=130, manager=False):
        with tempfile.TemporaryDirectory(dir="/tmp/opencode") as directory:
            capture = Path(directory)
            plan = struct.pack("<I", 2004) + struct.pack("<I", 0x500030) + bytes(2000)
            report = {"plan_sha256": hashlib.sha256(plan).hexdigest(), "reference_ranges": [{}, {}]}
            if manager:
                report["manager"] = {}
            (capture / "complete").write_text("read-only\n")
            (capture / "matches.txt").write_text(matches)
            (capture / "references.bin").write_bytes(plan + (b"x" if modified_plan else b""))
            (capture / "read-requests.txt").write_text("read\n" * reads)
            return objects.load_object_observation(capture, report), report

    def test_unique_plan_bound_observation(self):
        reference, report = self.observation(reads=131)
        self.assertEqual(reference.address, 0x08004000)
        self.assertEqual(len(reference.expected), 2004)
        self.assertEqual(report["payload_candidates"], ["0x08004004"])
        self.assertTrue(report["unique_heap_match_rechecked"])

    def test_missing_ambiguous_or_bad_range_aborts(self):
        for matches in ("", "0x08004000\n0x08005000\n", "0x08004001\n", "0x00000000\n"):
            with self.subTest(matches=matches), self.assertRaises(ValueError):
                self.observation(matches=matches, reads=131)

    def test_modified_plan_or_bad_read_count_aborts(self):
        with self.assertRaisesRegex(ValueError, "plan changed"):
            self.observation(modified_plan=True, reads=131)
        with self.assertRaisesRegex(ValueError, "read count"):
            self.observation(reads=130)

    def test_manager_reads_are_separately_accounted(self):
        _, report = self.observation(reads=192, manager=True)
        self.assertEqual(report["lua_memory_read_requests"], 192)
        with self.assertRaisesRegex(ValueError, "read count"):
            self.observation(reads=131, manager=True)


@unittest.skipUnless(shutil.which("lua5.4"), "Lua 5.4 is required")
class LuaObjectProbeTests(unittest.TestCase):
    def run_probe(self, mode):
        with tempfile.TemporaryDirectory(dir="/tmp/opencode") as directory:
            capture = Path(directory)
            reference = b"code"
            pattern = struct.pack("<I", 0x500030) + bytes(2000)
            plan = struct.pack("<III", 1, 0x100000, len(reference)) + reference
            plan += struct.pack("<I", len(pattern)) + pattern
            (capture / "plan").write_bytes(plan)
            env = {**os.environ, "ORAS_OBJECT_CAPTURE": directory,
                   "ORAS_OBJECT_PLAN": str(capture / "plan"),
                   "ORAS_OBJECT_SEARCH": str(ROOT / "tools/inventory_search.lua")}
            env.pop("ORAS_OBJECT_MANAGER_TABLE", None)
            if mode in ("manager", "references"):
                env["ORAS_OBJECT_MANAGER_TABLE"] = str(0x08CDCC78)
            env.pop("ORAS_OBJECT_MANAGER_REFERENCES", None)
            if mode == "references":
                env["ORAS_OBJECT_MANAGER_REFERENCES"] = "1"
            script = f"""
local mode = {mode!r}
local pattern = string.pack("<I4", 0x500030) .. string.rep("\\0", 2000)
local found = 0x08100000 - 12 -- Deliberately crosses a chunk boundary.
local calls = 0
emu = {{getsystemid=function() return "3DS" end}}
memory = {{
 getmemorydomainlist=function() return {{[0]=mode == "domain" and "other" or "System Bus"}} end,
 getmemorydomainsize=function() return 0 end,
 read_bytes_as_binary_string=function(address, length, domain)
   assert(domain == "System Bus")
   calls = calls + 1
   if address == 0x100000 then return mode == "reference" and "bad!" or "code" end
   if mode == "manager" or mode == "references" then
     if address == 0x08CDCC78 - 0x722D0 then return string.pack("<I4I4", 0x500000, 0x08300000) end
     if address == 0x08CDCC78 then
       local t = {{}} for i=0,57 do t[#t+1] = string.pack("<I4", 0x08200000+i*4) end
       return table.concat(t)
     end
     if length == 4 and address >= 0x08200000 and address < 0x08200000+232 then return string.pack("<I4", 0x500030) end
     if address == 0x08300000 and length == 504 then return string.rep("\\0", 504) end
   end
   if mode == "short" then return "" end
   if mode == "changed" and length == #pattern then return string.rep("\\0", length) end
   local bytes = string.rep("\\0", length)
   if mode ~= "empty" then
     local first, last = math.max(address, found), math.min(address+length, found+#pattern)
     if first < last then
       bytes = bytes:sub(1, first-address) .. pattern:sub(first-found+1, last-found) .. bytes:sub(last-address+1)
     end
   end
   if mode == "references" and address <= 0x08400100 and address+length >= 0x08400104 then
     local at = 0x08400100-address
     bytes = bytes:sub(1, at) .. string.pack("<I4", 0x08CDCC78-0x722D0) .. bytes:sub(at+5)
     if at+36 <= length then
       local path = "" for char in ("data:/main"):gmatch(".") do path=path..char.."\\0" end
       bytes = bytes:sub(1, at+8) .. string.pack("<I4", 0x76000) .. bytes:sub(at+13, at+16)
               .. path .. bytes:sub(at+37)
     end
   end
   if mode == "references" and address <= 0x08500120 and address+length >= 0x08500124 then
     local at = 0x08500120-address
     bytes = bytes:sub(1, at) .. string.pack("<I4", 0x08400100) .. bytes:sub(at+5)
   end
   return bytes
 end,
 write_bytes_as_array=function() error("WRITE forbidden") end,
}}
local ok, err = pcall(dofile, {str(ROOT / 'tools/bizhawk_save_object_probe.lua')!r})
if mode == "match" or mode == "empty" or mode == "manager" or mode == "references" then assert(ok, tostring(err))
else assert(not ok, "Fault did not fail") end
if mode == "domain" then assert(calls == 0) end
if mode == "reference" then assert(calls == 1) end
print("OBJECT_FIXTURE_PASS")
"""
            result = subprocess.run(["lua5.4", "-"], input=script, text=True, capture_output=True,
                                    timeout=15, env=env)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            complete = (capture / "complete").exists()
            if mode in ("manager", "references"):
                for name, size in (("manager-root.bin", 8), ("manager-table.bin", 232),
                                   ("manager-headers.bin", 232), ("manager-metadata.bin", 504)):
                    self.assertEqual((capture / name).stat().st_size, size)
            if mode == "references":
                self.assertEqual((capture / "manager-backrefs.txt").read_text(), "0x08400100 0x08400000 320\n")
                self.assertEqual((capture / "manager-backref-01.bin").stat().st_size, 320)
                self.assertEqual((capture / "save-records.txt").read_text(), "0x08400100\n")
                self.assertEqual((capture / "save-record-referrers.txt").read_text(),
                                 "0x08400100 0x08500120 0x08500020 512\n")
                self.assertEqual((capture / "save-record-referrer-01.bin").stat().st_size, 512)
            matches = (capture / "matches.txt").read_text() if complete else None
            reads = (capture / "read-requests.txt").read_text().splitlines() if (capture / "read-requests.txt").exists() else []
            return complete, matches, reads

    def test_read_only_match_and_recheck_across_chunk_boundary(self):
        complete, matches, reads = self.run_probe("match")
        self.assertTrue(complete)
        self.assertEqual(matches, "0x080FFFF4\n")
        self.assertEqual(len(reads), 130)  # Reference + 128 heap chunks + match recheck.

    def test_no_match_is_not_fabricated(self):
        complete, matches, reads = self.run_probe("empty")
        self.assertTrue(complete)
        self.assertEqual(matches, "")
        self.assertEqual(len(reads), 129)

    def test_manager_capture_adds_only_bounded_reads(self):
        complete, matches, reads = self.run_probe("manager")
        self.assertTrue(complete)
        self.assertEqual(matches, "0x080FFFF4\n")
        self.assertEqual(len(reads), 191)

    def test_manager_references_scanned_and_contexts_rechecked(self):
        complete, matches, reads = self.run_probe("references")
        self.assertTrue(complete)
        self.assertEqual(matches, "0x080FFFF4\n")
        self.assertEqual(len(reads), 449)

    def test_bad_references_domains_partial_reads_and_changed_object_abort(self):
        for mode in ("reference", "domain", "short", "changed"):
            with self.subTest(mode=mode):
                self.assertFalse(self.run_probe(mode)[0])


if __name__ == "__main__":
    unittest.main()

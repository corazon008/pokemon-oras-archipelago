"""Synthetic frames, saves and host files. No real ROM or game-memory writes."""

import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from oras_save import BLOCKS, METADATA_OFFSET
from oras_native_save_observation import prepare_observation, inspect_observation
from run_bizhawk_connector_probe import apply_initial_time
from save_fixtures import synthetic_save, update_fixture_crcs


def lua_value(value):
    if isinstance(value, dict):
        return "{" + ",".join(f"[{lua_value(k)}]={lua_value(v)}" for k, v in value.items()) + "}"
    if isinstance(value, list):
        return "{" + ",".join(lua_value(v) for v in value) + "}"
    if isinstance(value, str):
        return repr(value)
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def fixture(path):
    before = bytes(synthetic_save())
    after = bytearray(before)
    after[BLOCKS[6][0]] = 1
    update_fixture_crcs(after)
    after = bytes(after)
    objects = path / "objects"
    objects.mkdir()
    root = struct.pack("<II", 0x500010, 0x08100000)
    metadata = struct.pack("<II", 0x500020, 0) + before[METADATA_OFFSET:METADATA_OFFSET + 488] + bytes(8)
    (objects / "manager-root.bin").write_bytes(root)
    (objects / "manager-table.bin").write_bytes(bytes(232))
    (objects / "manager-metadata.bin").write_bytes(metadata)
    (objects / "references.bin").write_bytes(struct.pack("<I", 0x500030) + bytes(2000))
    data = bytearray(320)
    record = 0x08200100
    struct.pack_into("<I", data, 256, 0x08000000)
    struct.pack_into("<I", data, 264, 0x76000)
    data[272:292] = "data:/main".encode("utf-16le")
    (objects / "manager-backref-01.bin").write_bytes(data)
    report = {"manager": {
        "predicted_base": 0x08000000, "predicted_table": 0x08000200,
        "derived_slots": {1: {"object_offset": 0x1000}, 19: {"object_offset": 0x3000},
                          47: {"object_offset": 0x5000}},
        "references": {"main_save_record_candidates": [record], "manager_backrefs": [
            {"reference_address": record, "context_start": record - 256},
        ]},
    }}
    target = path / "main"
    target.write_bytes(before)
    config = prepare_observation(path, objects, target, before, report)
    (path / "after.bin").write_bytes(after)
    (path / "after-metadata.bin").write_bytes(metadata[:8] + after[METADATA_OFFSET:METADATA_OFFSET + 488] + metadata[496:])
    return before, after, config


@unittest.skipUnless(shutil.which("lua5.4"), "Lua 5.4 is required")
class NativeObservationTests(unittest.TestCase):
    def test_fixed_clock_changes_only_explicit_config_copy(self):
        with tempfile.TemporaryDirectory(dir="/tmp/opencode") as directory:
            path = Path(directory)
            config = {"CoreSyncSettings": {"fixture.Encore": {"UseRealTime": True}}}
            source, copy = path / "source", path / "copy"
            source.write_text(json.dumps(config))
            copy.write_bytes(source.read_bytes())
            self.assertEqual(apply_initial_time(copy, "2026-11-18T18:36:36"), "2026-11-18T18:36:36")
            self.assertTrue(json.loads(source.read_text())["CoreSyncSettings"]["fixture.Encore"]["UseRealTime"])
            self.assertFalse(json.loads(copy.read_text())["CoreSyncSettings"]["fixture.Encore"]["UseRealTime"])
            for invalid in ("1999-01-01", "2100-01-01", "2026-11-18T18:36:36+00:00"):
                with self.assertRaises(ValueError):
                    apply_initial_time(copy, invalid)

    def run_fixture(self, path, config, mode="normal"):
        script = f"""
local config = {lua_value(config)}
local mode = {mode!r}
local function load(path)
 local f=assert(io.open(path,"rb")); local b=f:read("*a"); f:close(); return b
end
local function write(path, bytes)
 local f=assert(io.open(path,"wb")); f:write(bytes); f:close()
end
local frame = 100
local observer = dofile({str(ROOT / 'tools/native_save_observer.lua')!r})(config, function(address, length)
 if mode == "short" then return "" end
 for _, range in ipairs(config.ranges) do
  if range.address == address then
   if mode == "stable" and frame == 101 and range.name == "manager_root" then return string.rep("x", length) end
   if frame >= 101 and range.name == "metadata" then return load({str(path / 'after-metadata.bin')!r}) end
   return load(range.reference_path)
  end
 end
 error("Unexpected read")
end)
local ok, err = pcall(function()
 for i=0,2 do
  frame=100+i
  if i == 1 then write(config.save_path, mode == "partial" and "" or load({str(path / 'after.bin')!r})) end
  if i == 2 then write(config.save_path, load({str(path / 'after.bin')!r})) end
  observer.tick(mode == "gap" and frame+2*i or frame, 1)
 end
 observer.finish()
end)
if mode == "normal" or mode == "partial" then assert(ok, tostring(err))
else assert(not ok, "Fault did not fail") end
"""
        result = subprocess.run(["lua5.4", "-"], input=script, text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_frame_samples_and_changed_native_file(self):
        with tempfile.TemporaryDirectory(dir="/tmp/opencode") as directory:
            path = Path(directory)
            before, after, config = fixture(path)
            self.run_fixture(path, config)
            report = inspect_observation(path, before, after)
            self.assertEqual(report["ticks"], 3)
            self.assertEqual(report["lua_memory_read_requests"], 21)
            self.assertEqual(report["changed_save_block_ids"], [6])
            self.assertTrue(report["final_ram_matches_native_file"])
            self.assertFalse(report["sampling_proves_crash_atomicity"])

    def test_partial_host_file_is_recorded_not_atomicity_proof(self):
        with tempfile.TemporaryDirectory(dir="/tmp/opencode") as directory:
            path = Path(directory)
            before, after, config = fixture(path)
            self.run_fixture(path, config, "partial")
            report = inspect_observation(path, before, after)
            self.assertEqual([row["all_58_crcs_valid"] for row in report["file_states"]], [True, False, True])

    def test_short_reads_stable_changes_and_frame_gaps_abort(self):
        for mode in ("short", "stable", "gap", "bound"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory(dir="/tmp/opencode") as directory:
                path = Path(directory)
                _, _, config = fixture(path)
                if mode == "bound":
                    config["max_ticks"] = 2
                self.run_fixture(path, config, mode)
                self.assertFalse((path / "observation-complete").exists())

    def test_fixed_clock_cli_refuses_existing_profiles(self):
        for options in ([], ["--session", "existing"]):
            result = subprocess.run(
                [sys.executable, str(ROOT / "tools/run_bizhawk_connector_probe.py"),
                 "--rom", "synthetic.3ds", "--initial-time", "2026-11-18T18:36:36", *options],
                text=True, capture_output=True, timeout=10,
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("fresh --seed-save", result.stderr)

    def test_malformed_journal_and_no_file_change_fail_analysis(self):
        with tempfile.TemporaryDirectory(dir="/tmp/opencode") as directory:
            path = Path(directory)
            before, after, config = fixture(path)
            self.run_fixture(path, config)
            with self.assertRaises(ValueError):
                inspect_observation(path, before, before)
            (path / "reads.tsv").write_text("invalid\n" * 21)
            with self.assertRaisesRegex(ValueError, "journal"):
                inspect_observation(path, before, after)

    def test_cli_rejects_existing_profile_and_potion_writes(self):
        for options in ([], ["--session", "existing"], ["--seed-save", "synthetic", "--experimental-potion-1-to-2"]):
            result = subprocess.run(
                [sys.executable, str(ROOT / "tools/run_bizhawk_connector_probe.py"),
                 "--rom", "synthetic.3ds", "--observe-native-save", *options],
                text=True, capture_output=True, timeout=10,
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("fresh --seed-save", result.stderr)

    def test_post_ui_observer_waits_for_verified_signal(self):
        with tempfile.TemporaryDirectory(dir="/tmp/opencode") as directory:
            path = Path(directory)
            (path / "steps").write_text("2:B\n3:-\n")
            (path / "reference").write_bytes(b"code")
            (path / "main").write_bytes(b"synthetic")
            config = {"schema_version": 1, "capture": str(path), "save_path": str(path / "main"),
                      "max_ticks": 10, "ranges": [
                          {"name": "fixture", "address": 0x08000000, "length": 4,
                           "stable_prefix": 4, "reference_path": str(path / "reference")},
                      ]}
            (path / "config").write_text(json.dumps(config))
            env = {**os.environ,
                   "ORAS_CONNECTOR_POST_PLAN": str(path / "steps"),
                   "ORAS_CONNECTOR_POST_CAPTURE": str(path),
                   "ORAS_CONNECTOR_POST_SIGNAL": str(path / "signal"),
                   "ORAS_NATIVE_SAVE_OBSERVER_SCRIPT": str(ROOT / "tools/native_save_observer.lua"),
                   "ORAS_NATIVE_SAVE_OBSERVER_CONFIG": str(path / "config")}
            script = f"""
local callback, frame, reads = nil, 0, 0
package.preload.json = function() return {{decode=function() return {lua_value(config)} end}} end
event = {{onframeend=function(fn) callback=fn end}}
joypad = {{get=function() return {{B=false}} end, set=function() end}}
emu = {{framecount=function() return frame end, getsystemid=function() return "3DS" end}}
client = {{screenshot=function() end}}
memory = {{
 getmemorydomainlist=function() return {{[0]="System Bus"}} end,
 getmemorydomainsize=function() return 0 end,
 read_bytes_as_binary_string=function(address, length, domain)
  assert(address==0x08000000 and length==4 and domain=="System Bus"); reads=reads+1; return "code"
 end,
 write_bytes_as_array=function() error("WRITE forbidden") end,
}}
dofile({str(ROOT / 'tools/bizhawk_connector_post_ui.lua')!r})
for i=1,5 do callback() end
assert(reads == 0)
local signal=assert(io.open({str(path / 'signal')!r},"w")); signal:close()
for i=1,6 do frame=i; callback() end
assert(reads == 6)
"""
            result = subprocess.run(["lua5.4", "-"], input=script, text=True, capture_output=True,
                                    timeout=10, env=env)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual((path / "observation-complete").read_text(), "6\n")
            self.assertTrue((path / "complete").exists())


if __name__ == "__main__":
    unittest.main()

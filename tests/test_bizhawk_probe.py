"""Tests of probe mechanics, not evidence of ORAS or Encore compatibility."""

import copy
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("probe_runner", ROOT / "tools/run_bizhawk_probe.py")
RUNNER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUNNER)
LUA = shutil.which("lua5.4") or shutil.which("lua")


class IsolationTests(unittest.TestCase):
    def test_incomplete_or_wrong_system_reports_cannot_pass(self):
        report = {
            "status": "complete",
            "domain_inventory_ok": True,
            "bizhawk_version": {"ok": True, "value": "2.11.1"},
            "system": {"ok": True, "value": "3DS"},
            "domains": {"FCRAM": {"ok": True}, "System Bus": {"ok": True, "value": 0}},
            "completed_frames": 180,
            "requested_frames": 180,
        }
        self.assertTrue(RUNNER.probe_succeeded(report, 0))
        self.assertFalse(RUNNER.probe_succeeded(report, None))
        report["system"]["value"] = "NULL"
        self.assertFalse(RUNNER.probe_succeeded(report, 0))
        report["system"]["value"] = "3DS"
        report["bizhawk_version"] = {"ok": False}
        self.assertFalse(RUNNER.probe_succeeded(report, 0))

    def test_config_is_private_and_source_unchanged(self):
        config = {
            "RecentRoms": {"AutoLoad": True, "recentlist": ["original.3ds"]},
            "PathEntries": {"Paths": [
                {"System": "Global_NULL", "Type": "Base", "Path": "/original"},
                {"System": "3DS", "Type": "User", "Path": "/original/saves"},
            ]},
            "CoreSyncSettings": {"Encore": {
                "TempUserFolder": False, "PluginLoaderEnabled": True,
            }},
        }
        original = copy.deepcopy(config)
        isolated = RUNNER.isolate_config(config, Path("/private"))
        self.assertEqual(config, original)
        self.assertFalse(isolated["RecentRoms"]["AutoLoad"])
        self.assertEqual(isolated["RecentRoms"]["recentlist"], [])
        self.assertEqual(isolated["PathEntries"]["Paths"][1]["Path"], "/private/3DS/User")
        self.assertFalse(isolated["CoreSyncSettings"]["Encore"]["PluginLoaderEnabled"])


@unittest.skipUnless(LUA, "Lua is not installed")
class LuaProbeTests(unittest.TestCase):
    def run_probe(self, domain_expression='{[0]="FCRAM", [1]="System Bus"}', frames=2,
                  callable_wrappers=False):
        fixture = r'''
local frames = 0
client = {getversion=function() return "test" end}
emu = {
    getsystemid=function() return "3DS" end,
    framecount=function() return frames end,
    frameadvance=function() frames = frames + 1 end,
}
memory = {
    getmemorydomainlist=function() return DOMAIN_EXPRESSION end,
    getmemorydomainsize=function(name)
        if name == "System Bus" then return 0 end
        return 268435456
    end,
    read_bytes_as_array=function() error("Memory read forbidden") end,
    write_bytes_as_array=function() error("Memory write forbidden") end,
}
package.preload.socket=function() return {} end
'''.replace("DOMAIN_EXPRESSION", domain_expression)
        if callable_wrappers:
            fixture += '''
for _, api in ipairs({client, emu, memory}) do
    for name, fn in pairs(api) do
        api[name] = setmetatable({}, {__call=function(_, ...) return fn(...) end})
    end
end
'''
        with tempfile.TemporaryDirectory(dir="/tmp/opencode") as directory:
            output = Path(directory) / "capabilities.json"
            env = os.environ.copy()
            env.update({
                "ORAS_PROBE_OUTPUT": str(output),
                "ORAS_PROBE_FRAMES": str(frames),
                "ORAS_PROBE_EXIT": "0",
                "ORAS_PROBE_SCREENSHOT": "",
            })
            result = subprocess.run(
                [LUA, "-"], input=fixture + "\ndofile(" + json.dumps(str(ROOT / "tools/bizhawk_probe.lua")) + ")",
                env=env, text=True, capture_output=True, timeout=10,
            )
            if result.returncode:
                return result, None
            return result, json.loads(output.read_text())

    def test_zero_indexed_domains_and_no_memory_access(self):
        result, report = self.run_probe()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("FCRAM", report["domains"])
        self.assertEqual(report["domains"]["System Bus"]["value"], 0)
        self.assertEqual(report["completed_frames"], 2)
        self.assertEqual(report["memory_reads"], 0)
        self.assertEqual(report["memory_writes"], 0)
        self.assertEqual(report["status"], "complete")
        self.assertEqual(report["bizhawk_version"], {"ok": True, "value": "test"})
        self.assertEqual(report["system"], {"ok": True, "value": "3DS"})

    def test_callable_api_objects_do_not_require_function_type(self):
        result, report = self.run_probe(callable_wrappers=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(report["system"], {"ok": True, "value": "3DS"})
        self.assertTrue(report["api"]["domain_list_present"])
        self.assertIn("FCRAM", report["domains"])

    def test_json_escaping(self):
        _, report = self.run_probe(r'{[0]="quoted\"name\nline"}', frames=0)
        self.assertIn('quoted"name\nline', report["domains"])

    def test_invalid_frame_limit_is_rejected(self):
        result, report = self.run_probe(frames=-1)
        self.assertNotEqual(result.returncode, 0)
        self.assertIsNone(report)


if __name__ == "__main__":
    unittest.main()

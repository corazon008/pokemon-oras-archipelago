"""Private-profile and input-plan tests; no real game saves are included."""

from pathlib import Path
import os
import shutil
import subprocess
import sys
import tempfile
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from run_bizhawk_save_probe import parse_steps, save_destination, seed_save, validate_save_container
from save_fixtures import synthetic_save

ROOT = Path(__file__).resolve().parents[1]
LUA = shutil.which("lua5.4") or shutil.which("lua")


class SaveProbeTests(unittest.TestCase):
    def test_input_plan(self):
        self.assertEqual(parse_steps("180:-,2:A,60:A+Start"),
                         [(180, "-"), (2, "A"), (60, "A+Start")])

    def test_invalid_or_dangerous_buttons_are_rejected(self):
        for value in ["0:A", "3601:-", "1:Reset", "2:A+", "2:Touch", "3:A:extra", ""]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_steps(value)

    def test_total_frames_are_bounded(self):
        with self.assertRaises(ValueError):
            parse_steps(",".join(["3600:-"] * 9))

    def test_copy_preserves_source_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory(dir="/tmp/opencode") as directory:
            root = Path(directory)
            source, target = root / "source", root / "copy/main"
            data = synthetic_save(fill=0x55)
            source.write_bytes(data)
            seed_save(source, target)
            self.assertEqual(target.read_bytes(), source.read_bytes())
            target.write_bytes(b"existing")
            with self.assertRaises(FileExistsError):
                seed_save(source, target)
            self.assertEqual(target.read_bytes(), b"existing")
            self.assertEqual(source.read_bytes(), data)

    def test_expected_size_without_format_marker_is_rejected(self):
        with tempfile.TemporaryDirectory(dir="/tmp/opencode") as directory:
            source = Path(directory) / "main"
            source.write_bytes(b"\0" * 0x76000)
            with self.assertRaisesRegex(ValueError, "footer marker"):
                validate_save_container(source)

    def test_unexpected_save_size_is_not_imported(self):
        with tempfile.TemporaryDirectory(dir="/tmp/opencode") as directory:
            root = Path(directory)
            source, target = root / "source", root / "copy/main"
            source.write_bytes(b"not a save")
            with self.assertRaises(ValueError):
                seed_save(source, target)
            self.assertFalse(target.exists())

    def test_sd_path_is_inside_private_runtime(self):
        runtime = Path("/private/runtime")
        target = save_destination(runtime, "000400000011C400")
        self.assertTrue(target.is_relative_to(runtime))
        self.assertTrue(str(target).endswith("title/00040000/0011c400/data/00000001/main"))


@unittest.skipUnless(LUA, "Lua is not installed")
class NativeInputTests(unittest.TestCase):
    def test_event_observer_samples_steps_and_final_without_writes(self):
        with tempfile.TemporaryDirectory(dir="/tmp/opencode") as directory:
            root = Path(directory)
            (root / "steps.txt").write_text("3:-\n2:A\n2:-\n")
            fixture = """
local reads, frames = 0, 0
joypad = {get=function() return {A=false} end, set=function() end}
emu = {frameadvance=function() frames=frames+1 end, framecount=function() return frames end}
client = {screenshot=function() end, exit=function() assert(reads == 3) end}
memory = setmetatable({
    read_bytes_as_binary_string=function(address, length, domain)
        assert(address == 0x08C7DAEC and length == 0x504 and domain == "System Bus")
        reads=reads+1
        return string.rep(string.char(reads), length)
    end,
}, {__index=function() error("Unexpected memory API") end})
dofile(%s)
"""
            env = os.environ.copy()
            env.update({
                "ORAS_UI_PLAN": str(root / "steps.txt"), "ORAS_UI_CAPTURE": str(root),
                "ORAS_UI_SCRIPT": str(ROOT / "tools/bizhawk_ui_probe.lua"),
                "ORAS_UI_CONTINUE": "1", "ORAS_UI_SPEED": "100",
                "ORAS_EVENT_MODE": "read", "ORAS_EVENT_ADDRESS": str(0x08C7DAEC),
                "ORAS_EVENT_SAMPLE_STEPS": "1,2",
            })
            result = subprocess.run(
                [LUA, "-"], input=fixture % repr(str(ROOT / "tools/bizhawk_event_probe.lua")),
                env=env, text=True, capture_output=True, timeout=10,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            for name, byte in (("event-step-01", 1), ("event-step-02", 2), ("event-final", 3)):
                self.assertEqual((root / f"{name}.bin").read_bytes(), bytes([byte]) * 0x504)
            self.assertEqual(len((root / "event-read-requests.txt").read_text().splitlines()), 3)

    def test_event_observer_counts_and_rejects_incomplete_read(self):
        with tempfile.TemporaryDirectory(dir="/tmp/opencode") as directory:
            root = Path(directory)
            (root / "steps.txt").write_text("1:-\n")
            fixture = """
joypad = {get=function() return {A=false} end, set=function() end}
emu = {frameadvance=function() end, framecount=function() return 1 end}
client = {screenshot=function() end, exit=function() error("Must not succeed") end}
memory = {read_bytes_as_binary_string=function() return string.rep("\\0", 0x503) end}
dofile(%s)
"""
            env = os.environ.copy()
            env.update({
                "ORAS_UI_PLAN": str(root / "steps.txt"), "ORAS_UI_CAPTURE": str(root),
                "ORAS_UI_SCRIPT": str(ROOT / "tools/bizhawk_ui_probe.lua"),
                "ORAS_UI_CONTINUE": "1", "ORAS_UI_SPEED": "100",
                "ORAS_EVENT_MODE": "read", "ORAS_EVENT_ADDRESS": str(0x08C7DAEC),
                "ORAS_EVENT_SAMPLE_STEPS": "",
            })
            result = subprocess.run(
                [LUA, "-"], input=fixture % repr(str(ROOT / "tools/bizhawk_event_probe.lua")),
                env=env, text=True, capture_output=True, timeout=10,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Incomplete event memory read", result.stderr)
            self.assertEqual(len((root / "event-read-requests.txt").read_text().splitlines()), 1)
            self.assertFalse((root / "event-final.bin").exists())

    def test_connector_post_ui_waits_for_signal_and_never_calls_memory(self):
        with tempfile.TemporaryDirectory(dir="/tmp/opencode") as directory:
            root = Path(directory)
            (root / "steps.txt").write_text("2:B\n3:-\n")
            fixture = """
local callback, frames, pressed = nil, 0, 0
event = {onframeend=function(fn) callback=fn end}
joypad = {get=function() return {B=false} end,
          set=function(buttons) if buttons.B then pressed=pressed+1 end end}
emu = {framecount=function() return frames end}
client = {screenshot=function() end}
memory = setmetatable({}, {__index=function() error("Unexpected memory API") end})
dofile(%s)
for i=1,5 do callback() end
assert(pressed == 0)
assert(not io.open(%s, "r"))
local signal = assert(io.open(%s, "w")); signal:close()
for i=1,6 do frames=frames+1; callback() end
assert(pressed == 2)
local complete = assert(io.open(%s, "r")); complete:close()
"""
            env = os.environ.copy()
            env.update({
                "ORAS_CONNECTOR_POST_PLAN": str(root / "steps.txt"),
                "ORAS_CONNECTOR_POST_CAPTURE": str(root),
                "ORAS_CONNECTOR_POST_SIGNAL": str(root / "signal"),
            })
            script = fixture % tuple(repr(str(path)) for path in [
                ROOT / "tools/bizhawk_connector_post_ui.lua", root / "complete",
                root / "signal", root / "complete",
            ])
            result = subprocess.run([LUA, "-"], input=script, env=env, text=True, capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_inventory_observer_samples_before_and_after_without_writes(self):
        with tempfile.TemporaryDirectory(dir="/tmp/opencode") as directory:
            root = Path(directory)
            (root / "steps.txt").write_text("3:-\n2:A\n")
            fixture = """
local reads, frames = 0, 0
joypad = {get=function() return {A=false} end, set=function() end}
emu = {frameadvance=function() frames=frames+1 end, framecount=function() return frames end}
client = {screenshot=function() end, exit=function() assert(reads == 2) end}
memory = setmetatable({
    read_bytes_as_array=function(address, length, domain)
        assert(address == 0x08C6AC80 and length == 0xB90 and domain == "System Bus")
        reads = reads + 1
        local bytes = {}
        for i=1,length do bytes[i]=0 end
        if reads == 1 then bytes[0x971]=17; bytes[0x973]=1 end
        return bytes
    end,
}, {__index=function() error("Unexpected memory API") end})
"""
            env = os.environ.copy()
            env.update({
                "ORAS_UI_PLAN": str(root / "steps.txt"),
                "ORAS_UI_CAPTURE": str(root),
                "ORAS_UI_SCRIPT": str(ROOT / "tools/bizhawk_ui_probe.lua"),
                "ORAS_UI_CONTINUE": "1", "ORAS_UI_SPEED": "100",
                "ORAS_INVENTORY_ADDRESS": str(0x08C6AC80),
                "ORAS_INVENTORY_LENGTH": str(0xB90),
                "ORAS_INVENTORY_SAMPLE_STEP": "1",
            })
            result = subprocess.run(
                [LUA, "-"], input=fixture + "\ndofile(" + repr(str(ROOT / "tools/bizhawk_inventory_probe.lua")) + ")",
                env=env, text=True, capture_output=True, timeout=10,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((root / "inventory-before.bin").read_bytes()[0x970], 17)
            self.assertEqual((root / "inventory-read.bin").read_bytes(), bytes(0xB90))
            self.assertEqual((root / "inventory-read-requests.txt").read_text().splitlines(),
                             ["inventory-before", "inventory-read"])

    def run_fixture(self, plan):
        with tempfile.TemporaryDirectory(dir="/tmp/opencode") as directory:
            root = Path(directory)
            plan_path = root / "steps.txt"
            plan_path.write_text(plan)
            fixture = """
local frames, pressed = 0, 0
joypad = {
    get=function() return {A=false, B=false} end,
    set=function(buttons)
        assert(buttons.B == false)
        if buttons.A then pressed = pressed + 1 end
    end,
}
emu = {
    frameadvance=function() frames = frames + 1 end,
    framecount=function() return frames end,
}
memory = setmetatable({}, {__index=function() error("Memory API forbidden") end})
client = {
    screenshot=function() end,
    exit=function() print("FIXTURE", frames, pressed) end,
}
"""
            env = os.environ.copy()
            env.update({"ORAS_UI_PLAN": str(plan_path), "ORAS_UI_CAPTURE": str(root)})
            result = subprocess.run(
                [LUA, "-"], input=fixture + "\ndofile(" + repr(str(ROOT / "tools/bizhawk_ui_probe.lua")) + ")",
                env=env, text=True, capture_output=True, timeout=10,
            )
            return result

    def test_native_input_frames_without_memory_access(self):
        result = self.run_fixture("3:-\n2:A\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("FIXTURE\t5\t2", result.stdout)

    def test_unknown_controller_button_is_rejected_in_lua_too(self):
        result = self.run_fixture("2:Reset\n")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Unsupported button", result.stderr)


if __name__ == "__main__":
    unittest.main()

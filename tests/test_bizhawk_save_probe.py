"""Private-profile and input-plan tests; no real game saves are included."""

from pathlib import Path
import os
import shutil
import subprocess
import struct
import sys
import tempfile
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from run_bizhawk_save_probe import parse_steps, save_destination, seed_save, validate_save_container

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
            data = bytearray(b"\x55" * 0x76000)
            struct.pack_into("<I", data, len(data) - 0x1F0, 0x42454546)
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

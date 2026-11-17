"""Run a memory-free capability probe in a fresh, disposable BizHawk copy."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def isolate_config(config: dict, runtime: Path) -> dict:
    """Do not retain automatic loads or references to the original user directory."""
    config = json.loads(json.dumps(config))
    for key, value in config.items():
        if key.startswith("Recent") and isinstance(value, dict):
            value["AutoLoad"] = False
            if "recentlist" in value:
                value["recentlist"] = []
    config["SingleInstanceMode"] = False
    config["AutosaveSaveRAM"] = False
    config["SoundEnabled"] = False
    config["SpeedPercent"] = 100
    entries = config.setdefault("PathEntries", {})
    entries["UseRecentForRoms"] = False
    entries["LastRomPath"] = str(runtime)
    for entry in entries.get("Paths", []):
        if entry["System"] == "Global_NULL" and entry["Type"] == "Base":
            entry["Path"] = str(runtime)
        elif entry["System"] == "3DS":
            if entry["Type"] == "Base":
                entry["Path"] = str(runtime / "3DS")
            elif entry["Type"] == "User":
                entry["Path"] = str(runtime / "3DS" / "User")
    for core, settings in config.get("CoreSyncSettings", {}).items():
        if core.rsplit(".", 1)[-1] == "Encore" and isinstance(settings, dict):
            settings["TempUserFolder"] = True
            settings["PluginLoaderEnabled"] = False
    return config


def probe_succeeded(report: dict, exit_code: int | None) -> bool:
    """Success means a completed 3DS capability inventory, never game compatibility."""
    domains = report.get("domains", {})
    return (
        exit_code == 0
        and report.get("status") == "complete"
        and report.get("domain_inventory_ok") is True
        and report.get("bizhawk_version", {}).get("ok") is True
        and report.get("system") == {"ok": True, "value": "3DS"}
        and all(domains.get(name, {}).get("ok") is True for name in ("FCRAM", "System Bus"))
        and report.get("completed_frames") == report.get("requested_frames")
    )


def prepare_runtime(source: Path, session: Path) -> Path:
    """Copy emulator files but never the existing 3DS user directory."""
    runtime = session / "runtime"

    def ignore(directory: str, names: list[str]) -> set[str]:
        if Path(directory) == source:
            return set(names) & {
                "3DS", "config.ini", "EmuHawkMono_laststdout.txt",
                "EmuHawkMono_laststderr.txt",
            }
        return set()

    shutil.copytree(source, runtime, ignore=ignore)
    config_path = source / "config.ini"
    config = json.loads(config_path.read_text()) if config_path.exists() else {}
    (runtime / "config.ini").write_text(
        json.dumps(isolate_config(config, runtime), indent=2) + "\n"
    )
    return runtime


def emulator_environment(runtime: Path, *, automated: bool = False) -> dict[str, str]:
    env = os.environ.copy()
    env.update({
        "LD_LIBRARY_PATH": f"{runtime}/dll:{runtime}:/usr/lib",
        "MONO_CRASH_NOFILE": "1",
        "MONO_WINFORMS_XIM_STYLE": "disabled",
    })
    if automated:
        # Avoid the observed SDL HID gamepad shutdown race in automated tests.
        # Interactive sessions retain the user's input drivers.
        env["SDL_JOYSTICK_HIDAPI"] = "0"
    return env


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--bizhawk",
        type=Path,
        default=PROJECT_ROOT / "bin/BizHawk-2.11.1-linux-x64",
    )
    parser.add_argument("--rom", type=Path, required=True)
    parser.add_argument("--frames", type=int, default=180)
    parser.add_argument("--timeout", type=float, default=120)
    args = parser.parse_args()
    source = args.bizhawk.resolve()
    rom = args.rom.resolve()
    if not (source / "EmuHawk.exe").is_file() or not rom.is_file():
        parser.error("BizHawk executable and ROM must exist")
    if not 0 <= args.frames <= 3600 or args.timeout <= 0:
        parser.error("Use 0..3600 frames and a positive timeout")
    mono = shutil.which("mono")
    if not mono:
        parser.error("Mono is not on PATH")

    temporary_root = Path("/tmp/opencode")
    temporary_root.mkdir(parents=True, exist_ok=True)
    session = Path(tempfile.mkdtemp(prefix="oras-bizhawk-", dir=temporary_root))
    runtime = prepare_runtime(source, session)
    report_path = session / "capabilities.json"
    env = emulator_environment(runtime, automated=True)
    env.update({
        "ORAS_PROBE_OUTPUT": str(report_path),
        "ORAS_PROBE_FRAMES": str(args.frames),
        "ORAS_PROBE_SCREENSHOT": str(session / "screen.png"),
        "ORAS_PROBE_EXIT": "1",
    })
    command = [
        mono, str(runtime / "EmuHawk.exe"),
        f"--config={runtime / 'config.ini'}",
        f"--lua={PROJECT_ROOT / 'tools/bizhawk_probe.lua'}",
        str(rom),
    ]
    manifest = {
        "schema_version": 1,
        "source_bizhawk": str(source),
        "runtime": str(runtime),
        "rom": str(rom),
        "rom_size": rom.stat().st_size,
        "existing_3ds_profile_copied": False,
        "emuhawk_sha256": sha256(source / "EmuHawk.exe"),
        "encore_sha256": sha256(source / "dll/libencore.so"),
        "requested_frames": args.frames,
        "timeout_seconds": args.timeout,
        "command": command,
    }
    print(f"Isolated probe session: {session}", flush=True)
    with (session / "stdout.txt").open("w") as stdout, (session / "stderr.txt").open("w") as stderr:
        try:
            result = subprocess.run(
                command, cwd=runtime, env=env, stdout=stdout, stderr=stderr,
                timeout=args.timeout, check=False,
            )
            manifest["exit_code"] = result.returncode
            manifest["timed_out"] = False
        except subprocess.TimeoutExpired:
            # subprocess.run terminates only the process created for this test.
            manifest["exit_code"] = None
            manifest["timed_out"] = True
    (session / "run.json").write_text(json.dumps(manifest, indent=2) + "\n")
    if report_path.exists():
        print(report_path.read_text(), end="")
        report = json.loads(report_path.read_text())
        if probe_succeeded(report, manifest["exit_code"]):
            return 0
    print(f"Probe incomplete; inspect {session / 'stderr.txt'} and stdout.txt")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

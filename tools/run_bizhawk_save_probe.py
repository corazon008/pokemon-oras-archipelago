"""Replay native button steps in a private profile, optionally seeded with a save copy."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile

from rom_identity import inspect_rom, sha256_file
from run_bizhawk_probe import (
    PROJECT_ROOT, emulator_environment, isolate_config, prepare_runtime, sha256,
)


BUTTONS = {"A", "B", "X", "Y", "Up", "Down", "Left", "Right", "L", "R", "Start", "Select"}
TEMP_ROOT = Path("/tmp/opencode")


def parse_steps(value: str) -> list[tuple[int, str]]:
    steps = []
    for raw in value.split(","):
        fields = raw.split(":")
        if len(fields) != 2:
            raise ValueError("Use comma-separated frames:buttons steps, e.g. 180:-,2:A,120:-")
        frames = int(fields[0])
        names = fields[1].split("+")
        if not 1 <= frames <= 3600:
            raise ValueError("Each step must contain 1..3600 frames")
        if fields[1] != "-" and (not names or any(name not in BUTTONS for name in names)):
            raise ValueError("Only ordinary 3DS buttons are allowed")
        steps.append((frames, fields[1]))
    if sum(frames for frames, _ in steps) > 30000:
        raise ValueError("UI plan exceeds 30000 frames")
    return steps


def save_destination(runtime: Path, program_id: str) -> Path:
    """Observed Encore default SD layout, not a physical-console save format."""
    return (
        runtime / "3DS/User/sdmc/Nintendo 3DS" / ("0" * 32) / ("0" * 32)
        / "title" / program_id[:8].lower() / program_id[8:].lower()
        / "data/00000001/main"
    )


def seed_save(source: Path, destination: Path) -> None:
    validate_save_container(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with source.open("rb") as original, destination.open("xb") as copied:
        shutil.copyfileobj(original, copied)
    if sha256(source) != sha256(destination):
        raise ValueError("Save copy does not match the source")


def validate_save_container(source: Path) -> None:
    """PKHeX SaveUtil's size/footer identification only, not full block CRC validation."""
    if source.stat().st_size != 0x76000:
        raise ValueError("Expected a 0x76000-byte ORAS decrypted main save; no conversion is performed")
    with source.open("rb") as savedata:
        savedata.seek(-0x1F0, 2)
        marker = struct.unpack("<I", savedata.read(4))[0]
    if marker != 0x42454546:
        raise ValueError("Save lacks the ORAS footer marker; uninitialized/encrypted files are not imported")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bizhawk", type=Path, default=PROJECT_ROOT / "bin/BizHawk-2.11.1-linux-x64")
    parser.add_argument("--rom", type=Path, required=True)
    parser.add_argument("--seed-save", type=Path)
    parser.add_argument("--session", type=Path, help="Reuse a profile created by this tool; never reseed it")
    parser.add_argument("--steps", default="180:-")
    parser.add_argument("--timeout", type=float, default=180)
    parser.add_argument(
        "--interactive", action="store_true",
        help="Open the private profile for manual play; no macro or automatic timeout",
    )
    args = parser.parse_args()
    try:
        steps = parse_steps(args.steps)
    except ValueError as error:
        parser.error(str(error))
    if not math.isfinite(args.timeout) or args.timeout <= 0:
        parser.error("Timeout must be positive and finite")
    if args.session and args.seed_save:
        parser.error("--session and --seed-save are mutually exclusive")
    if args.seed_save:
        try:
            validate_save_container(args.seed_save)
        except (OSError, ValueError) as error:
            parser.error(str(error))
    mono = shutil.which("mono")
    if not mono:
        parser.error("Mono is not on PATH")
    rom = args.rom.resolve()
    identity, _ = inspect_rom(rom)
    if identity["edition_from_program_id"] is None:
        parser.error("Only identified ORAS program IDs are supported")
    rom_hash = sha256_file(rom)
    TEMP_ROOT.mkdir(parents=True, exist_ok=True)
    if args.session:
        session = args.session.resolve()
        if not session.is_relative_to(TEMP_ROOT) or session == TEMP_ROOT:
            parser.error("Reusable sessions must be private children of /tmp/opencode")
        manifest = json.loads((session / "profile.json").read_text())
        if manifest.get("kind") != "oras_native_save_probe" or manifest.get("rom_sha256") != rom_hash:
            parser.error("Profile/ROM identity mismatch")
        runtime = session / "runtime"
        if not runtime.resolve().is_relative_to(session) or runtime.is_symlink():
            parser.error("Runtime must stay inside the private session")
        config_path = runtime / "config.ini"
        config = isolate_config(json.loads(config_path.read_text()), runtime)
        config_path.write_text(json.dumps(config, indent=2) + "\n")
    else:
        session = Path(tempfile.mkdtemp(prefix="oras-save-", dir=TEMP_ROOT))
        runtime = prepare_runtime(args.bizhawk.resolve(), session)
        manifest = {
            "kind": "oras_native_save_probe",
            "program_id": identity["program_id"],
            "rom_sha256": rom_hash,
            "seed_source": str(args.seed_save.resolve()) if args.seed_save else None,
            "seed_sha256": sha256(args.seed_save) if args.seed_save else None,
            "seed_validation": "size_footer_and_copy_integrity_only" if args.seed_save else "none",
            "archive_metadata_source": None,
            "archive_metadata_sha256": None,
        }
        if args.seed_save:
            metadata_source = args.seed_save.resolve().parent.with_suffix(".metadata")
            if not metadata_source.is_file() or metadata_source.stat().st_size != 16:
                parser.error(
                    "Seed import requires its 16-byte Encore 00000001.metadata sibling; "
                    "raw save conversion is not supported"
                )
            seed_save(args.seed_save, save_destination(runtime, identity["program_id"]))
            metadata_target = save_destination(runtime, identity["program_id"]).parent.with_suffix(".metadata")
            with metadata_source.open("rb") as original, metadata_target.open("xb") as copied:
                shutil.copyfileobj(original, copied)
            manifest["archive_metadata_source"] = str(metadata_source)
            manifest["archive_metadata_sha256"] = sha256(metadata_source)
            if sha256(metadata_target) != manifest["archive_metadata_sha256"]:
                raise ValueError("Archive metadata copy does not match the source")
        (session / "profile.json").write_text(json.dumps(manifest, indent=2) + "\n")
    attempt = Path(tempfile.mkdtemp(prefix="attempt-", dir=session))
    plan = attempt / "steps.txt"
    plan.write_text("".join(f"{frames}:{names}\n" for frames, names in steps))
    env = emulator_environment(runtime)
    env.update({"ORAS_UI_PLAN": str(plan), "ORAS_UI_CAPTURE": str(attempt)})
    command = [mono, str(runtime / "EmuHawk.exe"), f"--config={runtime / 'config.ini'}"]
    if not args.interactive:
        command.append(f"--lua={PROJECT_ROOT / 'tools/bizhawk_ui_probe.lua'}")
    command.append(str(rom))
    report = {
        "scope": "Native UI only; no direct memory requests",
        "steps": [] if args.interactive else steps,
        "memory_read_requests": 0,
        "memory_write_requests": 0,
        "interactive": args.interactive,
    }
    print(f"Private save session: {session}\nAttempt: {attempt}", flush=True)
    with (attempt / "stdout.txt").open("w") as stdout, (attempt / "stderr.txt").open("w") as stderr:
        try:
            result = subprocess.run(
                command, cwd=runtime, env=env, stdout=stdout, stderr=stderr,
                timeout=None if args.interactive else args.timeout, check=False,
            )
            report["exit_code"] = result.returncode
            report["complete"] = result.returncode == 0 and (
                args.interactive or (attempt / "complete").exists()
            )
        except subprocess.TimeoutExpired:
            report.update({"exit_code": None, "complete": False, "timed_out": True})
    if manifest["seed_source"]:
        report["seed_source_unchanged"] = sha256(Path(manifest["seed_source"])) == manifest["seed_sha256"]
    if manifest.get("archive_metadata_source"):
        report["archive_metadata_source_unchanged"] = (
            sha256(Path(manifest["archive_metadata_source"])) == manifest["archive_metadata_sha256"]
        )
    target = save_destination(runtime, identity["program_id"])
    report["native_save_exists"] = target.exists()
    report["native_save_sha256"] = sha256(target) if target.exists() else None
    (attempt / "result.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return 0 if (
        report["complete"]
        and report.get("seed_source_unchanged", True)
        and report.get("archive_metadata_source_unchanged", True)
    ) else 1


if __name__ == "__main__":
    raise SystemExit(main())

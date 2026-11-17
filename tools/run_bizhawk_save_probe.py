"""Replay native button steps in a private profile, optionally seeded with a save copy."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import shutil
import subprocess
import tempfile

from rom_identity import inspect_rom, sha256_file
from oras_save import validate_save, inventory_bytes, inventory_entries, compare_medicine_change
from oras_events import event_bytes, compare_events, EVENT_LENGTH
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
    """Validate ORAS size, footer, descriptors and all 58 block CRCs before import."""
    if source.stat().st_size != 0x76000:
        raise ValueError("Expected a 0x76000-byte ORAS decrypted main save; no conversion is performed")
    validate_save(source.read_bytes())


def seed_archive(source: Path, destination: Path) -> dict:
    """Copy only a validated main and its required Encore archive metadata."""
    source = source.resolve()
    metadata_source = source.parent.with_suffix(".metadata")
    if not metadata_source.is_file() or metadata_source.stat().st_size != 16:
        raise ValueError("Seed import requires its 16-byte Encore 00000001.metadata sibling")
    source_hash, metadata_hash = sha256(source), sha256(metadata_source)
    seed_save(source, destination)
    metadata_target = destination.parent.with_suffix(".metadata")
    with metadata_source.open("rb") as original, metadata_target.open("xb") as copied:
        shutil.copyfileobj(original, copied)
    if sha256(destination) != source_hash or sha256(metadata_target) != metadata_hash:
        raise ValueError("Archive copy does not match the source")
    return {
        "seed_source": str(source), "seed_sha256": source_hash,
        "archive_metadata_source": str(metadata_source),
        "archive_metadata_sha256": metadata_hash,
    }


def keyboard_only_config(config: dict) -> dict:
    """Opt-in 3DS keyboard bindings; never alter the source profile or other systems."""
    config = json.loads(json.dumps(config))
    config.setdefault("AllTrollers", {})["3DS Controller"] = {
        "A": "X", "B": "Z", "X": "S", "Y": "A",
        "Up": "Up", "Down": "Down", "Left": "Left", "Right": "Right",
        "L": "Q", "R": "W", "ZL": "E", "ZR": "R",
        "Select": "Space", "Start": "Enter", "Touch": "WMouse L",
    }
    config.setdefault("AllTrollersAutoFire", {})["3DS Controller"] = {}
    analog = config.setdefault("AllTrollersAnalog", {}).setdefault("3DS Controller", {})
    for axis in ("Circle Pad X", "Circle Pad Y", "C-Stick X", "C-Stick Y"):
        analog[axis] = {
            "Value": "", "Mult": 1.0, "Deadzone": 0.1,
            "ButtonBindPositive": "", "ButtonBindNegative": "",
        }
    return config


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bizhawk", type=Path, default=PROJECT_ROOT / "bin/BizHawk-2.11.1-linux-x64")
    parser.add_argument("--rom", type=Path, required=True)
    parser.add_argument("--seed-save", type=Path)
    parser.add_argument("--session", type=Path, help="Reuse a profile created by this tool; never reseed it")
    parser.add_argument("--steps", default="180:-")
    parser.add_argument("--timeout", type=float, default=180)
    parser.add_argument("--speed", type=int, default=100, help="Automated emulation speed in percent")
    parser.add_argument(
        "--interactive", action="store_true",
        help="Open the private profile for manual play; no macro or automatic timeout",
    )
    parser.add_argument(
        "--keyboard-only", action="store_true",
        help="Interactive private 3DS keyboard controls; unbind gamepads and disable child HIDAPI",
    )
    parser.add_argument(
        "--read-inventory", action="store_true",
        help="Compare a source-documented read-only candidate with this profile's validated save",
    )
    parser.add_argument(
        "--scan-inventory", action="store_true",
        help="Search the documented application heap for this validated save's inventory",
    )
    parser.add_argument("--sample-step", type=int, help="Read inventory once more after this native UI step")
    parser.add_argument("--expect-medicine", help="Verify a native quantity change, e.g. 17:0; no game writes")
    parser.add_argument("--scan-event-work", action="store_true", help="Search for CRC-validated EventWork block")
    parser.add_argument("--read-event-work", action="store_true", help="Observe a documented EventWork RAM candidate")
    parser.add_argument("--event-sample-steps", default="", help="Read EventWork after these comma-separated UI steps")
    args = parser.parse_args()
    try:
        steps = parse_steps(args.steps)
    except ValueError as error:
        parser.error(str(error))
    if not math.isfinite(args.timeout) or args.timeout <= 0:
        parser.error("Timeout must be positive and finite")
    if args.session and args.seed_save:
        parser.error("--session and --seed-save are mutually exclusive")
    if args.keyboard_only and not args.interactive:
        parser.error("--keyboard-only requires --interactive")
    event_mode = args.scan_event_work or args.read_event_work
    if sum((args.read_inventory, args.scan_inventory, args.scan_event_work, args.read_event_work)) > 1:
        parser.error("Choose a single memory observation mode")
    if args.interactive and (args.read_inventory or args.scan_inventory or event_mode or args.speed != 100):
        parser.error("Interactive mode does not support memory observation or speed overrides")
    if not 1 <= args.speed <= 1000:
        parser.error("Speed must be between 1 and 1000 percent")
    if args.sample_step is not None and (
        not args.read_inventory or not 1 <= args.sample_step < len(steps)
    ):
        parser.error("--sample-step requires --read-inventory and an intermediate UI step")
    expected_medicine = None
    if args.expect_medicine is not None:
        try:
            expected_medicine = tuple(int(value) for value in args.expect_medicine.split(":"))
            if len(expected_medicine) != 2 or not 1 <= expected_medicine[0] <= 65535 or not 0 <= expected_medicine[1] <= 999:
                raise ValueError
        except ValueError:
            parser.error("--expect-medicine must be item_id:quantity within valid integer bounds")
        if args.sample_step is None:
            parser.error("--expect-medicine requires --sample-step")
    event_samples = []
    if args.event_sample_steps:
        try:
            event_samples = [int(value) for value in args.event_sample_steps.split(",")]
            if (not args.read_event_work or len(set(event_samples)) != len(event_samples)
                    or any(not 1 <= step <= len(steps) for step in event_samples)):
                raise ValueError
        except ValueError:
            parser.error("--event-sample-steps requires --read-event-work and distinct valid step indices")
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
            "seed_validation": "58_block_crcs_and_copy_integrity" if args.seed_save else "none",
            "archive_metadata_source": None,
            "archive_metadata_sha256": None,
        }
        if args.seed_save:
            manifest.update(seed_archive(args.seed_save, save_destination(runtime, identity["program_id"])))
        (session / "profile.json").write_text(json.dumps(manifest, indent=2) + "\n")
    if args.keyboard_only:
        config_path = runtime / "config.ini"
        config_path.write_text(json.dumps(keyboard_only_config(json.loads(config_path.read_text())), indent=2) + "\n")
    attempt = Path(tempfile.mkdtemp(prefix="attempt-", dir=session))
    plan = attempt / "steps.txt"
    plan.write_text("".join(f"{frames}:{names}\n" for frames, names in steps))
    env = emulator_environment(runtime, automated=not args.interactive or args.keyboard_only)
    env.update({
        "ORAS_UI_PLAN": str(plan), "ORAS_UI_CAPTURE": str(attempt),
        "ORAS_UI_SPEED": str(args.speed),
    })
    reference = None
    candidate = None
    if event_mode:
        candidates = json.loads((PROJECT_ROOT / "tools/oras_memory_candidates.json").read_text())
        candidate = candidates["profiles"].get(rom_hash)
        if (candidate is None or candidate["program_id"] != identity["program_id"]
                or candidate["domain"] != "System Bus" or candidate["write_allowed"] is not False):
            parser.error("No read-only event research profile for this exact ROM")
        reference = event_bytes(save_destination(runtime, identity["program_id"]).read_bytes())
        if not any(reference):
            parser.error("All-zero event search references are not accepted")
        env.update({
            "ORAS_UI_SCRIPT": str(PROJECT_ROOT / "tools/bizhawk_ui_probe.lua"),
            "ORAS_UI_CONTINUE": "1", "ORAS_EVENT_MODE": "scan" if args.scan_event_work else "read",
        })
        if args.scan_event_work:
            ref_path = attempt / "event-reference.bin"
            ref_path.write_bytes(reference)
            env.update({
                "ORAS_EVENT_REFERENCE": str(ref_path),
                "ORAS_EVENT_SEARCH_SCRIPT": str(PROJECT_ROOT / "tools/inventory_search.lua"),
            })
        else:
            event_candidate = candidate.get("event_work")
            if (not event_candidate or event_candidate["length"] != EVENT_LENGTH
                    or event_candidate.get("write_allowed") is not False):
                parser.error("No documented EventWork RAM candidate; search must precede observation")
            env.update({
                "ORAS_EVENT_ADDRESS": str(int(event_candidate["address"], 16)),
                "ORAS_EVENT_SAMPLE_STEPS": ",".join(str(step) for step in event_samples),
            })
    if args.read_inventory or args.scan_inventory:
        candidates = json.loads((PROJECT_ROOT / "tools/oras_memory_candidates.json").read_text())
        candidate = candidates["profiles"].get(rom_hash)
        if candidate is None or candidate["program_id"] != identity["program_id"]:
            parser.error("No documented inventory candidate for this exact ROM")
        if candidate["write_allowed"] or candidate["domain"] != "System Bus":
            parser.error("This tool only supports read-only System Bus candidates")
        target = save_destination(runtime, identity["program_id"])
        reference = inventory_bytes(target.read_bytes())
        if len(reference) != candidate["inventory_length"] or not any(reference):
            parser.error("Inventory reference must have the documented length and nonzero contents")
        env.update({
            "ORAS_UI_SCRIPT": str(PROJECT_ROOT / "tools/bizhawk_ui_probe.lua"),
            "ORAS_UI_CONTINUE": "1",
            "ORAS_INVENTORY_ADDRESS": str(int(candidate["inventory_address"], 16)),
            "ORAS_INVENTORY_LENGTH": str(candidate["inventory_length"]),
        })
        if args.sample_step is not None:
            env["ORAS_INVENTORY_SAMPLE_STEP"] = str(args.sample_step)
        if args.scan_inventory:
            reference_path = attempt / "inventory-reference.bin"
            reference_path.write_bytes(reference)
            env.update({
                "ORAS_INVENTORY_REFERENCE": str(reference_path),
                "ORAS_INVENTORY_SEARCH_SCRIPT": str(PROJECT_ROOT / "tools/inventory_search.lua"),
            })
    command = [mono, str(runtime / "EmuHawk.exe"), f"--config={runtime / 'config.ini'}"]
    if not args.interactive:
        if event_mode:
            script = "bizhawk_event_probe.lua"
        elif args.scan_inventory:
            script = "bizhawk_inventory_search.lua"
        else:
            script = "bizhawk_inventory_probe.lua" if args.read_inventory else "bizhawk_ui_probe.lua"
        command.append(f"--lua={PROJECT_ROOT / 'tools' / script}")
    command.append(str(rom))
    report = {
        "scope": "Native UI only; no direct memory requests",
        "steps": [] if args.interactive else steps,
        "memory_read_requests": 0,
        "memory_write_requests": 0,
        "interactive": args.interactive,
        "keyboard_only": args.keyboard_only,
        "speed_percent": args.speed,
        "host_hidapi_disabled_for_automation": not args.interactive,
        "host_hidapi_disabled_for_keyboard_only": args.keyboard_only,
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
    if event_mode:
        report["scope"] = "Read-only EventWork search" if args.scan_event_work else "Native UI with read-only EventWork observations"
        journal = attempt / "event-read-requests.txt"
        report["memory_read_requests"] = len(journal.read_text().splitlines()) if journal.exists() else 0
        if args.scan_event_work:
            matches_path = attempt / "event-matches.txt"
            matches = matches_path.read_text().splitlines() if matches_path.exists() else []
            report["event_search"] = {
                "domain": "System Bus", "start": "0x08000000", "end_exclusive": "0x10000000",
                "length": len(reference), "matches": matches, "unique_match": len(matches) == 1,
            }
            report["complete"] = report["complete"] and len(matches) == 1
        else:
            samples = {}
            for step in sorted(event_samples):
                path = attempt / f"event-step-{step:02d}.bin"
                if path.exists():
                    samples[str(step)] = compare_events(reference, path.read_bytes())
            final = attempt / "event-final.bin"
            report["event_observation"] = {
                "domain": "System Bus", "address": event_candidate["address"], "length": EVENT_LENGTH,
                "samples": samples,
                "final_vs_save_before_launch": compare_events(reference, final.read_bytes()) if final.exists() else None,
            }
            baseline_matches = not event_samples or (
                str(min(event_samples)) in samples and samples[str(min(event_samples))]["matches_reference"]
            )
            report["event_observation"]["baseline_matches_validated_save"] = baseline_matches if event_samples else None
            report["complete"] = (
                report["complete"] and final.exists() and len(samples) == len(event_samples) and baseline_matches
            )
        if target.exists():
            # The game, not this tool, is responsible for any save-file changes.
            report["saved_event_vs_before_launch"] = compare_events(reference, event_bytes(target.read_bytes()))
    if args.read_inventory:
        report["scope"] = "Native UI and one explicit read-only inventory candidate"
        journal = attempt / "inventory-read-requests.txt"
        report["memory_read_requests"] = (
            len(journal.read_text().splitlines()) if journal.exists()
            else int((attempt / "inventory-requested").exists())
        )
        observed_path = attempt / "inventory-read.bin"
        matches = observed_path.exists() and observed_path.read_bytes() == reference
        report["inventory_read"] = {
            "candidate_address": candidate["inventory_address"],
            "domain": candidate["domain"],
            "length": len(reference),
            "matches_validated_save": matches,
            "reference_entries": inventory_entries(reference),
        }
        if expected_medicine is not None:
            report["scope"] = "Native medicine change with read-only before/after observations"
            report["expected_change_comparison_only"] = True
            before_path = attempt / "inventory-before.bin"
            if before_path.exists() and observed_path.exists():
                differential = compare_medicine_change(
                    reference, before_path.read_bytes(), observed_path.read_bytes(), *expected_medicine
                )
                report["inventory_read"]["differential"] = differential
                report["complete"] = report["complete"] and differential["passed"]
            else:
                report["complete"] = False
        else:
            report["complete"] = report["complete"] and matches
    if args.scan_inventory:
        report["scope"] = "Read-only exact inventory search in Encore's documented application heap"
        journal = attempt / "inventory-scan-reads.txt"
        report["memory_read_requests"] = len(journal.read_text().splitlines()) if journal.exists() else 0
        matches_path = attempt / "inventory-matches.txt"
        matches = matches_path.read_text().splitlines() if matches_path.exists() else []
        report["inventory_scan"] = {
            "domain": "System Bus", "start": "0x08000000", "end_exclusive": "0x10000000",
            "matches": matches, "unique_match": len(matches) == 1,
            "length": len(reference), "reference_entries": inventory_entries(reference),
        }
        report["complete"] = report["complete"] and matches_path.exists() and len(matches) == 1
    (attempt / "result.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return 0 if (
        report["complete"]
        and report.get("seed_source_unchanged", True)
        and report.get("archive_metadata_source_unchanged", True)
    ) else 1


if __name__ == "__main__":
    raise SystemExit(main())

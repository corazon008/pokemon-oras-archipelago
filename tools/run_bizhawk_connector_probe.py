"""Probe pinned AP transport; explicit Potion/native-SAVE experiments use isolated copies."""

from __future__ import annotations

import argparse
import asyncio
import base64
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import platform
import shutil
import socket
import subprocess
import tempfile

from ap_connector_bundle import fetch_bundle, load_upstream_api
from run_bizhawk_probe import (
    PROJECT_ROOT, emulator_environment, isolate_config, prepare_runtime, sha256,
)
from rom_identity import CodeReference, inspect_rom, sha256_file
from run_bizhawk_save_probe import parse_steps, save_destination, seed_archive
from oras_connector_inventory import (
    BOOT_MEDICINE_STEPS, NATIVE_SAVE_STEPS, InventoryReference,
    add_experimental_potion, load_inventory_reference, potion_transition, read_inventory,
)
from oras_save import inspect_save, inventory_bytes
from oras_events import event_bytes
from oras_connector_events import BOOT_GAMEPLAY_STEPS, EventReference, load_event_reference, read_events
from oras_profiles import (
    PROFILE_ROOT, backup_existing_save, validate_profile_path, validate_snapshot, require_single_file_archive,
)
from oras_archive import capture_stable_archive, source_archive_unchanged, tree_digest


REQUESTS = (
    {"type": "PING"},
    {"type": "SYSTEM"},
    {"type": "MEMORY_SIZE", "domain": "FCRAM"},
    {"type": "MEMORY_SIZE", "domain": "System Bus"},
)


def require_free_ports() -> None:
    """Abort rather than attach to an existing user's connector."""
    reservations = []
    try:
        for port in range(43055, 43061):
            reservation = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            reservations.append(reservation)
            reservation.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            reservation.bind(("127.0.0.1", port))
    except OSError as error:
        raise RuntimeError("Connector port already occupied; close that connector first") from error
    finally:
        for reservation in reservations:
            reservation.close()


async def connect_until_ready(api, context, process, deadline: float) -> None:
    loop = asyncio.get_running_loop()
    while loop.time() < deadline:
        if process.poll() is not None:
            raise RuntimeError("EmuHawk exited before the connector was ready")
        if await api.connect(context):
            return
        await asyncio.sleep(0.1)
    raise TimeoutError("Connector startup/reconnection timed out")


def validate_responses(responses: list) -> None:
    if len(responses) != 4:
        raise ValueError("Unexpected connector response count")
    if responses[0] != {"type": "PONG"}:
        raise ValueError("PING failed")
    if responses[1] != {"type": "SYSTEM_RESPONSE", "value": "3DS"}:
        raise ValueError("Connector did not identify the 3DS system")
    if responses[2] != {"type": "MEMORY_SIZE_RESPONSE", "value": 268435456}:
        raise ValueError("Unexpected FCRAM size for this New 3DS test profile")
    if responses[3] != {"type": "MEMORY_SIZE_RESPONSE", "value": 0}:
        raise ValueError("System Bus size API behavior changed; investigate")


async def exercise_connector(api, process, timeout: float,
                              code_reference: CodeReference | None = None,
                              audit: dict | None = None,
                              inventory_reference: InventoryReference | None = None,
                              potion_rom_hash: str | None = None,
                              event_reference: EventReference | None = None,
                              strict_ready: Path | None = None,
                              object_capture: Path | None = None,
                              bootstrap_references: list[CodeReference] | None = None) -> list[dict]:
    if event_reference is not None and (code_reference is None or audit is None):
        raise ValueError("Event reads require a runtime code guard and audit")
    if object_capture is not None and (strict_ready is None or audit is None):
        raise ValueError("Object rechecks require strict readiness and audit")
    if bootstrap_references is not None and (not bootstrap_references or code_reference is None or audit is None):
        raise ValueError("Bootstrap rechecks require code reference, audit and nonempty references")
    if potion_rom_hash is not None:
        if code_reference is None or inventory_reference is None or audit is None:
            raise ValueError("Potion experiment requires code, inventory and audit")
        potion_transition(potion_rom_hash, code_reference, inventory_reference)
    exchanges = []
    if audit is not None:
        audit["exchanges"] = exchanges
    context = api.BizHawkContext()
    deadline = asyncio.get_running_loop().time() + timeout
    try:
        if strict_ready is not None:
            if code_reference is None or audit is None:
                raise ValueError("Strict guard tests require code reference and audit")
            while not strict_ready.exists():
                if process.poll() is not None:
                    raise RuntimeError("EmuHawk exited before strict GUARD installation")
                if asyncio.get_running_loop().time() >= deadline:
                    raise TimeoutError("Strict GUARD installation timed out")
                await asyncio.sleep(0.1)
            audit["strict_guard_ready"] = True
        object_reference = None
        if object_capture is not None:
            from oras_save_objects import load_object_observation
            object_reference = load_object_observation(object_capture, audit["save_objects"])
        for attempt in range(3 if potion_rom_hash else 2):
            await connect_until_ready(api, context, process, deadline)
            version = await api.get_script_version(context)
            if version != 1:
                raise ValueError(f"Unexpected connector script version: {version}")
            responses = await api.send_requests(context, list(REQUESTS))
            validate_responses(responses)
            exchange = {
                "connection": attempt + 1,
                "script_version": version,
                "port": context._port,
                "requests": list(REQUESTS),
                "responses": responses,
            }
            if code_reference is not None:
                if audit is not None:
                    audit["memory_read_requests"] += 1
                payloads = await api.read(context, [
                    (code_reference.address, len(code_reference.expected), "System Bus"),
                ])
                if len(payloads) != 1 or payloads[0] != code_reference.expected:
                    raise ValueError("Runtime code prefix does not match the selected ROM/explicit patch reference")
                exchange["code_read"] = {
                    "domain": "System Bus",
                    "address": f"0x{code_reference.address:08X}",
                    "length": len(payloads[0]),
                    "sha256": hashlib.sha256(payloads[0]).hexdigest(),
                    "matches_rom_prefix": (
                        not bootstrap_references or audit.get("bootstrap", {}).get("mode") == "allocation-only"
                    ),
                }
                if bootstrap_references:
                    exchange["code_read"]["matches_bootstrap_prefix"] = True
            if bootstrap_references:
                audit["memory_read_requests"] += len(bootstrap_references)
                payloads = await api.read(context, [
                    (ref.address, len(ref.expected), "System Bus") for ref in bootstrap_references
                ])
                if len(payloads) != len(bootstrap_references) or any(
                    actual != ref.expected for actual, ref in zip(payloads, bootstrap_references)
                ):
                    raise ValueError("Bootstrap native marker or installed code differs")
                exchange["bootstrap_reads"] = [
                    {"address": ref.address, "length": len(actual),
                     "sha256": hashlib.sha256(actual).hexdigest(), "matches_expected": True}
                    for ref, actual in zip(bootstrap_references, payloads)
                ]
                trace_plan = audit.get("bootstrap", {}).get("registration_trace")
                if trace_plan:
                    from oras_save_registration import read_registration_trace
                    trace = await read_registration_trace(api, context, trace_plan, audit)
                    if exchanges and trace != exchanges[0]["registration_trace"]:
                        raise ValueError("Native registration trace changed after reconnect")
                    exchange["registration_trace"] = trace
            if object_reference is not None:
                audit["memory_read_requests"] += 1
                payloads = await api.read(context, [
                    (object_reference.address, len(object_reference.expected), "System Bus"),
                ])
                if len(payloads) != 1 or payloads[0] != object_reference.expected:
                    raise ValueError("Save-object bytes changed before/after AP reconnect")
                exchange["save_object_read"] = {
                    "address": f"0x{object_reference.address:08X}",
                    "length": len(payloads[0]), "matches_private_plan": True,
                    "sha256": hashlib.sha256(payloads[0]).hexdigest(),
                }
            if inventory_reference is not None:
                if code_reference is None or audit is None:
                    raise ValueError("Inventory reads require a runtime code guard and audit")
                exchange["inventory_read"] = await read_inventory(api, context, inventory_reference, audit)
            if event_reference is not None:
                exchange["event_read"] = await read_events(api, context, event_reference, audit)
            if strict_ready is not None:
                exchange["strict_guard_test"] = await test_strict_guard(api, context, code_reference, audit)
            if potion_rom_hash is not None and attempt == 1:
                inventory_reference = await add_experimental_potion(
                    api, context, potion_rom_hash, code_reference, inventory_reference, audit,
                )
            exchanges.append(exchange)
            writer = context.streams[1]
            api.disconnect(context)
            await writer.wait_closed()
    finally:
        api.disconnect(context)
    return exchanges


async def test_strict_guard(api, context, code: CodeReference, audit: dict) -> dict:
    """Read-only: valid guard, then invalid-domain guard followed by a skipped READ."""
    request = {
        "type": "GUARD", "address": code.address, "domain": "System Bus",
        "expected_data": base64.b64encode(code.expected).decode("ascii"),
    }
    audit["memory_guard_requests"] = audit.get("memory_guard_requests", 0) + 1
    valid = await api.send_requests(context, [request])
    if valid != [{"type": "GUARD_RESPONSE", "address": code.address, "value": True}]:
        raise ValueError("Strict GUARD rejected known matching code")
    audit["memory_guard_requests"] += 1
    audit["memory_read_requests"] += 1  # Submitted READ, expected to be skipped by failed guard.
    blocked = await api.send_requests(context, [
        {**request, "domain": "ORAS_TEST_ABSENT_DOMAIN"},
        {"type": "READ", "address": code.address, "size": len(code.expected), "domain": "System Bus"},
    ])
    expected = {"type": "GUARD_RESPONSE", "address": code.address, "value": False}
    if blocked != [expected, expected]:
        raise ValueError("Failed strict GUARD did not skip the following READ")
    audit["read_requests_blocked_by_guard"] = audit.get("read_requests_blocked_by_guard", 0) + 1
    return {"matching_code_accepted": True, "invalid_domain_failed_closed": True, "following_read_skipped": True}


async def finish_native_ui(process, signal: Path, marker: Path, timeout: float) -> None:
    signal.touch()  # Only called after the selected experiment's preconditions pass.
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if marker.exists():
            return
        if process.poll() is not None:
            raise RuntimeError("EmuHawk exited before native save macro completed")
        await asyncio.sleep(0.1)
    raise TimeoutError("Native save macro timed out; do not retry memory write")


def reuse_profile(path: Path, rom_hash: str) -> tuple[Path, dict]:
    """Reuse only a matching tool-created profile; never import another save."""
    path = validate_profile_path(path)
    manifest = json.loads((path / "profile.json").read_text())
    if manifest.get("kind") != "oras_native_save_probe" or manifest.get("rom_sha256") != rom_hash:
        raise ValueError("Profile/ROM identity mismatch")
    if manifest.get("experimental_bootstrap"):
        raise ValueError("Bootstrap profiles require a fresh explicit experiment, not normal profile reuse")
    if manifest.get("archive_file_count", 1) > 1 or manifest.get("archive_directory_count", 0):
        raise ValueError("Multi-file archives require a fresh read-only recovery fork")
    runtime = path / "runtime"
    if runtime.is_symlink() or not runtime.resolve().is_relative_to(path):
        raise ValueError("Runtime must stay inside the test profile")
    config_path = runtime / "config.ini"
    config_path.write_text(json.dumps(isolate_config(json.loads(config_path.read_text()), runtime), indent=2) + "\n")
    return runtime, manifest


def apply_initial_time(config_path: Path, value: str) -> str:
    clock = datetime.fromisoformat(value)
    if clock.tzinfo is not None or not datetime(2000, 1, 1) <= clock < datetime(2100, 1, 1):
        raise ValueError("Initial emulated time must be timezone-free and within 2000..2099")
    config = json.loads(config_path.read_text())
    matches = [settings for core, settings in config.get("CoreSyncSettings", {}).items()
               if core.rsplit(".", 1)[-1] == "Encore"]
    if len(matches) != 1:
        raise ValueError("Initial-time control requires one existing Encore configuration")
    canonical = clock.isoformat(timespec="seconds")
    matches[0].update({"UseRealTime": False, "InitialTime": canonical})
    config_path.write_text(json.dumps(config, indent=2) + "\n")
    return canonical


def recovery_snapshot_reference(snapshot: Path, identity: dict) -> dict:
    manifest = validate_snapshot(snapshot, identity["rom_sha256"])
    if manifest["program_id"] != identity["program_id"]:
        raise ValueError("Recovery snapshot/ROM program ID mismatch")
    return {
        "source_snapshot": str(snapshot.resolve()),
        "source_save_sha256": manifest["save_sha256"],
        "source_metadata_sha256": manifest["metadata_sha256"],
        "snapshot_schema_version": manifest["schema_version"],
        "source_archive_tree_sha256": manifest.get("archive_tree_sha256"),
        "restore_in_place": False, "ap_binding_proven": False,
        "next_delivery_index": None, "live_delivery_authorized": False,
        "journal_reset_or_replay_authorized": False,
    }


def inspect_initial_objects(objects, rom, report):
    from oras_save_manager import inspect_manager_capture
    manager = report["save_objects"]["manager"]
    manager.update(inspect_manager_capture(
        objects, rom, manager, (Path(report["backup_before_launch"]) / "00000001/main").read_bytes(),
    ))
    if (manager["size_mismatch_ids"] or manager["metadata_descriptors_matching_file_layout"] != 58
            or not manager["metadata_payload_matches_saved_footer"]):
        raise ValueError("Manager metadata or recognized sizes differ from the validated reference")
    if manager.get("backrefs_requested"):
        from oras_save_references import inspect_reference_capture
        manager["references"] = inspect_reference_capture(objects, rom, manager["predicted_base"])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bizhawk", type=Path, default=PROJECT_ROOT / "bin/BizHawk-2.11.1-linux-x64")
    parser.add_argument("--rom", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=60)
    parser.add_argument("--seed-save", type=Path, help="Copy a validated save/archive; read inventory after native boot")
    parser.add_argument("--recover-from-snapshot", type=Path,
                        help="Read-only recovery fork from verified snapshot; never restore in place or replay items")
    parser.add_argument("--session", type=Path, help="Reuse an identified tool-created profile for read-only probes")
    parser.add_argument("--read-event-work", action="store_true", help="Read full EventWork plus bounded clock-scene candidate")
    parser.add_argument("--scan-save-objects", action="store_true", help="Read-only executable-derived block47 object search")
    parser.add_argument("--trace-save-manager", action="store_true", help="Read-only constructor-derived manager table and object headers")
    parser.add_argument("--scan-save-references", action="store_true", help="Read-only heap references to the verified native save manager")
    parser.add_argument("--observe-native-save", action="store_true",
                        help="Frame-sample one native SAVE; requires a fresh --seed-save copy, no memory writes")
    parser.add_argument("--initial-time", help="Explicit emulated RTC time (ISO 8601); fresh seeded copies only")
    parser.add_argument("--experimental-bootstrap", choices=("hook", "allocation-only", "registration-trace"),
                        help="Fresh-copy native startup marker in an explicitly added volatile BSS page; no ledger")
    parser.add_argument("--steps", help="Native boot steps; defaults to gameplay for events, Medicine otherwise")
    parser.add_argument("--speed", type=int, default=100)
    parser.add_argument("--strict-guards", action="store_true", help="Install and read-only test a fail-closed GUARD shim")
    parser.add_argument(
        "--experimental-potion-1-to-2", action="store_true",
        help="One guarded 2-byte write in a fresh seeded copy, then native save; never an AP delivery",
    )
    parser.add_argument(
        "--read-code", action="store_true",
        help="Compare a 64-byte text prefix at the virtual address derived from the ROM ExHeader",
    )
    args = parser.parse_args()
    source, rom = args.bizhawk.resolve(), args.rom.resolve()
    if platform.system() != "Linux" or platform.machine() != "x86_64":
        parser.error("This pinned LuaSocket bundle targets Linux x86_64")
    if not math.isfinite(args.timeout) or args.timeout <= 0:
        parser.error("Timeout must be positive and finite")
    if not 1 <= args.speed <= 1000:
        parser.error("Speed must be between 1 and 1000 percent")
    if args.seed_save and args.session:
        parser.error("--seed-save and --session are mutually exclusive")
    if args.experimental_bootstrap:
        if (not args.seed_save or args.session or args.recover_from_snapshot or args.observe_native_save
                or args.experimental_potion_1_to_2 or args.steps or args.scan_save_objects
                or args.trace_save_manager or args.scan_save_references):
            parser.error("--experimental-bootstrap requires a fresh seed; no reuse/recovery/writes/scans/custom steps")
        args.read_event_work = True
        args.strict_guards = True
    if args.recover_from_snapshot:
        if args.seed_save or args.session or args.observe_native_save or args.experimental_potion_1_to_2 or args.steps:
            parser.error("--recover-from-snapshot requires a new read-only profile; no seed/session/SAVE/Potion/custom steps")
        args.recover_from_snapshot = args.recover_from_snapshot.resolve()
        args.seed_save = args.recover_from_snapshot / "00000001/main"
        args.scan_save_references = True
    has_profile = bool(args.seed_save or args.session)
    if args.initial_time and not args.seed_save:
        parser.error("--initial-time requires a fresh --seed-save copy; existing profiles are not changed")
    if args.observe_native_save:
        if not args.seed_save or args.session or args.experimental_potion_1_to_2:
            parser.error("--observe-native-save requires a fresh --seed-save copy and forbids Potion writes")
        args.scan_save_references = True
    if args.scan_save_references:
        args.trace_save_manager = True
    if args.trace_save_manager:
        args.scan_save_objects = True
    if args.scan_save_objects:
        if not has_profile:
            parser.error("--scan-save-objects requires a validated profile")
        args.read_event_work = True
        args.strict_guards = True
    if args.read_event_work and not has_profile:
        parser.error("--read-event-work requires --seed-save or --session")
    if args.read_event_work and args.experimental_potion_1_to_2:
        parser.error("Event probes are read-only; do not combine with the Potion experiment")
    if args.experimental_potion_1_to_2 and not args.seed_save:
        parser.error("--experimental-potion-1-to-2 requires --seed-save (fresh private copy)")
    strict_guards = args.strict_guards or args.experimental_potion_1_to_2
    if strict_guards and not (args.read_code or has_profile):
        parser.error("--strict-guards requires --read-code or a validated profile")
    try:
        steps = parse_steps(args.steps or (BOOT_GAMEPLAY_STEPS if args.read_event_work else BOOT_MEDICINE_STEPS))
    except ValueError as error:
        parser.error(str(error))
    if not (source / "EmuHawk.exe").is_file() or not rom.is_file():
        parser.error("BizHawk executable and ROM must exist")
    mono = shutil.which("mono")
    if not mono:
        parser.error("Mono is not on PATH")
    require_free_ports()
    temporary_root = PROFILE_ROOT
    temporary_root.mkdir(parents=True, exist_ok=True)
    if args.session:
        try:
            profile_path = validate_profile_path(args.session)
        except ValueError as error:
            parser.error(str(error))
        session = Path(tempfile.mkdtemp(prefix="connector-attempt-", dir=profile_path))
    else:
        session = Path(tempfile.mkdtemp(
            prefix="oras-recovery-" if args.recover_from_snapshot else "oras-connector-", dir=temporary_root,
        ))
    print(f"Isolated connector session: {session}", flush=True)
    report = {
        "schema_version": 1,
        "status": "preparing",
        "scope": "TCP metadata and reconnection only",
        "memory_read_requests": 0,
        "memory_write_requests": 0,
        "existing_3ds_profile_copied": False,
        "rom": str(rom),
        "strict_guards_enabled": strict_guards,
    }
    process = None
    archive = None
    try:
        code_reference = None
        inventory_reference = None
        event_reference = None
        bootstrap_references = None
        if args.read_code or has_profile:
            identity, code_reference = inspect_rom(rom)
            if identity["edition_from_program_id"] is None or code_reference is None:
                raise ValueError("ROM has no supported ORAS text-prefix reference")
            identity["rom_sha256"] = sha256_file(rom)
            report["rom_identity"] = identity
            report["scope"] = "TCP metadata and ROM-derived code-prefix reads only"
        if args.recover_from_snapshot:
            report["recovery_fork"] = recovery_snapshot_reference(args.recover_from_snapshot, identity)
        bundle = session / "connector"
        lock = fetch_bundle(bundle)
        api = load_upstream_api(bundle, lock)
        if args.session:
            runtime, archive = reuse_profile(args.session, identity["rom_sha256"])
            report["reused_profile"] = str(args.session.resolve())
            report["archive"] = archive
        else:
            runtime = prepare_runtime(source, session)
        if args.initial_time:
            report["emulated_initial_time"] = apply_initial_time(runtime / "config.ini", args.initial_time)
            report["emulated_use_real_time"] = False
        if has_profile:
            profile_save = args.seed_save or save_destination(runtime, identity["program_id"])
            if args.session:
                require_single_file_archive(profile_save)
            inventory_reference = load_inventory_reference(
                identity["rom_sha256"], identity["program_id"], profile_save,
            )
            if args.seed_save:
                archive = seed_archive(
                    args.seed_save, save_destination(runtime, identity["program_id"]),
                    identity["program_id"], identity["rom_sha256"],
                )
                report["archive"] = archive
                if (archive["archive_file_count"] > 1 or archive["archive_directory_count"]) and not args.recover_from_snapshot:
                    raise ValueError("Multi-file archive boot requires an explicit read-only recovery fork")
            report["save_sha256_before_launch"] = sha256(save_destination(runtime, identity["program_id"]))
            report["backup_before_launch"] = backup_existing_save(
                save_destination(runtime, identity["program_id"]),
                identity["program_id"], identity["rom_sha256"], "before-connector",
            )
            report["scope"] = "TCP metadata, code and validated inventory reads, including reconnection"
            report["native_boot_steps"] = steps
            report["speed_percent"] = args.speed
            if args.experimental_potion_1_to_2:
                potion_transition(identity["rom_sha256"], code_reference, inventory_reference)
                report["scope"] = "Experimental guarded Potion 1-to-2, readback, reconnect and native save"
            if args.read_event_work:
                report["event_mismatch_capture"] = str(session / "event-mismatch.bin")
                event_reference = load_event_reference(
                    identity["rom_sha256"], identity["program_id"], profile_save,
                )
                report["scope"] = "Read-only AP transport: code, inventory and EventWork before/after reconnect"
        if args.experimental_bootstrap:
            from oras_bootstrap_patch import install_bootstrap
            code_reference, bootstrap_references, report["bootstrap"] = install_bootstrap(
                rom, runtime, args.experimental_bootstrap,
            )
            report["scope"] = "Experimental native bootstrap on fresh copy; new volatile page, no SAVE or AP ledger"
            if args.experimental_bootstrap == "registration-trace":
                report["registration_trace_capture"] = str(session / "registration-trace")
                report["scope"] = "Experimental native constructor/registration trace; no SAVE or AP record"
        wrapper = bundle / "probe.lua"
        shutil.copyfile(PROJECT_ROOT / "tools/bizhawk_connector_probe.lua", wrapper)
        stop_file = session / "stop"
        env = emulator_environment(runtime, automated=True)
        for optional in ("ORAS_CONNECTOR_BOOT", "ORAS_CONNECTOR_POST_SCRIPT", "ORAS_CONNECTOR_OBJECT_SCRIPT",
                         "ORAS_CONNECTOR_STRICT_GUARD_SCRIPT", "ORAS_CONNECTOR_STRICT_GUARD_READY",
                         "ORAS_OBJECT_MANAGER_TABLE", "ORAS_OBJECT_MANAGER_REFERENCES",
                         "ORAS_NATIVE_SAVE_OBSERVER_SCRIPT", "ORAS_NATIVE_SAVE_OBSERVER_CONFIG"):
            env.pop(optional, None)
        env.update({
            "ORAS_CONNECTOR_DIRECTORY": str(bundle),
            "ORAS_CONNECTOR_STOP": str(stop_file),
            "ORAS_CONNECTOR_TIMEOUT": str(math.ceil(args.timeout) + 10),
        })
        strict_ready = None
        if strict_guards:
            strict_ready = session / "strict-guard-ready"
            strict_script = PROJECT_ROOT / "tools/strict_bizhawk_guard.lua"
            env.update({
                "ORAS_CONNECTOR_STRICT_GUARD_SCRIPT": str(strict_script),
                "ORAS_CONNECTOR_STRICT_GUARD_READY": str(strict_ready),
            })
            report["strict_guard_sha256"] = sha256(strict_script)
        if has_profile:
            capture = session / "boot"
            capture.mkdir()
            plan = capture / "steps.txt"
            plan.write_text("".join(f"{frames}:{names}\n" for frames, names in steps))
            env.update({
                "ORAS_CONNECTOR_BOOT": str(PROJECT_ROOT / "tools/bizhawk_ui_probe.lua"),
                "ORAS_UI_PLAN": str(plan), "ORAS_UI_CAPTURE": str(capture),
                "ORAS_UI_SPEED": str(args.speed), "ORAS_UI_CONTINUE": "1",
            })
        if args.scan_save_objects:
            from oras_save_objects import build_plan
            profile = json.loads((PROJECT_ROOT / "tools/oras_memory_candidates.json").read_text())["profiles"][
                identity["rom_sha256"]]
            plan_bytes, object_report = build_plan(
                rom, identity["rom_sha256"],
                save_destination(runtime, identity["program_id"]).read_bytes(), profile,
                manager=args.trace_save_manager,
            )
            objects = session / "objects"
            objects.mkdir()
            plan_path = objects / "references.bin"
            plan_path.write_bytes(plan_bytes)  # Private ROM-derived bytes, never distributed.
            report["save_objects"] = object_report
            report["scope"] = "Read-only executable references, save-object heap search and AP reconnect"
            report["save_objects"]["probe_sha256"] = sha256(PROJECT_ROOT / "tools/bizhawk_save_object_probe.lua")
            report["save_objects"]["search_sha256"] = sha256(PROJECT_ROOT / "tools/inventory_search.lua")
            report["save_objects"]["plan_sha256"] = sha256(plan_path)
            env.update({
                "ORAS_CONNECTOR_OBJECT_SCRIPT": str(PROJECT_ROOT / "tools/bizhawk_save_object_probe.lua"),
                "ORAS_OBJECT_CAPTURE": str(objects), "ORAS_OBJECT_PLAN": str(plan_path),
                "ORAS_OBJECT_SEARCH": str(PROJECT_ROOT / "tools/inventory_search.lua"),
            })
            if args.trace_save_manager:
                env["ORAS_OBJECT_MANAGER_TABLE"] = str(object_report["manager"]["predicted_table"])
                report["save_objects"]["manager"]["analysis_sha256"] = sha256(PROJECT_ROOT / "tools/oras_save_manager.py")
                if args.scan_save_references:
                    env["ORAS_OBJECT_MANAGER_REFERENCES"] = "1"
                    report["save_objects"]["manager"]["backrefs_requested"] = True
                    report["save_objects"]["manager"]["record_referrers_requested"] = True
                    report["save_objects"]["manager"]["references_analysis_sha256"] = sha256(
                        PROJECT_ROOT / "tools/oras_save_references.py")
        if args.experimental_potion_1_to_2 or args.observe_native_save:
            post = session / "native-save"
            post.mkdir()
            post_plan = post / "steps.txt"
            # Observation starts in the source-verified overworld, before any bag/menu work changes.
            observation_menu = "2:X,60:-,2:A,120:-,2:Right,60:-,"
            post_steps = parse_steps((observation_menu if args.observe_native_save else "") + NATIVE_SAVE_STEPS)
            post_plan.write_text("".join(f"{frames}:{names}\n" for frames, names in post_steps))
            report["native_save_steps"] = post_steps
            env.update({
                "ORAS_CONNECTOR_POST_SCRIPT": str(PROJECT_ROOT / "tools/bizhawk_connector_post_ui.lua"),
                "ORAS_CONNECTOR_POST_PLAN": str(post_plan),
                "ORAS_CONNECTOR_POST_CAPTURE": str(post),
                "ORAS_CONNECTOR_POST_SIGNAL": str(session / "finish-ui"),
            })
            if args.observe_native_save:
                observer_script = PROJECT_ROOT / "tools/native_save_observer.lua"
                env.update({
                    "ORAS_NATIVE_SAVE_OBSERVER_SCRIPT": str(observer_script),
                    "ORAS_NATIVE_SAVE_OBSERVER_CONFIG": str(post / "observer.json"),
                })
                report["native_observation"] = {"observer_sha256": sha256(observer_script)}
                report["scope"] = "Native SAVE on fresh seeded copy; read-only frame and host-file sampling"
        command = [
            mono, str(runtime / "EmuHawk.exe"),
            f"--config={runtime / 'config.ini'}", f"--lua={wrapper}", str(rom),
        ]
        report.update({
            "ap_commit": lock["commit"],
            "emuhawk_sha256": sha256(runtime / "EmuHawk.exe"),
            "encore_sha256": sha256(runtime / "dll/libencore.so"),
            "bundle_verified": True,
        })
        with (session / "stdout.txt").open("w") as stdout, (session / "stderr.txt").open("w") as stderr:
            process = subprocess.Popen(command, cwd=bundle, env=env, stdout=stdout, stderr=stderr)
            try:
                report["exchanges"] = asyncio.run(
                    asyncio.wait_for(
                        exercise_connector(
                            api, process, args.timeout, code_reference, report, inventory_reference,
                            identity["rom_sha256"] if args.experimental_potion_1_to_2 else None,
                            event_reference,
                            strict_ready,
                            objects if args.scan_save_objects else None,
                            bootstrap_references,
                        ),
                        timeout=args.timeout,
                    )
                )
                if args.experimental_bootstrap:
                    report["bootstrap"]["marker_observed_after_reconnect"] = True
                    report["bootstrap"]["native_execution_corroborated"] = args.experimental_bootstrap != "allocation-only"
                if args.observe_native_save:
                    from oras_native_save_observation import prepare_observation
                    if report["memory_write_requests"] != 0:
                        raise ValueError("Native observation must not submit memory writes")
                    inspect_initial_objects(objects, rom, report)
                    prepare_observation(
                        post, objects, save_destination(runtime, identity["program_id"]),
                        (Path(report["backup_before_launch"]) / "00000001/main").read_bytes(),
                        report["save_objects"],
                    )
                if args.experimental_potion_1_to_2 or args.observe_native_save:
                    asyncio.run(finish_native_ui(
                        process, session / "finish-ui", post / "complete", args.timeout,
                    ))
                    report["native_save_macro_completed"] = True
            finally:
                stop_file.touch()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
                    report["forced_shutdown"] = True
        report["exit_code"] = process.returncode
        if process.returncode != 0 or report.get("forced_shutdown"):
            raise RuntimeError("EmuHawk did not shut down cleanly")
        if has_profile:
            target = save_destination(runtime, identity["program_id"])
            report["resulting_save"] = inspect_save(target.read_bytes())
            expected_inventory = (
                potion_transition(identity["rom_sha256"], code_reference, inventory_reference).expected
                if args.experimental_potion_1_to_2 else inventory_reference.expected
            )
            if inventory_bytes(target.read_bytes()) != expected_inventory:
                raise ValueError("Saved inventory does not match expected experiment result")
            report["saved_inventory_matches_expected"] = True
            if event_reference is not None:
                events_unchanged = event_bytes(target.read_bytes()) == event_reference.expected
                if not events_unchanged and not args.observe_native_save:
                    raise ValueError("Saved EventWork changed during read-only probe")
                report["saved_events_match_reference"] = events_unchanged
            if not args.experimental_potion_1_to_2 and not args.observe_native_save:
                report["save_unchanged"] = sha256(target) == report["save_sha256_before_launch"]
                if not report["save_unchanged"]:
                    raise ValueError("Save file changed during read-only probe")
            if args.observe_native_save:
                from oras_native_save_observation import inspect_observation
                report["native_observation"].update(inspect_observation(
                    post, (Path(report["backup_before_launch"]) / "00000001/main").read_bytes(),
                    target.read_bytes(),
                ))
            # A hash-bound manifest permits a subsequent cold reload with the native UI tool.
            if args.seed_save:
                (session / "profile.json").write_text(json.dumps({
                    **archive, "kind": "oras_native_save_probe", "program_id": identity["program_id"],
                    "rom_sha256": identity["rom_sha256"],
                    **({"experimental_bootstrap": args.experimental_bootstrap} if args.experimental_bootstrap else {}),
                }, indent=2) + "\n")
        if args.trace_save_manager and not args.observe_native_save:
            inspect_initial_objects(objects, rom, report)
        if args.recover_from_snapshot:
            report["scope"] = "Read-only recovery fork; verified snapshot, cold boot and AP reconnect; no delivery replay"
            report["recovery_fork"]["target_profile"] = str(session)
            report["recovery_fork"]["copy_matches_snapshot_after_boot"] = report["save_unchanged"]
            _, current_metadata, current_tree = capture_stable_archive(save_destination(runtime, identity["program_id"]))
            unchanged = (
                tree_digest(current_tree) == archive["archive_tree_sha256"]
                and hashlib.sha256(current_metadata).hexdigest() == archive["archive_metadata_sha256"]
            )
            report["recovery_fork"]["full_archive_matches_snapshot_after_boot"] = unchanged
            if not unchanged:
                raise ValueError("Recovery fork archive changed during read-only boot")
        report["status"] = "complete"
    except Exception as error:
        report["status"] = "failed"
        report["error"] = f"{type(error).__name__}: {error}"
    finally:
        if process is not None and process.poll() is None:
            process.kill()
            process.wait()
        if process is not None:
            report["exit_code"] = process.returncode
            if has_profile:
                try:
                    report["backup_after_exit"] = backup_existing_save(
                        save_destination(runtime, identity["program_id"]),
                        identity["program_id"], identity["rom_sha256"], "after-connector",
                    )
                except (OSError, ValueError) as error:
                    report.update({"status": "failed", "backup_error": str(error)})
        if archive is not None:
            if archive.get("archive_tree_sha256"):
                try:
                    report["full_archive_source_unchanged"] = source_archive_unchanged(archive)
                except (OSError, ValueError):
                    report["full_archive_source_unchanged"] = False
                if not report["full_archive_source_unchanged"]:
                    report.update({"status": "failed", "error": "Full source archive changed during experiment"})
            for prefix in ("seed", "archive_metadata"):
                if not archive.get(f"{prefix}_source"):
                    continue
                try:
                    unchanged = sha256(Path(archive[f"{prefix}_source"])) == archive[f"{prefix}_sha256"]
                except OSError:
                    unchanged = False
                report[f"{prefix}_source_unchanged"] = unchanged
                if not unchanged:
                    report["status"] = "failed"
                    report["error"] = "Source archive changed during the experiment"
        (session / "result.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return 0 if report["status"] == "complete" else 1


if __name__ == "__main__":
    raise SystemExit(main())

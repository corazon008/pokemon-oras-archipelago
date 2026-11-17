"""Test upstream TCP metadata; optionally compare a ROM-derived text prefix in RAM."""

from __future__ import annotations

import argparse
import asyncio
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
    PROJECT_ROOT, emulator_environment, prepare_runtime, sha256,
)
from rom_identity import CodeReference, inspect_rom, sha256_file


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
                             audit: dict | None = None) -> list[dict]:
    exchanges = []
    context = api.BizHawkContext()
    deadline = asyncio.get_running_loop().time() + timeout
    try:
        for attempt in range(2):
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
                    raise ValueError("Runtime code prefix does not match the selected ROM")
                exchange["code_read"] = {
                    "domain": "System Bus",
                    "address": f"0x{code_reference.address:08X}",
                    "length": len(payloads[0]),
                    "sha256": hashlib.sha256(payloads[0]).hexdigest(),
                    "matches_rom_prefix": True,
                }
            exchanges.append(exchange)
            writer = context.streams[1]
            api.disconnect(context)
            await writer.wait_closed()
    finally:
        api.disconnect(context)
    return exchanges


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bizhawk", type=Path, default=PROJECT_ROOT / "bin/BizHawk-2.11.1-linux-x64")
    parser.add_argument("--rom", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=60)
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
    if not (source / "EmuHawk.exe").is_file() or not rom.is_file():
        parser.error("BizHawk executable and ROM must exist")
    mono = shutil.which("mono")
    if not mono:
        parser.error("Mono is not on PATH")
    require_free_ports()
    temporary_root = Path("/tmp/opencode")
    temporary_root.mkdir(parents=True, exist_ok=True)
    session = Path(tempfile.mkdtemp(prefix="oras-connector-", dir=temporary_root))
    print(f"Isolated connector session: {session}", flush=True)
    report = {
        "schema_version": 1,
        "status": "preparing",
        "scope": "TCP metadata and reconnection only",
        "memory_read_requests": 0,
        "memory_write_requests": 0,
        "existing_3ds_profile_copied": False,
        "rom": str(rom),
    }
    process = None
    try:
        code_reference = None
        if args.read_code:
            identity, code_reference = inspect_rom(rom)
            if identity["edition_from_program_id"] is None or code_reference is None:
                raise ValueError("ROM has no supported ORAS text-prefix reference")
            identity["rom_sha256"] = sha256_file(rom)
            report["rom_identity"] = identity
            report["scope"] = "TCP metadata and ROM-derived code-prefix reads only"
        bundle = session / "connector"
        lock = fetch_bundle(bundle)
        api = load_upstream_api(bundle, lock)
        runtime = prepare_runtime(source, session)
        wrapper = bundle / "probe.lua"
        shutil.copyfile(PROJECT_ROOT / "tools/bizhawk_connector_probe.lua", wrapper)
        stop_file = session / "stop"
        env = emulator_environment(runtime, automated=True)
        env.update({
            "ORAS_CONNECTOR_DIRECTORY": str(bundle),
            "ORAS_CONNECTOR_STOP": str(stop_file),
            "ORAS_CONNECTOR_TIMEOUT": str(math.ceil(args.timeout) + 10),
        })
        command = [
            mono, str(runtime / "EmuHawk.exe"),
            f"--config={runtime / 'config.ini'}", f"--lua={wrapper}", str(rom),
        ]
        report.update({
            "ap_commit": lock["commit"],
            "emuhawk_sha256": sha256(source / "EmuHawk.exe"),
            "encore_sha256": sha256(source / "dll/libencore.so"),
            "bundle_verified": True,
        })
        with (session / "stdout.txt").open("w") as stdout, (session / "stderr.txt").open("w") as stderr:
            process = subprocess.Popen(command, cwd=bundle, env=env, stdout=stdout, stderr=stderr)
            try:
                report["exchanges"] = asyncio.run(
                    exercise_connector(api, process, args.timeout, code_reference, report)
                )
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
        report["status"] = "complete"
    except Exception as error:
        report["status"] = "failed"
        report["error"] = f"{type(error).__name__}: {error}"
    finally:
        if process is not None and process.poll() is None:
            process.kill()
            process.wait()
        (session / "result.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return 0 if report["status"] == "complete" else 1


if __name__ == "__main__":
    raise SystemExit(main())

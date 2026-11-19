"""Deterministic research failpoint on the owned child, not a power-loss test."""

import asyncio
import signal
import struct

from oras_sidecar_probe import FILE_SIZE, WRITE_CALLERS, WRITE_STATUS_SIZE


def barrier_caller(status):
    if len(status) != WRITE_STATUS_SIZE:
        raise ValueError("Short inter-file barrier observation")
    if not any(status):
        return None
    attempt, lr, result, state = struct.unpack("<4I", status)
    if (attempt, result, state) != (1, 0xFFFFFFFF, 2) or lr - 4 not in WRITE_CALLERS:
        raise ValueError("Unexpected inter-file barrier status")
    return lr


async def interrupt_at_barrier(api, context, process, plan, expected, signal_path, report):
    """Caller bounds this coroutine and has already validated the connector/ROM."""
    if "interrupt_barrier" not in plan or process.poll() is not None:
        raise ValueError("Missing dedicated inter-file probe or running child")
    audit = report["interruption"] = {"kill_requested": False, "polls": 0}
    status_range = (plan["write_status"], WRITE_STATUS_SIZE, "System Bus")

    async def read(*ranges):
        report["memory_read_requests"] += len(ranges)
        values = await api.read(context, list(ranges))
        if len(values) != len(ranges) or any(len(v) != r[1] for v, r in zip(values, ranges)):
            raise ValueError("Incomplete inter-file probe read")
        return values

    if any((await read(status_range))[0]):
        raise ValueError("Inter-file probe not idle before SAVE")
    signal_path.touch(exist_ok=False)
    while process.poll() is None:
        status, = await read(status_range)
        audit["polls"] += 1
        lr = barrier_caller(status)
        if lr is not None:
            repeated, payload = await read(status_range, (plan["buffer"], FILE_SIZE, "System Bus"))
            if repeated != status or payload != expected:
                raise ValueError("Unstable barrier or changed sidecar RAM; cannot confirm interruption")
            audit.update({"barrier_hex": status.hex(), "caller_return": lr,
                          "sidecar_ram_unchanged": True, "kill_requested": True})
            process.kill()  # Popen for this freshly spawned profile only; no PID lookup.
            if process.wait(timeout=10) != -signal.SIGKILL:
                raise RuntimeError("Expected tool-owned emulator child to exit from SIGKILL")
            audit["sigkill_confirmed"] = True
            return
        if (signal_path.parent / "native-save/complete").exists():
            raise ValueError("SAVE input plan ended without an observed inter-file barrier")
        await asyncio.sleep(0.05)
    raise RuntimeError("Emulator exited before inter-file barrier")

"""Read-only AP transport probes for build-specific OR event observations."""

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path

from oras_events import EVENT_LENGTH, event_bytes, event_flag, event_work


OR_ROM_SHA256 = "d76faafacd746fdcc5ec04a60b8b82ceb9678c3ad937b374234a506c50c417e4"
BOOT_GAMEPLAY_STEPS = "1800:-,2:A,600:-,2:A,600:-,2:A,600:-"


@dataclass(frozen=True)
class EventReference:
    address: int
    expected: bytes
    rom_hash: str


def clock_scene_observation(block: bytes, rom_hash: str) -> dict:
    if rom_hash != OR_ROM_SHA256:
        raise ValueError("Clock-scene candidate is only observed on the verified OR build")
    value = event_work(block, 130)
    # Only observed values: do not extrapolate >= 3 or treat an unknown state as false.
    completed = {2: False, 3: True, 4: True}.get(value)
    return {
        "candidate": "initial_clock_and_upstairs_mother_sequence",
        "work_index_decimal": 130, "value": value,
        "completed_in_observed_states": completed,
        "state": "unknown" if completed is None else "observed_complete" if completed else "observed_incomplete",
        "production_location_approved": False,
    }


def pokedex_observation(block: bytes, rom_hash: str) -> dict:
    """Flag 2722: native false-to-true transition and cold reload verified on this OR build.

    This observation is not an approved production location or a server check.
    """
    if rom_hash != OR_ROM_SHA256:
        raise ValueError("Pokedex candidate requires the verified OR build")
    return {
        "candidate": "pokedex_obtained",
        "flag_index_decimal": 2722,
        "value": event_flag(block, 2722),
        "production_location_approved": False,
    }


def load_event_reference(rom_hash: str, program_id: str, save: Path) -> EventReference:
    profiles = json.loads(Path(__file__).with_name("oras_memory_candidates.json").read_text())["profiles"]
    profile = profiles.get(rom_hash)
    if (rom_hash != OR_ROM_SHA256 or not profile or profile["program_id"] != program_id
            or profile["domain"] != "System Bus" or profile["write_allowed"] is not False):
        raise ValueError("No read-only event profile for this exact ROM")
    candidate = profile.get("event_work")
    if (not candidate or candidate["length"] != EVENT_LENGTH
            or candidate.get("write_allowed") is not False or candidate["block_id"] != 19):
        raise ValueError("No documented read-only EventWork candidate")
    expected = event_bytes(save.read_bytes())
    if not any(expected):
        raise ValueError("All-zero event references are not accepted")
    return EventReference(int(candidate["address"], 16), expected, rom_hash)


async def read_events(api, context, reference: EventReference, audit: dict) -> dict:
    audit["memory_read_requests"] += 1
    payloads = await api.read(context, [(reference.address, EVENT_LENGTH, "System Bus")])
    if len(payloads) != 1 or payloads[0] != reference.expected:
        raise ValueError("Runtime events do not match the CRC-validated full EventWork reference")
    return {
        "domain": "System Bus", "address": f"0x{reference.address:08X}", "length": EVENT_LENGTH,
        "sha256": hashlib.sha256(payloads[0]).hexdigest(), "matches_validated_save": True,
        "clock_scene": clock_scene_observation(payloads[0], reference.rom_hash),
        "pokedex": pokedex_observation(payloads[0], reference.rom_hash),
    }

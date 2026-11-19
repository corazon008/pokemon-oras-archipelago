"""Build-restricted inventory references for experimental upstream AP transport probes."""

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path

from oras_save import inventory_bytes, inventory_entries
from rom_identity import CodeReference


BOOT_MEDICINE_STEPS = "1800:-,2:A,600:-,2:A,600:-,2:A,600:-,2:X,60:-,2:A,120:-,2:Right,60:-"
# Only the observed OR build and existing slot are eligible, never arbitrary writes.
EXPERIMENT_ROM_SHA256 = "d76faafacd746fdcc5ec04a60b8b82ceb9678c3ad937b374234a506c50c417e4"
EXPERIMENT_CODE_SHA256 = "92a5b3013f2d27923be3975e2046cc5e52b110822436fd5c9a9077cfb8061659"
NATIVE_SAVE_STEPS = "2:B,300:-,2:Down,20:-,2:A,60:-,2:A,600:-,2:A,120:-"


@dataclass(frozen=True)
class InventoryReference:
    address: int
    expected: bytes
    domain: str = "System Bus"
    origin: str = "crc_validated_save"


def load_inventory_reference(rom_hash: str, program_id: str, save: Path) -> InventoryReference:
    profiles = json.loads(Path(__file__).with_name("oras_memory_candidates.json").read_text())["profiles"]
    candidate = profiles.get(rom_hash)
    if candidate is None or candidate["program_id"] != program_id:
        raise ValueError("No documented inventory candidate for this exact ROM")
    if candidate["domain"] != "System Bus" or candidate["write_allowed"] is not False:
        raise ValueError("Expected a read-only System Bus research profile")
    expected = inventory_bytes(save.read_bytes())
    if len(expected) != candidate["inventory_length"] or not any(expected):
        raise ValueError("Inventory reference must have documented length and nonzero contents")
    return InventoryReference(int(candidate["inventory_address"], 16), expected)


async def read_inventory(api, context, reference: InventoryReference, audit: dict) -> dict:
    audit["memory_read_requests"] += 1
    payloads = await api.read(context, [
        (reference.address, len(reference.expected), reference.domain),
    ])
    if len(payloads) != 1 or payloads[0] != reference.expected:
        raise ValueError("Runtime inventory does not match the expected full inventory reference")
    return {
        "domain": reference.domain, "address": f"0x{reference.address:08X}",
        "length": len(reference.expected), "sha256": hashlib.sha256(payloads[0]).hexdigest(),
        "matches_reference": True, "reference_origin": reference.origin,
        "matches_validated_save": reference.origin == "crc_validated_save",
        "entries": inventory_entries(payloads[0]),
    }


def potion_transition(rom_hash: str, code: CodeReference, reference: InventoryReference) -> InventoryReference:
    """Permit exactly the independently observed slot's quantity 1 -> 2."""
    if (rom_hash != EXPERIMENT_ROM_SHA256 or code.address != 0x00100000
            or len(code.expected) != 64 or hashlib.sha256(code.expected).hexdigest() != EXPERIMENT_CODE_SHA256):
        raise ValueError("Potion experiment requires the verified OR ROM and code reference")
    if (reference.address != 0x08C6AC80 or reference.domain != "System Bus"
            or reference.origin != "crc_validated_save" or len(reference.expected) != 0xB90
            or reference.expected[0x970:0x974] != b"\x11\x00\x01\x00"):
        raise ValueError("Potion experiment requires verified inventory and slot 0 Potion x1")
    potions = [entry for entry in inventory_entries(reference.expected) if entry["item_id"] == 17]
    if len(potions) != 1:
        raise ValueError("Ambiguous Potion slots")
    after = bytearray(reference.expected)
    after[0x972:0x974] = b"\x02\x00"
    return InventoryReference(reference.address, bytes(after), reference.domain, "experimental_two_byte_transition")


async def add_experimental_potion(api, context, rom_hash: str, code: CodeReference,
                                  reference: InventoryReference, audit: dict, *,
                                  runtime_code: CodeReference | None = None,
                                  extra_guards=()) -> InventoryReference:
    after = potion_transition(rom_hash, code, reference)
    runtime_code = runtime_code or code
    if runtime_code.address != code.address or len(runtime_code.expected) != len(code.expected):
        raise ValueError("Potion experiment requires a runtime guard at the verified code prefix")
    guards = [
        (runtime_code.address, runtime_code.expected, "System Bus"),
        (reference.address, reference.expected, reference.domain),
        *extra_guards,
    ]
    audit["memory_guard_requests"] = audit.get("memory_guard_requests", 0) + len(guards)
    audit["memory_write_requests"] += 1  # Count submission even if rejected or response lost.
    audit["potion_experiment"] = {
        "status": "submitted_outcome_unknown", "address": "0x08C6B5F2",
        "length": 2, "expected_quantity": 1, "requested_quantity": 2,
        "automatic_retry": False,
    }
    accepted = await api.guarded_write(
        context, [(0x08C6B5F2, b"\x02\x00", "System Bus")], guards,
    )
    audit["potion_experiment"]["status"] = "acknowledged" if accepted else "guard_rejected"
    if not accepted:
        raise ValueError("Potion write guard rejected; no retry")
    audit["potion_experiment"]["readback"] = await read_inventory(api, context, after, audit)
    audit["potion_experiment"]["status"] = "full_inventory_readback_verified"
    return after

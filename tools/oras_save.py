"""Read-only ORAS save validation and inventory inspection.

Source: kwsch/PKHeX, 6c9583883c7551ac74a4b74180cead249d4277b8.
SaveBlockAccessor6AO.cs, BlockInfo3DS.cs, Checksums.cs, PlayerBag6AO.cs.
File offsets below are not runtime RAM addresses.
"""

import argparse
import binascii
import hashlib
import json
from pathlib import Path
import struct


SAVE_SIZE = 0x76000
METADATA_OFFSET = SAVE_SIZE - 0x200
BLOCKS = (
    (0x00000, 0x002C8), (0x00400, 0x00B90), (0x01000, 0x0002C),
    (0x01200, 0x00038), (0x01400, 0x00150), (0x01600, 0x00004),
    (0x01800, 0x00008), (0x01A00, 0x001C0), (0x01C00, 0x000BE),
    (0x01E00, 0x00024), (0x02000, 0x02100), (0x04200, 0x00130),
    (0x04400, 0x00440), (0x04A00, 0x00574), (0x05000, 0x04E28),
    (0x0A000, 0x04E28), (0x0F000, 0x04E28), (0x14000, 0x00170),
    (0x14200, 0x0061C), (0x14A00, 0x00504), (0x15000, 0x011CC),
    (0x16200, 0x00644), (0x16A00, 0x00104), (0x16C00, 0x00004),
    (0x16E00, 0x00420), (0x17400, 0x00064), (0x17600, 0x003F0),
    (0x17A00, 0x0070C), (0x18200, 0x00180), (0x18400, 0x00004),
    (0x18600, 0x0000C), (0x18800, 0x00048), (0x18A00, 0x00054),
    (0x18C00, 0x00644), (0x19400, 0x005C8), (0x19A00, 0x002F8),
    (0x19E00, 0x01B40), (0x1BA00, 0x001F4), (0x1BC00, 0x003E0),
    (0x1C000, 0x00216), (0x1C400, 0x00640), (0x1CC00, 0x01A90),
    (0x1E800, 0x00400), (0x1EC00, 0x00618), (0x1F400, 0x0025C),
    (0x1F800, 0x00834), (0x20200, 0x00318), (0x20600, 0x007D0),
    (0x20E00, 0x00C48), (0x21C00, 0x00078), (0x21E00, 0x00200),
    (0x22000, 0x00C84), (0x22E00, 0x00628), (0x23600, 0x00400),
    (0x23A00, 0x07AD0), (0x2B600, 0x078B0), (0x33000, 0x34AD0),
    (0x67C00, 0x0E058),
)
POUCHES = (
    ("items", 0x000, 0x640),
    ("key_items", 0x640, 0x7C0),
    ("tm_hm", 0x7C0, 0x970),
    ("medicine", 0x970, 0xA70),
    ("berries", 0xA70, 0xB90),
)


def validate_save(data: bytes) -> None:
    if len(data) != SAVE_SIZE:
        raise ValueError("Expected a 0x76000-byte ORAS decrypted main save")
    if struct.unpack_from("<I", data, METADATA_OFFSET + 0x10)[0] != 0x42454546:
        raise ValueError("Save lacks the ORAS footer marker")
    for block_id, (offset, length) in enumerate(BLOCKS):
        stored_length, stored_id, stored_crc = struct.unpack_from(
            "<IHH", data, METADATA_OFFSET + 0x14 + block_id * 8
        )
        if (stored_length, stored_id) != (length, block_id):
            raise ValueError(f"Invalid ORAS block descriptor {block_id}")
        if binascii.crc_hqx(data[offset:offset + length], 0xFFFF) != stored_crc:
            raise ValueError(f"ORAS block checksum mismatch: {block_id}")


def inventory_bytes(data: bytes) -> bytes:
    validate_save(data)
    offset, length = BLOCKS[1]
    return data[offset:offset + length]


def inventory_entries(inventory: bytes) -> list[dict]:
    if len(inventory) != BLOCKS[1][1]:
        raise ValueError("Unexpected ORAS inventory block length")
    entries = []
    for pouch, start, end in POUCHES:
        for offset in range(start, end, 4):
            item_id, quantity = struct.unpack_from("<HH", inventory, offset)
            if item_id:
                entries.append({
                    "pouch": pouch, "slot": (offset - start) // 4,
                    "item_id": item_id, "quantity": quantity,
                })
    return entries


def inspect_save(data: bytes) -> dict:
    inventory = inventory_bytes(data)
    return {
        "schema_version": 1,
        "size_bytes": len(data),
        "save_sha256": hashlib.sha256(data).hexdigest(),
        "validated_block_count": len(BLOCKS),
        "inventory_sha256": hashlib.sha256(inventory).hexdigest(),
        "inventory": inventory_entries(inventory),
        "money": struct.unpack_from("<I", data, BLOCKS[11][0] + 8)[0],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("save", type=Path)
    args = parser.parse_args()
    try:
        result = inspect_save(args.save.read_bytes())
    except (OSError, ValueError) as error:
        parser.exit(1, f"Save inspection failed: {error}\n")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

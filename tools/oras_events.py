"""Read-only EventWork6 decoding; PKHeX 6c9583883c7551ac74a4b74180cead249d4277b8.

SaveBlockAccessor6AO block 19; EventWork6 counts/bit layout, not RAM addresses.
Unknown block tail is compared as bytes, never assigned guessed semantics.
"""

import argparse
import hashlib
import json
from pathlib import Path
import struct

from oras_save import BLOCKS, validate_save


EVENT_BLOCK_ID = 19
EVENT_LENGTH = BLOCKS[EVENT_BLOCK_ID][1]
WORK_COUNT = 0x178
FLAG_COUNT = 0xD00
FLAG_OFFSET = WORK_COUNT * 2
TAIL_OFFSET = FLAG_OFFSET + FLAG_COUNT // 8


def event_bytes(save: bytes) -> bytes:
    validate_save(save)
    offset, length = BLOCKS[EVENT_BLOCK_ID]
    return save[offset:offset + length]


def validate_event_block(block: bytes) -> None:
    if len(block) != EVENT_LENGTH:
        raise ValueError("Unexpected ORAS EventWork block length")


def event_flag(block: bytes, index: int) -> bool:
    validate_event_block(block)
    if not 0 <= index < FLAG_COUNT:
        raise ValueError("Event flag index outside documented range")
    return bool(block[FLAG_OFFSET + index // 8] & (1 << (index % 8)))


def event_work(block: bytes, index: int) -> int:
    validate_event_block(block)
    if not 0 <= index < WORK_COUNT:
        raise ValueError("Event work index outside documented range")
    return struct.unpack_from("<H", block, index * 2)[0]


def compare_events(before: bytes, after: bytes) -> dict:
    validate_event_block(before)
    validate_event_block(after)
    return {
        "matches_reference": before == after,
        "sha256": hashlib.sha256(after).hexdigest(),
        "work_changes": [
            {"index": i, "before": event_work(before, i), "after": event_work(after, i)}
            for i in range(WORK_COUNT) if event_work(before, i) != event_work(after, i)
        ],
        "flag_changes": [
            {"index": i, "before": event_flag(before, i), "after": event_flag(after, i)}
            for i in range(FLAG_COUNT) if event_flag(before, i) != event_flag(after, i)
        ],
        "unknown_tail_changed_offsets": [
            f"0x{i:03X}" for i in range(TAIL_OFFSET, EVENT_LENGTH) if before[i] != after[i]
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("before", type=Path, help="CRC-validated decrypted ORAS main")
    parser.add_argument("after", type=Path, help="CRC-validated decrypted ORAS main")
    args = parser.parse_args()
    try:
        result = compare_events(event_bytes(args.before.read_bytes()), event_bytes(args.after.read_bytes()))
    except (OSError, ValueError) as error:
        parser.exit(1, f"Event comparison failed: {error}\n")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

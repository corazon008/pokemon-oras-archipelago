"""Read-only executable analysis. Decompressed bytes stay in memory.

BLZ layout and segment mapping cross-checked with Encore 49a332221e1c9dffcc2c52f85a1765b1951c222f:
ncch_container.cpp LZSS_Decompress; loader/ncch.cpp LoadExec.
No patch, decryption or game-memory write is implemented.
"""

import argparse
import hashlib
from pathlib import Path
import struct

from oras_save import BLOCKS
from rom_identity import inspect_rom, sha256_file


MAX_IMAGE = 64 * 1024 * 1024


def decompress_blz(data: bytes) -> bytes:
    if len(data) < 8:
        raise ValueError("Missing BLZ footer")
    packed, extra = struct.unpack_from("<II", data, len(data) - 8)
    header, suffix = packed >> 24, packed & 0xFFFFFF
    if not 8 <= header <= suffix <= len(data):
        raise ValueError("Invalid BLZ footer lengths")
    size = len(data) + extra
    if size > MAX_IMAGE:
        raise ValueError("BLZ output exceeds research bound")
    prefix = len(data) - suffix
    cursor, destination = len(data) - header, size
    output = bytearray(data)
    output.extend(bytes(extra))
    while cursor > prefix:
        cursor -= 1
        control = data[cursor]
        for bit in range(7, -1, -1):
            if cursor == prefix:
                break
            if control & (1 << bit):
                if cursor - 2 < prefix:
                    raise ValueError("Truncated BLZ back-reference")
                cursor -= 2
                token = struct.unpack_from("<H", data, cursor)[0]
                length, distance = (token >> 12) + 3, (token & 0xFFF) + 3
                if destination - length < prefix:
                    raise ValueError("BLZ back-reference overwrites prefix")
                for _ in range(length):
                    destination -= 1
                    source = destination + distance
                    if source >= size:
                        raise ValueError("BLZ reference outside reconstructed data")
                    output[destination] = output[source]
            else:
                if destination <= prefix:
                    raise ValueError("BLZ literal overwrites prefix")
                cursor -= 1
                destination -= 1
                output[destination] = data[cursor]
    if destination != prefix:
        raise ValueError("BLZ stream did not reconstruct the entire suffix")
    return bytes(output)


def image_address(info: dict, offset: int, length: int = 1) -> int | None:
    if offset < 0 or length < 1:
        raise ValueError("Invalid executable range")
    for segment in info["code_segments"]:
        start = segment["image_offset"]
        if start <= offset and offset + length <= start + segment["size"]:
            return segment["address"] + offset - start
    return None


def address_offset(info: dict, address: int, length: int = 1) -> int | None:
    if address < 0 or length < 1:
        raise ValueError("Invalid executable range")
    for segment in info["code_segments"]:
        start = segment["address"]
        if start <= address and address + length <= start + segment["size"]:
            return segment["image_offset"] + address - start
    return None


def arm_constant_return(info: dict, image: bytes, offset: int) -> tuple[int, int] | None:
    """Recognize only 1..3 unconditional A32 constant operations ending in BX LR/MOV PC,LR.

    This is a bounded syntactic recognizer, not a function-boundary or reachability proof.
    """
    value = None
    text = next(segment for segment in info["code_segments"] if segment["name"] == "text")
    text_end = text["image_offset"] + text["size"]
    if offset < text["image_offset"] or offset % 4 or offset + 4 > min(text_end, len(image)):
        return None
    for step in range(4):
        at = offset + step * 4
        if at + 4 > min(text_end, len(image)):
            return None
        word = struct.unpack_from("<I", image, at)[0]
        if word in (0xE12FFF1E, 0xE1A0F00E):
            return (value, step + 1) if value is not None else None
        if step == 3 or word >> 28 != 0xE:
            return None
        if word & 0x0F7FF000 == 0x051F0000:  # A32 LDR r0,[pc,+/-imm12], no writeback.
            pc = image_address(info, at, 4)
            if pc is None:
                return None
            literal = pc + 8 + ((word & 0xFFF) if word & 0x800000 else -(word & 0xFFF))
            mapped = address_offset(info, literal, 4)
            if mapped is None or literal % 4 or mapped + 4 > len(image):
                return None
            value = struct.unpack_from("<I", image, mapped)[0]
        elif word & 0x0E10F000 == 0x02000000:  # Immediate data processing, S=0, Rd=r0.
            immediate, rotate = word & 0xFF, ((word >> 8) & 15) * 2
            immediate = ((immediate >> rotate) | (immediate << ((32 - rotate) % 32))) & 0xFFFFFFFF
            opcode, source = (word >> 21) & 15, (word >> 16) & 15
            if opcode == 13 and source == 0:
                value = immediate
            elif value is not None and source == 0 and opcode in (2, 4, 12, 14):
                value = {
                    2: value - immediate, 4: value + immediate,
                    12: value | immediate, 14: value & ~immediate,
                }[opcode] & 0xFFFFFFFF
            else:
                return None
        else:
            return None
    return None


def find_provider_tables(info: dict, image: bytes, sizes: tuple[int, ...]) -> tuple[dict, list[dict]]:
    if len(sizes) < 4 or any(not 0 < size <= MAX_IMAGE for size in sizes):
        raise ValueError("Need at least four bounded block lengths")
    text = next(segment for segment in info["code_segments"] if segment["name"] == "text")
    providers = {size: set() for size in sizes}
    for offset in range(text["image_offset"], text["image_offset"] + text["size"] - 3, 4):
        result = arm_constant_return(info, image, offset)
        if result and result[0] in providers:
            providers[result[0]].add(image_address(info, offset))
    candidates = []
    for address in sorted(providers[sizes[0]]):
        needle = struct.pack("<I", address)
        cursor = 0
        while True:
            at = image.find(needle, cursor)
            if at < 0:
                break
            cursor = at + 1
            if at % 4:
                continue
            for stride in (4, 8, 12, 16, 20, 24, 32):
                length = (len(sizes) - 1) * stride + 4
                if at + length > len(image) or image_address(info, at, length) is None:
                    continue
                matches = [
                    i for i, size in enumerate(sizes)
                    if struct.unpack_from("<I", image, at + i * stride)[0] in providers[size]
                ]
                if len(matches) >= max(4, len(sizes) - 1):
                    candidates.append({
                        "image_offset": at, "virtual_address": image_address(info, at, length),
                        "stride": stride, "count": len(sizes),
                        "exact_provider_match": len(matches) == len(sizes),
                        "unrecognized_block_ids": [i for i in range(len(sizes)) if i not in matches],
                        "provider_addresses": [
                            struct.unpack_from("<I", image, at + i * stride)[0] for i in range(len(sizes))
                        ],
                    })
                    if len(candidates) > 64:
                        raise ValueError("Too many provider-table candidates")
    return providers, candidates


def load_code(path: Path) -> tuple[dict, bytes]:
    info, prefix = inspect_rom(path)
    if not info["no_crypto_flag"] or "code_file_offset_bytes" not in info:
        raise ValueError("Executable must be unencrypted and structurally identified")
    if info["code_stored_size_bytes"] > MAX_IMAGE:
        raise ValueError("Stored executable exceeds research bound")
    with path.open("rb") as source:
        source.seek(info["code_file_offset_bytes"])
        stored = source.read(info["code_stored_size_bytes"])
    if len(stored) != info["code_stored_size_bytes"]:
        raise ValueError("Truncated executable")
    image = decompress_blz(stored) if info["code_compressed"] else stored
    if len(image) > MAX_IMAGE:
        raise ValueError("Executable exceeds research bound")
    ranges = []
    for segment in info["code_segments"]:
        address, pages, length = segment["address"], segment["pages"], segment["size"]
        if (address % 0x1000 or length > pages * 0x1000
                or address + pages * 0x1000 > 1 << 32
                or segment["image_offset"] + length > len(image)):
            raise ValueError("Invalid executable segment mapping")
        if length:
            if any(address < end and start < address + pages * 0x1000 for start, end in ranges):
                raise ValueError("Overlapping executable segments")
            ranges.append((address, address + pages * 0x1000))
    if prefix is not None and image[:len(prefix.expected)] != prefix.expected:
        raise ValueError("Expanded executable does not match ROM-derived prefix")
    return info, image


def find_size_tables(image: bytes, sizes: tuple[int, ...], strides=(4, 8, 12, 16, 20, 24, 32)) -> list[dict]:
    """Find complete arrays only; an isolated length is not a save-table identification."""
    if len(sizes) < 4 or any(not 0 < size <= MAX_IMAGE for size in sizes):
        raise ValueError("Need at least four bounded block lengths")
    if not strides or any(stride < 4 or stride % 4 for stride in strides):
        raise ValueError("Stride must be word-aligned")
    anchor = struct.pack("<I", sizes[0])
    found = []
    cursor = 0
    while True:
        offset = image.find(anchor, cursor)
        if offset < 0:
            break
        cursor = offset + 1
        if offset % 4:
            continue
        for stride in strides:
            end = offset + (len(sizes) - 1) * stride + 4
            if end <= len(image) and all(
                struct.unpack_from("<I", image, offset + i * stride)[0] == size
                for i, size in enumerate(sizes)
            ):
                found.append({"image_offset": offset, "stride": stride, "count": len(sizes)})
                if len(found) > 64:
                    raise ValueError("Too many size-table candidates")
    return found


def main() -> int:
    import json
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("rom", type=Path)
    args = parser.parse_args()
    try:
        info, image = load_code(args.rom)
        if info["edition_from_program_id"] is None:
            raise ValueError("ORAS block layout requires an identified ORAS title")
        results = find_size_tables(image, tuple(length for _, length in BLOCKS))
        providers, callbacks = find_provider_tables(info, image, tuple(length for _, length in BLOCKS))
        report = {
            "rom_sha256": sha256_file(args.rom), "program_id": info["program_id"],
            "code_stored_size": info["code_stored_size_bytes"], "code_expanded_size": len(image),
            "expanded_code_sha256": hashlib.sha256(image).hexdigest(),
            "segments": info["code_segments"],
            "size_table_candidates": [
                {**row, "virtual_address": image_address(info, row["image_offset"],
                  (row["count"] - 1) * row["stride"] + 4)}
                for row in results
            ],
            "constant_provider_counts": {str(size): len(addresses) for size, addresses in providers.items()},
            "provider_table_candidates": callbacks,
            "block_47_storage_approved": False,
            "warning": "Static candidates are not proof of native ownership or runtime mapping.",
        }
    except (OSError, ValueError) as error:
        parser.exit(1, f"Executable research failed: {error}\n")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

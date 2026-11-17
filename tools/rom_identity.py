"""Inspect decrypted NCSD/NCCH metadata without extracting or changing game files.

Layout reference: CasualPokePlayer/encore at
49a332221e1c9dffcc2c52f85a1765b1951c222f:
src/core/file_sys/ncch_container.h and ncch_container.cpp.
Text mapping reference: src/core/loader/ncch.cpp, LoadExec().
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
import struct


MEDIA_UNIT = 0x200
PREFIX_SIZE = 64
ORAS_TITLES = {
    0x000400000011C400: "Pokemon Omega Ruby",
    0x000400000011C500: "Pokemon Alpha Sapphire",
}


@dataclass(frozen=True)
class CodeReference:
    address: int
    expected: bytes = field(repr=False)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def inspect_rom(path: Path) -> tuple[dict, CodeReference | None]:
    """Return public metadata and, only when safe to derive, a text-prefix reference."""
    size = path.stat().st_size
    with path.open("rb") as source:
        def read_at(offset: int, length: int, end: int = size) -> bytes:
            if offset < 0 or length < 0 or offset + length > min(end, size):
                raise ValueError("ROM structure exceeds its containing region")
            source.seek(offset)
            data = source.read(length)
            if len(data) != length:
                raise ValueError("Truncated ROM structure")
            return data

        header = read_at(0, MEDIA_UNIT)
        kind = header[0x100:0x104]
        ncch_offset = 0
        containing_end = size
        if kind == b"NCSD":
            offset_units, size_units = struct.unpack_from("<II", header, 0x120)
            ncch_offset = offset_units * MEDIA_UNIT
            containing_end = ncch_offset + size_units * MEDIA_UNIT
            if ncch_offset < MEDIA_UNIT or size_units == 0 or containing_end > size:
                raise ValueError("Invalid executable NCSD partition")
            header = read_at(ncch_offset, MEDIA_UNIT, containing_end)
        elif kind != b"NCCH":
            raise ValueError("Only NCSD cartridges or raw NCCH images are supported")
        if header[0x100:0x104] != b"NCCH":
            raise ValueError("Executable partition is not NCCH")
        if header[0x18E] != 0:
            raise ValueError("Unsupported NCCH content unit exponent")
        content_end = ncch_offset + struct.unpack_from("<I", header, 0x104)[0] * MEDIA_UNIT
        if content_end < ncch_offset + MEDIA_UNIT or content_end > containing_end:
            raise ValueError("Invalid NCCH content size")
        program_id = struct.unpack_from("<Q", header, 0x118)[0]
        no_crypto = bool(header[0x18F] & 4)
        info = {
            "schema_version": 1,
            "container": kind.decode("ascii"),
            "rom_size_bytes": size,
            "program_id": f"{program_id:016X}",
            "edition_from_program_id": ORAS_TITLES.get(program_id),
            "product_code": header[0x150:0x160].rstrip(b"\0").decode("ascii"),
            "ncch_format_version": struct.unpack_from("<H", header, 0x112)[0],
            "ncch_offset_bytes": ncch_offset,
            "no_crypto_flag": no_crypto,
            "commercial_update_version": None,
            "region_verified": False,
            "code_reference_available": False,
        }
        if not no_crypto:
            info["code_reference_unavailable_reason"] = "Encrypted content is not decrypted by this tool"
            return info, None
        if struct.unpack_from("<I", header, 0x180)[0] < 0x400:
            raise ValueError("Executable ExHeader is absent or too small")
        exheader = read_at(ncch_offset + MEDIA_UNIT, 0x400, content_end)
        if struct.unpack_from("<Q", exheader, 0x200)[0] != program_id:
            raise ValueError("ExHeader program ID does not match NCCH")
        text_address, text_pages, text_size = struct.unpack_from("<III", exheader, 0x10)
        if text_size < PREFIX_SIZE or text_pages * 0x1000 < text_size:
            raise ValueError("Invalid executable text segment")
        if text_address % 0x1000 or text_address + text_pages * 0x1000 > 1 << 32:
            raise ValueError("Invalid text virtual address range")
        compressed = bool(exheader[0x0D] & 1)
        info.update({
            "exheader_remaster_version": struct.unpack_from("<H", exheader, 0x0E)[0],
            "text_virtual_address": f"0x{text_address:08X}",
            "text_size_bytes": text_size,
            "code_compressed": compressed,
        })
        exefs_units, exefs_size_units = struct.unpack_from("<II", header, 0x1A0)
        exefs_start = ncch_offset + exefs_units * MEDIA_UNIT
        exefs_end = exefs_start + exefs_size_units * MEDIA_UNIT
        if exefs_start < ncch_offset + MEDIA_UNIT + 0x400 or exefs_end > content_end:
            raise ValueError("Invalid ExeFS range")
        exefs = read_at(exefs_start, MEDIA_UNIT, exefs_end)
        sections = []
        for index in range(8):
            entry = index * 16
            if exefs[entry:entry + 8].rstrip(b"\0") == b".code":
                sections.append(struct.unpack_from("<II", exefs, entry + 8))
        if len(sections) != 1:
            raise ValueError("Expected exactly one .code section")
        section_offset, code_size = sections[0]
        code_start = exefs_start + MEDIA_UNIT + section_offset
        if code_size < PREFIX_SIZE or code_start + code_size > exefs_end:
            raise ValueError("Invalid .code section range")
        prefix_size = code_size
        if compressed:
            # The backwards LZSS decoder copies the original buffer first and
            # only rewrites its compressed suffix. No decompressor is needed
            # if our entire reference lies before that suffix.
            top_bottom, extra_size = struct.unpack(
                "<II", read_at(code_start + code_size - 8, 8, exefs_end)
            )
            footer_size = top_bottom >> 24
            suffix_size = top_bottom & 0xFFFFFF
            if not 8 <= footer_size <= suffix_size <= code_size:
                raise ValueError("Invalid backwards LZSS footer")
            prefix_size = code_size - suffix_size
            if code_size + extra_size > 64 * 1024 * 1024:
                raise ValueError("Implausible expanded code size")
        info["code_stored_size_bytes"] = code_size
        info["code_uncompressed_prefix_size_bytes"] = prefix_size
        if prefix_size < PREFIX_SIZE:
            info["code_reference_unavailable_reason"] = "Compressed suffix overlaps the reference"
            return info, None
        expected = read_at(code_start, PREFIX_SIZE, exefs_end)
        if not any(expected):
            raise ValueError("All-zero code prefix cannot prove a mapped memory read")
        info.update({
            "code_reference_available": True,
            "code_prefix_length": PREFIX_SIZE,
            "code_prefix_sha256": hashlib.sha256(expected).hexdigest(),
        })
        return info, CodeReference(text_address, expected)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("rom", type=Path)
    args = parser.parse_args()
    try:
        info, _ = inspect_rom(args.rom)
        info["rom_sha256"] = sha256_file(args.rom)
    except (OSError, ValueError, UnicodeError) as error:
        parser.exit(1, f"ROM inspection failed: {error}\n")
    print(json.dumps(info, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

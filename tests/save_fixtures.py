"""Synthetic save structure, never copied from a personal game."""

import binascii
import struct

from oras_save import BLOCKS, METADATA_OFFSET, SAVE_SIZE


def synthetic_save(fill=0):
    data = bytearray([fill]) * SAVE_SIZE
    struct.pack_into("<I", data, METADATA_OFFSET + 0x10, 0x42454546)
    for block_id, (offset, length) in enumerate(BLOCKS):
        crc = binascii.crc_hqx(data[offset:offset + length], 0xFFFF)
        struct.pack_into("<IHH", data, METADATA_OFFSET + 0x14 + block_id * 8,
                         length, block_id, crc)
    return data


def update_fixture_crcs(data):
    for block_id, (offset, length) in enumerate(BLOCKS):
        struct.pack_into("<H", data, METADATA_OFFSET + 0x14 + block_id * 8 + 6,
                         binascii.crc_hqx(data[offset:offset + length], 0xFFFF))

"""Experimental exact-OR footer comparison. Neither an AP identity nor a receipt."""

import argparse
import hashlib
import json
from pathlib import Path

from oras_archive import capture_stable_archive, tree_digest
from oras_save import METADATA_OFFSET, validate_save
from oras_save_lifecycle import require_words
from oras_sidecar_probe import FILE_SIZE, MARKER_OFFSET, NAME, SAVE_MARKER, TEST_METADATA


HEADER = b"ORAS-AP-FOOTER-V1".ljust(20, b"\0")
FOOTER_SIZE = 488
METADATA_ACCESSOR = 0x465284
METADATA_DISPATCH = 0x5E09A4


def footer_payload(main, *, saved):
    validate_save(main)
    payload = (HEADER + main[METADATA_OFFSET:METADATA_OFFSET + FOOTER_SIZE]
               + (SAVE_MARKER if saved else bytes(len(SAVE_MARKER))))
    if len(payload) != FILE_SIZE:
        raise ValueError("Experimental footer payload has wrong size")
    return payload


def inspect_footer_archive(main: Path, *, saved=True):
    files, metadata, tree = capture_stable_archive(main)
    if set(files) != {"main", NAME} or metadata != TEST_METADATA or tree["directories"]:
        raise ValueError("Unexpected footer-binding archive layout")
    expected = footer_payload(files["main"], saved=saved)
    if files[NAME] != expected:
        raise ValueError("Sidecar footer differs from main or test marker is missing")
    return expected, {
        "archive_tree_sha256": tree_digest(tree),
        "main_sha256": hashlib.sha256(files["main"]).hexdigest(),
        "payload_sha256": hashlib.sha256(expected).hexdigest(),
        "footer_sha256": hashlib.sha256(expected[len(HEADER):MARKER_OFFSET]).hexdigest(),
        "marker_saved": saved, "footer_matches": True,
        "next_delivery_index": None, "live_delivery_authorized": False,
    }


def verify_footer_getter(info, image):
    # Main manager's slot +0x0c is its block accessor. Block 58 returns
    # manager+4; the metadata object's getter is payload at object+8.
    require_words(info, image, 0x5E0B30, [METADATA_ACCESSOR])
    require_words(info, image, METADATA_ACCESSOR, [
        0xE92D4070, 0xE351003A, 0xE1A04000, 0x05900004, 0xE1A05001, 0x0A000007,
    ])
    require_words(info, image, METADATA_ACCESSOR + 56, [0xE8BD8070])
    require_words(info, image, METADATA_DISPATCH + 12, [0x4630FC, 0x4630C4])
    require_words(info, image, 0x4630FC, [0xE2800008, 0xE12FFF1E])
    require_words(info, image, 0x4630C4, [0xE3A00F7A, 0xE12FFF1E])


def emit_footer_copy(stub):
    # Caller has saved the main write result and first initialized attempt
    # telemetry. If provenance fails, return without touching the sidecar.
    stub.literal(0, "status_address")
    stub.emit(0xE5900004, 0xE5901000)         # main manager and vptr
    stub.literal(2, "main_dispatch")
    stub.emit(0xE1510002)
    stub.branch("write_exit", condition=1)
    stub.emit(0xE3A0103A)                     # index 58
    stub.branch(METADATA_ACCESSOR, link=True)
    stub.emit(0xE3100003)                     # word-aligned
    stub.branch("write_exit", condition=1)
    stub.emit(0xE3500302)                     # >= 0x08000000
    stub.branch("write_exit", condition=3)   # LO
    stub.literal(1, "last_metadata_object")
    stub.emit(0xE1500001)
    stub.branch("write_exit", condition=8)   # HI
    stub.emit(0xE5901000)
    stub.literal(2, "metadata_dispatch")
    stub.emit(0xE1510002)
    stub.branch("write_exit", condition=1)
    stub.emit(0xE2800008)                    # getter verified statically
    stub.literal(1, "footer_destination")
    stub.emit(0xE3A0207A)                    # 122 words == 488 bytes
    stub.label("copy_footer")
    stub.emit(0xE4903004, 0xE4813004, 0xE2522001)
    stub.branch("copy_footer", condition=1)


def footer_literals(buffer):
    return [
        ("footer_destination", buffer + len(HEADER)), ("main_dispatch", 0x5E0B24),
        ("metadata_dispatch", METADATA_DISPATCH), ("last_metadata_object", 0x10000000 - 8 - FOOTER_SIZE),
    ]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive_main", type=Path)
    args = parser.parse_args()
    try:
        _, result = inspect_footer_archive(args.archive_main)
    except (OSError, ValueError) as error:
        parser.exit(1, f"Experimental footer pair refused: {error}\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

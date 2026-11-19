"""Exact-build, opt-in Encore bootstrap experiment. No persistent AP storage.

Reserve executable tail through an ExHeader size change and allocate a NEW BSS
page beyond the original page-rounded allocation. Never borrow save block 47,
original BSS padding, a heap address or a zero-filled save region.
Only a small generated IPS and private ExHeader are written, not code.bin.
"""

import hashlib
from pathlib import Path
import struct

from oras_code_research import load_code
from oras_save_objects import OR_HASH
from rom_identity import CodeReference, sha256_file


PAGE = 0x1000
MAGIC = int.from_bytes(b"APBT", "little")
MARKER = struct.pack("<II", MAGIC, 1)


def align(value, boundary):
    return (value + boundary - 1) // boundary * boundary


def arm_branch(source, target, link=False):
    delta = target - source - 8
    if source % 4 or target % 4 or not -(1 << 25) <= delta < (1 << 25):
        raise ValueError("Unaligned or out-of-range A32 branch")
    return (0xEB000000 if link else 0xEA000000) | ((delta // 4) & 0xFFFFFF)


def encode_ips(records):
    """Small non-RLE records only; reject overlaps, truncation and EOF ambiguity."""
    patch = bytearray(b"PATCH")
    end = 0
    for offset, data in records:
        if (not 0 <= offset < 1 << 24 or offset == int.from_bytes(b"EOF", "big")
                or offset < end or not 1 <= len(data) <= 0xFFFF
                or offset + len(data) > 1 << 24):
            raise ValueError("Invalid bounded IPS record")
        patch.extend(offset.to_bytes(3, "big") + len(data).to_bytes(2, "big") + data)
        end = offset + len(data)
    return bytes(patch + b"EOF")


def build_bootstrap(info, image, exheader, hook=True, registration_trace=False, sidecar=False):
    """Pure builder, also exercised with synthetic segments. Caller pins ROM hash."""
    if len(exheader) != 0x800:
        raise ValueError("Expected Encore's complete 0x800-byte ExHeader")
    segments = {s["name"]: s for s in info["code_segments"]}
    if set(segments) != {"text", "ro", "data"}:
        raise ValueError("Expected three executable segments")
    for name, offset in (("text", 0x10), ("ro", 0x20), ("data", 0x30)):
        s = segments[name]
        if struct.unpack_from("<III", exheader, offset) != (s["address"], s["pages"], s["size"]):
            raise ValueError("ExHeader/segment mapping differs")
    text, data = segments["text"], segments["data"]
    bss = info["bss_size_bytes"]
    if struct.unpack_from("<I", exheader, 0x3C)[0] != bss:
        raise ValueError("ExHeader/BSS mapping differs")
    # Entry is exactly an unconditional BL. Reproduce its LR and original target.
    start = text["image_offset"]
    entry = text["address"]
    word = struct.unpack_from("<I", image, start)[0]
    if word >> 24 != 0xEB:
        raise ValueError("Bootstrap requires an unconditional A32 BL entry")
    delta = word & 0xFFFFFF
    if delta & 0x800000:
        delta -= 1 << 24
    original_target = entry + 8 + delta * 4
    if not entry <= original_target < entry + text["size"] or original_target % 4:
        raise ValueError("Original startup target outside text")
    stub_offset = align(start + text["size"], 16)
    stub_address = entry + stub_offset - start
    # A whole additional loader-allocated RW page, not the original partial BSS page.
    owned_address = data["address"] + data["pages"] * PAGE + align(bss, PAGE)
    new_bss = align(bss, PAGE) + PAGE
    if owned_address + PAGE > 1 << 32:
        raise ValueError("Bootstrap BSS allocation overflows")
    for s in segments.values():
        if owned_address < s["address"] + s["pages"] * PAGE and s["address"] < owned_address + PAGE:
            raise ValueError("Bootstrap BSS allocation overlaps a segment")
    # PUSH/POP preserve registers, LR and 8-byte stack alignment. No flag-setting
    # operations. Tail B invokes original startup with LR still entry+4.
    words = [
        0xE92D4007,       # push {r0,r1,r2,lr}
        0xE59F0014,       # ldr r0,[pc,#20] -> literal at stub+32
        0xE59F1014,       # ldr r1,[pc,#20] -> literal at stub+36
        0xE3A02001,       # mov r2,#1
        0xE8800006,       # stmia r0,{r1,r2}
        0xE8BD4007,       # pop {r0,r1,r2,lr}
        arm_branch(stub_address + 24, original_target),
        0xE1A00000,       # nop; align literals
        owned_address, MAGIC,
    ]
    stub = struct.pack("<10I", *words)
    trace_records, trace_plan, sidecar_plan = [], None, None
    if sidecar:
        if not hook or registration_trace:
            raise ValueError("Sidecar probe requires an isolated bootstrap hook")
        from oras_sidecar_probe import build_sidecar
        trace_start = align(stub_address + len(stub), 16)
        trace_records, trace_code, sidecar_plan = build_sidecar(info, image, trace_start, owned_address)
        stub += bytes(trace_start - stub_address - len(stub)) + trace_code
    if registration_trace:
        if not hook:
            raise ValueError("Registration trace requires the native bootstrap hook")
        from oras_save_registration import build_trace
        trace_start = align(stub_address + len(stub), 16)
        trace_records, trace_code, trace_plan = build_trace(info, image, trace_start, owned_address)
        stub += bytes(trace_start - stub_address - len(stub)) + trace_code
    end = stub_offset + len(stub)
    if (end > start + text["pages"] * PAGE or end > len(image)
            or any(image[start + text["size"]:end])):
        raise ValueError("Bootstrap text extension is occupied or outside mapped text pages")
    changed = bytearray(exheader)
    struct.pack_into("<I", changed, 0x18, end - start)
    struct.pack_into("<I", changed, 0x3C, new_bss)
    records = []
    prefix = image[start:start + 64]
    if len(prefix) != 64:
        raise ValueError("Truncated startup prefix")
    references = []
    if hook:
        branch = struct.pack("<I", arm_branch(entry, stub_address, link=True))
        records = sorted([(start, branch), *trace_records, (stub_offset, stub)])
        prefix = branch + prefix[4:]
        references.append(CodeReference(stub_address, stub))
    references.append(CodeReference(owned_address, MARKER if hook else bytes(8)))
    report = {
        "kind": "oras_encore_bootstrap_v1",
        "mode": ("sidecar-load" if sidecar else "registration-trace" if registration_trace
                 else "hook" if hook else "allocation-only"),
        "entry_address": entry, "original_startup_target": original_target,
        "stub_address": stub_address, "stub_size": len(stub),
        "original_text_size": text["size"], "extended_text_size": end - start,
        "original_bss_size": bss, "extended_bss_size": new_bss,
        "owned_volatile_page": owned_address, "owned_volatile_page_size": PAGE,
        "expected_marker_hex": references[-1].expected.hex(),
        "native_marker_store_enabled": hook,
        "native_marker_store_width_bytes": 8 if hook else 0,
        "runtime_instruction_trace": False,
        "persistent_storage_allocated": False, "block47_write_allowed": False,
        "live_delivery_authorized": False, "next_delivery_index": None,
    }
    if trace_plan is not None:
        report["registration_trace"] = trace_plan
    if sidecar_plan is not None:
        report["sidecar_probe"] = sidecar_plan
        for offset, data in trace_records:
            references.append(CodeReference(entry + offset - start, data))
    return encode_ips(records), bytes(changed), CodeReference(entry, prefix), references, report


def install_bootstrap(rom: Path, runtime: Path, mode: str):
    if mode not in ("hook", "allocation-only", "registration-trace", "sidecar-load") or sha256_file(rom) != OR_HASH:
        raise ValueError("Bootstrap experiment requires the exact verified OR build and mode")
    # Never allow adjacent, unaccounted-for overlays on the user's ROM.
    for suffix in (".exheader", ".exefsdir", ".romfs"):
        if Path(str(rom) + suffix).exists():
            raise ValueError("Bootstrap refuses adjacent ROM overlays")
    info, image = load_code(rom)
    if info["program_id"] != "000400000011C400" or image[:4] != bytes.fromhex("070000eb"):
        raise ValueError("Exact OR startup signature differs")
    with rom.open("rb") as source:
        source.seek(info["ncch_offset_bytes"] + 0x200)
        exheader = source.read(0x800)
    ips, header, prefix, references, report = build_bootstrap(
        info, image, exheader, mode != "allocation-only", mode == "registration-trace", mode == "sidecar-load",
    )
    mod = runtime / "3DS/User/load/mods" / info["program_id"]
    mod.mkdir(mode=0o700, parents=True, exist_ok=False)
    for name, content in (("code.ips", ips), ("exheader.bin", header)):
        with (mod / name).open("xb") as output:
            output.write(content)
        report[f"{name}_sha256"] = hashlib.sha256(content).hexdigest()
    report["private_mod_directory"] = str(mod)
    report["rom_sha256"] = OR_HASH
    return prefix, references, report

"""Persistent, Git-ignored profiles and CRC-validated save snapshots.

Snapshots are private game data, not distributable research artifacts.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile

from oras_save import validate_save
from run_bizhawk_probe import PROJECT_ROOT


PROFILE_ROOT = PROJECT_ROOT / "local/oras/profiles"
BACKUP_ROOT = PROJECT_ROOT / "local/oras/backups"
LEGACY_ROOT = Path("/tmp/opencode")


def validate_profile_path(path: Path) -> Path:
    path = path.resolve()
    if not any(path != root.resolve() and path.is_relative_to(root.resolve())
               for root in (PROFILE_ROOT, LEGACY_ROOT)):
        raise ValueError("Reusable profiles must be private children of local/oras/profiles or /tmp/opencode")
    return path


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_synced(path: Path, data: bytes) -> None:
    with path.open("xb") as file:
        os.chmod(path, 0o600)
        file.write(data)
        file.flush()
        os.fsync(file.fileno())


def sync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def validate_snapshot(path: Path, rom_hash: str | None = None) -> dict:
    manifest = json.loads((path / "snapshot.json").read_text())
    if manifest.get("kind") != "oras_save_snapshot":
        raise ValueError("Not an ORAS save snapshot")
    if (manifest.get("program_id") not in ("000400000011C400", "000400000011C500")
            or not re.fullmatch(r"[0-9a-f]{64}", manifest.get("rom_sha256", ""))):
        raise ValueError("Invalid snapshot identity")
    if rom_hash is not None and manifest["rom_sha256"] != rom_hash:
        raise ValueError("Snapshot/ROM identity mismatch")
    data = (path / "00000001/main").read_bytes()
    metadata = (path / "00000001.metadata").read_bytes()
    validate_save(data)
    if (len(metadata) != 16 or digest(data) != manifest["save_sha256"]
            or digest(metadata) != manifest["metadata_sha256"]):
        raise ValueError("Snapshot integrity mismatch")
    return manifest


def snapshot_save(source: Path, program_id: str, rom_hash: str, label: str,
                  backup_root: Path = BACKUP_ROOT) -> Path:
    """Publish only a complete, verified snapshot; never modify the source."""
    if program_id not in ("000400000011C400", "000400000011C500"):
        raise ValueError("Unsupported snapshot Program ID")
    if not re.fullmatch(r"[0-9a-f]{64}", rom_hash) or not re.fullmatch(r"[a-z0-9-]+", label):
        raise ValueError("Invalid snapshot identity or label")
    source = source.resolve()
    metadata_source = source.parent.with_suffix(".metadata")
    data, metadata = source.read_bytes(), metadata_source.read_bytes()
    validate_save(data)
    if len(metadata) != 16:
        raise ValueError("Snapshot requires 16-byte Encore archive metadata")
    if source.read_bytes() != data or metadata_source.read_bytes() != metadata:
        raise ValueError("Source changed while reading snapshot")
    backup_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    staging = Path(tempfile.mkdtemp(prefix=f".partial-{label}-", dir=backup_root))
    archive = staging / "00000001"
    archive.mkdir(mode=0o700)
    write_synced(archive / "main", data)
    write_synced(staging / "00000001.metadata", metadata)
    manifest = {
        "kind": "oras_save_snapshot", "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(), "label": label,
        "program_id": program_id, "rom_sha256": rom_hash,
        "source": str(source), "save_sha256": digest(data),
        "metadata_sha256": digest(metadata), "validated_crc_blocks": 58,
    }
    write_synced(staging / "snapshot.json", (json.dumps(manifest, indent=2) + "\n").encode())
    validate_snapshot(staging, rom_hash)
    sync_directory(archive)
    sync_directory(staging)
    final = backup_root / staging.name.removeprefix(".partial-")
    if final.exists() or final.is_symlink():
        raise FileExistsError(final)
    staging.rename(final)
    sync_directory(backup_root)
    return final


def backup_existing_save(source: Path, program_id: str, rom_hash: str, label: str) -> str | None:
    if not source.exists():
        return None
    return str(snapshot_save(source, program_id, rom_hash, label))


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify a private ORAS save snapshot without modifying it.")
    parser.add_argument("snapshot", type=Path)
    args = parser.parse_args()
    try:
        manifest = validate_snapshot(args.snapshot)
    except (OSError, ValueError, KeyError) as error:
        parser.exit(1, f"Snapshot verification failed: {error}\n")
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

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
from oras_archive import capture_stable_archive, safe_archive_path, tree_digest
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


def require_single_file_archive(source: Path) -> None:
    """Legacy/unmanifested imports remain restricted to a single save file."""
    if source.is_symlink() or source.parent.is_symlink():
        raise ValueError("Single-file archive cannot contain symlinked save data")
    if {entry.name for entry in source.parent.iterdir()} != {source.name}:
        raise ValueError("Unsupported multi-file archive; refusing to omit additional save/AP data")


def write_archive(directory, files, tree):
    directory.mkdir(mode=0o700, exist_ok=False)
    for name in sorted(tree["directories"], key=lambda p: (p.count("/"), p)):
        (directory / safe_archive_path(name)).mkdir(mode=0o700)
    for name, data in sorted(files.items()):
        write_synced(directory / safe_archive_path(name), data)
    for name in sorted(tree["directories"], key=lambda p: (-p.count("/"), p)):
        sync_directory(directory / name)
    sync_directory(directory)


def validate_snapshot(path: Path, rom_hash: str | None = None, *, allow_unpublished=False) -> dict:
    if path.name.startswith(".partial-") and not allow_unpublished:
        raise ValueError("Unpublished partial snapshot is not recoverable")
    if (path.is_symlink() or (path / "snapshot.json").is_symlink()
            or (path / "snapshot.json").stat().st_size > 1024 * 1024):
        raise ValueError("Invalid snapshot manifest path/size")
    manifest = json.loads((path / "snapshot.json").read_text())
    if not isinstance(manifest, dict) or manifest.get("kind") != "oras_save_snapshot":
        raise ValueError("Not an ORAS save snapshot")
    if (manifest.get("program_id") not in ("000400000011C400", "000400000011C500")
            or not isinstance(manifest.get("rom_sha256"), str)
            or not re.fullmatch(r"[0-9a-f]{64}", manifest.get("rom_sha256", ""))):
        raise ValueError("Invalid snapshot identity")
    if rom_hash is not None and manifest["rom_sha256"] != rom_hash:
        raise ValueError("Snapshot/ROM identity mismatch")
    version = manifest.get("schema_version")
    if type(version) is not int or version not in (1, 2):
        raise ValueError("Unsupported snapshot schema version")
    source = path / "00000001/main"
    if version == 1:
        require_single_file_archive(source)
    files, metadata, tree = capture_stable_archive(source)
    data = files["main"]
    validate_save(data)
    if (len(metadata) != 16 or digest(data) != manifest["save_sha256"]
            or digest(metadata) != manifest["metadata_sha256"]):
        raise ValueError("Snapshot integrity mismatch")
    if version == 2 and (manifest.get("archive_tree") != tree
                         or tree_digest(manifest.get("archive_tree")) != tree_digest(tree)
                         or manifest.get("archive_tree_sha256") != tree_digest(tree)):
        raise ValueError("Snapshot archive inventory/integrity mismatch")
    return manifest


def snapshot_save(source: Path, program_id: str, rom_hash: str, label: str,
                  backup_root: Path = BACKUP_ROOT) -> Path:
    """Publish only a complete, verified snapshot; never modify the source."""
    if program_id not in ("000400000011C400", "000400000011C500"):
        raise ValueError("Unsupported snapshot Program ID")
    if not re.fullmatch(r"[0-9a-f]{64}", rom_hash) or not re.fullmatch(r"[a-z0-9-]+", label):
        raise ValueError("Invalid snapshot identity or label")
    files, metadata, tree = capture_stable_archive(source)
    source = source.resolve()
    data = files["main"]
    validate_save(data)
    if backup_root.resolve().is_relative_to(source.parent):
        raise ValueError("Snapshot destination must be outside source archive")
    backup_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    staging = Path(tempfile.mkdtemp(prefix=f".partial-{label}-", dir=backup_root))
    archive = staging / "00000001"
    write_archive(archive, files, tree)
    write_synced(staging / "00000001.metadata", metadata)
    manifest = {
        "kind": "oras_save_snapshot", "schema_version": 2,
        "created_at": datetime.now(timezone.utc).isoformat(), "label": label,
        "program_id": program_id, "rom_sha256": rom_hash,
        "source": str(source), "save_sha256": digest(data),
        "metadata_sha256": digest(metadata), "validated_crc_blocks": 58,
        "archive_tree": tree, "archive_tree_sha256": tree_digest(tree),
    }
    write_synced(staging / "snapshot.json", (json.dumps(manifest, indent=2) + "\n").encode())
    validate_snapshot(staging, rom_hash, allow_unpublished=True)
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

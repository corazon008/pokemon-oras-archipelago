"""Fetch a pinned upstream connector into a private directory, with SHA-256 checks."""

import concurrent.futures
import hashlib
import importlib.util
import json
from pathlib import Path, PurePosixPath
import re
import urllib.request


LOCK_PATH = Path(__file__).with_name("ap_connector.lock.json")


def read_lock() -> dict:
    lock = json.loads(LOCK_PATH.read_text())
    if lock["repository"] != "ArchipelagoMW/Archipelago":
        raise ValueError("Unexpected connector repository")
    if not re.fullmatch(r"[0-9a-f]{40}", lock["commit"]):
        raise ValueError("Connector must be pinned to a commit")
    for entry in lock["files"]:
        for field in ("path", "upstream_path"):
            path = PurePosixPath(entry[field])
            if path.is_absolute() or ".." in path.parts or not path.parts:
                raise ValueError("Unsafe bundle path")
        if not re.fullmatch(r"[0-9a-f]{64}", entry["sha256"]):
            raise ValueError("Invalid file checksum")
    return lock


def verify_bundle(directory: Path, lock: dict) -> None:
    for entry in lock["files"]:
        data = (directory / entry["path"]).read_bytes()
        if hashlib.sha256(data).hexdigest() != entry["sha256"]:
            raise ValueError(f"Connector checksum mismatch: {entry['path']}")


def fetch_bundle(directory: Path) -> dict:
    lock = read_lock()
    directory.mkdir(parents=True, exist_ok=False)

    def download(entry: dict) -> None:
        url = (
            f"https://raw.githubusercontent.com/{lock['repository']}/"
            f"{lock['commit']}/{entry['upstream_path']}"
        )
        request = urllib.request.Request(url, headers={"User-Agent": "ORAS-BizHawk-probe"})
        with urllib.request.urlopen(request, timeout=30) as response:
            data = response.read()
        if hashlib.sha256(data).hexdigest() != entry["sha256"]:
            raise ValueError(f"Downloaded checksum mismatch: {entry['path']}")
        path = directory / entry["path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(download, lock["files"]))
    verify_bundle(directory, lock)
    return lock


def load_upstream_api(directory: Path, lock: dict):
    """Verify all dependencies before importing upstream's standard-library-only API."""
    verify_bundle(directory, lock)
    spec = importlib.util.spec_from_file_location("oras_upstream_bizhawk", directory / "bizhawk_api.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

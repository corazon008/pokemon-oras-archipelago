"""Bounded private archive capture. Byte preservation is not AP reconciliation."""

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat


MAX_FILES = 128
MAX_DIRECTORIES = 64
MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_ARCHIVE_BYTES = 16 * 1024 * 1024


def safe_archive_path(path):
    if (not isinstance(path, str) or not path or len(path) > 256 or "\\" in path
            or PurePosixPath(path).is_absolute() or len(path.split("/")) > 8
            or any(part in ("", ".", "..") or not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", part)
                   for part in path.split("/"))):
        raise ValueError("Unsafe or unsupported archive path")
    return path


def tree_manifest(files, directories):
    return {
        "files": [{"path": name, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
                  for name, data in sorted(files.items())],
        "directories": sorted(directories),
    }


def tree_digest(tree):
    return hashlib.sha256(json.dumps(tree, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def capture_archive(root):
    """Use no-follow directory-relative opens; reject links, special files and changing reads."""
    files, directories, total = {}, [], 0

    def visit(fd, prefix=""):
        nonlocal total
        names = []
        with os.scandir(fd) as entries:
            for entry in entries:
                if len(names) >= MAX_FILES + MAX_DIRECTORIES:
                    raise ValueError("Archive entry limit exceeded")
                names.append(entry.name)
        for name in sorted(names):
            relative = safe_archive_path(f"{prefix}/{name}" if prefix else name)
            before = os.stat(name, dir_fd=fd, follow_symlinks=False)
            if stat.S_ISDIR(before.st_mode):
                if len(directories) >= MAX_DIRECTORIES:
                    raise ValueError("Archive directory limit exceeded")
                directories.append(relative)
                child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                try:
                    current = os.fstat(child)
                    if (before.st_dev, before.st_ino) != (current.st_dev, current.st_ino):
                        raise ValueError("Archive directory changed while opening")
                    visit(child, relative)
                finally:
                    os.close(child)
            elif stat.S_ISREG(before.st_mode) and before.st_nlink == 1:
                if (len(files) >= MAX_FILES or before.st_size > MAX_FILE_BYTES
                        or total + before.st_size > MAX_ARCHIVE_BYTES):
                    raise ValueError("Archive file/byte limit exceeded")
                file_fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
                with os.fdopen(file_fd, "rb") as source:
                    opened = os.fstat(source.fileno())
                    if not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1:
                        raise ValueError("Archive file changed type")
                    data = source.read(min(MAX_FILE_BYTES, MAX_ARCHIVE_BYTES - total) + 1)
                    after = os.fstat(source.fileno())
                key = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
                if key(before) != key(opened) or key(opened) != key(after) or len(data) != before.st_size:
                    raise ValueError("Archive file changed while reading")
                files[relative] = data
                total += len(data)
            else:
                raise ValueError("Archive links or special files are unsupported")
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        visit(fd)
    finally:
        os.close(fd)
    if "main" not in files:
        raise ValueError("Archive requires a regular main save")
    tree = tree_manifest(files, directories)
    return files, tree


def read_metadata(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as source:
        before = os.fstat(source.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_size != 16:
            raise ValueError("Archive requires regular 16-byte Encore metadata")
        data = source.read(17)
        after = os.fstat(source.fileno())
    if len(data) != 16 or (before.st_mtime_ns, before.st_ctime_ns) != (after.st_mtime_ns, after.st_ctime_ns):
        raise ValueError("Archive metadata changed while reading")
    return data


def capture_stable_archive(source):
    if source.name != "main" or source.is_symlink():
        raise ValueError("Archive source must be a regular main save")
    files, tree = capture_archive(source.parent)
    metadata = read_metadata(source.parent.with_suffix(".metadata"))
    second_files, second_tree = capture_archive(source.parent)
    if tree != second_tree or files != second_files or read_metadata(source.parent.with_suffix(".metadata")) != metadata:
        raise ValueError("Source changed while reading archive")
    return files, metadata, tree


def source_archive_unchanged(manifest):
    """Recheck all source files, not only main; never authorize an AP replay."""
    files, metadata, tree = capture_stable_archive(Path(manifest["seed_source"]))
    return (tree_digest(tree) == manifest["archive_tree_sha256"]
            and hashlib.sha256(metadata).hexdigest() == manifest["archive_metadata_sha256"])

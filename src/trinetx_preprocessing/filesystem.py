"""Filesystem helpers for durable metadata writes."""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path


def write_text_atomic(path: Path, text: str) -> None:
    """Write text to ``path`` by replacing it with a completed temp file."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.tmp-",
            delete=False,
        ) as handle:
            temp_path = Path(handle.name)
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    finally:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink()


def fsync_file_strict(path: Path) -> None:
    """Flush one existing regular file to its backing storage."""

    if path.is_symlink() or not path.is_file():
        raise ValueError(f"Cannot fsync non-regular file: {path}")
    with path.open("rb") as handle:
        os.fsync(handle.fileno())


def fsync_directory_strict(path: Path) -> None:
    """Flush one existing directory entry set to its backing storage."""

    if path.is_symlink() or not path.is_dir():
        raise ValueError(f"Cannot fsync non-directory: {path}")
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def remove_tree_strict(path: Path, *, context: str = "Directory") -> None:
    """Remove a directory tree and raise for real cleanup failures."""

    try:
        shutil.rmtree(path, onexc=_ignore_missing_rmtree_onexc)
    except TypeError:
        shutil.rmtree(path, onerror=_ignore_missing_rmtree_error)
    except FileNotFoundError:
        return
    if path.exists() or path.is_symlink():
        raise OSError(f"{context} was not deleted: {path}")


def _ignore_missing_rmtree_onexc(function, path, error) -> None:
    if isinstance(error, FileNotFoundError):
        return
    raise error


def _ignore_missing_rmtree_error(function, path, exc_info) -> None:
    error = exc_info[1]
    if isinstance(error, FileNotFoundError):
        return
    raise error

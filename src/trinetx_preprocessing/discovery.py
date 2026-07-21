"""Utilities for discovering domain CSV inputs."""

from __future__ import annotations

import re
from pathlib import Path

_CHUNK_SUFFIX_RE = re.compile(r"^(?P<prefix>.*?)(?P<index>\d+)$")


def discover_domain_files(domain_dir: Path, pattern: str) -> list[Path]:
    """Discover domain files matching a pattern.

    If chunked files are present, return only the chunked set.

    Args:
        domain_dir: Base directory to search from.
        pattern: Glob pattern to match files.

    Returns:
        Sorted list of matched file paths.

    Raises:
        FileNotFoundError: If the domain directory does not exist.
    """

    base_dir = Path(domain_dir)
    if not base_dir.exists():
        raise FileNotFoundError(f"Domain directory not found: {base_dir}")

    matches = [path for path in sorted(base_dir.glob(pattern)) if path.is_file()]
    if not matches:
        return []

    chunked = [path for path in matches if _chunk_index(path) is not None]
    if chunked:
        return sorted(chunked, key=_chunk_sort_key)
    return sorted(matches, key=lambda path: path.name)


def detect_chunked(files: list[Path]) -> bool:
    """Return True if any files look like chunked outputs."""

    return any(_chunk_index(path) is not None for path in files)


def _chunk_index(path: Path) -> int | None:
    match = _CHUNK_SUFFIX_RE.match(path.stem)
    if not match:
        return None
    return int(match.group("index"))


def _chunk_sort_key(path: Path) -> tuple[str, int, str]:
    match = _CHUNK_SUFFIX_RE.match(path.stem)
    if not match:
        return (path.stem, -1, path.name)
    prefix = match.group("prefix")
    return (prefix, int(match.group("index")), path.name)

"""Regression harness utilities for deterministic output hashing."""

from __future__ import annotations

import hashlib
import io
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping

import pandas as pd

HASH_MANIFEST_FILENAME = "hashes.json"
HASH_ALGORITHM = "sha256"


@dataclass(frozen=True)
class ComparisonResult:
    """Summary of hash comparisons against a baseline manifest."""

    missing: tuple[str, ...]
    extra: tuple[str, ...]
    mismatched: dict[str, tuple[str, str]]

    @property
    def ok(self) -> bool:
        """Return True when no differences are detected."""

        return not self.missing and not self.extra and not self.mismatched


def normalize_table(df: pd.DataFrame) -> pd.DataFrame:
    """Return a deterministically sorted copy of ``df``.

    Args:
        df: Input table to normalize.

    Returns:
        New DataFrame with columns and rows sorted deterministically.
    """

    sorted_columns = sorted(df.columns)
    normalized = df.loc[:, sorted_columns].copy()
    if sorted_columns:
        normalized = normalized.sort_values(
            by=sorted_columns,
            kind="mergesort",
            na_position="last",
        )
    return normalized.reset_index(drop=True)


def hash_table(df: pd.DataFrame) -> str:
    """Return a stable hash for a normalized DataFrame.

    Args:
        df: Input DataFrame to hash.

    Returns:
        Hex-encoded SHA-256 hash of the normalized table.
    """

    normalized = normalize_table(df)
    buffer = io.StringIO()
    normalized.to_csv(
        buffer,
        index=False,
        lineterminator="\n",
        na_rep="",
        float_format="%.15g",
    )
    return hashlib.sha256(buffer.getvalue().encode("utf-8")).hexdigest()


def hash_csv(path: Path) -> str:
    """Return a stable hash for a CSV file.

    Args:
        path: Path to the CSV file.

    Returns:
        Hex-encoded SHA-256 hash of the normalized CSV contents.
    """

    if path.suffix.lower() != ".csv":
        raise ValueError(f"Expected a CSV file, got: {path}")
    if not path.exists():
        raise FileNotFoundError(path)
    frame = pd.read_csv(
        path,
        dtype=str,
        keep_default_na=False,
        na_filter=False,
    )
    return hash_table(frame)


def output_key(path: Path, work_dir: Path, output_dir: Path) -> str:
    """Return a stable key for an output path.

    Args:
        path: Output file path.
        work_dir: Configured working directory.
        output_dir: Configured final output directory.

    Returns:
        Normalized key string for the output.
    """

    if path.is_relative_to(work_dir):
        return str(Path("work_dir") / path.relative_to(work_dir))
    if path.is_relative_to(output_dir):
        return str(Path("output_dir") / path.relative_to(output_dir))
    return path.name


def collect_output_hashes(
    output_paths: Iterable[Path],
    work_dir: Path,
    output_dir: Path,
) -> dict[str, str]:
    """Hash output CSV files from the pipeline.

    Args:
        output_paths: Iterable of output file paths.
        work_dir: Working directory used by the pipeline.
        output_dir: Final output directory used by the pipeline.

    Returns:
        Mapping of output keys to hashes.
    """

    hashes: dict[str, str] = {}
    for path in output_paths:
        key = output_key(path, work_dir, output_dir)
        if key in hashes:
            raise ValueError(f"Duplicate output key detected: {key}")
        hashes[key] = hash_csv(path)
    return hashes


def write_hash_manifest(directory: Path, hashes: Mapping[str, str]) -> Path:
    """Write a hash manifest JSON file under ``directory``.

    Args:
        directory: Directory to receive the manifest.
        hashes: Mapping of output keys to hashes.

    Returns:
        Path to the written manifest.
    """

    directory.mkdir(parents=True, exist_ok=True)
    manifest_path = directory / HASH_MANIFEST_FILENAME
    payload = {
        "schema_version": 1,
        "hash_algorithm": HASH_ALGORITHM,
        "hashes": dict(sorted(hashes.items())),
    }
    manifest_path.write_text(json.dumps(payload, indent=2, sort_keys=True))
    return manifest_path


def load_hash_manifest(path: Path) -> dict[str, str]:
    """Load hash manifest data from a directory or file path."""

    manifest_path = path
    if path.is_dir():
        manifest_path = path / HASH_MANIFEST_FILENAME
    raw = json.loads(manifest_path.read_text())
    if not isinstance(raw, dict):
        raise ValueError("Hash manifest must be a JSON object.")
    schema_version = raw.get("schema_version")
    if schema_version != 1:
        raise ValueError(f"Unsupported hash manifest schema version: {schema_version}")
    hashes = raw.get("hashes")
    if not isinstance(hashes, dict):
        raise ValueError("Hash manifest 'hashes' must be a JSON object.")
    normalized: dict[str, str] = {}
    for key, value in hashes.items():
        if not isinstance(key, str) or not isinstance(value, str):
            raise ValueError("Hash manifest entries must be string mappings.")
        normalized[key] = value
    return normalized


def compare_hashes(
    current: Mapping[str, str], baseline: Mapping[str, str]
) -> ComparisonResult:
    """Compare current hashes against baseline hashes."""

    missing = tuple(sorted(set(baseline) - set(current)))
    extra = tuple(sorted(set(current) - set(baseline)))
    mismatched: dict[str, tuple[str, str]] = {}
    for key in sorted(set(current) & set(baseline)):
        baseline_hash = baseline[key]
        current_hash = current[key]
        if baseline_hash != current_hash:
            mismatched[key] = (baseline_hash, current_hash)
    return ComparisonResult(missing=missing, extra=extra, mismatched=mismatched)

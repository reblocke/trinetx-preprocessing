"""Regression harness utilities for deterministic output hashing."""

from __future__ import annotations

import csv
import hashlib
import heapq
import io
import json
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Literal, Mapping, Sequence

import pandas as pd

from .filesystem import write_text_atomic
from .storage import logical_output_key

HASH_MANIFEST_FILENAME = "hashes.json"
HASH_ALGORITHM = "sha256"
TABLE_SUFFIXES = {".csv", ".parquet"}
HASH_SCOPE_VALUES = {"work", "final", "all"}
DEFAULT_CSV_HASH_CHUNK_ROWS = 100_000
NOISE_PATH_PARTS = {"__MACOSX"}
HashScope = Literal["work", "final", "all"]


@dataclass(frozen=True)
class TableHashEntry:
    """Manifest entry for a hashed table."""

    key: str
    hash: str
    row_count: int | None = None
    columns: tuple[str, ...] | None = None
    physical_format: str | None = None
    source_path: str | None = None
    source_size_bytes: int | None = None
    source_mtime_ns: int | None = None


@dataclass(frozen=True)
class CsvHashResult:
    """Normalized CSV hash plus manifest metadata."""

    hash: str
    row_count: int
    columns: tuple[str, ...]


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


@dataclass(frozen=True)
class ManifestComparisonResult:
    """Summary of manifest comparisons including optional metadata."""

    missing: tuple[str, ...]
    extra: tuple[str, ...]
    hash_mismatched: dict[str, tuple[str, str]]
    row_count_mismatched: dict[str, tuple[int | None, int | None]]
    columns_mismatched: dict[str, tuple[tuple[str, ...] | None, tuple[str, ...] | None]]

    @property
    def ok(self) -> bool:
        """Return True when no differences are detected."""

        return not (
            self.missing
            or self.extra
            or self.hash_mismatched
            or self.row_count_mismatched
            or self.columns_mismatched
        )


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


def csv_visible_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Return values normalized to the representation visible in CSV comparisons."""

    return df.astype("string").fillna("")


def hash_csv(path: Path, *, chunk_rows: int = DEFAULT_CSV_HASH_CHUNK_ROWS) -> str:
    """Return a stable hash for a CSV file.

    Args:
        path: Path to the CSV file.
        chunk_rows: Maximum data rows to sort in memory at once.

    Returns:
        Hex-encoded SHA-256 hash of the normalized CSV contents.
    """

    return hash_csv_with_metadata(path, chunk_rows=chunk_rows).hash


def hash_csv_with_metadata(
    path: Path,
    *,
    chunk_rows: int = DEFAULT_CSV_HASH_CHUNK_ROWS,
) -> CsvHashResult:
    """Return a normalized CSV hash without loading the full table in memory."""

    if path.suffix.lower() != ".csv":
        raise ValueError(f"Expected a CSV file, got: {path}")
    if not path.exists():
        raise FileNotFoundError(path)
    if chunk_rows < 1:
        raise ValueError("CSV hash chunk_rows must be at least 1.")

    hasher = hashlib.sha256()
    row_count = 0
    chunk: list[tuple[str, ...]] = []
    chunk_paths: list[Path] = []
    temp_dir: tempfile.TemporaryDirectory[str] | None = None
    original_columns: tuple[str, ...]

    try:
        with path.open(newline="", encoding="utf-8") as handle:
            reader = csv.reader(handle)
            try:
                header = next(reader)
            except StopIteration as exc:
                raise ValueError(f"CSV file is empty: {path}") from exc

            original_columns = tuple(header)
            sorted_indices = sorted(range(len(header)), key=header.__getitem__)
            sorted_columns = tuple(header[index] for index in sorted_indices)
            hasher.update(_render_csv_row(sorted_columns))

            for row in reader:
                _validate_csv_row_width(path, row, header)
                chunk.append(tuple(row[index] for index in sorted_indices))
                row_count += 1
                if len(chunk) >= chunk_rows:
                    temp_dir = _ensure_temp_dir(path, temp_dir)
                    chunk_paths.append(
                        _write_sorted_csv_chunk(
                            chunk,
                            Path(temp_dir.name),
                            len(chunk_paths),
                        )
                    )
                    chunk = []

        if chunk_paths:
            if chunk:
                temp_dir = _ensure_temp_dir(path, temp_dir)
                chunk_paths.append(
                    _write_sorted_csv_chunk(
                        chunk, Path(temp_dir.name), len(chunk_paths)
                    )
                )
            _hash_sorted_csv_chunks(hasher, chunk_paths)
        else:
            for row in sorted(chunk):
                hasher.update(_render_csv_row(row))
    finally:
        if temp_dir is not None:
            temp_dir.cleanup()

    return CsvHashResult(
        hash=hasher.hexdigest(),
        row_count=row_count,
        columns=original_columns,
    )


def hash_parquet(
    path: Path,
    *,
    chunk_rows: int = DEFAULT_CSV_HASH_CHUNK_ROWS,
) -> str:
    """Return a stable hash for a Parquet file."""

    return hash_parquet_with_metadata(path, chunk_rows=chunk_rows).hash


def hash_parquet_with_metadata(
    path: Path,
    *,
    chunk_rows: int = DEFAULT_CSV_HASH_CHUNK_ROWS,
) -> CsvHashResult:
    """Return a normalized Parquet hash without loading the full table."""

    if path.suffix.lower() != ".parquet":
        raise ValueError(f"Expected a Parquet file, got: {path}")
    if not path.exists():
        raise FileNotFoundError(path)
    if chunk_rows < 1:
        raise ValueError("Parquet hash chunk_rows must be at least 1.")

    import pyarrow.parquet as pq

    parquet_file = pq.ParquetFile(path)
    original_columns = tuple(parquet_file.schema_arrow.names)
    sorted_columns = tuple(sorted(original_columns))
    hasher = hashlib.sha256()
    hasher.update(_render_csv_row(sorted_columns))
    row_count = 0
    chunk: list[tuple[str, ...]] = []
    chunk_paths: list[Path] = []
    temp_dir: tempfile.TemporaryDirectory[str] | None = None

    try:
        for batch in parquet_file.iter_batches(batch_size=chunk_rows):
            frame = csv_visible_frame(batch.to_pandas())
            for row in frame.loc[:, list(sorted_columns)].itertuples(
                index=False,
                name=None,
            ):
                chunk.append(tuple(row))
                row_count += 1
                if len(chunk) >= chunk_rows:
                    temp_dir = _ensure_temp_dir(path, temp_dir)
                    chunk_paths.append(
                        _write_sorted_csv_chunk(
                            chunk,
                            Path(temp_dir.name),
                            len(chunk_paths),
                        )
                    )
                    chunk = []

        if chunk_paths:
            if chunk:
                temp_dir = _ensure_temp_dir(path, temp_dir)
                chunk_paths.append(
                    _write_sorted_csv_chunk(
                        chunk, Path(temp_dir.name), len(chunk_paths)
                    )
                )
            _hash_sorted_csv_chunks(hasher, chunk_paths)
        else:
            for row in sorted(chunk):
                hasher.update(_render_csv_row(row))
    finally:
        if temp_dir is not None:
            temp_dir.cleanup()

    return CsvHashResult(
        hash=hasher.hexdigest(),
        row_count=row_count,
        columns=original_columns,
    )


def hash_table_file(path: Path) -> str:
    """Return a stable hash for a supported table file."""

    suffix = path.suffix.lower()
    if suffix == ".csv":
        return hash_csv(path)
    if suffix == ".parquet":
        return hash_parquet(path)
    raise ValueError(f"Unsupported table file type: {path}")


def table_hash_entry(
    path: Path,
    work_dir: Path,
    output_dir: Path,
    *,
    csv_chunk_rows: int = DEFAULT_CSV_HASH_CHUNK_ROWS,
) -> TableHashEntry:
    """Return a manifest entry for a supported table file."""

    if path.suffix.lower() == ".csv":
        result = hash_csv_with_metadata(path, chunk_rows=csv_chunk_rows)
        source_size_bytes, source_mtime_ns = _source_file_stat_metadata(path)
        return TableHashEntry(
            key=output_key(path, work_dir, output_dir),
            hash=result.hash,
            row_count=result.row_count,
            columns=result.columns,
            physical_format="csv",
            source_path=str(path),
            source_size_bytes=source_size_bytes,
            source_mtime_ns=source_mtime_ns,
        )

    result = hash_parquet_with_metadata(path, chunk_rows=csv_chunk_rows)
    source_size_bytes, source_mtime_ns = _source_file_stat_metadata(path)
    return TableHashEntry(
        key=output_key(path, work_dir, output_dir),
        hash=result.hash,
        row_count=result.row_count,
        columns=result.columns,
        physical_format=path.suffix.lower().lstrip("."),
        source_path=str(path),
        source_size_bytes=source_size_bytes,
        source_mtime_ns=source_mtime_ns,
    )


def output_key(path: Path, work_dir: Path, output_dir: Path) -> str:
    """Return a stable key for an output path.

    Args:
        path: Output file path.
        work_dir: Configured working directory.
        output_dir: Configured final output directory.

    Returns:
        Normalized key string for the output.
    """

    return logical_output_key(path, work_dir, output_dir)


def collect_output_hashes(
    output_paths: Iterable[Path],
    work_dir: Path,
    output_dir: Path,
    *,
    csv_chunk_rows: int = DEFAULT_CSV_HASH_CHUNK_ROWS,
) -> dict[str, str]:
    """Hash output CSV files from the pipeline.

    Args:
        output_paths: Iterable of output file paths.
        work_dir: Working directory used by the pipeline.
        output_dir: Final output directory used by the pipeline.

    Returns:
        Mapping of output keys to hashes.
    """

    entries = collect_output_entries(
        output_paths,
        work_dir=work_dir,
        output_dir=output_dir,
        csv_chunk_rows=csv_chunk_rows,
    )
    return {key: entry.hash for key, entry in entries.items()}


def collect_output_entries(
    output_paths: Iterable[Path],
    work_dir: Path,
    output_dir: Path,
    *,
    csv_chunk_rows: int = DEFAULT_CSV_HASH_CHUNK_ROWS,
) -> dict[str, TableHashEntry]:
    """Hash output table files from a pipeline run with manifest metadata."""

    entries: dict[str, TableHashEntry] = {}
    for path in output_paths:
        entry = table_hash_entry(
            path,
            work_dir,
            output_dir,
            csv_chunk_rows=csv_chunk_rows,
        )
        _add_entry(entries, entry)
    return entries


def collect_directory_hashes(
    *,
    work_dir: Path,
    output_dir: Path,
    scope: HashScope = "all",
    csv_chunk_rows: int = DEFAULT_CSV_HASH_CHUNK_ROWS,
) -> dict[str, str]:
    """Hash all supported table files under work and output directories."""

    entries = collect_directory_entries(
        work_dir=work_dir,
        output_dir=output_dir,
        scope=scope,
        csv_chunk_rows=csv_chunk_rows,
    )
    return {key: entry.hash for key, entry in entries.items()}


def collect_directory_entries(
    *,
    work_dir: Path,
    output_dir: Path,
    scope: HashScope = "all",
    csv_chunk_rows: int = DEFAULT_CSV_HASH_CHUNK_ROWS,
) -> dict[str, TableHashEntry]:
    """Hash supported table files under selected work/output directories."""

    _validate_scope(scope)
    roots: list[Path] = []
    if scope in {"work", "all"}:
        roots.append(work_dir)
    if scope in {"final", "all"}:
        roots.append(output_dir)

    entries: dict[str, TableHashEntry] = {}
    for root in roots:
        if not root.exists():
            raise FileNotFoundError(root)
        for path in sorted(root.rglob("*")):
            if _is_noise_path(path, root):
                continue
            if not path.is_file() or path.suffix.lower() not in TABLE_SUFFIXES:
                continue
            entry = table_hash_entry(
                path,
                work_dir,
                output_dir,
                csv_chunk_rows=csv_chunk_rows,
            )
            _add_entry(entries, entry)
    return entries


def write_hash_manifest(
    directory: Path,
    hashes: Mapping[str, str] | Mapping[str, TableHashEntry],
    *,
    scope: HashScope | None = None,
    work_dir: Path | None = None,
    output_dir: Path | None = None,
    generated_at: str | None = None,
) -> Path:
    """Write a hash manifest JSON file under ``directory``.

    Args:
        directory: Directory to receive the manifest.
        hashes: Mapping of output keys to hashes or metadata entries.
        scope: Optional hashed-output scope used to create the manifest.
        work_dir: Optional work-table root used for manifest generation.
        output_dir: Optional final-output root used for manifest generation.
        generated_at: Optional ISO timestamp; defaults to the current UTC time.

    Returns:
        Path to the written manifest.
    """

    if scope is not None:
        _validate_scope(scope)

    directory.mkdir(parents=True, exist_ok=True)
    manifest_path = directory / HASH_MANIFEST_FILENAME
    entries = _coerce_entries(hashes)
    payload = {
        "schema_version": 2,
        "generated_at": generated_at or datetime.now(timezone.utc).isoformat(),
        "hash_algorithm": HASH_ALGORITHM,
        "hashes": {key: entry.hash for key, entry in sorted(entries.items())},
        "tables": [_entry_to_payload(entry) for _, entry in sorted(entries.items())],
    }
    if scope is not None:
        payload["scope"] = scope
    if work_dir is not None:
        payload["work_dir"] = str(work_dir.resolve(strict=False))
    if output_dir is not None:
        payload["output_dir"] = str(output_dir.resolve(strict=False))
    write_text_atomic(manifest_path, json.dumps(payload, indent=2, sort_keys=True))
    return manifest_path


def load_hash_manifest(path: Path) -> dict[str, str]:
    """Load hash manifest data from a directory or file path."""

    entries = load_hash_manifest_entries(path)
    return {key: entry.hash for key, entry in entries.items()}


def load_hash_manifest_entries(path: Path) -> dict[str, TableHashEntry]:
    """Load hash manifest entries from a directory or file path."""

    manifest_path = path
    if path.is_dir():
        manifest_path = path / HASH_MANIFEST_FILENAME
    raw = json.loads(manifest_path.read_text())
    if not isinstance(raw, dict):
        raise ValueError("Hash manifest must be a JSON object.")
    schema_version = raw.get("schema_version")
    if schema_version not in {1, 2}:
        raise ValueError(f"Unsupported hash manifest schema version: {schema_version}")
    if schema_version == 2 and isinstance(raw.get("tables"), list):
        return _load_v2_manifest_entries(raw["tables"])
    hashes = raw.get("hashes")
    if not isinstance(hashes, dict):
        raise ValueError("Hash manifest 'hashes' must be a JSON object.")
    normalized: dict[str, TableHashEntry] = {}
    for key, value in hashes.items():
        if not isinstance(key, str) or not isinstance(value, str):
            raise ValueError("Hash manifest entries must be string mappings.")
        normalized[key] = TableHashEntry(key=key, hash=value)
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


def compare_manifest_entries(
    current: Mapping[str, TableHashEntry],
    baseline: Mapping[str, TableHashEntry],
) -> ManifestComparisonResult:
    """Compare current manifest entries against baseline manifest entries."""

    missing = tuple(sorted(set(baseline) - set(current)))
    extra = tuple(sorted(set(current) - set(baseline)))
    hash_mismatched: dict[str, tuple[str, str]] = {}
    row_count_mismatched: dict[str, tuple[int | None, int | None]] = {}
    columns_mismatched: dict[
        str,
        tuple[tuple[str, ...] | None, tuple[str, ...] | None],
    ] = {}
    for key in sorted(set(current) & set(baseline)):
        baseline_entry = baseline[key]
        current_entry = current[key]
        if baseline_entry.hash != current_entry.hash:
            hash_mismatched[key] = (baseline_entry.hash, current_entry.hash)
        if (
            baseline_entry.row_count is not None
            and current_entry.row_count is not None
            and baseline_entry.row_count != current_entry.row_count
        ):
            row_count_mismatched[key] = (
                baseline_entry.row_count,
                current_entry.row_count,
            )
        if (
            baseline_entry.columns is not None
            and current_entry.columns is not None
            and baseline_entry.columns != current_entry.columns
        ):
            columns_mismatched[key] = (baseline_entry.columns, current_entry.columns)
    return ManifestComparisonResult(
        missing=missing,
        extra=extra,
        hash_mismatched=hash_mismatched,
        row_count_mismatched=row_count_mismatched,
        columns_mismatched=columns_mismatched,
    )


def _ensure_temp_dir(
    path: Path,
    temp_dir: tempfile.TemporaryDirectory[str] | None,
) -> tempfile.TemporaryDirectory[str]:
    if temp_dir is not None:
        return temp_dir
    return tempfile.TemporaryDirectory(prefix=".trinetx-hash-", dir=path.parent)


def _render_csv_row(values: Sequence[str]) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(values)
    return buffer.getvalue().encode("utf-8")


def _write_sorted_csv_chunk(
    rows: list[tuple[str, ...]],
    directory: Path,
    index: int,
) -> Path:
    path = directory / f"chunk-{index:06d}.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerows(sorted(rows))
    return path


def _hash_sorted_csv_chunks(
    hasher: hashlib._Hash,
    chunk_paths: Sequence[Path],
) -> None:
    handles = [path.open(newline="", encoding="utf-8") for path in chunk_paths]
    readers = [csv.reader(handle) for handle in handles]
    heap: list[tuple[tuple[str, ...], int]] = []
    try:
        for index, reader in enumerate(readers):
            try:
                row = tuple(next(reader))
            except StopIteration:
                continue
            heapq.heappush(heap, (row, index))

        while heap:
            row, index = heapq.heappop(heap)
            hasher.update(_render_csv_row(row))
            try:
                next_row = tuple(next(readers[index]))
            except StopIteration:
                continue
            heapq.heappush(heap, (next_row, index))
    finally:
        for handle in handles:
            handle.close()


def _validate_csv_row_width(
    path: Path, row: Sequence[str], header: Sequence[str]
) -> None:
    if len(row) == len(header):
        return
    raise ValueError(
        f"CSV row has {len(row)} field(s), expected {len(header)} in {path}."
    )


def _is_noise_path(path: Path, root: Path) -> bool:
    try:
        relative = path.relative_to(root)
    except ValueError:
        relative = path
    return any(
        part.startswith(".") or part in NOISE_PATH_PARTS for part in relative.parts
    )


def _add_entry(entries: dict[str, TableHashEntry], entry: TableHashEntry) -> None:
    existing = entries.get(entry.key)
    if existing is None:
        entries[entry.key] = entry
        return
    if existing.hash == entry.hash:
        return
    first_path = existing.source_path or "<unknown>"
    second_path = entry.source_path or "<unknown>"
    raise ValueError(
        "Conflicting duplicate logical output "
        f"'{entry.key}': {first_path} and {second_path}"
    )


def _coerce_entries(
    values: Mapping[str, str] | Mapping[str, TableHashEntry],
) -> dict[str, TableHashEntry]:
    entries: dict[str, TableHashEntry] = {}
    for key, value in values.items():
        if isinstance(value, TableHashEntry):
            entry = value
        elif isinstance(value, str):
            entry = TableHashEntry(key=key, hash=value)
        else:
            raise ValueError("Hash manifest values must be strings or TableHashEntry.")
        entries[key] = entry
    return entries


def _entry_to_payload(entry: TableHashEntry) -> dict[str, object]:
    return {
        "key": entry.key,
        "hash": entry.hash,
        "row_count": entry.row_count,
        "columns": list(entry.columns) if entry.columns is not None else None,
        "physical_format": entry.physical_format,
        "source_path": entry.source_path,
        "source_size_bytes": entry.source_size_bytes,
        "source_mtime_ns": entry.source_mtime_ns,
    }


def _load_v2_manifest_entries(raw_tables: list[object]) -> dict[str, TableHashEntry]:
    entries: dict[str, TableHashEntry] = {}
    for raw_entry in raw_tables:
        if not isinstance(raw_entry, dict):
            raise ValueError("Hash manifest table entries must be JSON objects.")
        key = raw_entry.get("key")
        value = raw_entry.get("hash")
        if not isinstance(key, str) or not isinstance(value, str):
            raise ValueError("Hash manifest table entries require string key/hash.")
        raw_columns = raw_entry.get("columns")
        columns = None
        if raw_columns is not None:
            if not isinstance(raw_columns, list) or not all(
                isinstance(column, str) for column in raw_columns
            ):
                raise ValueError("Hash manifest table columns must be strings.")
            columns = tuple(raw_columns)
        row_count = raw_entry.get("row_count")
        if row_count is not None and not isinstance(row_count, int):
            raise ValueError("Hash manifest table row_count must be an integer.")
        physical_format = raw_entry.get("physical_format")
        if physical_format is not None and not isinstance(physical_format, str):
            raise ValueError("Hash manifest physical_format must be a string.")
        source_path = raw_entry.get("source_path")
        if source_path is not None and not isinstance(source_path, str):
            raise ValueError("Hash manifest source_path must be a string.")
        source_size_bytes = raw_entry.get("source_size_bytes")
        if source_size_bytes is not None and not isinstance(source_size_bytes, int):
            raise ValueError("Hash manifest source_size_bytes must be an integer.")
        source_mtime_ns = raw_entry.get("source_mtime_ns")
        if source_mtime_ns is not None and not isinstance(source_mtime_ns, int):
            raise ValueError("Hash manifest source_mtime_ns must be an integer.")
        _add_entry(
            entries,
            TableHashEntry(
                key=key,
                hash=value,
                row_count=row_count,
                columns=columns,
                physical_format=physical_format,
                source_path=source_path,
                source_size_bytes=source_size_bytes,
                source_mtime_ns=source_mtime_ns,
            ),
        )
    return entries


def _source_file_stat_metadata(path: Path) -> tuple[int, int]:
    source_stat = path.stat()
    return source_stat.st_size, source_stat.st_mtime_ns


def _validate_scope(scope: str) -> None:
    if scope not in HASH_SCOPE_VALUES:
        allowed = ", ".join(sorted(HASH_SCOPE_VALUES))
        raise ValueError(f"Hash scope must be one of: {allowed}.")

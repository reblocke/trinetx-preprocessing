"""Intermediate table storage helpers."""

from __future__ import annotations

import tempfile
from collections.abc import Iterable, Sequence
from pathlib import Path
from types import TracebackType

import pandas as pd

from .config import Config
from .filesystem import remove_tree_strict
from .io.csv import iter_csv

CSV_FORMAT = "csv"
PARQUET_FORMAT = "parquet"


class PartitionedParquetStore:
    """Temporary, bounded hash partitions written through Parquet writers."""

    def __init__(
        self,
        work_dir: Path,
        *,
        prefix: str,
        key_columns: Sequence[str],
        bucket_count: int = 256,
        row_group_size: int = 250_000,
        cleanup_context: str | None = None,
    ) -> None:
        if bucket_count <= 0 or bucket_count & (bucket_count - 1):
            raise ValueError("bucket_count must be a positive power of two.")
        if row_group_size <= 0:
            raise ValueError("row_group_size must be positive.")
        self.work_dir = work_dir
        self.prefix = prefix
        self.key_columns = tuple(key_columns)
        self.bucket_count = bucket_count
        self.row_group_size = row_group_size
        self.cleanup_context = cleanup_context or f"{prefix} scratch"
        self.path: Path | None = None
        self._writers: dict[int, object] = {}
        self._paths: dict[int, Path] = {}
        self._schema = None
        self._sealed = False

    def __enter__(self) -> "PartitionedParquetStore":
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self.path = Path(tempfile.mkdtemp(prefix=self.prefix, dir=self.work_dir))
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.seal()
        if self.path is not None:
            remove_tree_strict(self.path, context=self.cleanup_context)

    def add_frame(self, frame: pd.DataFrame) -> None:
        """Partition and append a non-empty frame."""

        if frame.empty:
            return
        if self._sealed:
            raise RuntimeError("Cannot add rows after partition store is sealed.")
        missing = [column for column in self.key_columns if column not in frame]
        if missing:
            raise ValueError(f"Partition keys are missing: {', '.join(missing)}")

        bucket_ids = stable_bucket_ids(
            frame.loc[:, self.key_columns],
            bucket_count=self.bucket_count,
        )
        for bucket, rows in frame.groupby(bucket_ids, sort=False):
            self._write_bucket(int(bucket), rows)

    def iter_frames(
        self,
        *,
        columns: Sequence[str] | None = None,
    ) -> Iterable[tuple[int, pd.DataFrame]]:
        """Seal writers and yield populated partitions in bucket order."""

        self.seal()
        for bucket, path in sorted(self._paths.items()):
            yield (
                bucket,
                pd.read_parquet(
                    path,
                    columns=list(columns) if columns is not None else None,
                ),
            )

    def read_frame(
        self,
        bucket: int,
        *,
        columns: Sequence[str] | None = None,
    ) -> pd.DataFrame | None:
        """Read one populated partition, or return ``None`` when absent."""

        self.seal()
        path = self._paths.get(bucket)
        if path is None:
            return None
        return pd.read_parquet(
            path,
            columns=list(columns) if columns is not None else None,
        )

    def seal(self) -> None:
        """Close all writers so partitions can be read."""

        if self._sealed:
            return
        for writer in self._writers.values():
            writer.close()
        self._writers.clear()
        self._sealed = True

    def disk_size_bytes(self) -> int:
        """Return the current physical size of populated partitions."""

        self.seal()
        return sum(path.stat().st_size for path in self._paths.values())

    def _write_bucket(self, bucket: int, frame: pd.DataFrame) -> None:
        import pyarrow as pa
        import pyarrow.parquet as pq

        if self.path is None:
            raise RuntimeError("Partition store is not open.")
        table = pa.Table.from_pandas(frame, preserve_index=False)
        if self._schema is None:
            self._schema = table.schema
        elif table.schema != self._schema:
            table = table.cast(self._schema, safe=False)

        writer = self._writers.get(bucket)
        if writer is None:
            path = self.path / f"bucket-{bucket:03}.parquet"
            writer = pq.ParquetWriter(
                path,
                self._schema,
                compression="snappy",
                use_dictionary=True,
            )
            self._writers[bucket] = writer
            self._paths[bucket] = path
        writer.write_table(table, row_group_size=self.row_group_size)


class PartitionedKeyLookup:
    """Disk-backed exact-key lookup built on bounded Parquet partitions."""

    def __init__(
        self,
        work_dir: Path,
        *,
        prefix: str,
        key_column: str,
        stored_columns: Sequence[str],
        bucket_count: int = 256,
        row_group_size: int = 250_000,
        require_unique: bool = False,
        cleanup_context: str | None = None,
    ) -> None:
        if key_column not in stored_columns:
            raise ValueError("key_column must be included in stored_columns.")
        self.key_column = key_column
        self.stored_columns = tuple(stored_columns)
        self.bucket_count = bucket_count
        self.require_unique = require_unique
        self._store = PartitionedParquetStore(
            work_dir,
            prefix=prefix,
            key_columns=[key_column],
            bucket_count=bucket_count,
            row_group_size=row_group_size,
            cleanup_context=cleanup_context,
        )
        self._finalized = False
        self._unique_count: int | None = None

    def __enter__(self) -> "PartitionedKeyLookup":
        self._store.__enter__()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self._store.__exit__(exc_type, exc, tb)

    def add_frame(self, frame: pd.DataFrame) -> None:
        """Append lookup rows after validating their stored schema."""

        if self._finalized:
            raise RuntimeError("Cannot add lookup rows after finalization.")
        missing = [column for column in self.stored_columns if column not in frame]
        if missing:
            raise ValueError(f"Lookup columns are missing: {', '.join(missing)}")
        selected = frame.loc[:, self.stored_columns]
        if self.require_unique and selected[self.key_column].duplicated().any():
            raise ValueError(f"Duplicate lookup key: {self.key_column}")
        self._store.add_frame(selected)

    def finalize(self) -> None:
        """Seal partitions, validate uniqueness, and count distinct keys."""

        if self._finalized:
            return
        unique_count = 0
        for _, frame in self._store.iter_frames(columns=[self.key_column]):
            keys = frame[self.key_column]
            if self.require_unique and keys.duplicated().any():
                raise ValueError(f"Duplicate lookup key: {self.key_column}")
            unique_count += int(keys.nunique(dropna=False))
        self._unique_count = unique_count
        self._finalized = True

    def frame_for_keys(self, keys: pd.Series) -> pd.DataFrame:
        """Return stored rows matching the requested exact keys."""

        self.finalize()
        requested = (
            keys.dropna().astype("string").drop_duplicates().reset_index(drop=True)
        )
        if requested.empty:
            return pd.DataFrame(columns=self.stored_columns)
        requested_frame = pd.DataFrame({self.key_column: requested})
        requested_frame["_bucket"] = stable_bucket_ids(
            requested_frame.loc[:, [self.key_column]],
            bucket_count=self.bucket_count,
        ).to_numpy()
        frames: list[pd.DataFrame] = []
        for bucket, bucket_keys in requested_frame.groupby("_bucket", sort=False):
            stored = self._store.read_frame(int(bucket), columns=self.stored_columns)
            if stored is None or stored.empty:
                continue
            matches = stored.loc[
                stored[self.key_column].isin(bucket_keys[self.key_column]),
                self.stored_columns,
            ]
            if not matches.empty:
                frames.append(matches)
        if not frames:
            return pd.DataFrame(columns=self.stored_columns)
        result = pd.concat(frames, ignore_index=True)
        if not self.require_unique:
            result = result.drop_duplicates(subset=[self.key_column], keep="first")
        return result.reset_index(drop=True)

    def matching_keys(self, keys: pd.Series) -> set[str]:
        """Return the requested keys present in the lookup."""

        matches = self.frame_for_keys(keys)
        return set(matches[self.key_column].dropna().astype("string"))

    def unique_count(self) -> int:
        """Return the number of distinct keys in the sealed lookup."""

        self.finalize()
        return int(self._unique_count or 0)

    def disk_size_bytes(self) -> int:
        """Return compressed partition footprint."""

        return self._store.disk_size_bytes()


def stable_bucket_ids(frame: pd.DataFrame, *, bucket_count: int) -> pd.Series:
    """Return vectorized deterministic partition IDs for one or more keys."""

    if bucket_count <= 0 or bucket_count & (bucket_count - 1):
        raise ValueError("bucket_count must be a positive power of two.")
    normalized = frame.astype("string").fillna("<NA>")
    hashes = pd.util.hash_pandas_object(normalized, index=False)
    return (hashes & (bucket_count - 1)).astype("int64")


class WorkTableWriter:
    """Append-capable writer for a configured work table."""

    def __init__(self, config: Config, logical_name: str) -> None:
        self.config = config
        self.logical_name = logical_name
        self.primary_path = work_table_path(config, logical_name)
        self._parquet_writer = None
        self._csv_written = False
        self.rows_written = 0
        self.written_paths: list[Path] = []

    def __enter__(self) -> "WorkTableWriter":
        self.config.work_dir.mkdir(parents=True, exist_ok=True)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def write(self, df: pd.DataFrame) -> None:
        """Append ``df`` to the configured work table."""

        if self.config.storage.intermediate_format == PARQUET_FORMAT:
            self._write_parquet(df)
            if self.config.storage.emit_legacy_csv_intermediates:
                self._write_csv(
                    legacy_csv_path(self.config, self.logical_name),
                    df,
                    count_rows=False,
                )
            return

        self._write_csv(self.primary_path, df)

    def close(self) -> None:
        """Close any open file handles."""

        if self._parquet_writer is not None:
            self._parquet_writer.close()
            self._parquet_writer = None

    def _write_parquet(self, df: pd.DataFrame) -> None:
        import pyarrow as pa
        import pyarrow.parquet as pq

        table = pa.Table.from_pandas(df, preserve_index=False)
        if self._parquet_writer is None:
            self.primary_path.parent.mkdir(parents=True, exist_ok=True)
            self._parquet_writer = pq.ParquetWriter(
                self.primary_path,
                table.schema,
                compression="snappy",
                use_dictionary=True,
            )
            self.written_paths.append(self.primary_path)
        self._parquet_writer.write_table(
            table,
            row_group_size=self.config.storage.parquet_row_group_size,
        )
        self.rows_written += len(df)

    def _write_csv(
        self,
        path: Path,
        df: pd.DataFrame,
        *,
        count_rows: bool = True,
    ) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        mode = "a" if self._csv_written else "w"
        df.to_csv(path, index=False, mode=mode, header=not self._csv_written)
        if not self._csv_written:
            self.written_paths.append(path)
            self._csv_written = True
        if count_rows:
            self.rows_written += len(df)


def write_work_table(
    config: Config,
    logical_name: str,
    df: pd.DataFrame,
) -> list[Path]:
    """Write a work table using the configured intermediate format.

    ``logical_name`` should use the legacy CSV filename. When Parquet is enabled,
    the physical primary file uses the same stem with a ``.parquet`` suffix.
    """

    with WorkTableWriter(config, logical_name) as writer:
        writer.write(df)
        return list(writer.written_paths)


def work_table_path(config: Config, logical_name: str) -> Path:
    """Return the configured primary work-table path for a legacy logical name."""

    suffix = (
        ".parquet" if config.storage.intermediate_format == PARQUET_FORMAT else ".csv"
    )
    return _with_suffix(config.work_dir / logical_name, suffix)


def resolve_work_table(config: Config, logical_name: str) -> Path:
    """Return the existing work-table path for a logical name.

    The configured primary format is preferred, with legacy CSV as fallback.
    """

    primary_path = work_table_path(config, logical_name)
    if primary_path.exists():
        return primary_path

    csv_path = legacy_csv_path(config, logical_name)
    if csv_path.exists():
        return csv_path

    return primary_path


def legacy_csv_path(config: Config, logical_name: str) -> Path:
    """Return the legacy CSV path for a work-table logical name."""

    return _with_suffix(config.work_dir / logical_name, ".csv")


def find_work_tables(config: Config, logical_pattern: str) -> list[Path]:
    """Find work tables for a legacy CSV glob pattern.

    The configured primary format is preferred. CSV is used as a fallback so
    users can still inspect or compare legacy work directories.
    """

    primary_pattern = _pattern_with_suffix(logical_pattern, _primary_suffix(config))
    primary_paths = sorted(config.work_dir.glob(primary_pattern))
    if primary_paths:
        return primary_paths

    csv_pattern = _pattern_with_suffix(logical_pattern, ".csv")
    return sorted(config.work_dir.glob(csv_pattern))


def read_table(
    path: Path,
    *,
    usecols: Sequence[str] | None = None,
    dtype: dict[str, str] | str | None = None,
) -> pd.DataFrame:
    """Read a CSV or Parquet table with optional column and dtype selection."""

    if path.suffix.lower() == ".parquet":
        frame = pd.read_parquet(path, columns=list(usecols) if usecols else None)
        return _cast_frame(frame, dtype)

    return pd.read_csv(path, usecols=usecols, dtype=dtype)


def iter_work_tables(
    paths: Iterable[Path],
    *,
    chunksize: int | None = None,
    usecols: Sequence[str] | None = None,
    dtype: dict[str, str] | str | None = None,
) -> Iterable[pd.DataFrame]:
    """Iterate CSV or Parquet work tables.

    CSV files stream by chunks when ``chunksize`` is provided. Parquet files use
    record batches with the same row bound, or one table per file when chunking
    is disabled.
    """

    for path in paths:
        if path.suffix.lower() == ".parquet":
            if chunksize is None:
                yield read_table(path, usecols=usecols, dtype=dtype)
            else:
                yield from _iter_parquet_batches(
                    path,
                    chunksize=chunksize,
                    usecols=usecols,
                    dtype=dtype,
                )
        else:
            yield from iter_csv(path, chunksize=chunksize, usecols=usecols, dtype=dtype)


def logical_output_key(path: Path, work_dir: Path, output_dir: Path) -> str:
    """Return a stable regression key, independent of intermediate suffix."""

    if path.is_relative_to(work_dir):
        relative = path.relative_to(work_dir)
        if relative.suffix.lower() == ".parquet":
            relative = relative.with_suffix(".csv")
        return str(Path("work_dir") / relative)
    if path.is_relative_to(output_dir):
        return str(Path("output_dir") / path.relative_to(output_dir))
    if path.suffix.lower() == ".parquet":
        return path.with_suffix(".csv").name
    return path.name


def _primary_suffix(config: Config) -> str:
    return (
        ".parquet" if config.storage.intermediate_format == PARQUET_FORMAT else ".csv"
    )


def _with_suffix(path: Path, suffix: str) -> Path:
    if path.suffix:
        return path.with_suffix(suffix)
    return path.with_name(f"{path.name}{suffix}")


def _pattern_with_suffix(pattern: str, suffix: str) -> str:
    path = Path(pattern)
    if path.suffix:
        return str(path.with_suffix(suffix))
    return f"{pattern}{suffix}"


def _cast_frame(
    frame: pd.DataFrame,
    dtype: dict[str, str] | str | None,
) -> pd.DataFrame:
    if dtype is None:
        return frame
    if isinstance(dtype, str):
        return frame.astype(dtype)
    applicable = {column: kind for column, kind in dtype.items() if column in frame}
    if not applicable:
        return frame
    return frame.astype(applicable)


def _iter_parquet_batches(
    path: Path,
    *,
    chunksize: int,
    usecols: Sequence[str] | None,
    dtype: dict[str, str] | str | None,
) -> Iterable[pd.DataFrame]:
    if chunksize <= 0:
        raise ValueError("chunksize must be a positive integer for Parquet batches.")

    import pyarrow.parquet as pq

    parquet_file = pq.ParquetFile(path)
    columns = list(usecols) if usecols else None
    for batch in parquet_file.iter_batches(batch_size=chunksize, columns=columns):
        frame = batch.to_pandas()
        yield _cast_frame(frame, dtype)

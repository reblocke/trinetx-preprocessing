"""Intermediate table storage helpers."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from pathlib import Path
from types import TracebackType

import pandas as pd

from .config import Config
from .io.csv import iter_csv

CSV_FORMAT = "csv"
PARQUET_FORMAT = "parquet"


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
            self._parquet_writer = pq.ParquetWriter(self.primary_path, table.schema)
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

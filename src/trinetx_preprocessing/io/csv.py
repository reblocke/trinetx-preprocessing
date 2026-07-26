"""CSV streaming utilities for TriNetX preprocessing."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from pathlib import Path

import pandas as pd


def read_csv_head(path: Path | str, n: int = 5) -> pd.DataFrame:
    """Read the first ``n`` rows of a CSV file.

    Args:
        path: Path to the CSV file.
        n: Number of rows to read (use ``0`` for header-only).

    Returns:
        DataFrame containing the requested head rows.
    """

    if n < 0:
        raise ValueError("n must be greater than or equal to 0.")
    csv_path = Path(path)
    return pd.read_csv(csv_path, nrows=n)


def iter_csv(
    path: Path | str,
    chunksize: int | None = None,
    usecols: Sequence[str] | None = None,
    dtype: dict[str, str] | str | None = None,
    parse_dates: Sequence[str] | None = None,
    preserve_source_tokens: bool = False,
) -> Iterator[pd.DataFrame]:
    """Iterate over CSV rows in streaming chunks.

    Args:
        path: Path to the CSV file.
        chunksize: Number of rows per chunk. If ``None``, yields one DataFrame.
        usecols: Optional subset of columns to read.
        dtype: Optional dtype mapping or single dtype.
        parse_dates: Optional date columns to parse.
        preserve_source_tokens: Preserve literal pandas NA-like tokens such as
            ``NA``, ``N/A``, and ``NULL`` while still treating empty CSV fields
            as missing.

    Yields:
        DataFrames containing the requested rows.
    """

    csv_path = Path(path)
    read_options: dict[str, object] = {}
    if preserve_source_tokens:
        read_options.update(
            {
                "keep_default_na": False,
                "na_values": [""],
            }
        )
    if chunksize is None:
        yield pd.read_csv(
            csv_path,
            usecols=usecols,
            dtype=dtype,
            parse_dates=parse_dates,
            **read_options,
        )
        return
    if chunksize <= 0:
        raise ValueError("chunksize must be a positive integer.")
    reader = pd.read_csv(
        csv_path,
        chunksize=chunksize,
        usecols=usecols,
        dtype=dtype,
        parse_dates=parse_dates,
        **read_options,
    )
    yield from reader


def iter_many_csv(
    paths: Sequence[Path | str],
    chunksize: int | None = None,
    usecols: Sequence[str] | None = None,
    dtype: dict[str, str] | str | None = None,
    parse_dates: Sequence[str] | None = None,
    preserve_source_tokens: bool = False,
) -> Iterator[pd.DataFrame]:
    """Iterate over multiple CSV files in sequence.

    Args:
        paths: Paths to CSV files.
        chunksize: Number of rows per chunk. If ``None``, yields one DataFrame per file.
        usecols: Optional subset of columns to read.
        dtype: Optional dtype mapping or single dtype.
        parse_dates: Optional date columns to parse.
        preserve_source_tokens: Preserve literal pandas NA-like source tokens.

    Yields:
        DataFrames from each CSV file in order.
    """

    for path in paths:
        yield from iter_csv(
            path,
            chunksize=chunksize,
            usecols=usecols,
            dtype=dtype,
            parse_dates=parse_dates,
            preserve_source_tokens=preserve_source_tokens,
        )

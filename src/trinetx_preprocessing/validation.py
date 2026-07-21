"""Schema validation utilities."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from pathlib import Path

from pandas.errors import EmptyDataError

from .io.csv import read_csv_head


def require_columns(
    df_or_columns: Iterable[object],
    required: Sequence[str],
    context: str,
) -> None:
    """Ensure required columns exist in a DataFrame or iterable.

    Args:
        df_or_columns: DataFrame (or similar) with ``.columns`` or iterable of names.
        required: Required column names.
        context: Human-readable identifier for error messages.

    Raises:
        ValueError: If required columns are missing.
        TypeError: If ``df_or_columns`` is not iterable.
    """

    columns = _normalize_columns(df_or_columns)
    missing = [column for column in required if column not in columns]
    if missing:
        missing_list = ", ".join(missing)
        raise ValueError(f"{context} is missing required columns: {missing_list}")


def validate_csv_columns(path: Path | str, required_cols: Sequence[str]) -> None:
    """Validate CSV headers against required columns.

    Args:
        path: Path to the CSV file.
        required_cols: Required column names.
    """

    csv_path = Path(path)
    try:
        sample = read_csv_head(csv_path, n=0)
    except EmptyDataError as exc:
        raise ValueError(f"Input file is empty: {csv_path}") from exc
    require_columns(sample, required_cols, context=str(csv_path))


def _normalize_columns(df_or_columns: Iterable[object]) -> list[object]:
    if hasattr(df_or_columns, "columns"):
        columns = list(getattr(df_or_columns, "columns"))
    elif isinstance(df_or_columns, str):
        raise TypeError("Expected DataFrame or iterable of column names, got str.")
    else:
        try:
            columns = list(df_or_columns)
        except TypeError as exc:  # pragma: no cover - defensive
            raise TypeError("Expected DataFrame or iterable of column names.") from exc

    normalized: list[object] = []
    for column in columns:
        if isinstance(column, str):
            normalized.append(column.strip())
        else:
            normalized.append(column)
    return normalized

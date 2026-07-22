"""Shared parsing for ISO and compact TriNetX date/timestamp values."""

from __future__ import annotations

import pandas as pd
from pandas.api.types import is_datetime64_any_dtype


def parse_trinetx_datetime(series: pd.Series) -> pd.Series:
    """Parse mixed ISO, ``YYYYMMDD``, and ``YYYYMMDDHHMMSS`` values."""

    if is_datetime64_any_dtype(series.dtype):
        return pd.to_datetime(series)

    text = series.astype("string").str.strip()
    parsed = pd.Series(pd.NaT, index=series.index, dtype="datetime64[ns]")
    compact_date = text.str.fullmatch(r"\d{8}", na=False)
    compact_timestamp = text.str.fullmatch(r"\d{14}", na=False)
    parsed.loc[compact_date] = pd.to_datetime(
        text.loc[compact_date],
        format="%Y%m%d",
        errors="coerce",
    )
    parsed.loc[compact_timestamp] = pd.to_datetime(
        text.loc[compact_timestamp],
        format="%Y%m%d%H%M%S",
        errors="coerce",
    )
    other = ~(compact_date | compact_timestamp) & text.notna() & text.ne("")
    parsed.loc[other] = pd.to_datetime(
        text.loc[other],
        format="mixed",
        errors="coerce",
    )
    invalid = text.notna() & text.ne("") & parsed.isna()
    if invalid.any():
        raise ValueError(
            f"Could not parse {int(invalid.sum())} TriNetX date/time value(s)."
        )
    return parsed

"""Shared helpers for splitting normalized rows into overlapping code groups."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

import pandas as pd

from ..validation import require_columns


class CodeGroup(Protocol):
    """Code-group definition required by the splitter."""

    name: str

    def matches(self, code: object, code_system: object | None = None) -> bool: ...


def split_rows_by_code_groups(
    df: pd.DataFrame,
    *,
    columns: Sequence[str],
    code_groups: Sequence[CodeGroup],
    context: str,
    code_column: str = "code",
) -> dict[str, pd.DataFrame]:
    """Split rows into possibly overlapping code groups.

    Rules are evaluated once per unique code in the chunk, then rows are fanned
    out to every matching group. Overlapping outputs remain supported.
    """

    require_columns(df, columns, context=context)
    if code_column not in columns:
        raise ValueError(f"{code_column!r} must be present in columns.")

    empty = df.iloc[0:0].loc[:, columns].copy().reset_index(drop=True)
    codes = df[code_column].astype("string")
    matched_codes_by_group = {group.name: set[str]() for group in code_groups}

    for raw_code in codes.dropna().unique():
        code = str(raw_code)
        for group in code_groups:
            if group.matches(code):
                matched_codes_by_group[group.name].add(code)

    split: dict[str, pd.DataFrame] = {}
    for group in code_groups:
        matched_codes = matched_codes_by_group[group.name]
        if not matched_codes:
            split[group.name] = empty.copy()
            continue

        mask = codes.isin(matched_codes)
        split[group.name] = df.loc[mask, columns].copy().reset_index(drop=True)

    return split

"""Helpers for compact, consolidated analysis-candidate work tables."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import pandas as pd

FEATURE_NAME_COLUMN = "source_name"
RFS_CATEGORY_COLUMN = "category"


def stack_grouped_frames(
    grouped: Mapping[str, pd.DataFrame],
    *,
    columns: Sequence[str],
) -> pd.DataFrame:
    """Stack overlapping named feature groups into one long table."""

    frames: list[pd.DataFrame] = []
    for name, frame in grouped.items():
        if frame.empty:
            continue
        indexed = frame.loc[:, columns].copy()
        indexed.insert(0, FEATURE_NAME_COLUMN, f"{name}.csv")
        frames.append(indexed)
    if not frames:
        return pd.DataFrame(columns=[FEATURE_NAME_COLUMN, *columns])
    return pd.concat(frames, ignore_index=True)


def stack_rfs_events(
    events: Mapping[str, pd.DataFrame],
    *,
    event_columns: Sequence[str],
) -> pd.DataFrame:
    """Stack category-specific RFS events into one candidate table."""

    frames: list[pd.DataFrame] = []
    for category, frame in events.items():
        if frame.empty:
            continue
        indexed = frame.loc[:, event_columns].copy()
        indexed.insert(0, RFS_CATEGORY_COLUMN, category)
        frames.append(indexed)
    if not frames:
        return pd.DataFrame(columns=[RFS_CATEGORY_COLUMN, *event_columns])
    return pd.concat(frames, ignore_index=True)

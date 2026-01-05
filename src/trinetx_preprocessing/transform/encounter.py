"""Pure encounter transforms derived from legacy notebooks."""

from __future__ import annotations

import pandas as pd

from ..validation import require_columns

RAW_ENCOUNTER_COLUMNS = [
    "encounter_id",
    "patient_id",
    "start_date",
    "end_date",
    "type",
    "start_date_derived_by_TriNetX",
    "end_date_derived_by_TriNetX",
    "derived_by_TriNetX",
    "source_id",
]

ENCOUNTER_COLUMNS = [
    "patient_id",
    "encounter_id",
    "start_date",
    "end_date",
    "type",
]

DROP_COLUMNS = [
    "start_date_derived_by_TriNetX",
    "end_date_derived_by_TriNetX",
    "derived_by_TriNetX",
    "source_id",
]

ENCOUNTER_TYPES = ("AMB", "EMER", "IMP")
ALLOWED_ENCOUNTER_TYPES = set(ENCOUNTER_TYPES)

DEFAULT_START_DATE = pd.Timestamp("2022-01-01")
DEFAULT_END_DATE_FILL = pd.Timestamp("2022-12-31")

ENCOUNTER_OUTPUT_COLUMNS = [
    "patient_id",
    "encounter_id",
    "start_date",
    "end_date",
    "type",
    "LOS",
]


def normalize_encounter_chunk(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize raw encounter exports for downstream processing.

    Args:
        df: Raw encounter DataFrame with TriNetX export columns.

    Returns:
        DataFrame with normalized columns and allowed encounter types only.
    """

    require_columns(df, RAW_ENCOUNTER_COLUMNS, context="Encounter raw input")

    normalized = df.drop(columns=DROP_COLUMNS).copy()
    normalized = normalized.loc[:, ENCOUNTER_COLUMNS]
    normalized["patient_id"] = normalized["patient_id"].astype("string")
    normalized["encounter_id"] = normalized["encounter_id"].astype("string")
    normalized["type"] = normalized["type"].astype("string")
    normalized = normalized.loc[normalized["type"].isin(ALLOWED_ENCOUNTER_TYPES)]
    normalized["start_date"] = pd.to_datetime(normalized["start_date"])
    normalized["end_date"] = pd.to_datetime(normalized["end_date"])
    return normalized.reset_index(drop=True)


def filter_encounters_by_type(
    df: pd.DataFrame,
    encounter_type: str,
    start_date_min: pd.Timestamp = DEFAULT_START_DATE,
    end_date_fill: pd.Timestamp = DEFAULT_END_DATE_FILL,
) -> pd.DataFrame:
    """Filter encounter rows for a specific care setting.

    Args:
        df: Normalized encounter DataFrame.
        encounter_type: Encounter type to retain (AMB, EMER, IMP).
        start_date_min: Minimum start date to include.
        end_date_fill: Date to use when end dates are missing.

    Returns:
        Filtered DataFrame with required encounter columns.
    """

    if encounter_type not in ALLOWED_ENCOUNTER_TYPES:
        raise ValueError(f"Unexpected encounter type: {encounter_type}")

    require_columns(df, ENCOUNTER_COLUMNS, context="Encounter normalized input")

    filtered = df.loc[:, ENCOUNTER_COLUMNS].copy()
    filtered["type"] = filtered["type"].astype("string")
    filtered["start_date"] = pd.to_datetime(filtered["start_date"])
    filtered["end_date"] = pd.to_datetime(filtered["end_date"])
    filtered = filtered.loc[filtered["start_date"] >= start_date_min]
    filtered = filtered.loc[filtered["type"] == encounter_type]
    filtered["end_date"] = filtered["end_date"].fillna(end_date_fill)
    filtered["end_date"] = pd.to_datetime(filtered["end_date"])
    return filtered.reset_index(drop=True)


def finalize_encounters(df: pd.DataFrame) -> pd.DataFrame:
    """Finalize encounter data by deduping and computing LOS.

    Args:
        df: Filtered encounter DataFrame.

    Returns:
        DataFrame sorted, deduplicated, and augmented with LOS.
    """

    require_columns(df, ENCOUNTER_COLUMNS, context="Encounter filtered input")

    if df.empty:
        return pd.DataFrame(columns=ENCOUNTER_OUTPUT_COLUMNS)

    finalized = df.loc[:, ENCOUNTER_COLUMNS].copy()
    finalized["start_date"] = pd.to_datetime(finalized["start_date"])
    finalized["end_date"] = pd.to_datetime(finalized["end_date"])
    finalized = finalized.sort_values(
        by=["start_date", "encounter_id"],
        ascending=[True, False],
    )
    finalized = finalized.drop_duplicates(subset=["encounter_id"], keep="first")
    finalized["LOS"] = (finalized["end_date"] - finalized["start_date"]).dt.days + 1
    finalized = finalized.loc[finalized["LOS"] > 0]
    return finalized.loc[:, ENCOUNTER_OUTPUT_COLUMNS].reset_index(drop=True)

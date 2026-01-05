"""Pure lab-results transforms derived from legacy notebooks."""

from __future__ import annotations

import pandas as pd

from ..validation import require_columns

RAW_LAB_COLUMNS = [
    "patient_id",
    "encounter_id",
    "code_system",
    "code",
    "date",
    "lab_result_num_val",
    "lab_result_text_val",
    "units_of_measure",
    "derived_by_TriNetX",
    "source_id",
]

LAB_COLUMNS = [
    "patient_id",
    "encounter_id",
    "code",
    "date",
    "lab_result_num_val",
]

DROP_COLUMNS = [
    "code_system",
    "lab_result_text_val",
    "units_of_measure",
    "derived_by_TriNetX",
    "source_id",
]


def normalize_lab_results_chunk(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize raw lab-results exports for downstream processing.

    Args:
        df: Raw lab-results DataFrame with TriNetX export columns.

    Returns:
        DataFrame with normalized lab-result columns.
    """

    require_columns(df, RAW_LAB_COLUMNS, context="Lab results raw input")

    normalized = df.drop(columns=DROP_COLUMNS).copy()
    normalized = normalized.loc[:, LAB_COLUMNS]
    normalized["patient_id"] = normalized["patient_id"].astype("string")
    normalized["encounter_id"] = normalized["encounter_id"].astype("string")
    normalized["code"] = normalized["code"].astype("string")
    normalized["date"] = pd.to_datetime(normalized["date"])
    return normalized.reset_index(drop=True)

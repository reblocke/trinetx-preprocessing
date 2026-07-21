"""Procedure feature assembly for final analytic outputs."""

from __future__ import annotations

import pandas as pd

from ..config import Config
from .cohort import QUALIFY_DATE_MIN
from .final_feature_common import (
    _left_merge_new_columns,
    _load_filtered_work_rows,
    _select_first_encounter_patient_date,
    _select_last_encounter_patient_date,
)
from .final_feature_sources import FinalFeatureBucket
from .final_output_schema import FINAL_OUTPUT_COLUMNS


def _merge_encounter_first_last_features(
    df: pd.DataFrame,
    *,
    config: Config,
    groups: list,
    source_columns: list[str],
    patient_ids: set[str],
    encounter_ids: set[str],
    chunksize: int,
    source_bucket: FinalFeatureBucket | None = None,
) -> pd.DataFrame:
    enriched = df
    for group in groups:
        if group.name not in FINAL_OUTPUT_COLUMNS:
            continue
        rows = _load_filtered_work_rows(
            config,
            f"{group.name}.csv",
            columns=source_columns,
            dtype={"patient_id": "string", "encounter_id": "string", "code": "string"},
            patient_ids=patient_ids,
            encounter_ids=encounter_ids,
            encounter_filter="include",
            chunksize=chunksize,
            source_bucket=source_bucket,
        )
        if rows.empty:
            continue
        rows["date"] = pd.to_datetime(rows["date"], errors="coerce")
        rows = rows.loc[rows["date"] >= QUALIFY_DATE_MIN].copy()
        if rows.empty:
            continue
        suffix = group.name.removeprefix("HAS_")
        first = _select_first_encounter_patient_date(
            rows,
            date_column=f"first_date_{suffix}",
        )
        last = _select_last_encounter_patient_date(
            rows,
            date_column=f"last_date_{suffix}",
        )
        feature = first.merge(last, on="encounter_id", how="outer")
        feature[group.name] = 1
        feature = feature.loc[
            :,
            [
                "encounter_id",
                group.name,
                f"first_date_{suffix}",
                f"last_date_{suffix}",
            ],
        ]
        enriched = _left_merge_new_columns(enriched, feature, on="encounter_id")
    return enriched

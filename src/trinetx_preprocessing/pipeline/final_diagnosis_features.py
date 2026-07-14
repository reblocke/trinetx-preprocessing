"""Diagnosis feature assembly for final analytic outputs."""

from __future__ import annotations

import pandas as pd

from ..config import Config
from ..transform.diagnosis import (
    CURRENT_DIAGNOSIS_CODE_GROUPS,
    DIAGNOSIS_COLUMNS,
    INDICATOR_COLUMNS,
    PRIOR_DIAGNOSIS_CODE_GROUPS,
)
from .cohort import QUALIFY_DATE_MIN
from .final_feature_common import (
    _filter_patient_rows_on_or_before_qualify,
    _left_merge_new_columns,
    _load_filtered_work_rows,
    _select_first_patient_date,
    _select_last_patient_date,
)
from .final_feature_sources import FinalFeatureBucket
from .final_output_schema import FINAL_OUTPUT_COLUMNS


def _merge_current_diagnosis_features(
    df: pd.DataFrame,
    *,
    config: Config,
    patient_ids: set[str],
    encounter_ids: set[str],
    chunksize: int,
    source_bucket: FinalFeatureBucket | None = None,
) -> pd.DataFrame:
    enriched = df
    for group in CURRENT_DIAGNOSIS_CODE_GROUPS:
        if group.name not in FINAL_OUTPUT_COLUMNS:
            continue
        rows = _load_filtered_work_rows(
            config,
            f"{group.name}.csv",
            columns=DIAGNOSIS_COLUMNS,
            dtype={
                "patient_id": "string",
                "encounter_id": "string",
                "code": "string",
                **{column: "string" for column in INDICATOR_COLUMNS},
            },
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
        selected = _select_current_diagnosis(rows)
        suffix = group.name.removeprefix("HAS_")
        if group.name in {
            "HAS_J9612",
            "HAS_J9622",
            "HAS_J9602",
            "HAS_J9692",
            "HAS_E662",
        }:
            selected = selected.rename(
                columns={
                    "principal_diagnosis_indicator": f"pcpl_dx_ind_{suffix}",
                    "admitting_diagnosis": f"adm_dx_{suffix}",
                    "reason_for_visit": f"visit_reason_{suffix}",
                    "date": f"date_{suffix}",
                }
            )
            selected[group.name] = 1
            keep_columns = [
                "encounter_id",
                group.name,
                f"pcpl_dx_ind_{suffix}",
                f"adm_dx_{suffix}",
                f"visit_reason_{suffix}",
                f"date_{suffix}",
            ]
            for column in keep_columns[2:5]:
                selected[column] = (
                    selected[column].replace({"Unknown": "U"}).fillna("U")
                )
        elif group.name == "HAS_J9600":
            selected = selected.rename(columns={"date": "date_J9600"})
            selected[group.name] = 1
            keep_columns = [
                "encounter_id",
                group.name,
                "principal_diagnosis_indicator",
                "admitting_diagnosis",
                "reason_for_visit",
                "date_J9600",
            ]
            for column in INDICATOR_COLUMNS:
                selected[column] = selected[column].replace({"Unknown": "U"})
        else:
            selected = selected.rename(columns={"date": f"date_{suffix}"})
            selected[group.name] = 1
            keep_columns = ["encounter_id", group.name, f"date_{suffix}"]
        selected = selected.loc[:, keep_columns]
        enriched = _left_merge_new_columns(enriched, selected, on="encounter_id")
    return enriched


def _merge_prior_diagnosis_features(
    df: pd.DataFrame,
    *,
    config: Config,
    patient_ids: set[str],
    encounter_ids: set[str],
    chunksize: int,
    source_bucket: FinalFeatureBucket | None = None,
) -> pd.DataFrame:
    enriched = df
    for group in PRIOR_DIAGNOSIS_CODE_GROUPS:
        suffix = group.name.removeprefix("HAS_")
        if f"first_date_{suffix}" not in FINAL_OUTPUT_COLUMNS:
            continue
        rows = _load_filtered_work_rows(
            config,
            f"{group.name}.csv",
            columns=DIAGNOSIS_COLUMNS,
            dtype={
                "patient_id": "string",
                "encounter_id": "string",
                "code": "string",
                **{column: "string" for column in INDICATOR_COLUMNS},
            },
            patient_ids=patient_ids,
            encounter_ids=encounter_ids,
            encounter_filter="exclude",
            chunksize=chunksize,
            source_bucket=source_bucket,
        )
        if rows.empty:
            continue
        rows["date"] = pd.to_datetime(rows["date"], errors="coerce")
        rows = _filter_patient_rows_on_or_before_qualify(
            rows,
            final_rows=enriched.loc[:, ["patient_id", "qualify_date"]],
            date_column="date",
        )
        if rows.empty:
            continue
        first = _select_first_patient_date(rows, date_column="date")
        last = _select_last_patient_date(rows, date_column="date")
        feature = enriched.loc[:, ["patient_id", "qualify_date"]].merge(
            first.rename(columns={"date": f"first_date_{suffix}"}),
            on="patient_id",
            how="left",
        )
        feature = feature.merge(
            last.rename(columns={"date": f"last_date_{suffix}"}),
            on="patient_id",
            how="left",
        )
        qualify_dates = pd.to_datetime(feature["qualify_date"], errors="coerce")
        first_valid = (
            pd.to_datetime(feature[f"first_date_{suffix}"], errors="coerce")
            <= qualify_dates
        )
        last_valid = (
            pd.to_datetime(feature[f"last_date_{suffix}"], errors="coerce")
            <= qualify_dates
        )
        feature[group.name] = first_valid.astype("int32")
        feature.loc[~first_valid, f"first_date_{suffix}"] = pd.NA
        feature.loc[~last_valid, f"last_date_{suffix}"] = pd.NA
        feature = feature.drop(columns=["qualify_date"])
        enriched = _left_merge_new_columns(enriched, feature, on="patient_id")
    return enriched


def _select_current_diagnosis(rows: pd.DataFrame) -> pd.DataFrame:
    """Reduce current diagnosis rows deterministically by encounter."""

    if rows.empty:
        return pd.DataFrame(columns=DIAGNOSIS_COLUMNS)
    selected = rows.loc[:, DIAGNOSIS_COLUMNS].copy()
    selected["date"] = pd.to_datetime(selected["date"], errors="coerce")
    selected["_row_order"] = range(len(selected))
    earliest = (
        selected.sort_values(
            by=["date", "_row_order"],
            ascending=[True, True],
            kind="mergesort",
        )
        .drop_duplicates(subset=["encounter_id"], keep="first")
        .copy()
    )
    priorities = {
        "principal_diagnosis_indicator": {"P": 3, "S": 2, "U": 1},
        "admitting_diagnosis": {"Y": 3, "T": 3, "N": 2, "F": 2, "U": 1},
        "reason_for_visit": {"Y": 3, "T": 3, "N": 2, "F": 2, "U": 1},
    }
    for column, priority in priorities.items():
        reduced = selected.groupby("encounter_id", sort=False)[column].agg(
            lambda values: _highest_priority_indicator(values, priority)
        )
        earliest[column] = earliest["encounter_id"].map(reduced)
    return earliest.loc[:, DIAGNOSIS_COLUMNS].reset_index(drop=True)


def _highest_priority_indicator(
    values: pd.Series,
    priority: dict[str, int],
) -> str:
    normalized = values.astype("string").fillna("U").replace({"Unknown": "U"})
    normalized = normalized.str.strip().str.upper()
    ranks = normalized.map(priority).fillna(0)
    return str(normalized.loc[ranks.idxmax()])

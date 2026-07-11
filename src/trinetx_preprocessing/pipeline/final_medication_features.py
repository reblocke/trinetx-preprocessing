"""Medication feature assembly for final analytic outputs."""

from __future__ import annotations

import pandas as pd

from ..config import Config
from ..transform.medications import MEDICATION_CODE_GROUPS, MEDICATION_COLUMNS
from .cohort import QUALIFY_DATE_MIN
from .final_feature_common import (
    _filter_patient_rows_on_or_before_qualify,
    _left_merge_new_columns,
    _load_filtered_work_rows,
)
from .final_feature_sources import FinalFeatureBucket


def _merge_medication_features(
    df: pd.DataFrame,
    *,
    config: Config,
    patient_ids: set[str],
    encounter_ids: set[str],
    chunksize: int,
    source_bucket: FinalFeatureBucket | None = None,
) -> pd.DataFrame:
    enriched = df
    for group in MEDICATION_CODE_GROUPS:
        rows = _load_filtered_work_rows(
            config,
            f"{group.name}.csv",
            columns=MEDICATION_COLUMNS,
            dtype={"patient_id": "string", "encounter_id": "string", "code": "string"},
            patient_ids=patient_ids,
            encounter_ids=encounter_ids,
            encounter_filter="include" if group.name.startswith("IPmed") else "exclude",
            chunksize=chunksize,
            source_bucket=source_bucket,
        )
        if rows.empty:
            continue
        rows["start_date"] = pd.to_datetime(rows["start_date"], errors="coerce")
        if group.name.startswith("IPmed"):
            med_index = group.name.removeprefix("IPmed_list")
            selected = _select_ip_medication(rows, med_index=med_index)
            enriched = _left_merge_new_columns(enriched, selected, on="encounter_id")
        else:
            med_index = group.name.removeprefix("OPmed_list")
            rows = _filter_patient_rows_on_or_before_qualify(
                rows,
                final_rows=enriched.loc[:, ["patient_id", "qualify_date"]],
                date_column="start_date",
            )
            selected = _select_op_medication(rows, med_index=med_index)
            if selected.empty:
                continue
            feature = enriched.loc[:, ["patient_id", "qualify_date"]].merge(
                selected,
                on="patient_id",
                how="left",
            )
            first_column = f"first_date_OP_Med_{med_index}"
            last_column = f"last_date_OP_Med_{med_index}"
            qualify_dates = pd.to_datetime(feature["qualify_date"], errors="coerce")
            first_valid = (
                pd.to_datetime(
                    feature[first_column],
                    errors="coerce",
                )
                <= qualify_dates
            )
            last_valid = (
                pd.to_datetime(
                    feature[last_column],
                    errors="coerce",
                )
                <= qualify_dates
            )
            feature[f"OP_Med_{med_index}"] = first_valid.astype("int32")
            feature.loc[~first_valid, first_column] = pd.NA
            feature.loc[~last_valid, last_column] = pd.NA
            feature = feature.drop(columns=["qualify_date"])
            enriched = _left_merge_new_columns(enriched, feature, on="patient_id")
    return enriched


def _select_ip_medication(rows: pd.DataFrame, *, med_index: str) -> pd.DataFrame:
    selected = rows.loc[rows["start_date"] >= QUALIFY_DATE_MIN].copy()
    if selected.empty:
        return pd.DataFrame(
            columns=[
                "encounter_id",
                f"IP_Med_{med_index}",
                f"date_IP_Med_{med_index}",
            ]
        )
    selected = selected.sort_values(
        by=["start_date", "encounter_id"],
        ascending=[True, False],
        kind="mergesort",
    )
    selected = selected.drop_duplicates(subset=["encounter_id"], keep="first")
    selected = selected.rename(columns={"start_date": f"date_IP_Med_{med_index}"})
    selected[f"IP_Med_{med_index}"] = 1
    return selected.loc[
        :,
        ["encounter_id", f"IP_Med_{med_index}", f"date_IP_Med_{med_index}"],
    ]


def _select_op_medication(rows: pd.DataFrame, *, med_index: str) -> pd.DataFrame:
    if rows.empty:
        return pd.DataFrame(
            columns=[
                "patient_id",
                f"first_date_OP_Med_{med_index}",
                f"last_date_OP_Med_{med_index}",
            ]
        )
    first = rows.sort_values(
        by=["start_date", "encounter_id"],
        ascending=[True, False],
        kind="mergesort",
    )
    first = first.drop_duplicates(subset=["encounter_id"], keep="first")
    first = first.sort_values(
        by=["start_date", "patient_id"],
        ascending=[True, False],
        kind="mergesort",
    )
    first = first.drop_duplicates(subset=["patient_id"], keep="first")
    first = first.rename(columns={"start_date": f"first_date_OP_Med_{med_index}"})

    last = rows.sort_values(
        by=["start_date", "encounter_id"],
        ascending=[True, False],
        kind="mergesort",
    )
    last = last.drop_duplicates(subset=["encounter_id"], keep="last")
    last = last.sort_values(
        by=["start_date", "patient_id"],
        ascending=[True, False],
        kind="mergesort",
    )
    last = last.drop_duplicates(subset=["patient_id"], keep="last")
    last = last.rename(columns={"start_date": f"last_date_OP_Med_{med_index}"})

    return first.loc[:, ["patient_id", f"first_date_OP_Med_{med_index}"]].merge(
        last.loc[:, ["patient_id", f"last_date_OP_Med_{med_index}"]],
        on="patient_id",
        how="outer",
    )

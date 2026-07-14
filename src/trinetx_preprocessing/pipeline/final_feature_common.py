"""Shared filtering, reduction, and merge helpers for final features."""

from __future__ import annotations

import pandas as pd

from ..config import Config
from ..storage import iter_work_tables, resolve_work_table
from ..validation import require_columns
from .cohort import QUALIFY_DATE_MIN
from .final_feature_sources import FinalFeatureBucket

FINAL_LAB_CODE_PRIORITY_COLUMN = "_code_priority"


def _load_filtered_work_rows(
    config: Config,
    logical_name: str,
    *,
    columns: list[str],
    dtype: dict[str, str],
    patient_ids: set[str],
    encounter_ids: set[str],
    encounter_filter: str,
    chunksize: int,
    source_bucket: FinalFeatureBucket | None = None,
) -> pd.DataFrame:
    if source_bucket is not None:
        chunk = source_bucket.frame(logical_name, columns)
        if chunk.empty:
            return pd.DataFrame(columns=columns)
        filtered = _filter_ids(
            chunk,
            patient_ids=patient_ids,
            encounter_ids=encounter_ids,
            encounter_filter=encounter_filter,
        )
        return filtered.loc[:, columns].copy().reset_index(drop=True)

    path = resolve_work_table(config, logical_name)
    if not path.exists():
        return pd.DataFrame(columns=columns)
    frames: list[pd.DataFrame] = []
    for chunk in iter_work_tables(
        [path],
        chunksize=chunksize,
        usecols=columns,
        dtype=dtype,
    ):
        require_columns(chunk, columns, context=str(path))
        filtered = _filter_ids(
            chunk,
            patient_ids=patient_ids,
            encounter_ids=encounter_ids,
            encounter_filter=encounter_filter,
        )
        if not filtered.empty:
            frames.append(filtered.loc[:, columns].copy())
    if not frames:
        return pd.DataFrame(columns=columns)
    return pd.concat(frames, ignore_index=True)


def _filter_ids(
    frame: pd.DataFrame,
    *,
    patient_ids: set[str],
    encounter_ids: set[str],
    encounter_filter: str,
) -> pd.DataFrame:
    mask = frame["patient_id"].astype("string").isin(patient_ids)
    if encounter_filter == "include":
        mask &= frame["encounter_id"].astype("string").isin(encounter_ids)
    elif encounter_filter == "exclude":
        mask &= ~frame["encounter_id"].astype("string").isin(encounter_ids)
    else:
        raise ValueError(f"Unknown encounter filter: {encounter_filter}")
    return frame.loc[mask].copy()


def _filter_patient_rows_on_or_before_qualify(
    rows: pd.DataFrame,
    *,
    final_rows: pd.DataFrame,
    date_column: str,
) -> pd.DataFrame:
    if rows.empty:
        return rows.copy()
    cohort = final_rows.loc[:, ["patient_id", "qualify_date"]].copy()
    cohort["patient_id"] = cohort["patient_id"].astype("string")
    cohort["qualify_date"] = pd.to_datetime(cohort["qualify_date"], errors="coerce")
    cohort = cohort.dropna(subset=["patient_id", "qualify_date"])
    if cohort.empty:
        return rows.iloc[0:0].copy()
    qualify_dates_by_patient = (
        cohort.drop_duplicates(subset=["patient_id"], keep="first")
        .set_index("patient_id")["qualify_date"]
        .to_dict()
    )
    filtered = rows.copy()
    filtered[date_column] = pd.to_datetime(filtered[date_column], errors="coerce")
    filtered["_qualify_date"] = (
        filtered["patient_id"]
        .astype("string")
        .map(
            qualify_dates_by_patient,
        )
    )
    filtered = filtered.loc[filtered[date_column] <= filtered["_qualify_date"]].copy()
    return filtered.drop(columns=["_qualify_date"])


def _select_first_encounter_patient_value(
    rows: pd.DataFrame,
    *,
    value_column: str,
    date_column: str,
    output_value_column: str,
) -> pd.DataFrame:
    if rows.empty:
        return pd.DataFrame(columns=["encounter_id", date_column, output_value_column])
    selected = rows.copy()
    selected["date"] = pd.to_datetime(selected["date"], errors="coerce")
    selected = selected.loc[selected["date"] >= QUALIFY_DATE_MIN].copy()
    if selected.empty:
        return pd.DataFrame(columns=["encounter_id", date_column, output_value_column])
    selected = _sort_first_date(selected)
    selected = selected.drop_duplicates(subset=["encounter_id"], keep="first")
    selected = _sort_first_date(selected, id_column="patient_id")
    selected = selected.drop_duplicates(subset=["patient_id"], keep="first")
    selected = selected.rename(
        columns={"date": date_column, value_column: output_value_column}
    )
    return selected.loc[:, ["encounter_id", date_column, output_value_column]]


def _select_highest_encounter_patient_value(
    rows: pd.DataFrame,
    *,
    value_column: str,
    date_column: str,
    output_value_column: str,
) -> pd.DataFrame:
    if rows.empty:
        return pd.DataFrame(columns=["encounter_id", date_column, output_value_column])
    selected = rows.copy()
    selected["date"] = pd.to_datetime(selected["date"], errors="coerce")
    selected[value_column] = pd.to_numeric(selected[value_column], errors="coerce")
    selected = selected.loc[selected["date"] >= QUALIFY_DATE_MIN].copy()
    if selected.empty:
        return pd.DataFrame(columns=["encounter_id", date_column, output_value_column])
    selected = selected.sort_values(
        by=[value_column, "encounter_id"],
        ascending=[False, False],
        kind="mergesort",
    )
    selected = selected.drop_duplicates(subset=["encounter_id"], keep="first")
    selected = selected.sort_values(
        by=[value_column, "patient_id"],
        ascending=[False, False],
        kind="mergesort",
    )
    selected = selected.drop_duplicates(subset=["patient_id"], keep="first")
    selected = selected.rename(
        columns={"date": date_column, value_column: output_value_column}
    )
    return selected.loc[:, ["encounter_id", date_column, output_value_column]]


def _select_previous_patient_value(
    rows: pd.DataFrame,
    *,
    value_column: str,
    output_value_column: str,
    output_date_column: str,
) -> pd.DataFrame:
    selected = rows.copy()
    selected["date"] = pd.to_datetime(selected["date"], errors="coerce")
    selected = _sort_first_date(selected)
    selected = selected.drop_duplicates(subset=["encounter_id"], keep="last")
    selected = _sort_first_date(selected, id_column="patient_id")
    selected = selected.drop_duplicates(subset=["patient_id"], keep="last")
    selected = selected.rename(
        columns={"date": output_date_column, value_column: output_value_column}
    )
    return selected.loc[:, ["patient_id", output_value_column, output_date_column]]


def _select_first_encounter_patient_date(
    rows: pd.DataFrame,
    *,
    date_column: str,
) -> pd.DataFrame:
    selected = _sort_first_date(rows.copy())
    selected = selected.drop_duplicates(subset=["encounter_id"], keep="first")
    selected = _sort_first_date(selected, id_column="patient_id")
    selected = selected.drop_duplicates(subset=["patient_id"], keep="first")
    selected = selected.rename(columns={"date": date_column})
    return selected.loc[:, ["encounter_id", date_column]]


def _select_last_encounter_patient_date(
    rows: pd.DataFrame,
    *,
    date_column: str,
) -> pd.DataFrame:
    selected = _sort_first_date(rows.copy())
    selected = selected.drop_duplicates(subset=["encounter_id"], keep="last")
    selected = _sort_first_date(selected, id_column="patient_id")
    selected = selected.drop_duplicates(subset=["patient_id"], keep="last")
    selected = selected.rename(columns={"date": date_column})
    return selected.loc[:, ["encounter_id", date_column]]


def _select_first_patient_date(rows: pd.DataFrame, *, date_column: str) -> pd.DataFrame:
    selected = _sort_first_date(rows.copy())
    selected = selected.drop_duplicates(subset=["encounter_id"], keep="first")
    selected = _sort_first_date(selected, id_column="patient_id")
    selected = selected.drop_duplicates(subset=["patient_id"], keep="first")
    return selected.loc[:, ["patient_id", date_column]]


def _select_last_patient_date(rows: pd.DataFrame, *, date_column: str) -> pd.DataFrame:
    selected = _sort_first_date(rows.copy())
    selected = selected.drop_duplicates(subset=["encounter_id"], keep="last")
    selected = _sort_first_date(selected, id_column="patient_id")
    selected = selected.drop_duplicates(subset=["patient_id"], keep="last")
    return selected.loc[:, ["patient_id", date_column]]


def _sort_first_date(
    rows: pd.DataFrame,
    *,
    id_column: str = "encounter_id",
) -> pd.DataFrame:
    by = ["date", id_column]
    ascending = [True, False]
    if FINAL_LAB_CODE_PRIORITY_COLUMN in rows.columns:
        by.append(FINAL_LAB_CODE_PRIORITY_COLUMN)
        ascending.append(True)
    return rows.sort_values(
        by=by,
        ascending=ascending,
        kind="mergesort",
    )


def _left_merge_new_columns(
    df: pd.DataFrame,
    feature: pd.DataFrame,
    *,
    on: str,
) -> pd.DataFrame:
    if feature.empty:
        return df
    new_columns = [column for column in feature.columns if column != on]
    existing = [column for column in new_columns if column in df.columns]
    if existing:
        df = df.drop(columns=existing)
    return df.merge(feature, on=on, how="left", validate="one_to_one")


def _string_id_set(series: pd.Series) -> set[str]:
    return set(series.dropna().astype("string"))

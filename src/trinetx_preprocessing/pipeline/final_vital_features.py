"""Vital-sign feature assembly for final analytic outputs."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from ..config import Config
from ..storage import PartitionedParquetStore, iter_work_tables, resolve_work_table
from ..transform.lab_features import (
    legacy_csv_visible_numeric_series as _legacy_csv_visible_numeric_series,
)
from ..transform.vitals import VITAL_SIGN_RULES, VITALS_COLUMNS
from ..validation import require_columns
from .final_feature_common import (
    _filter_ids,
    _left_merge_new_columns,
    _load_filtered_work_rows,
    _select_first_encounter_patient_value,
    _select_previous_patient_value,
    _string_id_set,
)
from .final_feature_sources import FinalFeatureBucket
from .final_output_schema import FINAL_OUTPUT_COLUMNS

FINAL_PREVIOUS_VITAL_BUCKET_COUNT = 256
FINAL_PREVIOUS_VITAL_BUCKET_COLUMNS = ["vital_name", *VITALS_COLUMNS]


def _merge_vital_value_features(
    df: pd.DataFrame,
    *,
    config: Config,
    patient_ids: set[str],
    encounter_ids: set[str],
    chunksize: int,
    source_bucket: FinalFeatureBucket | None = None,
) -> pd.DataFrame:
    enriched = df
    for rule in VITAL_SIGN_RULES:
        value_name = rule.name.removeprefix("value_")
        date_column = f"date_{value_name}"
        value_column = rule.name
        if (
            date_column not in FINAL_OUTPUT_COLUMNS
            or value_column not in FINAL_OUTPUT_COLUMNS
        ):
            continue
        rows = _load_filtered_work_rows(
            config,
            f"{rule.name}.csv",
            columns=VITALS_COLUMNS,
            dtype={"patient_id": "string", "encounter_id": "string", "code": "string"},
            patient_ids=patient_ids,
            encounter_ids=encounter_ids,
            encounter_filter="include",
            chunksize=chunksize,
            source_bucket=source_bucket,
        )
        if not rows.empty:
            rows["value"] = _legacy_csv_visible_numeric_series(rows["value"])
        selected = _select_first_encounter_patient_value(
            rows,
            value_column="value",
            date_column=date_column,
            output_value_column=value_column,
        )
        enriched = _left_merge_new_columns(enriched, selected, on="encounter_id")
    return enriched


def _merge_previous_vital_features(
    df: pd.DataFrame,
    *,
    config: Config,
    patient_ids: set[str],
    encounter_ids: set[str],
    chunksize: int,
    source_bucket: FinalFeatureBucket | None = None,
) -> pd.DataFrame:
    enriched = df
    for name in ("Weight", "Height", "BMI"):
        selected = _load_previous_vital_candidates(
            config,
            name,
            final_rows=enriched.loc[:, ["patient_id", "encounter_id", "qualify_date"]],
            chunksize=chunksize,
            source_bucket=source_bucket,
        )
        if selected.empty:
            continue
        enriched = enriched.merge(selected, on="patient_id", how="left")
        date_column = f"date_Prev_{name}"
        value_column = f"value_Prev_{name}"
        valid = pd.to_datetime(enriched[date_column], errors="coerce") < pd.to_datetime(
            enriched["qualify_date"],
            errors="coerce",
        )
        enriched.loc[~valid, [date_column]] = pd.NA
        enriched.loc[~valid, value_column] = 0
    return enriched


def _load_previous_vital_candidates(
    config: Config,
    name: str,
    *,
    final_rows: pd.DataFrame,
    chunksize: int,
    source_bucket: FinalFeatureBucket | None = None,
) -> pd.DataFrame:
    logical_name = f"value_{name}.csv"
    path = resolve_work_table(config, logical_name)
    output_columns = ["patient_id", f"value_Prev_{name}", f"date_Prev_{name}"]
    if source_bucket is None and not path.exists():
        return pd.DataFrame(columns=output_columns)

    cohort = final_rows.loc[:, ["patient_id", "encounter_id", "qualify_date"]].copy()
    cohort["patient_id"] = cohort["patient_id"].astype("string")
    cohort["encounter_id"] = cohort["encounter_id"].astype("string")
    cohort["qualify_date"] = pd.to_datetime(cohort["qualify_date"], errors="coerce")
    cohort = cohort.dropna(subset=["patient_id", "qualify_date"])
    if cohort.empty:
        return pd.DataFrame(columns=output_columns)

    patient_ids = _string_id_set(cohort["patient_id"])
    encounter_ids = _string_id_set(cohort["encounter_id"])
    qualify_dates_by_patient = (
        cohort.drop_duplicates(subset=["patient_id"], keep="first")
        .set_index("patient_id")["qualify_date"]
        .to_dict()
    )

    if source_bucket is not None:
        chunks = [source_bucket.frame(logical_name, VITALS_COLUMNS)]
        filtered_frames: list[pd.DataFrame] = []
        for chunk in chunks:
            require_columns(chunk, VITALS_COLUMNS, context=str(path))
            filtered = _filter_ids(
                chunk,
                patient_ids=patient_ids,
                encounter_ids=encounter_ids,
                encounter_filter="exclude",
            )
            if filtered.empty:
                continue
            filtered["date"] = pd.to_datetime(filtered["date"], errors="coerce")
            filtered["value"] = _legacy_csv_visible_numeric_series(filtered["value"])
            filtered["_qualify_date"] = (
                filtered["patient_id"].astype("string").map(qualify_dates_by_patient)
            )
            filtered = filtered.loc[filtered["date"] < filtered["_qualify_date"]].copy()
            if filtered.empty:
                continue
            filtered_frames.append(filtered.loc[:, VITALS_COLUMNS])
        if not filtered_frames:
            return pd.DataFrame(columns=output_columns)
        rows = pd.concat(filtered_frames, ignore_index=True)
        return _select_previous_patient_value(
            rows,
            value_column="value",
            output_value_column=f"value_Prev_{name}",
            output_date_column=f"date_Prev_{name}",
        )

    with _FinalPreviousVitalCandidateStore(config.work_dir) as store:
        chunks = iter_work_tables(
            [path],
            chunksize=chunksize,
            usecols=VITALS_COLUMNS,
            dtype={
                "patient_id": "string",
                "encounter_id": "string",
                "code": "string",
            },
        )
        for chunk in chunks:
            require_columns(chunk, VITALS_COLUMNS, context=str(path))
            filtered = _filter_ids(
                chunk,
                patient_ids=patient_ids,
                encounter_ids=encounter_ids,
                encounter_filter="exclude",
            )
            if filtered.empty:
                continue
            filtered["date"] = pd.to_datetime(filtered["date"], errors="coerce")
            filtered["value"] = _legacy_csv_visible_numeric_series(filtered["value"])
            filtered["_qualify_date"] = (
                filtered["patient_id"].astype("string").map(qualify_dates_by_patient)
            )
            filtered = filtered.loc[filtered["date"] < filtered["_qualify_date"]].copy()
            if not filtered.empty:
                store.add_frame(name, filtered.loc[:, VITALS_COLUMNS])
        selected = store.reduce().get(name)
    if selected is None:
        return pd.DataFrame(columns=output_columns)
    return selected


class _FinalPreviousVitalCandidateStore:
    """Patient-bucketed reducer for previous Weight/Height/BMI candidates."""

    def __init__(self, work_dir: Path) -> None:
        self.work_dir = work_dir
        self._store: PartitionedParquetStore | None = None

    def __enter__(self) -> "_FinalPreviousVitalCandidateStore":
        self._store = PartitionedParquetStore(
            self.work_dir,
            prefix=".trinetx-final-prev-vitals-",
            key_columns=["vital_name", "patient_id"],
            bucket_count=FINAL_PREVIOUS_VITAL_BUCKET_COUNT,
            cleanup_context="Final previous vital scratch",
        )
        self._store.__enter__()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._store is not None:
            self._store.__exit__(exc_type, exc, tb)

    def add_frame(self, vital_name: str, frame: pd.DataFrame) -> None:
        if frame.empty:
            return
        require_columns(
            frame,
            VITALS_COLUMNS,
            context="Final previous vital candidates",
        )
        bucketed = frame.loc[:, VITALS_COLUMNS].copy()
        bucketed.insert(0, "vital_name", vital_name)
        self._partition_store().add_frame(
            bucketed.loc[:, FINAL_PREVIOUS_VITAL_BUCKET_COLUMNS]
        )

    def reduce(self) -> dict[str, pd.DataFrame]:
        frames_by_name: dict[str, list[pd.DataFrame]] = {}
        for _, frame in self._partition_store().iter_frames(
            columns=FINAL_PREVIOUS_VITAL_BUCKET_COLUMNS
        ):
            frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
            if frame.empty:
                continue
            for vital_name, group in frame.groupby("vital_name", sort=False):
                name = str(vital_name)
                reduced = _select_previous_patient_value(
                    group.loc[:, VITALS_COLUMNS],
                    value_column="value",
                    output_value_column=f"value_Prev_{name}",
                    output_date_column=f"date_Prev_{name}",
                )
                if not reduced.empty:
                    frames_by_name.setdefault(name, []).append(reduced)
        return {
            name: pd.concat(frames, ignore_index=True)
            for name, frames in frames_by_name.items()
            if frames
        }

    def _partition_store(self) -> PartitionedParquetStore:
        if self._store is None:
            raise RuntimeError("Final previous vital store is not open.")
        return self._store

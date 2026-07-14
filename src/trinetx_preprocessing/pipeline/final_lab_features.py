"""Lab feature assembly for final analytic outputs."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from ..config import Config
from ..storage import PartitionedParquetStore, find_work_tables, iter_work_tables
from ..transform.lab_features import (
    LAB_VALUE_RULES,
    classify_lab_feature_rows,
    legacy_lab_feature_values,
)
from ..transform.lab_features import (
    LabFeatureRule as _LabValueRule,
)
from ..transform.lab_features import (
    lab_code_priority as _lab_code_priority,
)
from ..transform.labs import LAB_COLUMNS
from ..validation import require_columns
from .cohort import QUALIFY_DATE_MIN
from .final_feature_common import (
    FINAL_LAB_CODE_PRIORITY_COLUMN,
    _filter_ids,
    _left_merge_new_columns,
    _select_first_encounter_patient_value,
    _select_highest_encounter_patient_value,
    _sort_first_date,
)
from .final_feature_sources import LAB_SOURCE_NAME, FinalFeatureBucket
from .final_output_schema import FINAL_OUTPUT_COLUMNS

FINAL_LAB_BUCKET_COUNT = 256
FINAL_LAB_FEATURE_FIRST = "first"
FINAL_LAB_FEATURE_HIGHEST = "highest"
FINAL_LAB_BUCKET_COLUMNS = [
    "rule_name",
    "feature_kind",
    *LAB_COLUMNS,
    FINAL_LAB_CODE_PRIORITY_COLUMN,
]


def _merge_lab_value_features(
    df: pd.DataFrame,
    *,
    config: Config,
    patient_ids: set[str],
    encounter_ids: set[str],
    chunksize: int,
    source_bucket: FinalFeatureBucket | None = None,
) -> pd.DataFrame:
    lab_rows_by_name = _load_lab_rows_by_rule(
        config,
        patient_ids=patient_ids,
        encounter_ids=encounter_ids,
        chunksize=chunksize,
        source_bucket=source_bucket,
    )
    enriched = df
    for rule in LAB_VALUE_RULES:
        feature_rows = lab_rows_by_name.get(rule.name, {})
        rows = feature_rows.get(FINAL_LAB_FEATURE_FIRST)
        if rows is None or rows.empty:
            continue
        value_name = rule.name.removeprefix("value_")
        first = _select_first_encounter_patient_value(
            rows,
            value_column="lab_result_num_val",
            date_column=f"date_{value_name}",
            output_value_column=rule.name,
        )
        enriched = _left_merge_new_columns(enriched, first, on="encounter_id")
        if rule.include_highest:
            rows = feature_rows.get(FINAL_LAB_FEATURE_HIGHEST)
            if rows is None or rows.empty:
                continue
            highest = _select_highest_encounter_patient_value(
                rows,
                value_column="lab_result_num_val",
                date_column=f"date_highest_{value_name}",
                output_value_column=f"value_highest_{value_name}",
            )
            enriched = _left_merge_new_columns(enriched, highest, on="encounter_id")
    return enriched


def _load_lab_rows_by_rule(
    config: Config,
    *,
    patient_ids: set[str],
    encounter_ids: set[str],
    chunksize: int,
    source_bucket: FinalFeatureBucket | None = None,
) -> dict[str, dict[str, pd.DataFrame]]:
    paths = find_work_tables(config, "lab_results_NEW_*.csv")
    if source_bucket is None and not paths:
        return {}
    rules_by_name = {
        rule.name: rule for rule in LAB_VALUE_RULES if _lab_rule_outputs_requested(rule)
    }
    if source_bucket is not None:
        normalized = source_bucket.frame(LAB_SOURCE_NAME, LAB_COLUMNS)
        if normalized.empty:
            grouped = {
                name: source_bucket.frame(name, LAB_COLUMNS)
                for name in rules_by_name
                if source_bucket.has_source(name)
            }
        else:
            grouped = classify_lab_feature_rows(normalized)
        return _reduce_lab_candidates(
            grouped,
            rules_by_name=rules_by_name,
            patient_ids=patient_ids,
            encounter_ids=encounter_ids,
        )

    with _FinalLabCandidateStore(config.work_dir) as store:
        chunks = iter_work_tables(
            paths,
            chunksize=chunksize,
            usecols=LAB_COLUMNS,
            dtype={
                "patient_id": "string",
                "encounter_id": "string",
                "code": "string",
            },
        )
        grouped_chunks = (
            classify_lab_feature_rows(
                _filter_ids(
                    chunk,
                    patient_ids=patient_ids,
                    encounter_ids=encounter_ids,
                    encounter_filter="include",
                )
            )
            for chunk in chunks
        )
        for grouped in grouped_chunks:
            for name, candidate_rows in grouped.items():
                rule = rules_by_name.get(name)
                if rule is None or candidate_rows.empty:
                    continue
                rows = _filter_ids(
                    candidate_rows,
                    patient_ids=patient_ids,
                    encounter_ids=encounter_ids,
                    encounter_filter="include",
                )
                if rows.empty:
                    continue
                rows["date"] = pd.to_datetime(rows["date"], errors="coerce")
                rows[FINAL_LAB_CODE_PRIORITY_COLUMN] = _lab_code_priority(
                    rule, rows["code"]
                )
                store.add_frame(
                    rule.name,
                    FINAL_LAB_FEATURE_FIRST,
                    _reduce_first_lab_candidate_rows(rows),
                )
                if rule.include_highest:
                    store.add_frame(
                        rule.name,
                        FINAL_LAB_FEATURE_HIGHEST,
                        _reduce_highest_lab_candidate_rows(rows),
                    )
        return store.reduce()


def _reduce_lab_candidates(
    grouped: dict[str, pd.DataFrame],
    *,
    rules_by_name: dict[str, _LabValueRule],
    patient_ids: set[str],
    encounter_ids: set[str],
) -> dict[str, dict[str, pd.DataFrame]]:
    reduced: dict[str, dict[str, pd.DataFrame]] = {}
    for name, candidate_rows in grouped.items():
        rule = rules_by_name.get(name)
        if rule is None or candidate_rows.empty:
            continue
        rows = _filter_ids(
            candidate_rows,
            patient_ids=patient_ids,
            encounter_ids=encounter_ids,
            encounter_filter="include",
        )
        if rows.empty:
            continue
        rows["date"] = pd.to_datetime(rows["date"], errors="coerce")
        rows[FINAL_LAB_CODE_PRIORITY_COLUMN] = _lab_code_priority(rule, rows["code"])
        features = {FINAL_LAB_FEATURE_FIRST: _reduce_first_lab_candidate_rows(rows)}
        if rule.include_highest:
            features[FINAL_LAB_FEATURE_HIGHEST] = _reduce_highest_lab_candidate_rows(
                rows
            )
        reduced[name] = features
    return reduced


def _lab_rule_outputs_requested(rule: _LabValueRule) -> bool:
    columns = _lab_output_value_columns()
    value_name = rule.name.removeprefix("value_")
    return rule.name in columns or f"value_highest_{value_name}" in columns


def _legacy_lab_feature_values(
    rule: _LabValueRule,
    codes: pd.Series,
    values: pd.Series,
) -> pd.Series:
    """Compatibility wrapper for focused feature-precision tests."""

    return legacy_lab_feature_values(rule, codes, values)


def _reduce_first_lab_candidate_rows(rows: pd.DataFrame) -> pd.DataFrame:
    if rows.empty:
        return pd.DataFrame(columns=LAB_COLUMNS)
    selected = rows.loc[:, LAB_COLUMNS].copy()
    if FINAL_LAB_CODE_PRIORITY_COLUMN in rows.columns:
        selected[FINAL_LAB_CODE_PRIORITY_COLUMN] = rows[
            FINAL_LAB_CODE_PRIORITY_COLUMN
        ].to_numpy()
    selected["date"] = pd.to_datetime(selected["date"], errors="coerce")
    selected = selected.loc[selected["date"] >= QUALIFY_DATE_MIN].copy()
    if selected.empty:
        return pd.DataFrame(columns=LAB_COLUMNS)
    selected = _sort_first_date(selected)
    selected = selected.drop_duplicates(subset=["encounter_id"], keep="first")
    selected = _sort_first_date(selected, id_column="patient_id")
    selected = selected.drop_duplicates(subset=["patient_id"], keep="first")
    columns = [*LAB_COLUMNS]
    if FINAL_LAB_CODE_PRIORITY_COLUMN in selected.columns:
        columns.append(FINAL_LAB_CODE_PRIORITY_COLUMN)
    return selected.loc[:, columns]


def _reduce_highest_lab_candidate_rows(rows: pd.DataFrame) -> pd.DataFrame:
    if rows.empty:
        return pd.DataFrame(columns=LAB_COLUMNS)
    selected = rows.loc[:, LAB_COLUMNS].copy()
    selected["date"] = pd.to_datetime(selected["date"], errors="coerce")
    selected["lab_result_num_val"] = pd.to_numeric(
        selected["lab_result_num_val"], errors="coerce"
    )
    selected = selected.loc[selected["date"] >= QUALIFY_DATE_MIN].copy()
    if selected.empty:
        return pd.DataFrame(columns=LAB_COLUMNS)
    selected = selected.sort_values(
        by=["lab_result_num_val", "encounter_id"],
        ascending=[False, False],
        kind="mergesort",
    )
    selected = selected.drop_duplicates(subset=["encounter_id"], keep="first")
    selected = selected.sort_values(
        by=["lab_result_num_val", "patient_id"],
        ascending=[False, False],
        kind="mergesort",
    )
    selected = selected.drop_duplicates(subset=["patient_id"], keep="first")
    return selected.loc[:, LAB_COLUMNS]


def _lab_output_value_columns() -> set[str]:
    return {
        column
        for column in FINAL_OUTPUT_COLUMNS
        if column.startswith("value_") or column.startswith("value_highest_")
    }


class _FinalLabCandidateStore:
    """Bucketed lab-feature reducer for final assembly analytic columns."""

    def __init__(self, work_dir: Path) -> None:
        self.work_dir = work_dir
        self._store: PartitionedParquetStore | None = None

    def __enter__(self) -> "_FinalLabCandidateStore":
        self._store = PartitionedParquetStore(
            self.work_dir,
            prefix=".trinetx-final-labs-",
            key_columns=["rule_name", "feature_kind", "patient_id"],
            bucket_count=FINAL_LAB_BUCKET_COUNT,
            cleanup_context="Final lab feature scratch",
        )
        self._store.__enter__()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._store is not None:
            self._store.__exit__(exc_type, exc, tb)

    def add_frame(
        self,
        rule_name: str,
        feature_kind: str,
        frame: pd.DataFrame,
    ) -> None:
        if frame.empty:
            return
        require_columns(frame, LAB_COLUMNS, context="Final lab candidates")
        bucketed = frame.loc[:, LAB_COLUMNS].copy()
        if FINAL_LAB_CODE_PRIORITY_COLUMN in frame.columns:
            bucketed[FINAL_LAB_CODE_PRIORITY_COLUMN] = frame[
                FINAL_LAB_CODE_PRIORITY_COLUMN
            ].to_numpy()
        else:
            bucketed[FINAL_LAB_CODE_PRIORITY_COLUMN] = 0
        bucketed.insert(0, "feature_kind", feature_kind)
        bucketed.insert(0, "rule_name", rule_name)
        self._partition_store().add_frame(bucketed.loc[:, FINAL_LAB_BUCKET_COLUMNS])

    def reduce(self) -> dict[str, dict[str, pd.DataFrame]]:
        frames_by_rule: dict[str, dict[str, list[pd.DataFrame]]] = {}
        for _, frame in self._partition_store().iter_frames(
            columns=FINAL_LAB_BUCKET_COLUMNS
        ):
            frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
            if frame.empty:
                continue
            for (rule_name, feature_kind), group in frame.groupby(
                ["rule_name", "feature_kind"],
                sort=False,
            ):
                columns = [*LAB_COLUMNS]
                if FINAL_LAB_CODE_PRIORITY_COLUMN in group.columns:
                    columns.append(FINAL_LAB_CODE_PRIORITY_COLUMN)
                candidates = group.loc[:, columns].copy()
                if feature_kind == FINAL_LAB_FEATURE_FIRST:
                    reduced = _reduce_first_lab_candidate_rows(candidates)
                elif feature_kind == FINAL_LAB_FEATURE_HIGHEST:
                    reduced = _reduce_highest_lab_candidate_rows(candidates)
                else:
                    raise ValueError(f"Unknown lab feature kind: {feature_kind}")
                if reduced.empty:
                    continue
                frames_by_rule.setdefault(str(rule_name), {}).setdefault(
                    str(feature_kind),
                    [],
                ).append(reduced)

        return {
            rule_name: {
                feature_kind: pd.concat(frames, ignore_index=True)
                for feature_kind, frames in feature_frames.items()
                if frames
            }
            for rule_name, feature_frames in frames_by_rule.items()
        }

    def _partition_store(self) -> PartitionedParquetStore:
        if self._store is None:
            raise RuntimeError("Final lab candidate store is not open.")
        return self._store

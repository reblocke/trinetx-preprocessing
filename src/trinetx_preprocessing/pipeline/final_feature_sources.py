"""One-scan, patient-partitioned source cache for final analytic features."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

import numpy as np
import pandas as pd

from ..config import Config
from ..storage import (
    PartitionedParquetStore,
    find_work_tables,
    iter_work_tables,
    resolve_work_table,
)
from ..transform.diagnosis import DIAGNOSIS_CODE_GROUPS, DIAGNOSIS_COLUMNS
from ..transform.labs import LAB_COLUMNS
from ..transform.medications import MEDICATION_CODE_GROUPS, MEDICATION_COLUMNS
from ..transform.procedure import PROCEDURE_CODE_GROUPS, PROCEDURE_COLUMNS
from ..transform.vitals import VITAL_SIGN_RULES, VITALS_COLUMNS

LAB_SOURCE_NAME = "__normalized_labs__"
SOURCE_COLUMNS = [
    "source_name",
    "patient_id",
    "encounter_id",
    "code",
    "date",
    "numeric_value",
    "principal_diagnosis_indicator",
    "admitting_diagnosis",
    "reason_for_visit",
    "_source_row_order",
]


@dataclass(frozen=True)
class _SourceDefinition:
    name: str
    paths: tuple[Path, ...]
    columns: tuple[str, ...]
    date_column: str
    numeric_column: str | None = None


class FinalFeatureBucket:
    """Feature source rows for one patient hash partition."""

    def __init__(self, frame: pd.DataFrame | None) -> None:
        if frame is None or frame.empty:
            self._frame = pd.DataFrame(columns=SOURCE_COLUMNS)
            self._source_positions: dict[str, np.ndarray] = {}
            return
        self._frame = frame
        source_row_order = frame["_source_row_order"].to_numpy(copy=False)
        self._source_positions = {}
        for name, positions in frame.groupby("source_name", sort=False).indices.items():
            source_positions = np.asarray(positions, dtype=np.int64)
            stable_order = np.argsort(
                source_row_order[source_positions],
                kind="stable",
            )
            self._source_positions[str(name)] = source_positions[stable_order]

    def frame(self, source_name: str, columns: Sequence[str]) -> pd.DataFrame:
        """Return one source in its historical logical column shape."""

        positions = self._source_positions.get(source_name)
        if positions is None:
            return pd.DataFrame(columns=columns)
        result: dict[str, pd.Series] = {}
        for column in columns:
            if column == "start_date":
                source_column = "date"
            elif column in {"value", "lab_result_num_val"}:
                source_column = "numeric_value"
            else:
                source_column = column
            result[column] = (
                self._frame[source_column].take(positions).reset_index(drop=True)
            )
        return pd.DataFrame(result, columns=columns)

    def has_source(self, source_name: str) -> bool:
        """Return whether this patient bucket contains the logical source."""

        return source_name in self._source_positions


class FinalFeatureSourceStore:
    """Build and expose all final-feature sources with one source scan."""

    def __init__(self, config: Config, *, chunksize: int | None) -> None:
        self.config = config
        self.chunksize = chunksize
        self._store: PartitionedParquetStore | None = None
        self.rows_indexed = 0
        self.files_scanned = 0
        self.source_files_scanned: list[str] = []

    def __enter__(self) -> "FinalFeatureSourceStore":
        self._store = PartitionedParquetStore(
            self.config.work_dir,
            prefix=".trinetx-final-feature-sources-",
            key_columns=["patient_id"],
            bucket_count=self.config.storage.analysis_bucket_count,
            row_group_size=self.config.storage.parquet_row_group_size,
            cleanup_context="Final feature source index scratch",
        )
        self._store.__enter__()
        self._build()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._store is not None:
            self._store.__exit__(exc_type, exc, tb)

    def bucket(self, bucket: int) -> FinalFeatureBucket:
        """Load one source partition for reuse across all final outputs."""

        frame = self._partition_store().read_frame(bucket, columns=SOURCE_COLUMNS)
        return FinalFeatureBucket(frame)

    def populated_buckets(self) -> set[int]:
        """Return populated partition numbers without retaining row frames."""

        return {
            bucket
            for bucket, _ in self._partition_store().iter_frames(columns=["patient_id"])
        }

    def disk_size_bytes(self) -> int:
        """Return the compressed source-index footprint."""

        return self._partition_store().disk_size_bytes()

    def _build(self) -> None:
        next_row_order = 0
        for definition in _source_definitions(self.config):
            for path in definition.paths:
                self.files_scanned += 1
                self.source_files_scanned.append(path.name)
                for chunk in iter_work_tables(
                    [path],
                    chunksize=self.chunksize,
                    usecols=definition.columns,
                    dtype={
                        "patient_id": "string",
                        "encounter_id": "string",
                        "code": "string",
                    },
                ):
                    indexed = _to_index_frame(
                        chunk,
                        definition,
                        row_order_start=next_row_order,
                    )
                    next_row_order += len(indexed)
                    self.rows_indexed += len(indexed)
                    self._partition_store().add_frame(indexed)

    def _partition_store(self) -> PartitionedParquetStore:
        if self._store is None:
            raise RuntimeError("Final feature source store is not open.")
        return self._store


def _source_definitions(config: Config) -> Iterable[_SourceDefinition]:
    vital_analysis = resolve_work_table(config, "analysis_vital_features.csv")
    if vital_analysis.exists():
        yield _SourceDefinition(
            "__indexed_vitals__",
            (vital_analysis,),
            ("source_name", *VITALS_COLUMNS),
            "date",
            "value",
        )
    else:
        for rule in VITAL_SIGN_RULES:
            yield from _logical_source(
                config, f"{rule.name}.csv", VITALS_COLUMNS, "date", "value"
            )

    lab_analysis = resolve_work_table(config, "analysis_lab_features.csv")
    if lab_analysis.exists():
        yield _SourceDefinition(
            "__indexed_labs__",
            (lab_analysis,),
            ("source_name", *LAB_COLUMNS),
            "date",
            "lab_result_num_val",
        )
    else:
        lab_paths = tuple(find_work_tables(config, "lab_results_NEW_*.csv"))
        if not lab_paths:
            lab_paths = ()
    if not lab_analysis.exists() and lab_paths:
        yield _SourceDefinition(
            LAB_SOURCE_NAME,
            lab_paths,
            tuple(LAB_COLUMNS),
            "date",
            "lab_result_num_val",
        )

    diagnosis_analysis = resolve_work_table(config, "analysis_diagnosis_features.csv")
    if diagnosis_analysis.exists():
        yield _SourceDefinition(
            "__indexed_diagnosis__",
            (diagnosis_analysis,),
            ("source_name", *DIAGNOSIS_COLUMNS),
            "date",
        )
    else:
        for group in DIAGNOSIS_CODE_GROUPS:
            yield from _logical_source(
                config,
                f"{group.name}.csv",
                DIAGNOSIS_COLUMNS,
                "date",
            )

    procedure_analysis = resolve_work_table(config, "analysis_procedure_features.csv")
    if procedure_analysis.exists():
        yield _SourceDefinition(
            "__indexed_procedure__",
            (procedure_analysis,),
            ("source_name", *PROCEDURE_COLUMNS),
            "date",
        )
    else:
        for group in PROCEDURE_CODE_GROUPS:
            yield from _logical_source(
                config,
                f"{group.name}.csv",
                PROCEDURE_COLUMNS,
                "date",
            )

    medication_analysis = resolve_work_table(config, "analysis_medication_features.csv")
    if medication_analysis.exists():
        yield _SourceDefinition(
            "__indexed_medications__",
            (medication_analysis,),
            ("source_name", *MEDICATION_COLUMNS),
            "start_date",
        )
    else:
        for group in MEDICATION_CODE_GROUPS:
            yield from _logical_source(
                config,
                f"{group.name}.csv",
                MEDICATION_COLUMNS,
                "start_date",
            )


def _logical_source(
    config: Config,
    logical_name: str,
    columns: Sequence[str],
    date_column: str,
    numeric_column: str | None = None,
) -> Iterable[_SourceDefinition]:
    path = resolve_work_table(config, logical_name)
    if path.exists():
        yield _SourceDefinition(
            logical_name,
            (path,),
            tuple(columns),
            date_column,
            numeric_column,
        )


def _to_index_frame(
    frame: pd.DataFrame,
    definition: _SourceDefinition,
    *,
    row_order_start: int,
) -> pd.DataFrame:
    size = len(frame)
    indexed = pd.DataFrame(index=frame.index)
    if "source_name" in frame:
        indexed["source_name"] = frame["source_name"].astype("string")
    else:
        indexed["source_name"] = pd.Series(
            [definition.name] * size,
            index=frame.index,
            dtype="string",
        )
    for column in ("patient_id", "encounter_id", "code"):
        indexed[column] = frame[column].astype("string")
    indexed["date"] = pd.to_datetime(frame[definition.date_column], errors="coerce")
    if definition.numeric_column is None:
        indexed["numeric_value"] = np.nan
    else:
        indexed["numeric_value"] = pd.to_numeric(
            frame[definition.numeric_column], errors="coerce"
        ).astype("float64")
    for column in (
        "principal_diagnosis_indicator",
        "admitting_diagnosis",
        "reason_for_visit",
    ):
        if column in frame:
            indexed[column] = frame[column].astype("string")
        else:
            indexed[column] = pd.Series(pd.NA, index=frame.index, dtype="string")
    indexed["_source_row_order"] = np.arange(
        row_order_start,
        row_order_start + size,
        dtype=np.int64,
    )
    return indexed.loc[:, SOURCE_COLUMNS].reset_index(drop=True)

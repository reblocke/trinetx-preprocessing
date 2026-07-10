"""RFS stage runner built from legacy notebook logic."""

from __future__ import annotations

import json
import logging
from contextlib import ExitStack
from pathlib import Path
from typing import Iterable

import pandas as pd

from ..config import Config
from ..filesystem import write_text_atomic
from ..guardrails import log_row_count
from ..storage import (
    PartitionedParquetStore,
    WorkTableWriter,
    find_work_tables,
    iter_work_tables,
    resolve_work_table,
    stable_bucket_ids,
)
from ..transform.diagnosis import DIAGNOSIS_COLUMNS
from ..transform.labs import NORMALIZED_LAB_COLUMNS
from ..transform.procedure import PROCEDURE_COLUMNS
from ..transform.rfs import (
    ENCOUNTER_ID_COLUMNS,
    RFS_CATEGORIES,
    RFS_EVENT_COLUMNS,
    RFS_FLAG_COLUMNS,
    RFS_OUTPUT_COLUMNS,
    derive_diagnosis_rfs_event_frames,
    derive_lab_rfs_event_frames_with_audit,
    derive_procedure_rfs_event_frames,
    derive_vitals_rfs_event_frames,
)
from ..transform.vitals import VITALS_COLUMNS

ENCOUNTER_DTYPE = {
    "patient_id": "string",
    "encounter_id": "string",
}

LAB_DTYPE = {
    "patient_id": "string",
    "encounter_id": "string",
    "code_system": "string",
    "code": "string",
    "date": "string",
    "lab_result_num_val": "float64",
    "units_of_measure": "string",
}

DIAGNOSIS_DTYPE = {
    "patient_id": "string",
    "encounter_id": "string",
    "code": "string",
    "principal_diagnosis_indicator": "string",
    "admitting_diagnosis": "string",
    "reason_for_visit": "string",
    "date": "string",
}

PROCEDURE_DTYPE = {
    "patient_id": "string",
    "encounter_id": "string",
    "code": "string",
    "date": "string",
}

VITALS_DTYPE = {
    "patient_id": "string",
    "encounter_id": "string",
    "code": "string",
    "date": "string",
    "value": "float64",
}

RFS_BUCKET_COUNT = 256
RFS_MEMBERSHIP_COLUMNS = ["category", "encounter_id"]
RFS_BUCKETED_ENCOUNTER_COLUMNS = ["_row_order", "patient_id", "encounter_id"]
RFS_ANALYSIS_SOURCES = {
    "labs": "analysis_rfs_labs.csv",
    "diagnosis": "analysis_rfs_diagnosis.csv",
    "procedure": "analysis_rfs_procedure.csv",
    "vitals": "analysis_rfs_vitals.csv",
}


def run_rfs_stage(config: Config) -> list[Path]:
    """Run the RFS derivation stage.

    Args:
        config: Pipeline configuration.

    Returns:
        List of written file paths.
    """

    logger = logging.getLogger(__name__)
    config.work_dir.mkdir(parents=True, exist_ok=True)

    output_paths: list[Path] = []
    event_counts = {category: 0 for category in RFS_CATEGORIES}
    lab_audit_counts: dict[str, dict[str, int]] = {
        category: {
            "considered": 0,
            "accepted": 0,
            "rejected_code_system": 0,
            "rejected_unit": 0,
            "rejected_non_numeric": 0,
            "rejected_range": 0,
        }
        for category in ("ABG", "VBG")
    }
    input_rows: dict[str, int] = {}

    def derive_lab_events(frame: pd.DataFrame) -> dict[str, pd.DataFrame]:
        events, audits = derive_lab_rfs_event_frames_with_audit(
            frame,
            abg_min_pco2_mmhg=config.rfs.abg_min_pco2_mmhg,
            vbg_min_pco2_mmhg=config.rfs.vbg_min_pco2_mmhg,
        )
        for category, audit in audits.items():
            for field in lab_audit_counts[category]:
                lab_audit_counts[category][field] += int(getattr(audit, field))
        return events

    with ExitStack() as stack, _RfsMembershipStore(config.work_dir) as membership:
        event_writers = {
            category: stack.enter_context(
                WorkTableWriter(config, f"RFS_{category}.csv")
            )
            for category in RFS_CATEGORIES
        }

        using_analysis_index = _has_complete_rfs_analysis(config)
        if using_analysis_index:
            input_rows = _stream_indexed_rfs_events(
                config,
                event_writers=event_writers,
                event_counts=event_counts,
                membership=membership,
                logger=logger,
            )
        else:
            input_rows["labs"] = _stream_domain_events(
                config,
                pattern="lab_results_NEW_*.csv",
                usecols=NORMALIZED_LAB_COLUMNS,
                dtype=LAB_DTYPE,
                derive=derive_lab_events,
                label="labs",
                event_writers=event_writers,
                event_counts=event_counts,
                membership=membership,
                logger=logger,
            )
            input_rows["diagnosis"] = _stream_domain_events(
                config,
                pattern="diagnosis_NEW_*.csv",
                usecols=DIAGNOSIS_COLUMNS,
                dtype=DIAGNOSIS_DTYPE,
                derive=derive_diagnosis_rfs_event_frames,
                label="diagnosis",
                event_writers=event_writers,
                event_counts=event_counts,
                membership=membership,
                logger=logger,
            )
            input_rows["procedure"] = _stream_domain_events(
                config,
                pattern="procedure_NEW_*.csv",
                usecols=PROCEDURE_COLUMNS,
                dtype=PROCEDURE_DTYPE,
                derive=derive_procedure_rfs_event_frames,
                label="procedure",
                event_writers=event_writers,
                event_counts=event_counts,
                membership=membership,
                logger=logger,
            )
            input_rows["vitals"] = _stream_domain_events(
                config,
                pattern="vital_signs_NEW_*.csv",
                usecols=VITALS_COLUMNS,
                dtype=VITALS_DTYPE,
                derive=derive_vitals_rfs_event_frames,
                label="vitals",
                event_writers=event_writers,
                event_counts=event_counts,
                membership=membership,
                logger=logger,
            )

        for category in RFS_CATEGORIES:
            if event_counts[category] == 0:
                event_writers[category].write(pd.DataFrame(columns=RFS_EVENT_COLUMNS))

        output_paths.extend(_write_rfs_flags(config, membership, logger))
        for category in RFS_CATEGORIES:
            writer = event_writers[category]
            output_paths.extend(writer.written_paths)
            logger.info(
                "Wrote %s rows to %s",
                event_counts[category],
                writer.written_paths[0].name,
            )
        if not using_analysis_index:
            for category, counts in lab_audit_counts.items():
                logger.info("%s rule audit: %s", category, counts)
        else:
            logger.info(
                "Using preclassified RFS candidates; gas audit: %s",
                config.work_dir / "rfs_rule_audit.json",
            )

    metrics = {
        "schema_version": 1,
        "ruleset": config.rfs.ruleset,
        "used_analysis_index": using_analysis_index,
        "source_files": sorted(
            path.name
            for path in (
                resolve_work_table(config, logical_name)
                for logical_name in RFS_ANALYSIS_SOURCES.values()
            )
            if path.exists()
        ),
        "input_rows": input_rows,
        "event_rows": event_counts,
    }
    write_text_atomic(
        config.work_dir / "rfs_stage_metrics.json",
        json.dumps(metrics, indent=2, sort_keys=True) + "\n",
    )

    return output_paths


def _has_complete_rfs_analysis(config: Config) -> bool:
    return all(
        resolve_work_table(config, logical_name).exists()
        for logical_name in RFS_ANALYSIS_SOURCES.values()
    )


def _stream_indexed_rfs_events(
    config: Config,
    *,
    event_writers: dict[str, WorkTableWriter],
    event_counts: dict[str, int],
    membership: "_RfsMembershipStore",
    logger: logging.Logger,
) -> dict[str, int]:
    chunksize = config.chunking.lines_per_chunk if config.chunking.enabled else None
    input_rows: dict[str, int] = {}
    for label, logical_name in RFS_ANALYSIS_SOURCES.items():
        path = resolve_work_table(config, logical_name)
        rows_read = 0
        for frame in iter_work_tables(
            [path],
            chunksize=chunksize,
            usecols=["category", *RFS_EVENT_COLUMNS],
            dtype={
                "category": "string",
                "patient_id": "string",
                "encounter_id": "string",
            },
        ):
            rows_read += len(frame)
            for category, events in frame.groupby("category", sort=False):
                category_name = str(category)
                if category_name not in event_writers:
                    raise ValueError(f"Unknown RFS category in {path}: {category_name}")
                selected = events.loc[:, RFS_EVENT_COLUMNS]
                event_writers[category_name].write(selected)
                event_counts[category_name] += len(selected)
                membership.add_events(category_name, selected["encounter_id"])
        log_row_count(logger, f"rfs indexed input {label}", rows_read)
        input_rows[label] = rows_read
    return input_rows


def _iter_work_domain(
    config: Config,
    pattern: str,
    *,
    usecols: list[str],
    dtype: dict[str, str],
):
    paths = find_work_tables(config, pattern)
    if not paths:
        raise FileNotFoundError(
            f"No files found for pattern '{pattern}' under {config.work_dir}."
        )

    chunksize = config.chunking.lines_per_chunk if config.chunking.enabled else None
    yield from iter_work_tables(
        paths,
        chunksize=chunksize,
        usecols=usecols,
        dtype=dtype,
    )


def _stream_domain_events(
    config: Config,
    *,
    pattern: str,
    usecols: list[str],
    dtype: dict[str, str],
    derive,
    label: str,
    event_writers: dict[str, WorkTableWriter],
    event_counts: dict[str, int],
    membership: "_RfsMembershipStore",
    logger: logging.Logger,
) -> int:
    rows_read = 0
    for frame in _iter_work_domain(config, pattern, usecols=usecols, dtype=dtype):
        rows_read += len(frame)
        for category, events in derive(frame).items():
            if events.empty:
                continue
            event_writers[category].write(events)
            event_counts[category] += len(events)
            membership.add_events(
                category,
                events["encounter_id"].dropna().astype("string").tolist(),
            )
    log_row_count(logger, f"rfs input {label}", rows_read)
    return rows_read


def _write_rfs_flags(
    config: Config,
    membership: "_RfsMembershipStore",
    logger: logging.Logger,
) -> list[Path]:
    rows_written = 0
    with (
        WorkTableWriter(config, "rfs_encounter_flags.csv") as writer,
        _RfsEncounterStore(config.work_dir, membership.bucket_count) as encounters,
    ):
        for frame in _iter_work_domain(
            config,
            "encounter_NEW_*.csv",
            usecols=ENCOUNTER_ID_COLUMNS,
            dtype=ENCOUNTER_DTYPE,
        ):
            base = frame.loc[:, ENCOUNTER_ID_COLUMNS].dropna(subset=["encounter_id"])
            base = base.drop_duplicates(subset=["encounter_id"], keep="first")
            encounters.add_frame(base)

        for bucket, current in encounters.iter_unique_frames():
            if current.empty:
                continue
            flags = _build_rfs_flags_from_membership(
                current,
                membership,
                bucket=bucket,
            )
            rows_written += len(flags)
            writer.write(flags)
        if rows_written == 0:
            writer.write(pd.DataFrame(columns=RFS_OUTPUT_COLUMNS))
        log_row_count(logger, "rfs input encounters", encounters.seen_count)
        logger.info("Wrote %s rows to %s", rows_written, writer.written_paths[0].name)
        return list(writer.written_paths)


def _build_rfs_flags_from_membership(
    encounters: pd.DataFrame,
    membership: "_RfsMembershipStore",
    *,
    bucket: int | None = None,
) -> pd.DataFrame:
    base = encounters.loc[:, ENCOUNTER_ID_COLUMNS].drop_duplicates().copy()
    base["patient_id"] = base["patient_id"].astype("string")
    base["encounter_id"] = base["encounter_id"].astype("string")
    if bucket is not None:
        membership.add_flags_for_bucket(base, bucket=bucket)
    else:
        for category, column in RFS_FLAG_COLUMNS:
            matches = membership.matching_encounter_ids(
                category,
                base["encounter_id"].tolist(),
            )
            base[column] = base["encounter_id"].isin(matches)
    return base.loc[:, RFS_OUTPUT_COLUMNS].reset_index(drop=True)


class _RfsMembershipStore:
    """Hash-bucketed RFS encounter-id membership sets for the RFS stage."""

    def __init__(self, work_dir: Path, *, bucket_count: int = RFS_BUCKET_COUNT) -> None:
        self.work_dir = work_dir
        self.bucket_count = bucket_count
        self._store: PartitionedParquetStore | None = None

    def __enter__(self) -> "_RfsMembershipStore":
        self._store = PartitionedParquetStore(
            self.work_dir,
            prefix=".trinetx-rfs-membership-",
            key_columns=["encounter_id"],
            bucket_count=self.bucket_count,
            cleanup_context="RFS membership scratch",
        )
        self._store.__enter__()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._store is not None:
            self._store.__exit__(exc_type, exc, tb)

    def add_events(self, category: str, encounter_ids: Iterable[object]) -> None:
        normalized_ids = _normalized_identifier_values(encounter_ids)
        if not normalized_ids:
            return
        frame = pd.DataFrame({"category": category, "encounter_id": normalized_ids})
        self._partition_store().add_frame(frame.loc[:, RFS_MEMBERSHIP_COLUMNS])

    def matching_encounter_ids(
        self,
        category: str,
        encounter_ids: Iterable[object],
    ) -> set[str]:
        normalized_ids = _normalized_identifier_values(encounter_ids)
        if not normalized_ids:
            return set()

        requested = pd.DataFrame({"encounter_id": normalized_ids}).drop_duplicates()
        requested["_bucket"] = stable_bucket_ids(
            requested.loc[:, ["encounter_id"]],
            bucket_count=self.bucket_count,
        ).to_numpy()

        matches: set[str] = set()
        for bucket, group in requested.groupby("_bucket", sort=False):
            frame = self._partition_store().read_frame(
                int(bucket), columns=RFS_MEMBERSHIP_COLUMNS
            )
            if frame is None:
                continue
            ids = set(group["encounter_id"].astype(str))
            available = set(
                frame.loc[frame["category"] == category, "encounter_id"].astype(str)
            )
            matches.update(ids & available)
        return matches

    def add_flags_for_bucket(self, encounters: pd.DataFrame, *, bucket: int) -> None:
        """Add every category flag using one membership partition read."""

        membership = self._partition_store().read_frame(
            bucket,
            columns=RFS_MEMBERSHIP_COLUMNS,
        )
        for category, column in RFS_FLAG_COLUMNS:
            if membership is None or membership.empty:
                encounters[column] = False
                continue
            available = membership.loc[
                membership["category"] == category,
                "encounter_id",
            ]
            encounters[column] = encounters["encounter_id"].isin(available)

    def _partition_store(self) -> PartitionedParquetStore:
        if self._store is None:
            raise RuntimeError("RFS membership store is not open.")
        return self._store


class _RfsEncounterStore:
    """Hash-bucketed first-seen encounter rows for RFS flag generation."""

    def __init__(self, work_dir: Path, bucket_count: int) -> None:
        self.work_dir = work_dir
        self.bucket_count = bucket_count
        self._store: PartitionedParquetStore | None = None
        self._next_row_order = 0
        self.seen_count = 0

    def __enter__(self) -> "_RfsEncounterStore":
        self._store = PartitionedParquetStore(
            self.work_dir,
            prefix=".trinetx-rfs-encounters-",
            key_columns=["encounter_id"],
            bucket_count=self.bucket_count,
            cleanup_context="RFS encounter scratch",
        )
        self._store.__enter__()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._store is not None:
            self._store.__exit__(exc_type, exc, tb)

    def add_frame(self, encounters: pd.DataFrame) -> None:
        if encounters.empty:
            return
        frame = encounters.loc[:, ENCOUNTER_ID_COLUMNS].copy()
        frame["patient_id"] = frame["patient_id"].astype("string")
        frame["encounter_id"] = frame["encounter_id"].astype("string")
        frame["_row_order"] = range(
            self._next_row_order,
            self._next_row_order + len(frame),
        )
        self._next_row_order += len(frame)
        self._partition_store().add_frame(frame.loc[:, RFS_BUCKETED_ENCOUNTER_COLUMNS])

    def iter_unique_frames(self) -> Iterable[tuple[int, pd.DataFrame]]:
        for bucket, frame in self._partition_store().iter_frames(
            columns=RFS_BUCKETED_ENCOUNTER_COLUMNS
        ):
            if frame.empty:
                continue
            unique = (
                frame.sort_values("_row_order", kind="mergesort")
                .drop_duplicates(subset=["encounter_id"], keep="first")
                .loc[:, ENCOUNTER_ID_COLUMNS]
                .reset_index(drop=True)
            )
            self.seen_count += len(unique)
            yield bucket, unique

    def _partition_store(self) -> PartitionedParquetStore:
        if self._store is None:
            raise RuntimeError("RFS encounter store is not open.")
        return self._store


def _normalized_identifier_values(values: Iterable[object]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if pd.isna(value):
            continue
        normalized = str(value)
        if normalized in seen:
            continue
        result.append(normalized)
        seen.add(normalized)
    return result

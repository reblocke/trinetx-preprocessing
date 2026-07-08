"""RFS stage runner built from legacy notebook logic."""

from __future__ import annotations

import hashlib
import logging
import tempfile
from contextlib import ExitStack
from pathlib import Path
from typing import Iterable

import pandas as pd

from ..config import Config
from ..filesystem import remove_tree_strict
from ..guardrails import log_row_count
from ..storage import WorkTableWriter, find_work_tables, iter_work_tables
from ..transform.diagnosis import DIAGNOSIS_COLUMNS
from ..transform.labs import LAB_COLUMNS
from ..transform.procedure import PROCEDURE_COLUMNS
from ..transform.rfs import (
    ENCOUNTER_ID_COLUMNS,
    RFS_CATEGORIES,
    RFS_EVENT_COLUMNS,
    RFS_FLAG_COLUMNS,
    RFS_OUTPUT_COLUMNS,
    derive_diagnosis_rfs_event_frames,
    derive_lab_rfs_event_frames,
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
    "code": "string",
    "date": "string",
    "lab_result_num_val": "float32",
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
    "value": "float32",
}

RFS_BUCKET_COUNT = 256
RFS_MEMBERSHIP_COLUMNS = ["encounter_id"]
RFS_BUCKETED_ENCOUNTER_COLUMNS = ["_row_order", "patient_id", "encounter_id"]


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

    with ExitStack() as stack, _RfsMembershipStore(config.work_dir) as membership:
        event_writers = {
            category: stack.enter_context(
                WorkTableWriter(config, f"RFS_{category}.csv")
            )
            for category in RFS_CATEGORIES
        }

        _stream_domain_events(
            config,
            pattern="lab_results_NEW_*.csv",
            usecols=LAB_COLUMNS,
            dtype=LAB_DTYPE,
            derive=derive_lab_rfs_event_frames,
            label="labs",
            event_writers=event_writers,
            event_counts=event_counts,
            membership=membership,
            logger=logger,
        )
        _stream_domain_events(
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
        _stream_domain_events(
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
        _stream_domain_events(
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

    return output_paths


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
) -> None:
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

        for _, current in encounters.iter_unique_frames():
            if current.empty:
                continue
            flags = _build_rfs_flags_from_membership(current, membership)
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
) -> pd.DataFrame:
    base = encounters.loc[:, ENCOUNTER_ID_COLUMNS].drop_duplicates().copy()
    base["patient_id"] = base["patient_id"].astype("string")
    base["encounter_id"] = base["encounter_id"].astype("string")
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
        self.path: Path | None = None
        self._written_paths: set[Path] = set()

    def __enter__(self) -> "_RfsMembershipStore":
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self.path = Path(
            tempfile.mkdtemp(prefix=".trinetx-rfs-membership-", dir=self.work_dir)
        )
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self._remove_scratch_dir()

    def add_events(self, category: str, encounter_ids: Iterable[object]) -> None:
        normalized_ids = _normalized_identifier_values(encounter_ids)
        if not normalized_ids:
            return
        frame = pd.DataFrame({"encounter_id": normalized_ids})
        frame["_bucket"] = frame["encounter_id"].map(
            lambda value: _encounter_id_bucket(value, self.bucket_count)
        )
        for bucket, bucket_frame in frame.groupby("_bucket", sort=False):
            _append_csv_frame(
                self._bucket_path(category, int(bucket)),
                bucket_frame.loc[:, RFS_MEMBERSHIP_COLUMNS],
                written_paths=self._written_paths,
            )

    def matching_encounter_ids(
        self,
        category: str,
        encounter_ids: Iterable[object],
    ) -> set[str]:
        normalized_ids = _normalized_identifier_values(encounter_ids)
        if not normalized_ids:
            return set()

        ids_by_bucket: dict[int, set[str]] = {}
        for encounter_id in normalized_ids:
            bucket = _encounter_id_bucket(encounter_id, self.bucket_count)
            ids_by_bucket.setdefault(bucket, set()).add(encounter_id)

        matches: set[str] = set()
        for bucket, ids in ids_by_bucket.items():
            matches.update(ids & self._load_bucket(category, bucket))
        return matches

    def _bucket_path(self, category: str, bucket: int) -> Path:
        if self.path is None:
            raise RuntimeError("RFS membership store is not open.")
        return self.path / f"{category}_{bucket:03}.csv"

    def _load_bucket(self, category: str, bucket: int) -> set[str]:
        path = self._bucket_path(category, bucket)
        if not path.exists():
            return set()
        frame = pd.read_csv(
            path,
            usecols=RFS_MEMBERSHIP_COLUMNS,
            dtype={"encounter_id": "string"},
        )
        return set(frame["encounter_id"].dropna().astype("string").astype(str))

    def _remove_scratch_dir(self) -> None:
        if self.path is None:
            return
        remove_tree_strict(self.path, context="RFS membership scratch")


class _RfsEncounterStore:
    """Hash-bucketed first-seen encounter rows for RFS flag generation."""

    def __init__(self, work_dir: Path, bucket_count: int) -> None:
        self.work_dir = work_dir
        self.bucket_count = bucket_count
        self.path: Path | None = None
        self._written_paths: set[Path] = set()
        self._next_row_order = 0
        self.seen_count = 0

    def __enter__(self) -> "_RfsEncounterStore":
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self.path = Path(
            tempfile.mkdtemp(prefix=".trinetx-rfs-encounters-", dir=self.work_dir)
        )
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self._remove_scratch_dir()

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
        frame["_bucket"] = frame["encounter_id"].map(
            lambda value: _encounter_id_bucket(str(value), self.bucket_count)
        )

        for bucket, bucket_frame in frame.groupby("_bucket", sort=False):
            _append_csv_frame(
                self._bucket_path(int(bucket)),
                bucket_frame.loc[:, RFS_BUCKETED_ENCOUNTER_COLUMNS],
                written_paths=self._written_paths,
            )

    def iter_unique_frames(self) -> Iterable[tuple[int, pd.DataFrame]]:
        for bucket in range(self.bucket_count):
            path = self._bucket_path(bucket)
            if not path.exists():
                continue
            frame = pd.read_csv(
                path,
                usecols=RFS_BUCKETED_ENCOUNTER_COLUMNS,
                dtype={"patient_id": "string", "encounter_id": "string"},
            )
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

    def _bucket_path(self, bucket: int) -> Path:
        if self.path is None:
            raise RuntimeError("RFS encounter store is not open.")
        return self.path / f"encounters_{bucket:03}.csv"

    def _remove_scratch_dir(self) -> None:
        if self.path is None:
            return
        remove_tree_strict(self.path, context="RFS encounter scratch")


def _append_csv_frame(
    path: Path,
    frame: pd.DataFrame,
    *,
    written_paths: set[Path],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    is_written = path in written_paths
    frame.to_csv(
        path,
        index=False,
        mode="a" if is_written else "w",
        header=not is_written,
    )
    written_paths.add(path)


def _encounter_id_bucket(encounter_id: str, bucket_count: int) -> int:
    digest = hashlib.blake2b(encounter_id.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, byteorder="big") % bucket_count


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

"""Encounter stage runner built from legacy notebook logic."""

from __future__ import annotations

import json
import logging
import re
from collections import Counter
from collections.abc import Iterable
from pathlib import Path

import pandas as pd

from ..config import Config, ConfigError, collect_domain_paths
from ..guardrails import log_row_count
from ..io.csv import iter_csv
from ..storage import PartitionedParquetStore, WorkTableWriter
from ..transform.encounter import (
    DEFAULT_END_DATE_FILL,
    DEFAULT_START_DATE,
    ENCOUNTER_COLUMNS,
    ENCOUNTER_OUTPUT_COLUMNS,
    ENCOUNTER_TYPES,
    RAW_ENCOUNTER_COLUMNS,
    filter_encounters_for_types,
    normalize_encounter_chunk,
)

RAW_DTYPE = {
    "encounter_id": "string",
    "patient_id": "string",
    "type": "string",
    "start_date_derived_by_TriNetX": "string",
    "end_date_derived_by_TriNetX": "string",
    "derived_by_TriNetX": "string",
    "source_id": "string",
}

OUTPUT_FILENAMES = {
    "AMB": "AMB_encounters.csv",
    "EMER": "EMER_encounters.csv",
    "IMP": "INPAT_encounters.csv",
}

REDUCER_BUCKET_COUNT = 128
REDUCER_COLUMNS = [
    "encounter_type",
    "encounter_id_key",
    "encounter_id",
    "patient_id",
    "start_date_ns",
    "end_date_ns",
    "type",
    "row_order",
]


def run_encounter_stage(config: Config, *, strict: bool = False) -> list[Path]:
    """Run the encounter stage and write outputs under ``work_dir``.

    Args:
        config: Pipeline configuration.

    Returns:
        List of written file paths.
    """

    logger = logging.getLogger(__name__)
    domain_paths = collect_domain_paths(config)
    encounter_paths = domain_paths.get("encounter")
    if not encounter_paths:
        raise ConfigError("Encounter domain is not configured.")

    config.work_dir.mkdir(parents=True, exist_ok=True)

    output_paths: list[Path] = []
    filtered_counts: dict[str, int] = {
        encounter_type: 0 for encounter_type in ENCOUNTER_TYPES
    }

    with _EncounterReducerStore(config.work_dir) as reducer:
        for index, path in enumerate(encounter_paths, start=1):
            logger.info("Reading encounter export: %s", path.name)
            rows_read = 0
            rows_normalized = 0
            chunksize = (
                config.chunking.lines_per_chunk if config.chunking.enabled else None
            )
            with WorkTableWriter(config, _normalized_filename(path, index)) as writer:
                chunk_index = 0
                for chunk in iter_csv(
                    path,
                    chunksize=chunksize,
                    usecols=RAW_ENCOUNTER_COLUMNS,
                    dtype=RAW_DTYPE,
                    parse_dates=["start_date", "end_date"],
                ):
                    chunk_index += 1
                    rows_read += len(chunk)
                    normalized = normalize_encounter_chunk(chunk)
                    rows_normalized += len(normalized)
                    writer.write(normalized)

                    filtered = filter_encounters_for_types(
                        normalized,
                        start_date_min=DEFAULT_START_DATE,
                        end_date_fill=DEFAULT_END_DATE_FILL,
                    )
                    reducer.update(filtered)
                    for encounter_type, count in (
                        filtered["type"].value_counts(sort=False).items()
                    ):
                        filtered_counts[str(encounter_type)] += int(count)
                    if chunk_index % 10 == 0:
                        logger.info(
                            "Processed %s encounter chunks from %s (%s rows read)",
                            chunk_index,
                            path.name,
                            rows_read,
                        )
                output_paths.extend(writer.written_paths)
                log_row_count(logger, f"encounter read {path.name}", rows_read)
                log_row_count(
                    logger,
                    f"encounter normalized {path.name}",
                    rows_normalized,
                )

        conflict_summary = reducer.conflict_summary()
        if conflict_summary["encounter_conflict_count"]:
            if strict:
                raise ConfigError(
                    "Encounter IDs appear in multiple settings: "
                    f"{conflict_summary['encounter_conflict_count']} conflicts."
                )
            conflict_path = config.work_dir / "encounter_conflicts.json"
            conflict_path.write_text(
                json.dumps(conflict_summary, indent=2, sort_keys=True) + "\n"
            )
            output_paths.append(conflict_path)
            logger.warning(
                "Resolved %s cross-setting encounter conflicts; aggregate report: %s",
                conflict_summary["encounter_conflict_count"],
                conflict_path,
            )

        for encounter_type, filename in OUTPUT_FILENAMES.items():
            log_row_count(
                logger,
                f"encounter post-filter {encounter_type}",
                filtered_counts[encounter_type],
            )
            with WorkTableWriter(config, filename) as writer:
                rows_written = 0
                wrote_any = False
                for batch_index, finalized in enumerate(
                    reducer.iter_finalized_frames(
                        encounter_type,
                        batch_size=config.storage.parquet_row_group_size,
                    ),
                    start=1,
                ):
                    writer.write(finalized)
                    rows_written += len(finalized)
                    wrote_any = True
                    if batch_index % 10 == 0:
                        logger.info(
                            "Wrote %s %s encounter rows so far",
                            rows_written,
                            encounter_type,
                        )
                if not wrote_any:
                    writer.write(pd.DataFrame(columns=ENCOUNTER_OUTPUT_COLUMNS))
                output_paths.extend(writer.written_paths)
                logger.info(
                    "Wrote %s rows to %s",
                    rows_written,
                    writer.written_paths[0].name,
                )

    return output_paths


def _normalized_filename(path: Path, index: int) -> str:
    match = re.search(r"(\d{4})$", path.stem)
    suffix = match.group(1) if match else f"{index:04}"
    return f"encounter_NEW_{suffix}.csv"


class _EncounterReducerStore:
    """Disk-backed reducer for setting-level encounter outputs."""

    def __init__(
        self,
        work_dir: Path,
        *,
        bucket_count: int = REDUCER_BUCKET_COUNT,
    ) -> None:
        if bucket_count <= 0:
            raise ValueError("bucket_count must be a positive integer.")
        self.work_dir = work_dir
        self.bucket_count = bucket_count
        self._store: PartitionedParquetStore | None = None
        self.next_row_order = 0

    def __enter__(self) -> "_EncounterReducerStore":
        self._store = PartitionedParquetStore(
            self.work_dir,
            prefix=".trinetx-encounter-reducer-",
            key_columns=["encounter_id_key"],
            bucket_count=self.bucket_count,
            cleanup_context="Encounter reducer scratch",
        )
        self._store.__enter__()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._store is not None:
            self._store.__exit__(exc_type, exc, tb)

    def update(self, filtered: pd.DataFrame) -> None:
        if filtered.empty:
            return
        observed = filtered.copy()
        observed["_row_order"] = range(
            self.next_row_order,
            self.next_row_order + len(observed),
        )
        self.next_row_order += len(observed)
        candidates = (
            observed.sort_values(
                by=["start_date", "_row_order"],
                ascending=[True, True],
                kind="mergesort",
            )
            .drop_duplicates(subset=["type", "encounter_id"], keep="first")
            .reset_index(drop=True)
        )
        if candidates.empty:
            return

        encounter_id = candidates["encounter_id"]
        records = pd.DataFrame(
            {
                "encounter_type": candidates["type"],
                "encounter_id_key": _encounter_id_keys(encounter_id),
                "encounter_id": _nullable_series(encounter_id),
                "patient_id": _nullable_series(candidates["patient_id"]),
                "start_date_ns": _timestamp_ns_series(candidates["start_date"]),
                "end_date_ns": _timestamp_ns_series(candidates["end_date"]),
                "type": _nullable_series(candidates["type"]),
                "row_order": candidates["_row_order"],
            }
        )

        self._partition_store().add_frame(records.loc[:, REDUCER_COLUMNS])

    def frame(self, encounter_type: str) -> pd.DataFrame:
        frames = list(
            self._iter_reduced_frames(
                encounter_type,
                batch_size=max(self.next_row_order, 1),
            )
        )
        if not frames:
            return pd.DataFrame(columns=ENCOUNTER_COLUMNS)
        return pd.concat(frames, ignore_index=True)

    def iter_finalized_frames(
        self,
        encounter_type: str,
        *,
        batch_size: int,
    ) -> Iterable[pd.DataFrame]:
        """Yield finalized setting encounter output frames in bounded batches."""

        for frame in self._iter_reduced_frames(
            encounter_type,
            batch_size=batch_size,
        ):
            finalized = _finalize_reduced_frame(frame)
            if not finalized.empty:
                yield finalized

    def conflict_summary(self) -> dict[str, object]:
        """Return aggregate counts for encounter IDs seen in multiple settings."""

        conflict_count = 0
        combinations: Counter[str] = Counter()
        for _, bucket in self._partition_store().iter_frames(columns=REDUCER_COLUMNS):
            if bucket.empty:
                continue
            types = bucket.groupby("encounter_id_key", sort=False)[
                "encounter_type"
            ].agg(lambda values: tuple(sorted(set(values.dropna().astype(str)))))
            conflicts = types.loc[types.map(len) > 1]
            conflict_count += len(conflicts)
            combinations.update("+".join(values) for values in conflicts)
        return {
            "schema_version": 1,
            "encounter_conflict_count": conflict_count,
            "type_combinations": dict(sorted(combinations.items())),
        }

    def _iter_reduced_frames(
        self,
        encounter_type: str,
        *,
        batch_size: int,
    ) -> Iterable[pd.DataFrame]:
        if batch_size <= 0:
            raise ValueError("batch_size must be a positive integer.")
        for _, bucket in self._partition_store().iter_frames(columns=REDUCER_COLUMNS):
            if bucket.empty:
                continue
            reduced = (
                bucket.sort_values(
                    by=["start_date_ns", "row_order"],
                    ascending=[True, True],
                    kind="mergesort",
                )
                .drop_duplicates(subset=["encounter_id_key"], keep="first")
                .reset_index(drop=True)
            )
            reduced = reduced.loc[reduced["encounter_type"] == encounter_type]
            if reduced.empty:
                continue
            for start in range(0, len(reduced), batch_size):
                rows = reduced.iloc[start : start + batch_size].loc[
                    :,
                    [
                        "patient_id",
                        "encounter_id",
                        "start_date_ns",
                        "end_date_ns",
                        "type",
                    ],
                ]
                yield _rows_to_encounter_frame(
                    list(rows.itertuples(index=False, name=None))
                )

    def _partition_store(self) -> PartitionedParquetStore:
        if self._store is None:
            raise RuntimeError("Encounter reducer store is not open.")
        return self._store


def _timestamp_ns_series(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series).astype("int64")


def _nullable_series(series: pd.Series) -> pd.Series:
    values = series.astype(object)
    return values.where(pd.notna(values), None)


def _encounter_id_keys(series: pd.Series) -> pd.Series:
    values = series.astype("string")
    keys = "value:" + values
    return keys.where(values.notna(), "missing:")


def _rows_to_encounter_frame(rows: list[tuple[object, ...]]) -> pd.DataFrame:
    frame = pd.DataFrame.from_records(
        rows,
        columns=[
            "patient_id",
            "encounter_id",
            "start_date_ns",
            "end_date_ns",
            "type",
        ],
    )
    frame["start_date"] = pd.to_datetime(frame.pop("start_date_ns"), unit="ns")
    frame["end_date"] = pd.to_datetime(frame.pop("end_date_ns"), unit="ns")
    return frame.loc[:, ENCOUNTER_COLUMNS]


def _finalize_reduced_frame(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=ENCOUNTER_OUTPUT_COLUMNS)
    finalized = frame.loc[:, ENCOUNTER_COLUMNS].copy()
    finalized["start_date"] = pd.to_datetime(finalized["start_date"])
    finalized["end_date"] = pd.to_datetime(finalized["end_date"])
    finalized["LOS"] = (finalized["end_date"] - finalized["start_date"]).dt.days + 1
    finalized = finalized.loc[finalized["LOS"] > 0]
    return finalized.loc[:, ENCOUNTER_OUTPUT_COLUMNS].reset_index(drop=True)

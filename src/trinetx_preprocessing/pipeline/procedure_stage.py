"""Procedure stage runner built from legacy notebook logic."""

from __future__ import annotations

import logging
import re
from contextlib import ExitStack
from pathlib import Path

import pandas as pd

from ..config import Config, ConfigError, collect_domain_paths
from ..guardrails import log_row_count
from ..io.csv import iter_csv
from ..storage import WorkTableWriter
from ..transform.procedure import (
    PROCEDURE_CODE_GROUPS,
    PROCEDURE_COLUMNS,
    RAW_PROCEDURE_COLUMNS,
    normalize_procedure_chunk,
    split_procedure_by_code,
)
from ..transform.rfs import RFS_EVENT_COLUMNS, derive_procedure_rfs_event_frames
from .analysis_index import (
    FEATURE_NAME_COLUMN,
    RFS_CATEGORY_COLUMN,
    stack_grouped_frames,
    stack_rfs_events,
)

RAW_DTYPE = {
    "patient_id": "string",
    "encounter_id": "string",
    "code_system": "string",
    "code": "string",
    "principal_procedure_indicator": "string",
    "derived_by_TriNetX": "string",
    "source_id": "string",
}


def run_procedure_stage(config: Config) -> list[Path]:
    """Run the procedure stage and write outputs under ``work_dir``.

    Args:
        config: Pipeline configuration.

    Returns:
        List of written file paths.
    """

    logger = logging.getLogger(__name__)
    domain_paths = collect_domain_paths(config)
    procedure_paths = domain_paths.get("procedure")
    if not procedure_paths:
        raise ConfigError("Procedure domain is not configured.")

    config.work_dir.mkdir(parents=True, exist_ok=True)

    output_paths: list[Path] = []
    grouped_counts = {group.name: 0 for group in PROCEDURE_CODE_GROUPS}
    chunksize = config.chunking.lines_per_chunk if config.chunking.enabled else None

    with ExitStack() as stack:
        analysis_writer = stack.enter_context(
            WorkTableWriter(config, "analysis_procedure_features.csv")
        )
        analysis_rows = 0
        rfs_writer = stack.enter_context(
            WorkTableWriter(config, "analysis_rfs_procedure.csv")
        )
        rfs_rows = 0
        grouped_writers: dict[str, WorkTableWriter] = {}
        for index, path in enumerate(procedure_paths, start=1):
            logger.info("Reading procedure export: %s", path.name)
            rows_read = 0
            rows_normalized = 0
            with WorkTableWriter(config, _normalized_filename(path, index)) as writer:
                for chunk in iter_csv(
                    path,
                    chunksize=chunksize,
                    usecols=RAW_PROCEDURE_COLUMNS,
                    dtype=RAW_DTYPE,
                    parse_dates=["date"],
                ):
                    rows_read += len(chunk)
                    normalized = normalize_procedure_chunk(chunk)
                    rows_normalized += len(normalized)
                    writer.write(normalized)
                    rfs_index = stack_rfs_events(
                        derive_procedure_rfs_event_frames(normalized),
                        event_columns=RFS_EVENT_COLUMNS,
                    )
                    if not rfs_index.empty:
                        rfs_writer.write(rfs_index)
                        rfs_rows += len(rfs_index)

                    grouped = split_procedure_by_code(normalized)
                    analysis = stack_grouped_frames(grouped, columns=PROCEDURE_COLUMNS)
                    if not analysis.empty:
                        analysis_writer.write(analysis)
                        analysis_rows += len(analysis)
                    for name, frame in grouped.items():
                        if frame.empty:
                            continue
                        grouped_counts[name] += len(frame)
                        if not config.storage.emit_legacy_group_tables:
                            continue
                        group_writer = grouped_writers.get(name)
                        if group_writer is None:
                            group_writer = stack.enter_context(
                                WorkTableWriter(config, f"{name}.csv")
                            )
                            grouped_writers[name] = group_writer
                        group_writer.write(frame)
                output_paths.extend(writer.written_paths)
                log_row_count(logger, f"procedure read {path.name}", rows_read)
                log_row_count(
                    logger,
                    f"procedure normalized {path.name}",
                    rows_normalized,
                )
                logger.info(
                    "Wrote %s rows to %s",
                    rows_normalized,
                    writer.written_paths[0].name,
                )

        if analysis_rows == 0:
            analysis_writer.write(
                pd.DataFrame(columns=[FEATURE_NAME_COLUMN, *PROCEDURE_COLUMNS])
            )
        if rfs_rows == 0:
            rfs_writer.write(
                pd.DataFrame(columns=[RFS_CATEGORY_COLUMN, *RFS_EVENT_COLUMNS])
            )

        if config.storage.emit_legacy_group_tables:
            for group in PROCEDURE_CODE_GROUPS:
                writer = grouped_writers.get(group.name)
                if writer is None:
                    with WorkTableWriter(config, f"{group.name}.csv") as empty_writer:
                        empty_writer.write(pd.DataFrame(columns=PROCEDURE_COLUMNS))
                        output_paths.extend(empty_writer.written_paths)
                        logger.info(
                            "Wrote 0 rows to %s", empty_writer.written_paths[0].name
                        )
                else:
                    output_paths.extend(writer.written_paths)
                    logger.info(
                        "Wrote %s rows to %s",
                        grouped_counts[group.name],
                        writer.written_paths[0].name,
                    )

    return output_paths


def _normalized_filename(path: Path, index: int) -> str:
    match = re.search(r"(\d{4})$", path.stem)
    suffix = match.group(1) if match else f"{index:04}"
    return f"procedure_NEW_{suffix}.csv"

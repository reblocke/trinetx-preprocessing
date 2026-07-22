"""Vital-signs stage runner built from legacy notebook logic."""

from __future__ import annotations

import logging
import re
from contextlib import ExitStack
from pathlib import Path

import pandas as pd

from ..combined_preprocessing.elements import ElementCaptureWriter
from ..config import Config, ConfigError, collect_domain_paths
from ..guardrails import log_row_count
from ..io.csv import iter_csv
from ..storage import WorkTableWriter
from ..transform.rfs import RFS_EVENT_COLUMNS, derive_vitals_rfs_event_frames
from ..transform.vitals import (
    RAW_VITALS_COLUMNS,
    VITAL_SIGN_RULES,
    VITALS_COLUMNS,
    normalize_vitals_chunk,
    split_vitals_by_rule,
)
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
    "text_value": "string",
    "units_of_measure": "string",
    "derived_by_TriNetX": "string",
    "source_id": "string",
}


def run_vitals_stage(config: Config) -> list[Path]:
    """Run the vital-signs stage and write outputs under ``work_dir``.

    Args:
        config: Pipeline configuration.

    Returns:
        List of written file paths.
    """

    logger = logging.getLogger(__name__)
    domain_paths = collect_domain_paths(config)
    vitals_paths = domain_paths.get("vitals")
    if not vitals_paths:
        raise ConfigError("Vitals domain is not configured.")

    config.work_dir.mkdir(parents=True, exist_ok=True)

    output_paths: list[Path] = []
    grouped_counts = {rule.name: 0 for rule in VITAL_SIGN_RULES}
    chunksize = config.chunking.lines_per_chunk if config.chunking.enabled else None

    with ExitStack() as stack:
        element_writer = stack.enter_context(ElementCaptureWriter(config, "vitals"))
        analysis_writer = stack.enter_context(
            WorkTableWriter(config, "analysis_vital_features.csv")
        )
        analysis_rows = 0
        rfs_writer = stack.enter_context(
            WorkTableWriter(config, "analysis_rfs_vitals.csv")
        )
        rfs_rows = 0
        grouped_writers: dict[str, WorkTableWriter] = {}
        for index, path in enumerate(vitals_paths, start=1):
            logger.info("Reading vital-signs export: %s", path.name)
            rows_read = 0
            rows_normalized = 0
            with WorkTableWriter(
                config,
                _normalized_filename(path, index),
                enabled=config.storage.emit_normalized_domain_tables,
            ) as writer:
                for chunk in iter_csv(
                    path,
                    chunksize=chunksize,
                    usecols=RAW_VITALS_COLUMNS,
                    dtype=(
                        {column: "string" for column in RAW_VITALS_COLUMNS}
                        if config.combined.enabled
                        else RAW_DTYPE
                    ),
                    parse_dates=None if config.combined.enabled else ["date"],
                ):
                    rows_read += len(chunk)
                    element_writer.add_chunk(chunk, source_path=path)
                    normalized = normalize_vitals_chunk(chunk)
                    rows_normalized += len(normalized)
                    writer.write(normalized)
                    rfs_index = stack_rfs_events(
                        derive_vitals_rfs_event_frames(normalized),
                        event_columns=RFS_EVENT_COLUMNS,
                    )
                    if not rfs_index.empty:
                        rfs_writer.write(rfs_index)
                        rfs_rows += len(rfs_index)

                    grouped = split_vitals_by_rule(normalized)
                    analysis = stack_grouped_frames(grouped, columns=VITALS_COLUMNS)
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
                log_row_count(logger, f"vitals read {path.name}", rows_read)
                log_row_count(logger, f"vitals normalized {path.name}", rows_normalized)
                if writer.written_paths:
                    logger.info(
                        "Wrote %s rows to %s",
                        rows_normalized,
                        writer.written_paths[0].name,
                    )

        if analysis_rows == 0:
            analysis_writer.write(
                pd.DataFrame(columns=[FEATURE_NAME_COLUMN, *VITALS_COLUMNS])
            )
        if rfs_rows == 0:
            rfs_writer.write(
                pd.DataFrame(columns=[RFS_CATEGORY_COLUMN, *RFS_EVENT_COLUMNS])
            )
        output_paths.extend(analysis_writer.written_paths)
        output_paths.extend(rfs_writer.written_paths)

        if config.storage.emit_legacy_group_tables:
            for rule in VITAL_SIGN_RULES:
                writer = grouped_writers.get(rule.name)
                if writer is None:
                    with WorkTableWriter(config, f"{rule.name}.csv") as empty_writer:
                        empty_writer.write(pd.DataFrame(columns=VITALS_COLUMNS))
                        output_paths.extend(empty_writer.written_paths)
                        logger.info(
                            "Wrote 0 rows to %s", empty_writer.written_paths[0].name
                        )
                else:
                    output_paths.extend(writer.written_paths)
                    logger.info(
                        "Wrote %s rows to %s",
                        grouped_counts[rule.name],
                        writer.written_paths[0].name,
                    )

    output_paths.extend(element_writer.written_paths)

    return output_paths


def _normalized_filename(path: Path, index: int) -> str:
    match = re.search(r"(\d{4})$", path.stem)
    suffix = match.group(1) if match else f"{index:04}"
    return f"vital_signs_NEW_{suffix}.csv"

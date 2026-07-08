"""Medications stage runner built from legacy notebook logic."""

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
from ..transform.medications import (
    MEDICATION_CODE_GROUPS,
    MEDICATION_COLUMNS,
    RAW_MEDICATION_COLUMNS,
    normalize_medications_chunk,
    split_medications_by_code,
)

RAW_DTYPE = {
    "patient_id": "string",
    "encounter_id": "string",
    "unique_id": "string",
    "code_system": "string",
    "code": "string",
    "route": "string",
    "brand": "string",
    "strength": "string",
    "derived_by_TriNetX": "string",
    "source_id": "string",
}


def run_medications_stage(config: Config) -> list[Path]:
    """Run the medications stage and write outputs under ``work_dir``.

    Args:
        config: Pipeline configuration.

    Returns:
        List of written file paths.
    """

    logger = logging.getLogger(__name__)
    domain_paths = collect_domain_paths(config)
    meds_paths = domain_paths.get("meds")
    if not meds_paths:
        raise ConfigError("Meds domain is not configured.")

    config.work_dir.mkdir(parents=True, exist_ok=True)

    output_paths: list[Path] = []
    grouped_counts = {group.name: 0 for group in MEDICATION_CODE_GROUPS}
    chunksize = config.chunking.lines_per_chunk if config.chunking.enabled else None

    with ExitStack() as stack:
        grouped_writers: dict[str, WorkTableWriter] = {}
        for index, path in enumerate(meds_paths, start=1):
            logger.info("Reading medications export: %s", path.name)
            rows_read = 0
            rows_normalized = 0
            with WorkTableWriter(config, _normalized_filename(path, index)) as writer:
                for chunk in iter_csv(
                    path,
                    chunksize=chunksize,
                    usecols=RAW_MEDICATION_COLUMNS,
                    dtype=RAW_DTYPE,
                    parse_dates=["start_date"],
                ):
                    rows_read += len(chunk)
                    normalized = normalize_medications_chunk(chunk)
                    rows_normalized += len(normalized)
                    writer.write(normalized)

                    grouped = split_medications_by_code(normalized)
                    for name, frame in grouped.items():
                        if frame.empty:
                            continue
                        group_writer = grouped_writers.get(name)
                        if group_writer is None:
                            group_writer = stack.enter_context(
                                WorkTableWriter(config, f"{name}.csv")
                            )
                            grouped_writers[name] = group_writer
                        group_writer.write(frame)
                        grouped_counts[name] += len(frame)
                output_paths.extend(writer.written_paths)
                log_row_count(logger, f"medications read {path.name}", rows_read)
                log_row_count(
                    logger,
                    f"medications normalized {path.name}",
                    rows_normalized,
                )
                logger.info(
                    "Wrote %s rows to %s",
                    rows_normalized,
                    writer.written_paths[0].name,
                )

        for group in MEDICATION_CODE_GROUPS:
            writer = grouped_writers.get(group.name)
            if writer is None:
                with WorkTableWriter(config, f"{group.name}.csv") as empty_writer:
                    empty_writer.write(pd.DataFrame(columns=MEDICATION_COLUMNS))
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
    return f"medication_NEW_{suffix}.csv"

"""Lab-results stage runner built from legacy notebook logic."""

from __future__ import annotations

import logging
import re
from pathlib import Path

from ..config import Config, ConfigError, collect_domain_paths
from ..guardrails import log_row_count
from ..io.csv import iter_csv
from ..storage import WorkTableWriter
from ..transform.labs import RAW_LAB_COLUMNS, normalize_lab_results_chunk

RAW_DTYPE = {
    "patient_id": "string",
    "encounter_id": "string",
    "code_system": "string",
    "code": "string",
    "lab_result_text_val": "string",
    "units_of_measure": "string",
    "derived_by_TriNetX": "string",
    "source_id": "string",
}


def run_labs_stage(config: Config) -> list[Path]:
    """Run the lab-results stage and write outputs under ``work_dir``.

    Args:
        config: Pipeline configuration.

    Returns:
        List of written file paths.
    """

    logger = logging.getLogger(__name__)
    domain_paths = collect_domain_paths(config)
    labs_paths = domain_paths.get("labs")
    if not labs_paths:
        raise ConfigError("Labs domain is not configured.")

    config.work_dir.mkdir(parents=True, exist_ok=True)

    output_paths: list[Path] = []
    chunksize = config.chunking.lines_per_chunk if config.chunking.enabled else None
    for index, path in enumerate(labs_paths, start=1):
        logger.info("Reading lab-results export: %s", path.name)
        rows_read = 0
        rows_written = 0
        with WorkTableWriter(config, _normalized_filename(path, index)) as writer:
            for chunk in iter_csv(
                path,
                chunksize=chunksize,
                usecols=RAW_LAB_COLUMNS,
                dtype=RAW_DTYPE,
                parse_dates=["date"],
            ):
                rows_read += len(chunk)
                normalized = normalize_lab_results_chunk(chunk)
                rows_written += len(normalized)
                writer.write(normalized)
            output_paths.extend(writer.written_paths)
            log_row_count(logger, f"labs read {path.name}", rows_read)
            log_row_count(logger, f"labs normalized {path.name}", rows_written)
            logger.info(
                "Wrote %s rows to %s", rows_written, writer.written_paths[0].name
            )

    return output_paths


def _normalized_filename(path: Path, index: int) -> str:
    match = re.search(r"(\d{4})$", path.stem)
    suffix = match.group(1) if match else f"{index:04}"
    return f"lab_results_NEW_{suffix}.csv"

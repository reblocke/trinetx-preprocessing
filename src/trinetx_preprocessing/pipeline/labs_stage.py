"""Lab-results stage runner built from legacy notebook logic."""

from __future__ import annotations

import logging
import re
from pathlib import Path

import pandas as pd

from ..config import Config, ConfigError, collect_domain_paths
from ..guardrails import log_row_count
from ..transform.labs import normalize_lab_results_chunk

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
    for index, path in enumerate(labs_paths, start=1):
        logger.info("Reading lab-results export: %s", path.name)
        chunk = pd.read_csv(
            path,
            dtype=RAW_DTYPE,
            parse_dates=["date"],
        )
        log_row_count(logger, f"labs read {path.name}", len(chunk))
        normalized = normalize_lab_results_chunk(chunk)
        log_row_count(logger, f"labs normalized {path.name}", len(normalized))
        output_path = config.work_dir / _normalized_filename(path, index)
        normalized.to_csv(output_path, index=False)
        output_paths.append(output_path)
        logger.info("Wrote %s rows to %s", len(normalized), output_path.name)

    return output_paths


def _normalized_filename(path: Path, index: int) -> str:
    match = re.search(r"(\d{4})$", path.stem)
    suffix = match.group(1) if match else f"{index:04}"
    return f"lab_results_NEW_{suffix}.csv"

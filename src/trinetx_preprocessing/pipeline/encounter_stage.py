"""Encounter stage runner built from legacy notebook logic."""

from __future__ import annotations

import logging
import re
from pathlib import Path

import pandas as pd

from ..config import Config, ConfigError, collect_domain_paths
from ..guardrails import log_row_count
from ..transform.encounter import (
    DEFAULT_END_DATE_FILL,
    DEFAULT_START_DATE,
    ENCOUNTER_OUTPUT_COLUMNS,
    ENCOUNTER_TYPES,
    filter_encounters_by_type,
    finalize_encounters,
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


def run_encounter_stage(config: Config) -> list[Path]:
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
    filtered_by_type: dict[str, list[pd.DataFrame]] = {
        encounter_type: [] for encounter_type in ENCOUNTER_TYPES
    }
    filtered_counts: dict[str, int] = {
        encounter_type: 0 for encounter_type in ENCOUNTER_TYPES
    }

    for index, path in enumerate(encounter_paths, start=1):
        logger.info("Reading encounter export: %s", path.name)
        chunk = pd.read_csv(
            path,
            dtype=RAW_DTYPE,
            parse_dates=["start_date", "end_date"],
        )
        log_row_count(logger, f"encounter read {path.name}", len(chunk))
        normalized = normalize_encounter_chunk(chunk)
        log_row_count(logger, f"encounter normalized {path.name}", len(normalized))
        normalized_path = config.work_dir / _normalized_filename(path, index)
        normalized.to_csv(normalized_path, index=False)
        output_paths.append(normalized_path)

        for encounter_type in ENCOUNTER_TYPES:
            filtered = filter_encounters_by_type(
                normalized,
                encounter_type,
                start_date_min=DEFAULT_START_DATE,
                end_date_fill=DEFAULT_END_DATE_FILL,
            )
            if not filtered.empty:
                filtered_by_type[encounter_type].append(filtered)
            filtered_counts[encounter_type] += len(filtered)

    for encounter_type, filename in OUTPUT_FILENAMES.items():
        frames = filtered_by_type[encounter_type]
        log_row_count(
            logger,
            f"encounter post-filter {encounter_type}",
            filtered_counts[encounter_type],
        )
        if frames:
            combined = pd.concat(frames, ignore_index=True)
        else:
            combined = pd.DataFrame(columns=ENCOUNTER_OUTPUT_COLUMNS)
        finalized = finalize_encounters(combined)
        output_path = config.work_dir / filename
        finalized.to_csv(output_path, index=False)
        output_paths.append(output_path)
        logger.info("Wrote %s rows to %s", len(finalized), output_path.name)

    return output_paths


def _normalized_filename(path: Path, index: int) -> str:
    match = re.search(r"(\d{4})$", path.stem)
    suffix = match.group(1) if match else f"{index:04}"
    return f"encounter_NEW_{suffix}.csv"

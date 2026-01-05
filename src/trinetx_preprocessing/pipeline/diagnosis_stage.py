"""Diagnosis stage runner built from legacy notebook logic."""

from __future__ import annotations

import logging
import re
from pathlib import Path

import pandas as pd

from ..config import Config, ConfigError, collect_domain_paths
from ..guardrails import log_row_count
from ..transform.diagnosis import (
    DIAGNOSIS_CODE_GROUPS,
    DIAGNOSIS_COLUMNS,
    normalize_diagnosis_chunk,
    split_diagnosis_by_code,
)

RAW_DTYPE = {
    "patient_id": "string",
    "encounter_id": "string",
    "code_system": "string",
    "code": "string",
    "principal_diagnosis_indicator": "string",
    "admitting_diagnosis": "string",
    "reason_for_visit": "string",
    "derived_by_TriNetX": "string",
    "source_id": "string",
}


def run_diagnosis_stage(config: Config) -> list[Path]:
    """Run the diagnosis stage and write outputs under ``work_dir``.

    Args:
        config: Pipeline configuration.

    Returns:
        List of written file paths.
    """

    logger = logging.getLogger(__name__)
    domain_paths = collect_domain_paths(config)
    diagnosis_paths = domain_paths.get("diagnosis")
    if not diagnosis_paths:
        raise ConfigError("Diagnosis domain is not configured.")

    config.work_dir.mkdir(parents=True, exist_ok=True)

    output_paths: list[Path] = []
    grouped_frames: dict[str, list[pd.DataFrame]] = {
        group.name: [] for group in DIAGNOSIS_CODE_GROUPS
    }

    for index, path in enumerate(diagnosis_paths, start=1):
        logger.info("Reading diagnosis export: %s", path.name)
        chunk = pd.read_csv(
            path,
            dtype=RAW_DTYPE,
            parse_dates=["date"],
        )
        log_row_count(logger, f"diagnosis read {path.name}", len(chunk))
        normalized = normalize_diagnosis_chunk(chunk)
        log_row_count(logger, f"diagnosis normalized {path.name}", len(normalized))
        normalized_path = config.work_dir / _normalized_filename(path, index)
        normalized.to_csv(normalized_path, index=False)
        output_paths.append(normalized_path)

        grouped = split_diagnosis_by_code(normalized)
        for name, frame in grouped.items():
            grouped_frames[name].append(frame)

    for group in DIAGNOSIS_CODE_GROUPS:
        frames = grouped_frames[group.name]
        if frames:
            combined = pd.concat(frames, ignore_index=True)
        else:
            combined = pd.DataFrame(columns=DIAGNOSIS_COLUMNS)
        log_row_count(logger, f"diagnosis post-filter {group.name}", len(combined))
        output_path = config.work_dir / f"{group.name}.csv"
        combined.to_csv(output_path, index=False)
        output_paths.append(output_path)
        logger.info("Wrote %s rows to %s", len(combined), output_path.name)

    return output_paths


def _normalized_filename(path: Path, index: int) -> str:
    match = re.search(r"(\d{4})$", path.stem)
    suffix = match.group(1) if match else f"{index:04}"
    return f"diagnosis_NEW_{suffix}.csv"

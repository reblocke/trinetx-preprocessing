"""Medications stage runner built from legacy notebook logic."""

from __future__ import annotations

import logging
import re
from pathlib import Path

import pandas as pd

from ..config import Config, ConfigError, collect_domain_paths
from ..guardrails import log_row_count
from ..io.csv import iter_csv
from ..transform.medications import (
    MEDICATION_CODE_GROUPS,
    MEDICATION_COLUMNS,
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
    grouped_frames: dict[str, list[pd.DataFrame]] = {
        group.name: [] for group in MEDICATION_CODE_GROUPS
    }
    chunksize = config.chunking.lines_per_chunk if config.chunking.enabled else None

    for index, path in enumerate(meds_paths, start=1):
        logger.info("Reading medications export: %s", path.name)
        normalized, rows_read = _read_normalized(path, chunksize)
        log_row_count(logger, f"medications read {path.name}", rows_read)
        log_row_count(logger, f"medications normalized {path.name}", len(normalized))
        normalized_path = config.work_dir / _normalized_filename(path, index)
        normalized.to_csv(normalized_path, index=False)
        output_paths.append(normalized_path)

        grouped = split_medications_by_code(normalized)
        for name, frame in grouped.items():
            if not frame.empty:
                grouped_frames[name].append(frame)

        logger.info("Wrote %s rows to %s", len(normalized), normalized_path.name)

    for group in MEDICATION_CODE_GROUPS:
        frames = grouped_frames[group.name]
        if frames:
            combined = pd.concat(frames, ignore_index=True)
        else:
            combined = pd.DataFrame(columns=MEDICATION_COLUMNS)
        output_path = config.work_dir / f"{group.name}.csv"
        combined.to_csv(output_path, index=False)
        output_paths.append(output_path)
        logger.info("Wrote %s rows to %s", len(combined), output_path.name)

    return output_paths


def _read_normalized(path: Path, chunksize: int | None) -> tuple[pd.DataFrame, int]:
    chunks: list[pd.DataFrame] = []
    rows_read = 0
    for chunk in iter_csv(path, chunksize=chunksize, dtype=RAW_DTYPE):
        rows_read += len(chunk)
        chunks.append(normalize_medications_chunk(chunk))
    if not chunks:
        return pd.DataFrame(columns=MEDICATION_COLUMNS), rows_read
    if len(chunks) == 1:
        return chunks[0], rows_read
    return pd.concat(chunks, ignore_index=True), rows_read


def _normalized_filename(path: Path, index: int) -> str:
    match = re.search(r"(\d{4})$", path.stem)
    suffix = match.group(1) if match else f"{index:04}"
    return f"medication_NEW_{suffix}.csv"

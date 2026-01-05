"""RFS stage runner built from legacy notebook logic."""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from ..config import Config
from ..guardrails import log_row_count
from ..io.csv import iter_many_csv
from ..transform.diagnosis import DIAGNOSIS_COLUMNS
from ..transform.labs import LAB_COLUMNS
from ..transform.procedure import PROCEDURE_COLUMNS
from ..transform.rfs import (
    ENCOUNTER_ID_COLUMNS,
    RFS_CATEGORIES,
    RFS_EVENT_COLUMNS,
    derive_rfs_encounter_flags,
    derive_rfs_event_frames,
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


def run_rfs_stage(config: Config) -> list[Path]:
    """Run the RFS derivation stage.

    Args:
        config: Pipeline configuration.

    Returns:
        List of written file paths.
    """

    logger = logging.getLogger(__name__)
    config.work_dir.mkdir(parents=True, exist_ok=True)

    encounters = _read_work_domain(
        config.work_dir,
        "encounter_NEW_*.csv",
        usecols=ENCOUNTER_ID_COLUMNS,
        dtype=ENCOUNTER_DTYPE,
    )
    log_row_count(logger, "rfs input encounters", len(encounters))
    labs = _read_work_domain(
        config.work_dir,
        "lab_results_NEW_*.csv",
        usecols=LAB_COLUMNS,
        dtype=LAB_DTYPE,
    )
    log_row_count(logger, "rfs input labs", len(labs))
    diagnosis = _read_work_domain(
        config.work_dir,
        "diagnosis_NEW_*.csv",
        usecols=DIAGNOSIS_COLUMNS,
        dtype=DIAGNOSIS_DTYPE,
    )
    log_row_count(logger, "rfs input diagnosis", len(diagnosis))
    procedure = _read_work_domain(
        config.work_dir,
        "procedure_NEW_*.csv",
        usecols=PROCEDURE_COLUMNS,
        dtype=PROCEDURE_DTYPE,
    )
    log_row_count(logger, "rfs input procedure", len(procedure))
    vitals = _read_work_domain(
        config.work_dir,
        "vital_signs_NEW_*.csv",
        usecols=VITALS_COLUMNS,
        dtype=VITALS_DTYPE,
    )
    log_row_count(logger, "rfs input vitals", len(vitals))

    flags = derive_rfs_encounter_flags(
        encounters,
        labs=labs,
        diagnosis=diagnosis,
        procedure=procedure,
        vitals=vitals,
    )

    events = derive_rfs_event_frames(
        labs=labs,
        diagnosis=diagnosis,
        procedure=procedure,
        vitals=vitals,
    )

    output_path = config.work_dir / "rfs_encounter_flags.csv"
    flags.to_csv(output_path, index=False)
    logger.info("Wrote %s rows to %s", len(flags), output_path.name)

    output_paths = [output_path]
    for category in RFS_CATEGORIES:
        frame = events.get(category, pd.DataFrame(columns=RFS_EVENT_COLUMNS))
        event_path = config.work_dir / f"RFS_{category}.csv"
        frame.to_csv(event_path, index=False)
        output_paths.append(event_path)
        logger.info("Wrote %s rows to %s", len(frame), event_path.name)

    return output_paths


def _read_work_domain(
    work_dir: Path,
    pattern: str,
    *,
    usecols: list[str],
    dtype: dict[str, str],
) -> pd.DataFrame:
    paths = sorted(work_dir.glob(pattern))
    if not paths:
        raise FileNotFoundError(
            f"No files found for pattern '{pattern}' under {work_dir}."
        )

    frames = list(iter_many_csv(paths, usecols=usecols, dtype=dtype))
    if not frames:
        return pd.DataFrame(columns=usecols)
    if len(frames) == 1:
        return frames[0]
    return pd.concat(frames, ignore_index=True)

"""Full pipeline orchestration helpers."""

from __future__ import annotations

import logging
from pathlib import Path

from ..config import Config
from ..profiling import StageTimer
from .diagnosis_stage import run_diagnosis_stage
from .encounter_stage import run_encounter_stage
from .final_assembly import run_final_assembly
from .labs_stage import run_labs_stage
from .medications_stage import run_medications_stage
from .procedure_stage import run_procedure_stage
from .rfs_stage import run_rfs_stage
from .vitals_stage import run_vitals_stage


def run_pipeline(
    config: Config,
    *,
    timings: dict[str, float] | None = None,
    strict: bool = False,
) -> list[Path]:
    """Run the full preprocessing pipeline in order.

    Args:
        config: Pipeline configuration.
        timings: Optional mapping to collect stage wall times.
        strict: Whether to enable guardrail assertions.

    Returns:
        List of output file paths.
    """

    logger = logging.getLogger(__name__)
    output_paths: list[Path] = []

    logger.info("Starting encounter stage")
    with StageTimer("encounter", timings=timings, logger=logger):
        output_paths.extend(run_encounter_stage(config))

    logger.info("Starting labs stage")
    with StageTimer("labs", timings=timings, logger=logger):
        output_paths.extend(run_labs_stage(config))

    logger.info("Starting diagnosis stage")
    with StageTimer("diagnosis", timings=timings, logger=logger):
        output_paths.extend(run_diagnosis_stage(config))

    logger.info("Starting medications stage")
    with StageTimer("medications", timings=timings, logger=logger):
        output_paths.extend(run_medications_stage(config))

    logger.info("Starting procedure stage")
    with StageTimer("procedure", timings=timings, logger=logger):
        output_paths.extend(run_procedure_stage(config))

    logger.info("Starting vitals stage")
    with StageTimer("vitals", timings=timings, logger=logger):
        output_paths.extend(run_vitals_stage(config))

    logger.info("Starting RFS stage")
    with StageTimer("rfs", timings=timings, logger=logger):
        output_paths.extend(run_rfs_stage(config))

    logger.info("Starting final assembly stage")
    with StageTimer("final_assembly", timings=timings, logger=logger):
        output_paths.extend(run_final_assembly(config, strict=strict))

    return output_paths

"""Full pipeline orchestration helpers."""

from __future__ import annotations

import logging
from pathlib import Path

from ..config import Config
from ..profiling import StageTimer
from ..storage import release_unused_tabular_memory
from ..work_manifest import (
    initialize_work_manifest,
    mark_stage_complete,
    mark_stage_started,
)
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
    final_output_dir: Path | None = None,
) -> list[Path]:
    """Run the full preprocessing pipeline in order.

    Args:
        config: Pipeline configuration.
        timings: Optional mapping to collect stage wall times.
        strict: Whether to enable guardrail assertions.
        final_output_dir: Optional physical root for staged final CSV writes.

    Returns:
        List of output file paths.
    """

    logger = logging.getLogger(__name__)
    output_paths: list[Path] = []
    initialize_work_manifest(config)

    def run_stage(
        name: str,
        stage,
        *,
        physical_output_dir: Path | None = None,
    ) -> None:
        logger.info("Starting %s stage", name)
        mark_stage_started(config, name)
        with StageTimer(name, timings=timings, logger=logger):
            try:
                paths = list(stage())
            finally:
                release_unused_tabular_memory()
        mark_stage_complete(
            config,
            name,
            paths,
            physical_output_dir=physical_output_dir,
        )
        output_paths.extend(paths)

    run_stage("labs", lambda: run_labs_stage(config))
    run_stage("encounter", lambda: run_encounter_stage(config, strict=strict))
    run_stage("diagnosis", lambda: run_diagnosis_stage(config))
    run_stage("medications", lambda: run_medications_stage(config))
    run_stage("procedure", lambda: run_procedure_stage(config))
    run_stage("vitals", lambda: run_vitals_stage(config))
    run_stage("rfs", lambda: run_rfs_stage(config))
    run_stage(
        "final_assembly",
        lambda: run_final_assembly(
            config,
            strict=strict,
            output_dir=final_output_dir,
        ),
        physical_output_dir=final_output_dir,
    )

    return output_paths

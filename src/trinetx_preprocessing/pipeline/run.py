"""Full pipeline orchestration helpers."""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from pathlib import Path

from ..config import Config
from ..profiling import StageTimer
from ..storage import release_unused_tabular_memory
from ..work_manifest import (
    STAGE_ORDER,
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

    initialize_work_manifest(config)
    return _run_pipeline_stages(
        config,
        stage_names=STAGE_ORDER,
        timings=timings,
        strict=strict,
        final_output_dir=final_output_dir,
    )


def run_pipeline_before_final_assembly(
    config: Config,
    *,
    strict: bool = False,
) -> list[Path]:
    """Run and checkpoint every pipeline stage before final assembly."""

    initialize_work_manifest(config)
    return _run_pipeline_stages(
        config,
        stage_names=STAGE_ORDER[:-1],
        timings=None,
        strict=strict,
        final_output_dir=None,
    )


def run_final_pipeline_stage(
    config: Config,
    *,
    strict: bool = False,
    final_output_dir: Path | None = None,
) -> list[Path]:
    """Run and checkpoint final assembly against completed prerequisite work."""

    return _run_pipeline_stages(
        config,
        stage_names=("final_assembly",),
        timings=None,
        strict=strict,
        final_output_dir=final_output_dir,
    )


def _run_pipeline_stages(
    config: Config,
    *,
    stage_names: Sequence[str],
    timings: dict[str, float] | None,
    strict: bool,
    final_output_dir: Path | None,
) -> list[Path]:
    """Run an ordered pipeline stage sequence through the shared checkpoint shell."""

    logger = logging.getLogger(__name__)
    output_paths: list[Path] = []

    def run_stage(
        name: str,
        stage: Callable[[], list[Path]],
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

    stages: dict[str, tuple[Callable[[], list[Path]], Path | None]] = {
        "labs": (lambda: run_labs_stage(config), None),
        "encounter": (lambda: run_encounter_stage(config, strict=strict), None),
        "diagnosis": (lambda: run_diagnosis_stage(config), None),
        "medications": (lambda: run_medications_stage(config), None),
        "procedure": (lambda: run_procedure_stage(config), None),
        "vitals": (lambda: run_vitals_stage(config), None),
        "rfs": (lambda: run_rfs_stage(config), None),
        "final_assembly": (
            lambda: run_final_assembly(
                config,
                strict=strict,
                output_dir=final_output_dir,
            ),
            final_output_dir,
        ),
    }
    for name in stage_names:
        stage, physical_output_dir = stages[name]
        run_stage(
            name,
            stage,
            physical_output_dir=physical_output_dir,
        )

    return output_paths

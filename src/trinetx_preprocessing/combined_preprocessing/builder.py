"""Orchestration for the canonical combined preprocessing build."""

from __future__ import annotations

import fcntl
import hashlib
import json
import multiprocessing
import os
import socket
import stat
import subprocess
import time
import unicodedata
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Iterator, TextIO

from ..config import (
    Config,
    path_is_within,
    paths_overlap,
    validate_combined_path_separation,
)
from ..filesystem import remove_tree_strict, write_text_atomic
from ..pipeline.run import (
    run_final_pipeline_stage,
    run_pipeline_before_final_assembly,
)
from ..process_locks import duplicate_lock_file_descriptors_for_spawn
from ..regression import HASH_SCRATCH_PREFIX, CsvHashResult, hash_csv_with_metadata
from ..work_manifest import (
    STAGE_ORDER,
    StaleWorkError,
    refresh_stage_output_metadata,
    require_current_work,
    require_strict_encounter_work,
    work_identity_sha256,
    work_manifest_path,
)
from .contract import compatibility_outputs
from .database import (
    COMBINED_MANIFEST_FILENAME,
    current_work_manifest_sha256,
    export_compatibility_outputs,
    finalize_combined_database,
    initialize_combined_database,
    inspect_combined_database,
    load_combined_memberships,
    load_combined_observability,
    refresh_database_work_manifest_fingerprint,
    verify_compatibility_outputs,
    write_combined_manifest,
)
from .scratch import (
    COMBINED_BUILD_PREFIX,
    COMBINED_DUCKDB_SPILL_PREFIX,
    COMBINED_LOCK_PREFIX,
    COMBINED_PREVIOUS_PREFIX,
    COMBINED_PUBLICATION_PREFIX,
    COMBINED_VALIDATION_PREFIX,
)
from .validation import CombinedValidationResult, validate_preprocessed_database

_BUILD_STATE_SCHEMA_VERSION = 1
_PUBLICATION_JOURNAL_SCHEMA_VERSION = 1
_EXPORT_PROGRESS_DATABASE_FINGERPRINT_PENDING = "database_fingerprint_pending"
_PHASE_ORDER = {
    "pipeline": 1,
    "database": 2,
    "compatibility_export": 3,
    "validation": 4,
}


@dataclass(frozen=True)
class CombinedBuildResult:
    """Published paths and aggregate evidence for a combined build."""

    database_path: Path
    manifest_path: Path
    compatibility_paths: tuple[Path, ...]
    run_id: str
    validation: CombinedValidationResult


class CombinedLockError(RuntimeError):
    """Raised when another combined operation holds a required filesystem lock."""


@dataclass(frozen=True)
class _CombinedBuildPaths:
    staging_output: Path
    state_path: Path
    backup_output: Path
    publication_journal: Path


def build_preprocessed(
    config: Config,
    *,
    strict: bool = False,
    replace_existing: bool = False,
    timings: dict[str, float] | None = None,
) -> CombinedBuildResult:
    """Build, validate, and transactionally publish one combined product."""

    combined_config = replace(
        config,
        combined=replace(config.combined, enabled=True),
    )
    validate_combined_path_separation(combined_config)
    require_safe_output_location(
        combined_config.work_dir,
        artifact_label="work directory",
    )
    require_safe_output_location(
        combined_config.output_dir,
        artifact_label="output directory",
    )
    published_output = combined_config.output_dir
    database_path = published_output / combined_config.combined.database_name

    with _canonical_build_lock(combined_config) as lock_file_descriptors:
        build_identity = _combined_build_identity(
            combined_config,
            strict=strict,
        )
        paths = _combined_build_paths(
            published_output,
            build_identity=build_identity,
        )
        _recover_interrupted_publication(
            published_output,
            publication_journal=paths.publication_journal,
            backup_output=paths.backup_output,
            database_name=combined_config.combined.database_name,
        )
        _validate_existing_product(
            published_output,
            database_name=combined_config.combined.database_name,
            replace_existing=replace_existing,
        )
        return _build_locked(
            combined_config,
            paths=paths,
            build_identity=build_identity,
            database_path=database_path,
            strict=strict,
            replace_existing=replace_existing,
            timings=timings,
            lock_file_descriptors=lock_file_descriptors,
        )


def export_legacy_compatibility_outputs(
    database_path: Path,
    output_dir: Path,
    *,
    replace_existing: bool = False,
) -> tuple[Path, ...]:
    """Validate and atomically publish the 36-file compatibility export.

    The destination is deliberately a compatibility-only tree. In-place
    mutation of the canonical product directory would either follow unsafe
    descendants or require copying/moving the multi-gigabyte database during
    publication, so callers must use a separate external destination.
    """

    database = Path(database_path)
    requested_output = Path(output_dir)
    if database.is_symlink() or not database.is_file():
        raise ValueError(f"Combined database must be a regular file: {database}")
    if requested_output.is_symlink():
        raise ValueError(
            f"Compatibility export root must be a real directory: {requested_output}"
        )

    database = database.resolve()
    output = requested_output.resolve(strict=False)
    require_safe_output_location(
        output,
        artifact_label="compatibility export directory",
    )
    canonical_root = database.parent
    if paths_overlap(canonical_root, output):
        raise ValueError(
            "Compatibility exports must use a separate destination outside "
            f"the canonical database directory: {output}"
        )

    paths = _compatibility_export_paths(output)
    with _compatibility_export_lock(database, output):
        _recover_interrupted_publication(
            output,
            publication_journal=paths.publication_journal,
            backup_output=paths.backup_output,
            database_name=database.name,
            compatibility_only=True,
        )
        _discard_incomplete_compatibility_staging(paths)
        _validate_compatibility_export_tree(output, require_complete=False)
        had_existing = output.exists()
        if had_existing and any(output.iterdir()) and not replace_existing:
            raise FileExistsError(
                f"Compatibility export already exists: {output}; use --replace."
            )

        paths.staging_output.mkdir(parents=False)
        try:
            export_compatibility_outputs(
                database,
                paths.staging_output,
                spill_root=paths.staging_output,
            )
            _remove_appledouble_sidecars(paths.staging_output)
            _validate_compatibility_export_tree(
                paths.staging_output,
                require_complete=True,
            )
            verify_compatibility_outputs(
                database,
                paths.staging_output,
                spill_root=paths.staging_output,
            )
            _fsync_compatibility_export(paths.staging_output)
            _publish_staged_product(
                paths,
                published_output=output,
                database_name=database.name,
                replace_existing=replace_existing,
                compatibility_only=True,
            )
        except BaseException:
            if paths.staging_output.exists():
                _validate_compatibility_export_tree(
                    paths.staging_output,
                    require_complete=False,
                    allow_temporary=True,
                )
                remove_tree_strict(
                    paths.staging_output,
                    context="Incomplete compatibility export staging directory",
                )
            raise

    return tuple(output / item.relative_path for item in compatibility_outputs())


def _build_locked(
    config: Config,
    *,
    paths: _CombinedBuildPaths,
    build_identity: str,
    database_path: Path,
    strict: bool,
    replace_existing: bool,
    timings: dict[str, float] | None,
    lock_file_descriptors: tuple[int, ...],
) -> CombinedBuildResult:
    if paths.staging_output.is_symlink() or (
        paths.staging_output.exists() and not paths.staging_output.is_dir()
    ):
        raise ValueError(
            f"Combined staging output must be a real directory: {paths.staging_output}"
        )
    if paths.staging_output.is_dir():
        _remove_staging_runtime_scratch(paths.staging_output)
    state = _load_build_state(
        paths.state_path,
        expected_identity=build_identity,
        paths=paths,
        published_output=config.output_dir,
    )
    if state is not None and not paths.staging_output.is_dir():
        if _phase_at_least(state, "database"):
            raise ValueError(
                "Combined resumable state exists without its staging directory: "
                f"{paths.state_path}"
            )
        _unlink_generated_file(paths.state_path)
        state = None

    pipeline_current = _pipeline_outputs_are_current(
        config,
        paths.staging_output,
        strict=strict,
    )
    if (
        state is not None
        and not _phase_at_least(state, "database")
        and not pipeline_current
    ):
        _remove_staging_for_restart(
            paths.staging_output,
            database_name=config.combined.database_name,
        )
        _unlink_generated_file(paths.state_path)
        state = None
    if state is None and paths.staging_output.exists() and not pipeline_current:
        _remove_staging_for_restart(
            paths.staging_output,
            database_name=config.combined.database_name,
        )

    if state is None and not pipeline_current:
        paths.staging_output.mkdir(parents=True)
        phase_started = time.perf_counter()
        _run_combined_pipeline_isolated(
            config,
            strict=strict,
            paths=paths,
            build_identity=build_identity,
            lock_file_descriptors=lock_file_descriptors,
        )
        _record_timing(timings, "pipeline", phase_started)
        state = _load_build_state(
            paths.state_path,
            expected_identity=build_identity,
            paths=paths,
            published_output=config.output_dir,
        )
        if state is None:
            raise RuntimeError(
                "Combined final-assembly worker completed without resumable state."
            )
        _deserialize_hashes(state.get("baseline"))
    elif state is None:
        baseline = _compatibility_hashes(paths.staging_output)
        state = _new_build_state(
            paths,
            build_identity=build_identity,
            published_output=config.output_dir,
            baseline=baseline,
        )
        _write_build_state(paths.state_path, state)
    else:
        _deserialize_hashes(state.get("baseline"))

    if not _phase_at_least(state, "database"):
        phase_started = time.perf_counter()
        _run_isolated_phase_process(
            "database-core",
            _run_database_core_phase_worker,
            (config, paths, build_identity),
            lock_file_descriptors=lock_file_descriptors,
        )
        _run_isolated_phase_process(
            "database-observability",
            _run_database_observability_phase_worker,
            (config, paths, build_identity),
            lock_file_descriptors=lock_file_descriptors,
        )
        _run_isolated_phase_process(
            "database-membership",
            _run_database_membership_phase_worker,
            (config, paths, build_identity),
            lock_file_descriptors=lock_file_descriptors,
        )
        _run_isolated_phase_process(
            "database-finalize",
            _run_database_finalize_phase_worker,
            (config, paths, build_identity),
            lock_file_descriptors=lock_file_descriptors,
        )
        _record_timing(timings, "database", phase_started)
        state = _require_reloaded_build_state(
            config,
            paths=paths,
            build_identity=build_identity,
            expected_phase="database",
        )

    if not _phase_at_least(state, "compatibility_export"):
        phase_started = time.perf_counter()
        _run_isolated_phase_process(
            "compatibility-export",
            _run_compatibility_export_phase_worker,
            (config, paths, build_identity),
            lock_file_descriptors=lock_file_descriptors,
        )
        _record_timing(timings, "compatibility_export", phase_started)
        state = _require_reloaded_build_state(
            config,
            paths=paths,
            build_identity=build_identity,
            expected_phase="compatibility_export",
        )

    validation_already_complete = _phase_at_least(state, "validation")
    if not validation_already_complete:
        phase_started = time.perf_counter()
    _run_isolated_phase_process(
        "validation-state-check" if validation_already_complete else "validation",
        _run_validation_phase_worker,
        (config, paths, build_identity),
        lock_file_descriptors=lock_file_descriptors,
    )
    if not validation_already_complete:
        _record_timing(timings, "validation", phase_started)
    state = _require_reloaded_build_state(
        config,
        paths=paths,
        build_identity=build_identity,
        expected_phase="validation",
    )
    manifest = _require_manifest_state(state)
    validation = _deserialize_validation(state.get("validation"))

    _remove_appledouble_sidecars(paths.staging_output)
    _validate_product_tree(
        paths.staging_output,
        database_name=config.combined.database_name,
        require_complete=True,
        allow_temporary=False,
    )
    phase_started = time.perf_counter()
    _publish_staged_product(
        paths,
        published_output=config.output_dir,
        database_name=config.combined.database_name,
        replace_existing=replace_existing,
    )
    _record_timing(timings, "publication", phase_started)
    compatibility_paths = tuple(
        config.output_dir / output.relative_path for output in compatibility_outputs()
    )
    return CombinedBuildResult(
        database_path=database_path,
        manifest_path=config.output_dir / COMBINED_MANIFEST_FILENAME,
        compatibility_paths=compatibility_paths,
        run_id=str(manifest["run_id"]),
        validation=validation,
    )


def _run_combined_pipeline_isolated(
    config: Config,
    *,
    strict: bool,
    paths: _CombinedBuildPaths,
    build_identity: str,
    lock_file_descriptors: tuple[int, ...],
) -> None:
    """Run allocation-heavy pipeline phases in sequential fresh processes."""

    _run_isolated_phase_process(
        "pre-final",
        _run_pre_final_pipeline_worker,
        (config, strict),
        lock_file_descriptors=lock_file_descriptors,
    )
    _run_isolated_phase_process(
        "final-assembly",
        _run_final_pipeline_worker,
        (
            config,
            strict,
            paths,
            build_identity,
        ),
        lock_file_descriptors=lock_file_descriptors,
    )


def _run_isolated_phase_process(
    phase: str,
    target: Callable[..., None],
    args: tuple[object, ...],
    *,
    lock_file_descriptors: tuple[int, ...],
) -> None:
    context = multiprocessing.get_context("spawn")
    duplicated_locks = duplicate_lock_file_descriptors_for_spawn(lock_file_descriptors)
    process = context.Process(
        target=_run_isolated_phase_worker,
        args=(target, args, duplicated_locks),
        name=f"trinetx-combined-{phase}",
    )
    process.start()
    try:
        process.join()
    except BaseException:
        if process.is_alive():
            process.terminate()
        process.join()
        raise
    if process.exitcode != 0:
        raise RuntimeError(
            f"Combined {phase} worker exited with status {process.exitcode}."
        )


def _run_isolated_phase_worker(
    target: Callable[..., None],
    args: tuple[object, ...],
    duplicated_locks: tuple[int, ...],
) -> None:
    try:
        target(
            *args,
            retained_lock_file_descriptors=duplicated_locks,
        )
    finally:
        for descriptor in reversed(duplicated_locks):
            os.close(descriptor)


def _run_pre_final_pipeline_worker(
    config: Config,
    strict: bool,
    *,
    retained_lock_file_descriptors: tuple[int, ...],
) -> None:
    _ = retained_lock_file_descriptors
    run_pipeline_before_final_assembly(config, strict=strict)


def _run_final_pipeline_worker(
    config: Config,
    strict: bool,
    paths: _CombinedBuildPaths,
    build_identity: str,
    *,
    retained_lock_file_descriptors: tuple[int, ...],
) -> None:
    run_final_pipeline_stage(
        config,
        strict=strict,
        final_output_dir=paths.staging_output,
        lock_file_descriptors=retained_lock_file_descriptors,
    )
    baseline = _compatibility_hashes(paths.staging_output)
    _fsync_export_checkpoint_inputs(
        paths.staging_output,
        work_manifest=work_manifest_path(config),
    )
    state = _new_build_state(
        paths,
        build_identity=build_identity,
        published_output=config.output_dir,
        baseline=baseline,
    )
    _write_build_state(paths.state_path, state)


def _run_database_core_phase_worker(
    config: Config,
    paths: _CombinedBuildPaths,
    build_identity: str,
    *,
    retained_lock_file_descriptors: tuple[int, ...],
) -> None:
    """Create core/source tables in the first fresh database process."""

    _ = retained_lock_file_descriptors
    state = _require_reloaded_build_state(
        config,
        paths=paths,
        build_identity=build_identity,
        expected_phase="pipeline",
    )
    baseline = _deserialize_hashes(state.get("baseline"))
    staged_database = paths.staging_output / config.combined.database_name
    _remove_incomplete_database(staged_database)
    manifest = initialize_combined_database(
        config,
        staged_database,
        compatibility_hashes=baseline,
        compatibility_output_dir=paths.staging_output,
        published_output_dir=config.output_dir,
    )
    _write_build_state(
        paths.state_path,
        {
            **state,
            "database_progress": "core",
            "manifest": manifest,
            "database_stat": _file_stat(staged_database),
        },
    )


def _run_database_observability_phase_worker(
    config: Config,
    paths: _CombinedBuildPaths,
    build_identity: str,
    *,
    retained_lock_file_descriptors: tuple[int, ...],
) -> None:
    """Create source observability in a second fresh database process."""

    _ = retained_lock_file_descriptors
    state = _require_reloaded_build_state(
        config,
        paths=paths,
        build_identity=build_identity,
        expected_phase="pipeline",
    )
    _require_database_progress(state, "core")
    staged_database = paths.staging_output / config.combined.database_name
    _require_file_state_current(
        staged_database,
        state.get("database_stat"),
        label="in-progress combined database",
    )
    load_combined_observability(config, staged_database)
    _write_build_state(
        paths.state_path,
        {
            **state,
            "database_progress": "observability",
            "database_stat": _file_stat(staged_database),
        },
    )


def _run_database_membership_phase_worker(
    config: Config,
    paths: _CombinedBuildPaths,
    build_identity: str,
    *,
    retained_lock_file_descriptors: tuple[int, ...],
) -> None:
    """Create membership tables in a third fresh database process."""

    _ = retained_lock_file_descriptors
    state = _require_reloaded_build_state(
        config,
        paths=paths,
        build_identity=build_identity,
        expected_phase="pipeline",
    )
    _require_database_progress(state, "observability")
    staged_database = paths.staging_output / config.combined.database_name
    _require_file_state_current(
        staged_database,
        state.get("database_stat"),
        label="in-progress combined database",
    )
    load_combined_memberships(config, staged_database)
    _write_build_state(
        paths.state_path,
        {
            **state,
            "database_progress": "membership",
            "database_stat": _file_stat(staged_database),
        },
    )


def _run_database_finalize_phase_worker(
    config: Config,
    paths: _CombinedBuildPaths,
    build_identity: str,
    *,
    retained_lock_file_descriptors: tuple[int, ...],
) -> None:
    """Finalize the database in a fourth fresh process and advance state."""

    _ = retained_lock_file_descriptors
    state = _require_reloaded_build_state(
        config,
        paths=paths,
        build_identity=build_identity,
        expected_phase="pipeline",
    )
    _require_database_progress(state, "membership")
    staged_database = paths.staging_output / config.combined.database_name
    _require_file_state_current(
        staged_database,
        state.get("database_stat"),
        label="in-progress combined database",
    )
    manifest = finalize_combined_database(
        config,
        staged_database,
        manifest=_require_manifest_state(state),
    )
    completed_state = {
        key: value for key, value in state.items() if key != "database_progress"
    }
    _write_build_state(
        paths.state_path,
        {
            **completed_state,
            "phase": "database",
            "manifest": manifest,
            "database_stat": _file_stat(staged_database),
        },
    )


def _run_compatibility_export_phase_worker(
    config: Config,
    paths: _CombinedBuildPaths,
    build_identity: str,
    *,
    retained_lock_file_descriptors: tuple[int, ...],
) -> None:
    """Regenerate compatibility exports in a fresh process and persist state."""

    _ = retained_lock_file_descriptors
    state = _require_reloaded_build_state(
        config,
        paths=paths,
        build_identity=build_identity,
        expected_phase="database",
    )
    baseline = _deserialize_hashes(state.get("baseline"))
    manifest = _require_manifest_state(state)
    staged_database = paths.staging_output / config.combined.database_name
    if state.get("export_progress") is not None:
        _complete_compatibility_export_checkpoint(
            config,
            paths=paths,
            state=state,
        )
        return
    database_status = _require_database_state_current(
        staged_database,
        state,
        config=config,
    )
    export_compatibility_outputs(
        staged_database,
        paths.staging_output,
        memory_limit_mib=config.combined.duckdb_memory_limit_mib,
    )
    refresh_stage_output_metadata(
        config,
        "final_assembly",
        physical_output_dir=paths.staging_output,
    )
    _fsync_export_checkpoint_inputs(
        paths.staging_output,
        work_manifest=work_manifest_path(config),
    )
    exported = _compatibility_hashes(paths.staging_output)
    _require_matching_hashes(baseline, exported)
    manifest = {
        **manifest,
        "database": str(config.output_dir / config.combined.database_name),
        "database_size_bytes": staged_database.stat().st_size,
    }
    refreshed_work_manifest_sha256 = current_work_manifest_sha256(config)
    prepared_state = {
        **state,
        "manifest": manifest,
        "compatibility_stats": _compatibility_file_stats(paths.staging_output),
        "exported": _serialize_hashes(exported),
        "export_progress": {
            "status": _EXPORT_PROGRESS_DATABASE_FINGERPRINT_PENDING,
            "source_work_manifest_sha256_before": database_status[
                "source_work_manifest_sha256"
            ],
            "source_work_manifest_sha256_after": refreshed_work_manifest_sha256,
        },
    }
    _write_build_state(paths.state_path, prepared_state)
    _complete_compatibility_export_checkpoint(
        config,
        paths=paths,
        state=prepared_state,
    )


def _complete_compatibility_export_checkpoint(
    config: Config,
    *,
    paths: _CombinedBuildPaths,
    state: dict[str, object],
) -> None:
    """Finish or recover the write-ahead export provenance checkpoint."""

    progress = state.get("export_progress")
    if not isinstance(progress, dict) or set(progress) != {
        "status",
        "source_work_manifest_sha256_before",
        "source_work_manifest_sha256_after",
    }:
        raise ValueError("Combined export progress state is invalid.")
    if progress.get("status") != _EXPORT_PROGRESS_DATABASE_FINGERPRINT_PENDING:
        raise ValueError("Combined export progress state has an unknown status.")
    previous_sha256 = progress.get("source_work_manifest_sha256_before")
    expected_sha256 = progress.get("source_work_manifest_sha256_after")
    if not isinstance(previous_sha256, str) or not isinstance(expected_sha256, str):
        raise ValueError("Combined export progress has invalid provenance hashes.")

    baseline = _deserialize_hashes(state.get("baseline"))
    exported = _deserialize_hashes(state.get("exported"))
    _require_matching_hashes(baseline, exported)
    _require_compatibility_state_current(paths.staging_output, state)
    manifest = _require_manifest_state(state)
    run_id = manifest.get("run_id")
    if not isinstance(run_id, str):
        raise ValueError("Combined export progress has no database run ID.")
    staged_database = paths.staging_output / config.combined.database_name
    refreshed_sha256 = refresh_database_work_manifest_fingerprint(
        staged_database,
        config,
        expected_previous_sha256=previous_sha256,
        expected_new_sha256=expected_sha256,
        expected_run_id=run_id,
    )
    if refreshed_sha256 != current_work_manifest_sha256(config):
        raise RuntimeError("Combined database provenance refresh did not stabilize.")
    database_status = inspect_combined_database(
        staged_database,
        memory_limit_mib=config.combined.duckdb_memory_limit_mib,
    )
    if (
        database_status.get("status") != "complete"
        or database_status.get("run_id") != run_id
        or database_status.get("source_work_manifest_sha256") != refreshed_sha256
        or database_status.get("counts") != manifest.get("counts")
    ):
        raise ValueError(
            "Combined database changed unexpectedly during export checkpoint."
        )
    completed_state = {
        key: value for key, value in state.items() if key != "export_progress"
    }
    completed_manifest = {
        **manifest,
        "database": str(config.output_dir / config.combined.database_name),
        "database_size_bytes": staged_database.stat().st_size,
    }
    _write_build_state(
        paths.state_path,
        {
            **completed_state,
            "phase": "compatibility_export",
            "manifest": completed_manifest,
            "database_stat": _file_stat(staged_database),
            "compatibility_stats": _compatibility_file_stats(paths.staging_output),
            "exported": _serialize_hashes(exported),
        },
    )


def _run_validation_phase_worker(
    config: Config,
    paths: _CombinedBuildPaths,
    build_identity: str,
    *,
    retained_lock_file_descriptors: tuple[int, ...],
) -> None:
    """Validate or recheck a staged product in a fresh bounded process."""

    _ = retained_lock_file_descriptors
    state = _require_reloaded_build_state(
        config,
        paths=paths,
        build_identity=build_identity,
        expected_phase="compatibility_export",
    )
    staged_database = paths.staging_output / config.combined.database_name
    _require_database_state_current(staged_database, state, config=config)
    _require_compatibility_state_current(paths.staging_output, state)
    baseline = _deserialize_hashes(state.get("baseline"))
    exported = _deserialize_hashes(state.get("exported"))
    _require_matching_hashes(baseline, exported)
    if _phase_at_least(state, "validation"):
        _require_file_state_current(
            paths.staging_output / COMBINED_MANIFEST_FILENAME,
            state.get("sidecar_stat"),
            label="combined product sidecar",
        )
        validation = _deserialize_validation(state.get("validation"))
        if not validation.valid:
            raise RuntimeError(
                "Resumable combined validation state is not valid: "
                + "; ".join(validation.errors)
            )
        return

    manifest = _require_manifest_state(state)
    sidecar_path = write_combined_manifest(
        config,
        manifest,
        output_dir=paths.staging_output,
    )
    _fsync_directory_strict(sidecar_path.parent)
    validation = validate_preprocessed_database(
        staged_database,
        compatibility_output_dir=paths.staging_output,
        published_database_path=config.output_dir / config.combined.database_name,
        memory_limit_mib=config.combined.duckdb_memory_limit_mib,
    )
    if not validation.valid:
        raise RuntimeError(
            "Combined database validation failed: " + "; ".join(validation.errors)
        )
    _write_build_state(
        paths.state_path,
        {
            **state,
            "phase": "validation",
            "manifest": manifest,
            "database_stat": _file_stat(staged_database),
            "compatibility_stats": _compatibility_file_stats(paths.staging_output),
            "sidecar_stat": _file_stat(sidecar_path),
            "validation": _serialize_validation(validation),
        },
    )


def _new_build_state(
    paths: _CombinedBuildPaths,
    *,
    build_identity: str,
    published_output: Path,
    baseline: dict[str, CsvHashResult],
) -> dict[str, object]:
    return {
        "schema_version": _BUILD_STATE_SCHEMA_VERSION,
        "build_identity": build_identity,
        "phase": "pipeline",
        "staging_output": str(paths.staging_output),
        "published_output": str(published_output),
        "baseline": _serialize_hashes(baseline),
    }


def _combined_build_paths(
    published_output: Path,
    *,
    build_identity: str,
) -> _CombinedBuildPaths:
    output = Path(published_output)
    canonical_parent, _ = _canonicalized_path(output.parent)
    publication_identity = hashlib.sha256(_path_identity(output).encode()).hexdigest()
    build_token = build_identity[:24]
    publication_token = publication_identity[:24]
    return _CombinedBuildPaths(
        staging_output=canonical_parent / f"{COMBINED_BUILD_PREFIX}{build_token}",
        state_path=canonical_parent
        / f"{COMBINED_BUILD_PREFIX}{build_token}.state.json",
        backup_output=canonical_parent
        / f"{COMBINED_PREVIOUS_PREFIX}{publication_token}",
        publication_journal=canonical_parent
        / f"{COMBINED_PUBLICATION_PREFIX}{publication_token}.json",
    )


def _compatibility_export_paths(output_dir: Path) -> _CombinedBuildPaths:
    token = hashlib.sha256(
        f"compatibility-export:{_path_identity(output_dir)}".encode()
    ).hexdigest()[:24]
    parent, _ = _canonicalized_path(output_dir.parent)
    staging_output = parent / f"{COMBINED_BUILD_PREFIX}legacy-{token}"
    return _CombinedBuildPaths(
        staging_output=staging_output,
        state_path=staging_output.with_name(f"{staging_output.name}.state.json"),
        backup_output=parent / f"{COMBINED_PREVIOUS_PREFIX}legacy-{token}",
        publication_journal=(
            parent / f"{COMBINED_PUBLICATION_PREFIX}legacy-{token}.json"
        ),
    )


def _validate_compatibility_export_tree(
    root: Path,
    *,
    require_complete: bool,
    allow_temporary: bool = False,
) -> None:
    """Reject symlinks and entries outside the 36-file export contract."""

    if not root.exists():
        return
    _validate_product_tree(
        root,
        database_name="trinetx_preprocessed.duckdb",
        require_complete=require_complete,
        allow_temporary=allow_temporary,
        compatibility_only=True,
    )


def _discard_incomplete_compatibility_staging(
    paths: _CombinedBuildPaths,
) -> None:
    if paths.backup_output.exists() and not paths.publication_journal.exists():
        raise ValueError(
            "Compatibility export backup exists without its recovery journal: "
            f"{paths.backup_output}"
        )
    if not paths.staging_output.exists():
        return
    _validate_compatibility_export_tree(
        paths.staging_output,
        require_complete=False,
        allow_temporary=True,
    )
    remove_tree_strict(
        paths.staging_output,
        context="Incomplete compatibility export staging directory",
    )


def _fsync_compatibility_export(output_dir: Path) -> None:
    paths = tuple(
        output_dir / output.relative_path for output in compatibility_outputs()
    )
    for path in paths:
        _fsync_file_strict(path)
    directories = {output_dir, *(path.parent for path in paths)}
    for path in sorted(
        directories,
        key=lambda item: (-len(item.parts), str(item)),
    ):
        _fsync_directory_strict(path)


def _combined_build_identity(config: Config, *, strict: bool) -> str:
    """Bind resumable staging to source/code identity and execution policy."""

    payload = {
        "work_identity_sha256": work_identity_sha256(config),
        "strict": strict,
        "duckdb_memory_limit_mib": config.combined.duckdb_memory_limit_mib,
        "duckdb_core_memory_limit_mib": (config.combined.duckdb_core_memory_limit_mib),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _pipeline_outputs_are_current(
    config: Config,
    staging_output: Path,
    *,
    strict: bool,
) -> bool:
    if not staging_output.is_dir():
        return False
    try:
        require_current_work(
            config,
            required_stages=STAGE_ORDER,
            physical_output_dir=staging_output,
        )
        if strict:
            require_strict_encounter_work(config)
    except (FileNotFoundError, StaleWorkError, ValueError):
        return False
    return True


def _remove_staging_for_restart(
    staging_output: Path,
    *,
    database_name: str,
) -> None:
    _validate_product_tree(
        staging_output,
        database_name=database_name,
        require_complete=False,
        allow_temporary=True,
    )
    remove_tree_strict(
        staging_output,
        context="Incomplete combined preprocessing staging directory",
    )


def _remove_incomplete_database(database_path: Path) -> None:
    for path in (
        database_path,
        database_path.with_name(f"{database_path.name}.wal"),
    ):
        if path.is_symlink() or (path.exists() and not path.is_file()):
            raise ValueError(
                f"Refusing to replace unexpected database artifact: {path}"
            )
        path.unlink(missing_ok=True)
    for path in database_path.parent.glob(f"{COMBINED_DUCKDB_SPILL_PREFIX}*"):
        if path.is_dir() and not path.is_symlink():
            remove_tree_strict(path, context="Incomplete combined DuckDB spill")
        else:
            path.unlink(missing_ok=True)


def _compatibility_hashes(output_dir: Path) -> dict[str, CsvHashResult]:
    hashes: dict[str, CsvHashResult] = {}
    for output in compatibility_outputs():
        path = output_dir / output.relative_path
        hashes[output.key] = hash_csv_with_metadata(path)
    return hashes


def _remove_hash_scratch_directories(output_dir: Path) -> None:
    """Remove owned hash scratch left by an interrupted compatibility hash."""

    parent_directories = {
        (Path(output_dir) / output.relative_path).parent
        for output in compatibility_outputs()
    }
    for parent in sorted(parent_directories, key=str):
        if not parent.exists():
            continue
        if parent.is_symlink() or not parent.is_dir():
            raise ValueError(
                f"Compatibility output parent must be a real directory: {parent}"
            )
        for path in sorted(parent.glob(f"{HASH_SCRATCH_PREFIX}*"), key=str):
            if path.is_symlink() or not path.is_dir():
                raise ValueError(f"Hash scratch must be a real directory: {path}")
            remove_tree_strict(path, context="Interrupted compatibility hash scratch")


def _remove_staging_runtime_scratch(output_dir: Path) -> None:
    """Remove recognized row-level scratch left by an interrupted build phase."""

    root = Path(output_dir)
    for prefix in (COMBINED_DUCKDB_SPILL_PREFIX, COMBINED_VALIDATION_PREFIX):
        for path in sorted(root.glob(f"{prefix}*"), key=str):
            if path.is_symlink() or not path.is_dir():
                raise ValueError(
                    f"Combined staging scratch must be a real directory: {path}"
                )
            remove_tree_strict(path, context="Interrupted combined staging scratch")
    _remove_hash_scratch_directories(root)


def _serialize_hashes(
    hashes: dict[str, CsvHashResult],
) -> dict[str, dict[str, object]]:
    return {
        key: {
            "hash": value.hash,
            "row_count": value.row_count,
            "columns": list(value.columns),
        }
        for key, value in sorted(hashes.items())
    }


def _deserialize_hashes(value: object) -> dict[str, CsvHashResult]:
    if not isinstance(value, dict):
        raise ValueError("Combined build state has no compatibility hashes.")
    expected_keys = {output.key for output in compatibility_outputs()}
    if set(value) != expected_keys:
        raise ValueError(
            "Combined build state does not contain exactly 36 compatibility hashes."
        )
    results: dict[str, CsvHashResult] = {}
    for key, record in value.items():
        if not isinstance(key, str) or not isinstance(record, dict):
            raise ValueError("Combined build compatibility hash state is invalid.")
        hash_value = record.get("hash")
        row_count = record.get("row_count")
        columns = record.get("columns")
        if (
            not isinstance(hash_value, str)
            or isinstance(row_count, bool)
            or not isinstance(row_count, int)
            or not isinstance(columns, list)
            or not all(isinstance(column, str) for column in columns)
        ):
            raise ValueError("Combined build compatibility hash state is invalid.")
        results[key] = CsvHashResult(
            hash=hash_value,
            row_count=row_count,
            columns=tuple(columns),
        )
    return results


def _require_matching_hashes(
    baseline: dict[str, CsvHashResult],
    exported: dict[str, CsvHashResult],
) -> None:
    mismatched = sorted(
        key for key, value in baseline.items() if exported.get(key) != value
    )
    if mismatched:
        raise RuntimeError(
            "Database compatibility exports changed normalized CSV contents: "
            + ", ".join(mismatched)
        )


def _compatibility_file_stats(output_dir: Path) -> dict[str, dict[str, int]]:
    return {
        output.key: _file_stat(output_dir / output.relative_path)
        for output in compatibility_outputs()
    }


def _require_compatibility_state_current(
    output_dir: Path,
    state: dict[str, object],
) -> None:
    observed = _compatibility_file_stats(output_dir)
    if state.get("compatibility_stats") != observed:
        raise ValueError("Resumable combined compatibility files changed after export.")


def _file_stat(path: Path) -> dict[str, int]:
    stat = path.stat()
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"Expected a regular generated file: {path}")
    return {
        "size_bytes": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
    }


def _require_file_state_current(
    path: Path,
    expected: object,
    *,
    label: str,
) -> None:
    if not isinstance(expected, dict) or _file_stat(path) != expected:
        raise ValueError(f"Resumable {label} changed after validation: {path}")


def _require_database_state_current(
    database_path: Path,
    state: dict[str, object],
    *,
    config: Config,
) -> dict[str, Any]:
    _require_file_state_current(
        database_path,
        state.get("database_stat"),
        label="combined database",
    )
    manifest = _require_manifest_state(state)
    status = inspect_combined_database(
        database_path,
        memory_limit_mib=config.combined.duckdb_memory_limit_mib,
    )
    if status.get("status") != "complete" or status.get("run_id") != manifest.get(
        "run_id"
    ):
        raise ValueError(
            "Resumable combined database identity or terminal status changed."
        )
    return status


def _require_manifest_state(state: dict[str, object]) -> dict[str, Any]:
    manifest = state.get("manifest")
    if not isinstance(manifest, dict):
        raise ValueError("Combined build state has no database manifest.")
    return dict(manifest)


def _require_database_progress(
    state: dict[str, object],
    expected: str,
) -> None:
    observed = state.get("database_progress")
    if observed != expected:
        raise RuntimeError(
            "Combined database session did not durably advance progress "
            f"to {expected!r}; observed {observed!r}."
        )


def _serialize_validation(
    validation: CombinedValidationResult,
) -> dict[str, object]:
    return {
        "valid": validation.valid,
        "errors": list(validation.errors),
        "warnings": list(validation.warnings),
        "counts": validation.counts,
    }


def _deserialize_validation(value: object) -> CombinedValidationResult:
    if not isinstance(value, dict):
        raise ValueError("Combined build state has no validation result.")
    valid = value.get("valid")
    errors = value.get("errors")
    warnings = value.get("warnings")
    counts = value.get("counts")
    if (
        not isinstance(valid, bool)
        or not isinstance(errors, list)
        or not all(isinstance(item, str) for item in errors)
        or not isinstance(warnings, list)
        or not all(isinstance(item, str) for item in warnings)
        or not isinstance(counts, dict)
        or any(
            not isinstance(key, str)
            or isinstance(count, bool)
            or not isinstance(count, int)
            for key, count in counts.items()
        )
    ):
        raise ValueError("Combined build validation state is invalid.")
    return CombinedValidationResult(
        valid=valid,
        errors=tuple(errors),
        warnings=tuple(warnings),
        counts=dict(counts),
    )


def _phase_at_least(state: dict[str, object], phase: str) -> bool:
    current = state.get("phase")
    return (
        isinstance(current, str) and _PHASE_ORDER.get(current, 0) >= _PHASE_ORDER[phase]
    )


def _load_build_state(
    path: Path,
    *,
    expected_identity: str,
    paths: _CombinedBuildPaths,
    published_output: Path,
) -> dict[str, object] | None:
    if not path.exists():
        return None
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"Invalid combined build state path: {path}")
    try:
        payload = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Cannot read combined build state {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"Combined build state must be a JSON object: {path}")
    expected = {
        "schema_version": _BUILD_STATE_SCHEMA_VERSION,
        "build_identity": expected_identity,
        "staging_output": str(paths.staging_output),
        "published_output": str(published_output),
    }
    mismatched = [key for key, value in expected.items() if payload.get(key) != value]
    if payload.get("phase") not in _PHASE_ORDER:
        mismatched.append("phase")
    if mismatched:
        details = ", ".join(sorted(mismatched))
        raise ValueError(f"Combined build state is stale or invalid for: {details}")
    return payload


def _require_reloaded_build_state(
    config: Config,
    *,
    paths: _CombinedBuildPaths,
    build_identity: str,
    expected_phase: str,
) -> dict[str, object]:
    state = _load_build_state(
        paths.state_path,
        expected_identity=build_identity,
        paths=paths,
        published_output=config.output_dir,
    )
    if state is None or not _phase_at_least(state, expected_phase):
        observed = None if state is None else state.get("phase")
        raise RuntimeError(
            "Combined isolated phase did not durably advance build state "
            f"to {expected_phase!r}; observed {observed!r}."
        )
    return state


def _write_build_state(path: Path, payload: dict[str, object]) -> None:
    write_text_atomic(path, json.dumps(payload, indent=2, sort_keys=True) + "\n")
    _fsync_directory_strict(path.parent)


def _record_timing(
    timings: dict[str, float] | None,
    phase: str,
    started: float,
) -> None:
    if timings is not None:
        timings[phase] = time.perf_counter() - started


def _validate_existing_product(
    output_dir: Path,
    *,
    database_name: str,
    replace_existing: bool,
) -> None:
    if output_dir.is_symlink():
        raise ValueError(f"Combined output must be a directory: {output_dir}")
    if not output_dir.exists():
        return
    if not output_dir.is_dir():
        raise ValueError(f"Combined output must be a directory: {output_dir}")
    entries = list(output_dir.iterdir())
    if entries and not replace_existing:
        raise FileExistsError(
            f"Combined output already exists: {output_dir}; use --replace."
        )
    if entries:
        _validate_product_tree(
            output_dir,
            database_name=database_name,
            require_complete=False,
            allow_temporary=False,
        )


def _validate_product_tree(
    root: Path,
    *,
    database_name: str,
    require_complete: bool,
    allow_temporary: bool,
    compatibility_only: bool = False,
) -> None:
    if root.is_symlink() or not root.is_dir():
        raise ValueError(f"Combined product root must be a real directory: {root}")
    managed_files = {output.relative_path for output in compatibility_outputs()}
    if not compatibility_only:
        managed_files.update(
            {
                Path(database_name),
                Path(COMBINED_MANIFEST_FILENAME),
            }
        )
    managed_directories = {
        parent
        for path in managed_files
        for parent in path.parents
        if parent != Path(".")
    }
    observed_files: set[Path] = set()
    unknown: list[str] = []
    pending = [Path(root)]
    while pending:
        directory = pending.pop()
        for path in sorted(directory.iterdir(), key=lambda item: item.name):
            relative = path.relative_to(root)
            if path.is_symlink():
                unknown.append(relative.as_posix())
                continue
            if path.is_dir():
                if relative in managed_directories:
                    pending.append(path)
                elif allow_temporary and (
                    path.name.startswith(COMBINED_DUCKDB_SPILL_PREFIX)
                    or path.name.startswith(COMBINED_VALIDATION_PREFIX)
                    or path.name.startswith(HASH_SCRATCH_PREFIX)
                ):
                    continue
                else:
                    unknown.append(relative.as_posix())
                continue
            if not path.is_file():
                unknown.append(relative.as_posix())
                continue
            if relative in managed_files:
                observed_files.add(relative)
                continue
            if path.name == ".DS_Store" or path.name.startswith("._"):
                continue
            if allow_temporary and _is_allowed_temporary_file(
                relative,
                managed_files=managed_files,
                database_name=database_name,
                compatibility_only=compatibility_only,
            ):
                continue
            unknown.append(relative.as_posix())
    if unknown:
        raise ValueError(
            "Refusing to replace a combined output directory containing unmanaged "
            "entries: " + ", ".join(sorted(unknown))
        )
    missing = sorted(path.as_posix() for path in managed_files - observed_files)
    if require_complete and missing:
        raise ValueError(
            "Combined staged product is missing managed files: " + ", ".join(missing)
        )


def _is_allowed_temporary_file(
    relative: Path,
    *,
    managed_files: set[Path],
    database_name: str,
    compatibility_only: bool = False,
) -> bool:
    if not compatibility_only and relative == Path(f"{database_name}.wal"):
        return True
    for managed in managed_files:
        if (
            relative.parent == managed.parent
            and relative.name == f".{managed.name}.tmp"
        ):
            return True
        if relative.parent == managed.parent and relative.name.startswith(
            f".{managed.name}.tmp-"
        ):
            return True
    return False


def _publish_staged_product(
    paths: _CombinedBuildPaths,
    *,
    published_output: Path,
    database_name: str,
    replace_existing: bool,
    compatibility_only: bool = False,
) -> None:
    if paths.publication_journal.exists() or paths.backup_output.exists():
        raise ValueError(
            "Combined publication recovery artifacts must be reconciled before "
            "publication."
        )
    if published_output.is_symlink() or (
        published_output.exists() and not published_output.is_dir()
    ):
        raise ValueError(
            f"Combined output must be a real directory: {published_output}"
        )
    had_existing = published_output.exists()
    if had_existing:
        has_entries = any(published_output.iterdir())
        if has_entries and not replace_existing:
            raise FileExistsError(
                f"Combined output already exists: {published_output}; use --replace."
            )
        if has_entries:
            _validate_product_tree(
                published_output,
                database_name=database_name,
                require_complete=False,
                allow_temporary=False,
                compatibility_only=compatibility_only,
            )
    journal = {
        "schema_version": _PUBLICATION_JOURNAL_SCHEMA_VERSION,
        "state": "prepared",
        "had_existing": had_existing,
        "published_output": str(published_output),
        "staging_output": str(paths.staging_output),
        "backup_output": str(paths.backup_output),
    }
    if not compatibility_only:
        journal["build_state_path"] = str(paths.state_path)
    _write_publication_journal(paths.publication_journal, journal)
    installed = False
    try:
        if had_existing:
            os.replace(published_output, paths.backup_output)
            _fsync_directory(published_output.parent)
            journal["state"] = "old_moved"
            _write_publication_journal(paths.publication_journal, journal)
        os.replace(paths.staging_output, published_output)
        installed = True
        _fsync_directory(published_output.parent)
        journal["state"] = "new_installed"
        _write_publication_journal(paths.publication_journal, journal)
    except BaseException:
        rolled_back = False
        if (
            not installed
            and paths.backup_output.exists()
            and not published_output.exists()
        ):
            os.replace(paths.backup_output, published_output)
            _fsync_directory(published_output.parent)
            rolled_back = True
        safe_to_discard_journal = (
            rolled_back
            or (
                published_output.exists()
                and paths.staging_output.exists()
                and not paths.backup_output.exists()
            )
            or (
                not had_existing
                and not published_output.exists()
                and paths.staging_output.exists()
                and not paths.backup_output.exists()
            )
        )
        if not installed and safe_to_discard_journal:
            _unlink_generated_file(paths.publication_journal)
        raise

    if paths.backup_output.exists():
        _validate_product_tree(
            paths.backup_output,
            database_name=database_name,
            require_complete=False,
            allow_temporary=False,
            compatibility_only=compatibility_only,
        )
        remove_tree_strict(
            paths.backup_output,
            context="Previous combined preprocessing output",
        )
    if not compatibility_only:
        _unlink_generated_file(paths.state_path)
    _unlink_generated_file(paths.publication_journal)
    _fsync_directory(published_output.parent)


def _recover_interrupted_publication(
    published_output: Path,
    *,
    publication_journal: Path,
    backup_output: Path,
    database_name: str,
    compatibility_only: bool = False,
) -> None:
    journal_path = publication_journal
    if published_output.is_symlink() or backup_output.is_symlink():
        raise ValueError(
            "Combined publication paths must not be symbolic links: "
            f"{published_output}, {backup_output}"
        )
    if not journal_path.exists():
        if backup_output.exists():
            raise ValueError(
                "Combined publication backup exists without its recovery journal: "
                f"{backup_output}"
            )
        return
    if journal_path.is_symlink() or not journal_path.is_file():
        raise ValueError(
            f"Combined publication journal must be a regular file: {journal_path}"
        )
    try:
        journal = json.loads(journal_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(
            f"Cannot read combined publication journal {journal_path}: {exc}"
        ) from exc
    if not isinstance(journal, dict):
        raise ValueError(f"Invalid combined publication journal: {journal_path}")
    recorded_published = Path(str(journal.get("published_output", "")))
    recorded_staging = Path(str(journal.get("staging_output", "")))
    recorded_backup = Path(str(journal.get("backup_output", "")))
    recorded_state = Path(str(journal.get("build_state_path", "")))
    state_paths_are_valid = compatibility_only or (
        _same_path_identity(recorded_state.parent, published_output.parent)
        and recorded_state.name.startswith(COMBINED_BUILD_PREFIX)
        and recorded_state.name == f"{recorded_staging.name}.state.json"
    )
    if (
        journal.get("schema_version") != _PUBLICATION_JOURNAL_SCHEMA_VERSION
        or not _same_path_identity(recorded_published, published_output)
        or not _same_path_identity(recorded_backup, backup_output)
        or not _same_path_identity(recorded_staging.parent, published_output.parent)
        or not recorded_staging.name.startswith(COMBINED_BUILD_PREFIX)
        or not state_paths_are_valid
    ):
        raise ValueError(
            f"Combined publication journal paths are invalid: {journal_path}"
        )
    if recorded_staging.is_symlink() or (
        not compatibility_only and recorded_state.is_symlink()
    ):
        raise ValueError(
            f"Combined publication recovery paths must not be symbolic links: "
            f"{journal_path}"
        )
    if recorded_staging.exists() and not recorded_staging.is_dir():
        raise ValueError(
            f"Combined publication staging path must be a directory: {recorded_staging}"
        )
    if (
        not compatibility_only
        and recorded_state.exists()
        and not recorded_state.is_file()
    ):
        raise ValueError(
            f"Combined publication state path must be a regular file: {recorded_state}"
        )
    had_existing = journal.get("had_existing")
    if not isinstance(had_existing, bool):
        raise ValueError(
            f"Combined publication journal has invalid prior state: {journal_path}"
        )

    published_exists = published_output.exists()
    staging_exists = recorded_staging.exists()
    backup_exists = backup_output.exists()
    if published_exists:
        _validate_product_tree(
            published_output,
            database_name=database_name,
            require_complete=False,
            allow_temporary=False,
            compatibility_only=compatibility_only,
        )
    if backup_exists:
        _validate_product_tree(
            backup_output,
            database_name=database_name,
            require_complete=False,
            allow_temporary=False,
            compatibility_only=compatibility_only,
        )
    if published_exists and not staging_exists:
        _validate_product_tree(
            published_output,
            database_name=database_name,
            require_complete=True,
            allow_temporary=False,
            compatibility_only=compatibility_only,
        )
        if backup_exists:
            remove_tree_strict(
                backup_output,
                context="Recovered previous combined preprocessing output",
            )
        if not compatibility_only:
            _unlink_generated_file(recorded_state)
        _unlink_generated_file(journal_path)
        _fsync_directory(published_output.parent)
        return
    if not published_exists and backup_exists:
        os.replace(backup_output, published_output)
        _fsync_directory(published_output.parent)
        _unlink_generated_file(journal_path)
        return
    if published_exists and staging_exists and not backup_exists:
        _unlink_generated_file(journal_path)
        return
    if (
        not published_exists
        and not backup_exists
        and staging_exists
        and not had_existing
    ):
        _unlink_generated_file(journal_path)
        return
    raise ValueError(
        "Combined publication journal describes an ambiguous filesystem state: "
        f"{journal_path}"
    )


def _write_publication_journal(path: Path, payload: dict[str, object]) -> None:
    write_text_atomic(path, json.dumps(payload, indent=2, sort_keys=True) + "\n")
    _fsync_directory(path.parent)


def _unlink_generated_file(path: Path) -> None:
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise ValueError(f"Refusing to delete unexpected generated path: {path}")
    path.unlink(missing_ok=True)
    if path.exists() or path.is_symlink():
        raise OSError(f"Generated file was not deleted: {path}")


@contextmanager
def _canonical_build_lock(config: Config) -> Iterator[tuple[int, ...]]:
    lock_paths = sorted(
        {
            _lock_path(config.work_dir),
            _lock_path(config.output_dir),
        },
        key=str,
    )
    handles = []
    payload = {
        "schema_version": 1,
        "pid": os.getpid(),
        "hostname": socket.gethostname(),
        "work_dir": str(config.work_dir),
        "output_dir": str(config.output_dir),
    }
    try:
        for lock_path in lock_paths:
            lock_path.parent.mkdir(parents=True, exist_ok=True)
            handle = _open_lock_file(lock_path)
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                handle.seek(0)
                owner = handle.read().strip()
                handle.close()
                details = f" ({owner})" if owner else ""
                raise CombinedLockError(
                    "Another combined preprocessing build holds the canonical "
                    f"work/output lock: {lock_path}{details}"
                ) from exc
            handles.append(handle)
            handle.seek(0)
            handle.truncate()
            handle.write(json.dumps(payload, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        yield tuple(handle.fileno() for handle in handles)
    finally:
        for handle in reversed(handles):
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            finally:
                handle.close()


@contextmanager
def _compatibility_export_lock(
    database_path: Path,
    output_dir: Path,
) -> Iterator[None]:
    """Exclude canonical publication while reading and replacing exports."""

    lock_paths = sorted(
        {
            _lock_path(database_path.parent),
            _lock_path(output_dir),
        },
        key=str,
    )
    handles = []
    payload = {
        "schema_version": 1,
        "pid": os.getpid(),
        "hostname": socket.gethostname(),
        "operation": "export-legacy",
        "database": str(database_path),
        "output_dir": str(output_dir),
    }
    try:
        for lock_path in lock_paths:
            lock_path.parent.mkdir(parents=True, exist_ok=True)
            handle = _open_lock_file(lock_path)
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                handle.seek(0)
                owner = handle.read().strip()
                handle.close()
                details = f" ({owner})" if owner else ""
                raise CombinedLockError(
                    "Another combined preprocessing operation holds a canonical "
                    f"database/output lock: {lock_path}{details}"
                ) from exc
            handles.append(handle)
            handle.seek(0)
            handle.truncate()
            handle.write(json.dumps(payload, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        yield
    finally:
        for handle in reversed(handles):
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            finally:
                handle.close()


def _lock_path(root: Path) -> Path:
    resolved = Path(root).resolve(strict=False)
    token = hashlib.sha256(_path_identity(resolved).encode()).hexdigest()[:24]
    canonical_parent, _ = _canonicalized_path(resolved.parent)
    return canonical_parent / f"{COMBINED_LOCK_PREFIX}{token}"


def _path_identity(path: Path) -> str:
    """Return a stable identity across path aliases and root creation."""

    _, identity = _canonicalized_path(path)
    return f"canonical:{identity}"


def _same_path_identity(first: Path, second: Path) -> bool:
    """Return whether paths have the same stable, case-aware identity."""

    return _path_identity(first) == _path_identity(second)


def _canonicalized_path(path: Path) -> tuple[Path, Path]:
    """Return an operational path and stable case-aware identity path."""

    resolved = Path(path).resolve(strict=False)
    operational = Path(resolved.anchor)
    identity = Path(resolved.anchor)
    case_insensitive = _filesystem_is_case_insensitive(operational)
    for part in resolved.parts[1:]:
        if operational.exists():
            case_insensitive = _filesystem_is_case_insensitive(operational)
        requested = operational / part
        stored_name = _canonical_entry_name(
            operational,
            requested,
            fallback=part,
        )
        identity_name = unicodedata.normalize("NFC", stored_name)
        if case_insensitive:
            identity_name = identity_name.casefold()
        operational /= stored_name
        identity /= identity_name
    return operational, identity


def _filesystem_is_case_insensitive(path: Path) -> bool:
    """Detect case folding read-only from the closest useful path component."""

    candidate = Path(path)
    while candidate != candidate.parent:
        name = candidate.name
        swapped = name.swapcase()
        if candidate.exists() and swapped != name:
            alias = candidate.with_name(swapped)
            try:
                return alias.exists() and alias.samefile(candidate)
            except OSError:
                pass
        candidate = candidate.parent
    try:
        with os.scandir(candidate) as entries:
            for entry in entries:
                swapped = entry.name.swapcase()
                if swapped == entry.name:
                    continue
                alias = candidate / swapped
                return alias.exists() and alias.samefile(candidate / entry.name)
    except OSError:
        pass
    return False


def _canonical_entry_name(parent: Path, path: Path, *, fallback: str) -> str:
    """Return the stored directory-entry spelling for an existing path."""

    if not path.exists():
        return fallback
    try:
        target_metadata = path.stat()
        with os.scandir(parent) as entries:
            for entry in entries:
                try:
                    entry_metadata = entry.stat(follow_symlinks=True)
                except OSError:
                    continue
                if (entry_metadata.st_dev, entry_metadata.st_ino) == (
                    target_metadata.st_dev,
                    target_metadata.st_ino,
                ):
                    return entry.name
    except OSError:
        pass
    return fallback


def _open_lock_file(path: Path) -> TextIO:
    """Open a regular lock file without following a pre-existing symlink."""

    if path.is_symlink():
        raise ValueError(f"Combined lock path must be a regular file: {path}")
    flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
    descriptor: int | None = None
    try:
        descriptor = os.open(path, flags, 0o600)
        descriptor_stat = os.fstat(descriptor)
        path_stat = os.lstat(path)
        if (
            not stat.S_ISREG(descriptor_stat.st_mode)
            or not stat.S_ISREG(path_stat.st_mode)
            or (descriptor_stat.st_dev, descriptor_stat.st_ino)
            != (path_stat.st_dev, path_stat.st_ino)
        ):
            raise ValueError(f"Combined lock path must be a regular file: {path}")
        return os.fdopen(descriptor, "r+", encoding="utf-8")
    except BaseException:
        if descriptor is not None:
            os.close(descriptor)
        raise


def _fsync_directory(path: Path) -> None:
    try:
        descriptor = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)


def _fsync_export_checkpoint_inputs(
    output_dir: Path,
    *,
    work_manifest: Path,
) -> None:
    """Durably sync exported CSVs and their refreshed work manifest."""

    compatibility_paths = tuple(
        output_dir / output.relative_path for output in compatibility_outputs()
    )
    for path in (*compatibility_paths, work_manifest):
        _fsync_file_strict(path)

    directories = {
        output_dir,
        work_manifest.parent,
        *(path.parent for path in compatibility_paths),
    }
    for path in sorted(
        directories,
        key=lambda item: (-len(item.parts), str(item)),
    ):
        _fsync_directory_strict(path)


def _fsync_file_strict(path: Path) -> None:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"Cannot fsync non-regular checkpoint file: {path}")
    with path.open("rb") as handle:
        os.fsync(handle.fileno())


def _fsync_directory_strict(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _remove_appledouble_sidecars(root: Path) -> None:
    """Remove macOS metadata files before publishing the product directory."""

    for path in sorted(Path(root).rglob("._*"), reverse=True):
        if path.is_dir() and not path.is_symlink():
            remove_tree_strict(path, context="AppleDouble directory")
            continue
        path.unlink(missing_ok=True)
        if path.exists() or path.is_symlink():
            raise OSError(f"AppleDouble sidecar was not deleted: {path}")


def require_safe_output_location(
    output_dir: Path,
    *,
    artifact_label: str = "output directory",
) -> None:
    """Reject repository-local row-level combined artifacts."""

    output = Path(output_dir).resolve()
    existing_parent = output
    while not existing_parent.exists() and existing_parent != existing_parent.parent:
        existing_parent = existing_parent.parent
    try:
        result = subprocess.run(
            ["git", "-C", str(existing_parent), "rev-parse", "--show-toplevel"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return
    repository = Path(result.stdout.strip()).resolve()
    if not path_is_within(output, repository):
        return
    raise ValueError(
        f"Refusing repository-local combined preprocessing {artifact_label}: "
        f"{output}. Confidential outputs must be outside {repository}."
    )

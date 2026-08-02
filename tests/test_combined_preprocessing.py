from __future__ import annotations

import csv
import fcntl
import json
import multiprocessing
import os
import subprocess
import sys
import time
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from typing import Iterator

import duckdb
import pandas as pd
import pytest

import trinetx_preprocessing.combined_preprocessing.builder as combined_builder
import trinetx_preprocessing.combined_preprocessing.database as combined_database
import trinetx_preprocessing.combined_preprocessing.evidence as combined_evidence
import trinetx_preprocessing.combined_preprocessing.validation as combined_validation
from trinetx_preprocessing.combined_preprocessing.builder import (
    build_preprocessed,
    export_legacy_compatibility_outputs,
    require_safe_output_location,
)
from trinetx_preprocessing.combined_preprocessing.contract import (
    compatibility_outputs,
    final_output_columns,
)
from trinetx_preprocessing.combined_preprocessing.database import (
    _combined_run_id,
    _create_availability_tables,
    inspect_combined_database,
    open_combined_database,
)
from trinetx_preprocessing.combined_preprocessing.elements import (
    SOURCE_EVENT_COLUMNS,
    SOURCE_EVENT_DUCKDB_TYPES,
    ElementCaptureWriter,
    load_combined_catalog,
)
from trinetx_preprocessing.combined_preprocessing.evidence import (
    capture_compatibility_evidence,
    inspect_element_completeness,
    verify_compatibility_evidence,
    write_evidence,
)
from trinetx_preprocessing.combined_preprocessing.glp1_adapter import (
    materialize_glp1_observability_from_preprocessed,
    materialize_glp1_sources_from_preprocessed,
)
from trinetx_preprocessing.combined_preprocessing.scratch import (
    COMBINED_BUILD_PREFIX,
    COMBINED_DUCKDB_SPILL_PREFIX,
)
from trinetx_preprocessing.combined_preprocessing.validation import (
    CombinedValidationResult,
    validate_preprocessed_database,
)
from trinetx_preprocessing.config import (
    CombinedPreprocessingConfig,
    ConfigError,
    load_config,
)
from trinetx_preprocessing.glp1_eligibility.cohort import (
    build_cohort_flow,
    build_core_cohort,
)
from trinetx_preprocessing.glp1_eligibility.concept_sets import (
    Concept,
    ConceptSetCatalog,
    load_concept_sets,
)
from trinetx_preprocessing.glp1_eligibility.config import load_glp1_config
from trinetx_preprocessing.glp1_eligibility.database import initialize_database
from trinetx_preprocessing.glp1_eligibility.discovery import validate_export
from trinetx_preprocessing.glp1_eligibility.eligibility import (
    build_eligibility_phenotypes,
)
from trinetx_preprocessing.glp1_eligibility.ingestion import (
    build_raw_observability_summaries,
    ingest_core_sources,
)
from trinetx_preprocessing.glp1_eligibility.provenance import build_input_inventory
from trinetx_preprocessing.process_locks import SpawnedLockFileDescriptor
from trinetx_preprocessing.regression import (
    HASH_SCRATCH_PREFIX,
    CsvHashResult,
    hash_csv_with_metadata,
)
from trinetx_preprocessing.work_manifest import require_current_work

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def _hold_transferred_lock(
    descriptor: int,
    ready_path: Path,
    release_path: Path,
) -> None:
    ready_path.write_text("ready")
    deadline = time.monotonic() + 10
    try:
        while not release_path.exists():
            if time.monotonic() >= deadline:
                raise TimeoutError("lock-transfer test release was not observed")
            time.sleep(0.01)
    finally:
        os.close(descriptor)


def _record_isolated_worker_pid(
    output_path: Path,
    *,
    retained_lock_file_descriptors: tuple[int, ...],
) -> None:
    assert retained_lock_file_descriptors == ()
    output_path.write_text(str(os.getpid()))


def _run_isolated_phase_locally(
    phase: str,
    target: Callable[..., None],
    args: tuple[object, ...],
    *,
    lock_file_descriptors: tuple[int, ...],
) -> None:
    _ = phase
    target(
        *args,
        retained_lock_file_descriptors=lock_file_descriptors,
    )


def test_combined_run_id_ignores_volatile_work_status() -> None:
    identity = {
        "schema_version": 5,
        "intermediate_schema_version": 9,
        "package_version": "0.2.0",
        "git_code_state_sha256": "a" * 64,
        "runtime_versions": {"python": "3.11"},
        "ruleset": "corrected_v1",
        "combined_element_catalog_sha256": "b" * 64,
        "config_hash": "c" * 64,
        "inputs": [{"path": "input.csv", "size_bytes": 10}],
    }
    first = {
        **identity,
        "created_at": "2026-07-22T10:00:00Z",
        "updated_at": "2026-07-22T10:01:00Z",
        "stages": {"labs": {"completed_at": "2026-07-22T10:01:00Z"}},
    }
    second = {
        **identity,
        "created_at": "2026-07-22T11:00:00Z",
        "updated_at": "2026-07-22T11:01:00Z",
        "stages": {"labs": {"completed_at": "2026-07-22T11:01:00Z"}},
    }

    assert _combined_run_id(
        work_manifest=first,
        catalog_sha256="b" * 64,
        code_state="a" * 64,
    ) == _combined_run_id(
        work_manifest=second,
        catalog_sha256="b" * 64,
        code_state="a" * 64,
    )
    second["config_hash"] = "d" * 64
    assert _combined_run_id(
        work_manifest=first,
        catalog_sha256="b" * 64,
        code_state="a" * 64,
    ) != _combined_run_id(
        work_manifest=second,
        catalog_sha256="b" * 64,
        code_state="a" * 64,
    )


def test_combined_resumable_identity_includes_strict_policy(tmp_path: Path) -> None:
    config = load_config(_write_combined_config(tmp_path))

    assert combined_builder._combined_build_identity(
        config,
        strict=False,
    ) != combined_builder._combined_build_identity(
        config,
        strict=True,
    )


def test_combined_resumable_identity_includes_duckdb_memory_limits(
    tmp_path: Path,
) -> None:
    config = load_config(_write_combined_config(tmp_path))
    changed_default = replace(
        config,
        combined=replace(
            config.combined,
            duckdb_memory_limit_mib=config.combined.duckdb_memory_limit_mib + 1,
        ),
    )
    changed_core = replace(
        config,
        combined=replace(
            config.combined,
            duckdb_core_memory_limit_mib=(
                config.combined.duckdb_core_memory_limit_mib + 1
            ),
        ),
    )

    assert combined_builder._combined_build_identity(
        config,
        strict=False,
    ) != combined_builder._combined_build_identity(
        changed_default,
        strict=False,
    )
    assert combined_builder._combined_build_identity(
        config,
        strict=False,
    ) != combined_builder._combined_build_identity(
        changed_core,
        strict=False,
    )


def test_combined_pipeline_uses_sequential_fresh_phase_workers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = load_config(_write_combined_config(tmp_path))
    build_identity = combined_builder._combined_build_identity(config, strict=True)
    paths = combined_builder._combined_build_paths(
        config.output_dir,
        build_identity=build_identity,
    )
    calls: list[tuple[str, object, tuple[object, ...], tuple[int, ...]]] = []

    monkeypatch.setattr(
        combined_builder,
        "_run_isolated_phase_process",
        lambda phase, target, args, *, lock_file_descriptors: calls.append(
            (phase, target, args, lock_file_descriptors)
        ),
    )

    combined_builder._run_combined_pipeline_isolated(
        config,
        strict=True,
        paths=paths,
        build_identity=build_identity,
        lock_file_descriptors=(101, 102),
    )

    assert [phase for phase, _, _, _ in calls] == [
        "pre-final",
        "final-assembly",
    ]
    assert calls[0][1] is combined_builder._run_pre_final_pipeline_worker
    assert calls[0][2] == (config, True)
    assert calls[0][3] == (101, 102)
    assert calls[1][1] is combined_builder._run_final_pipeline_worker
    assert calls[1][2] == (config, True, paths, build_identity)
    assert calls[1][3] == (101, 102)


@pytest.mark.parametrize(
    "final_assembly_record",
    [
        None,
        {"status": "running", "outputs": []},
    ],
    ids=["not-started", "interrupted"],
)
def test_combined_retry_runs_only_final_assembly_when_prerequisites_are_current(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    final_assembly_record: dict[str, object] | None,
) -> None:
    config = load_config(_write_combined_config(tmp_path))
    build_identity = combined_builder._combined_build_identity(config, strict=True)
    paths = combined_builder._combined_build_paths(
        config.output_dir,
        build_identity=build_identity,
    )
    partial_output = paths.staging_output / compatibility_outputs()[0].relative_path
    partial_output.parent.mkdir(parents=True)
    partial_output.write_text("partial synthetic staging row\n")
    required_stage_calls: list[tuple[str, ...]] = []

    def require_current_prerequisites(
        config_arg,
        *,
        required_stages,
        physical_output_dir=None,
    ):
        _ = config_arg
        stages = tuple(required_stages)
        required_stage_calls.append(stages)
        if stages == combined_builder.STAGE_ORDER:
            assert physical_output_dir == paths.staging_output
            raise combined_builder.StaleWorkError("final assembly is incomplete")
        assert stages == combined_builder.FINAL_ASSEMBLY_PREREQUISITES
        assert physical_output_dir is None
        manifest_stages = {}
        if final_assembly_record is not None:
            manifest_stages["final_assembly"] = final_assembly_record
        return {"stages": manifest_stages}

    def run_expected_final_only(*args, **kwargs):
        _ = args, kwargs
        assert paths.staging_output.is_dir()
        assert not partial_output.exists()
        assert list(paths.staging_output.iterdir()) == []
        raise RuntimeError("selected final-assembly-only retry")

    def unexpected_full_restart(*args, **kwargs):
        raise AssertionError("current prerequisites triggered a full pre-final restart")

    monkeypatch.setattr(
        combined_builder,
        "require_current_work",
        require_current_prerequisites,
    )
    monkeypatch.setattr(
        combined_builder,
        "_run_final_pipeline_isolated",
        run_expected_final_only,
    )
    monkeypatch.setattr(
        combined_builder,
        "_run_combined_pipeline_isolated",
        unexpected_full_restart,
    )

    with pytest.raises(RuntimeError, match="selected final-assembly-only retry"):
        build_preprocessed(config, strict=True)

    assert required_stage_calls == [
        combined_builder.STAGE_ORDER,
        combined_builder.FINAL_ASSEMBLY_PREREQUISITES,
    ]


def test_combined_retry_recomputes_final_only_eligibility_after_stale_state_removal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = load_config(_write_combined_config(tmp_path))
    build_identity = combined_builder._combined_build_identity(config, strict=True)
    paths = combined_builder._combined_build_paths(
        config.output_dir,
        build_identity=build_identity,
    )
    partial_output = paths.staging_output / compatibility_outputs()[0].relative_path
    partial_output.parent.mkdir(parents=True)
    partial_output.write_text("partial synthetic staging row\n")
    combined_builder._write_build_state(
        paths.state_path,
        combined_builder._new_build_state(
            paths,
            build_identity=build_identity,
            published_output=config.output_dir,
            baseline={},
        ),
    )
    required_stage_calls: list[tuple[str, ...]] = []

    def require_current_prerequisites(
        config_arg,
        *,
        required_stages,
        physical_output_dir=None,
    ):
        _ = config_arg
        stages = tuple(required_stages)
        required_stage_calls.append(stages)
        if stages == combined_builder.STAGE_ORDER:
            assert physical_output_dir == paths.staging_output
            raise combined_builder.StaleWorkError("final assembly is incomplete")
        assert stages == combined_builder.FINAL_ASSEMBLY_PREREQUISITES
        assert physical_output_dir is None
        return {
            "stages": {
                "final_assembly": {"status": "running", "outputs": []},
            }
        }

    def run_expected_final_only(*args, **kwargs):
        _ = args, kwargs
        assert paths.staging_output.is_dir()
        assert not partial_output.exists()
        assert not paths.state_path.exists()
        raise RuntimeError("selected final-assembly-only retry")

    def unexpected_full_restart(*args, **kwargs):
        raise AssertionError("removed stale state retained its earlier decision")

    monkeypatch.setattr(
        combined_builder,
        "require_current_work",
        require_current_prerequisites,
    )
    monkeypatch.setattr(
        combined_builder,
        "_run_final_pipeline_isolated",
        run_expected_final_only,
    )
    monkeypatch.setattr(
        combined_builder,
        "_run_combined_pipeline_isolated",
        unexpected_full_restart,
    )

    with pytest.raises(RuntimeError, match="selected final-assembly-only retry"):
        build_preprocessed(config, strict=True)

    assert required_stage_calls == [
        combined_builder.STAGE_ORDER,
        combined_builder.FINAL_ASSEMBLY_PREREQUISITES,
    ]


@pytest.mark.parametrize(
    "stale_reason",
    ["missing prerequisite artifact", "changed prerequisite artifact"],
)
def test_combined_retry_reruns_pre_final_when_a_prerequisite_is_stale(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    stale_reason: str,
) -> None:
    config = load_config(_write_combined_config(tmp_path))
    build_identity = combined_builder._combined_build_identity(config, strict=True)
    paths = combined_builder._combined_build_paths(
        config.output_dir,
        build_identity=build_identity,
    )
    partial_output = paths.staging_output / compatibility_outputs()[0].relative_path
    partial_output.parent.mkdir(parents=True)
    partial_output.write_text("partial synthetic staging row\n")
    required_stage_calls: list[tuple[str, ...]] = []

    def reject_stale_work(
        config_arg,
        *,
        required_stages,
        physical_output_dir=None,
    ):
        _ = config_arg, physical_output_dir
        stages = tuple(required_stages)
        required_stage_calls.append(stages)
        raise combined_builder.StaleWorkError(stale_reason)

    def run_expected_full_restart(*args, **kwargs):
        _ = args, kwargs
        assert paths.staging_output.is_dir()
        assert not partial_output.exists()
        assert list(paths.staging_output.iterdir()) == []
        raise RuntimeError("selected full pre-final restart")

    def unexpected_final_only_retry(*args, **kwargs):
        raise AssertionError("stale prerequisites triggered final-only retry")

    monkeypatch.setattr(
        combined_builder,
        "require_current_work",
        reject_stale_work,
    )
    monkeypatch.setattr(
        combined_builder,
        "_run_combined_pipeline_isolated",
        run_expected_full_restart,
    )
    monkeypatch.setattr(
        combined_builder,
        "_run_final_pipeline_isolated",
        unexpected_final_only_retry,
    )

    with pytest.raises(RuntimeError, match="selected full pre-final restart"):
        build_preprocessed(config, strict=True)

    assert required_stage_calls == [
        combined_builder.STAGE_ORDER,
        combined_builder.FINAL_ASSEMBLY_PREREQUISITES,
    ]


def test_isolated_phase_process_runs_target_in_fresh_process(
    tmp_path: Path,
) -> None:
    worker_pid_path = tmp_path / "worker.pid"

    combined_builder._run_isolated_phase_process(
        "pid-proof",
        _record_isolated_worker_pid,
        (worker_pid_path,),
        lock_file_descriptors=(),
    )

    assert int(worker_pid_path.read_text()) != os.getpid()


def test_validation_worker_rechecks_serialized_export_hashes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = load_config(_write_combined_config(tmp_path))
    build_identity = combined_builder._combined_build_identity(config, strict=True)
    paths = combined_builder._combined_build_paths(
        config.output_dir,
        build_identity=build_identity,
    )
    baseline = {
        output.key: CsvHashResult(
            hash="a" * 64,
            row_count=0,
            columns=final_output_columns(),
        )
        for output in compatibility_outputs()
    }
    exported = dict(baseline)
    mismatched_key = compatibility_outputs()[0].key
    exported[mismatched_key] = replace(
        exported[mismatched_key],
        hash="b" * 64,
    )
    state: dict[str, object] = {
        "phase": "compatibility_export",
        "baseline": combined_builder._serialize_hashes(baseline),
        "exported": combined_builder._serialize_hashes(exported),
    }
    monkeypatch.setattr(
        combined_builder,
        "_require_reloaded_build_state",
        lambda *args, **kwargs: state,
    )
    monkeypatch.setattr(
        combined_builder,
        "_require_database_state_current",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        combined_builder,
        "_require_compatibility_state_current",
        lambda *args, **kwargs: None,
    )

    with pytest.raises(
        RuntimeError,
        match="Database compatibility exports changed normalized CSV contents",
    ):
        combined_builder._run_validation_phase_worker(
            config,
            paths,
            build_identity,
            retained_lock_file_descriptors=(),
        )


def test_validation_checkpoint_requires_durable_sidecar_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = load_config(_write_combined_config(tmp_path))
    build_identity = combined_builder._combined_build_identity(config, strict=True)
    paths = combined_builder._combined_build_paths(
        config.output_dir,
        build_identity=build_identity,
    )
    paths.staging_output.mkdir()
    staged_database = paths.staging_output / config.combined.database_name
    staged_database.write_bytes(b"synthetic database")
    hashes = {
        output.key: CsvHashResult(
            hash="a" * 64,
            row_count=0,
            columns=final_output_columns(),
        )
        for output in compatibility_outputs()
    }
    state: dict[str, object] = {
        "phase": "compatibility_export",
        "baseline": combined_builder._serialize_hashes(hashes),
        "exported": combined_builder._serialize_hashes(hashes),
        "manifest": {},
    }
    monkeypatch.setattr(
        combined_builder,
        "_require_reloaded_build_state",
        lambda *args, **kwargs: state,
    )
    monkeypatch.setattr(
        combined_builder,
        "_require_database_state_current",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        combined_builder,
        "_require_compatibility_state_current",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        combined_builder,
        "_compatibility_file_stats",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        combined_builder,
        "validate_preprocessed_database",
        lambda *args, **kwargs: CombinedValidationResult(
            valid=True,
            errors=(),
            warnings=(),
            counts={},
        ),
    )
    synced_directories: list[Path] = []
    real_fsync_directory = combined_builder._fsync_directory_strict
    fail_sidecar_sync = True

    def track_directory(path: Path) -> None:
        nonlocal fail_sidecar_sync
        if fail_sidecar_sync and path == paths.staging_output:
            raise OSError("injected sidecar directory fsync failure")
        synced_directories.append(path)
        real_fsync_directory(path)

    monkeypatch.setattr(
        combined_builder,
        "_fsync_directory_strict",
        track_directory,
    )

    with pytest.raises(OSError, match="sidecar directory fsync failure"):
        combined_builder._run_validation_phase_worker(
            config,
            paths,
            build_identity,
            retained_lock_file_descriptors=(),
        )

    assert not paths.state_path.exists()
    fail_sidecar_sync = False
    combined_builder._run_validation_phase_worker(
        config,
        paths,
        build_identity,
        retained_lock_file_descriptors=(),
    )

    assert synced_directories.index(paths.staging_output) < synced_directories.index(
        paths.state_path.parent
    )
    checkpoint = json.loads(paths.state_path.read_text())
    assert checkpoint["phase"] == "validation"


def test_spawned_worker_retains_canonical_lock_after_parent_descriptor_closes(
    tmp_path: Path,
) -> None:
    lock_path = tmp_path / "canonical.lock"
    ready_path = tmp_path / "worker.ready"
    release_path = tmp_path / "worker.release"
    parent_handle = lock_path.open("a+")
    fcntl.flock(parent_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    context = multiprocessing.get_context("spawn")
    process = context.Process(
        target=_hold_transferred_lock,
        args=(
            SpawnedLockFileDescriptor(parent_handle.fileno()),
            ready_path,
            release_path,
        ),
    )
    process.start()
    try:
        deadline = time.monotonic() + 10
        while not ready_path.exists():
            if time.monotonic() >= deadline:
                raise TimeoutError("spawned lock worker did not become ready")
            time.sleep(0.01)

        parent_handle.close()
        contender = lock_path.open("a+")
        try:
            with pytest.raises(BlockingIOError):
                fcntl.flock(contender.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        finally:
            contender.close()
    finally:
        release_path.touch()
        process.join(timeout=10)
        if process.is_alive():
            process.terminate()
            process.join()
        if not parent_handle.closed:
            fcntl.flock(parent_handle.fileno(), fcntl.LOCK_UN)
            parent_handle.close()

    assert process.exitcode == 0
    with lock_path.open("a+") as contender:
        fcntl.flock(contender.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(contender.fileno(), fcntl.LOCK_UN)


def test_combined_private_artifacts_reject_repository_paths() -> None:
    with pytest.raises(ValueError, match="work directory"):
        require_safe_output_location(
            REPOSITORY_ROOT / "results" / "combined-work",
            artifact_label="work directory",
        )


def test_combined_private_artifacts_reject_repository_case_alias() -> None:
    aliased_parent = REPOSITORY_ROOT.parent.with_name(
        REPOSITORY_ROOT.parent.name.swapcase()
    )
    aliased_repository = aliased_parent / REPOSITORY_ROOT.name
    if not aliased_repository.exists() or not aliased_repository.samefile(
        REPOSITORY_ROOT
    ):
        pytest.skip("requires a case-insensitive repository filesystem")

    with pytest.raises(ValueError, match="repository-local"):
        require_safe_output_location(
            aliased_repository / "future-private-output",
        )


def test_compatibility_evidence_guards_locations_before_hashing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_dir = tmp_path / "compatibility"
    events: list[tuple[str, Path, str]] = []

    def record_guard(path: Path, *, artifact_label: str) -> None:
        events.append(("guard", path, artifact_label))

    def record_hash(path: Path) -> CsvHashResult:
        events.append(("hash", path, ""))
        return CsvHashResult(
            hash="0" * 64,
            row_count=0,
            columns=final_output_columns(),
        )

    monkeypatch.setattr(
        combined_builder,
        "require_safe_output_location",
        record_guard,
    )
    monkeypatch.setattr(combined_evidence, "hash_csv_with_metadata", record_hash)

    payload = capture_compatibility_evidence(output_dir)

    assert payload["table_count"] == 36
    assert events[:4] == [
        ("guard", output_dir, "evidence compatibility output directory"),
        (
            "guard",
            output_dir / "AMBULATORY",
            "evidence compatibility hash directory",
        ),
        (
            "guard",
            output_dir / "EMERGENCY",
            "evidence compatibility hash directory",
        ),
        (
            "guard",
            output_dir / "INPATIENT",
            "evidence compatibility hash directory",
        ),
    ]
    assert len(events) == 40
    assert all(event == "hash" for event, _, _ in events[4:])


@pytest.mark.parametrize("nested_symlink", [False, True])
def test_compatibility_evidence_rejects_repository_hash_locations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    nested_symlink: bool,
) -> None:
    if nested_symlink:
        output_dir = tmp_path / "compatibility"
        output_dir.mkdir()
        (output_dir / "AMBULATORY").symlink_to(
            REPOSITORY_ROOT,
            target_is_directory=True,
        )
    else:
        output_dir = REPOSITORY_ROOT / "private-compatibility-evidence"
    monkeypatch.setattr(
        combined_evidence,
        "hash_csv_with_metadata",
        lambda *args, **kwargs: pytest.fail("unsafe location reached hashing"),
    )

    with pytest.raises(ValueError, match="repository-local"):
        capture_compatibility_evidence(output_dir)


@pytest.mark.parametrize("operation", ["parity", "element_completeness"])
def test_database_evidence_rejects_repository_spill_before_scanning(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    database = REPOSITORY_ROOT / "private-evidence.duckdb"
    monkeypatch.setattr(
        combined_evidence,
        "validate_preprocessed_database",
        lambda *args, **kwargs: pytest.fail("unsafe database reached validation"),
    )

    with pytest.raises(ValueError, match="evidence database/spill directory"):
        if operation == "parity":
            verify_compatibility_evidence(
                database,
                tmp_path / "compatibility",
                tmp_path / "baseline.json",
            )
        else:
            inspect_element_completeness(database)


def test_filesystem_aliases_share_locks_and_publication_paths(
    tmp_path: Path,
) -> None:
    canonical = tmp_path / "Shared"
    canonical.mkdir()
    alias = tmp_path / "shared"
    if not alias.exists() or not alias.samefile(canonical):
        pytest.skip("requires a case-insensitive filesystem")

    assert combined_builder._lock_path(canonical) == combined_builder._lock_path(alias)
    assert combined_builder._compatibility_export_paths(
        canonical
    ) == combined_builder._compatibility_export_paths(alias)


def test_absent_case_aliases_share_locks_and_publication_paths(
    tmp_path: Path,
) -> None:
    canonical_parent = tmp_path / "Parent"
    canonical_parent.mkdir()
    alias_parent = tmp_path / "parent"
    if not alias_parent.exists() or not alias_parent.samefile(canonical_parent):
        pytest.skip("requires a case-insensitive filesystem")
    canonical = canonical_parent / "Export"
    alias = alias_parent / "export"
    assert not canonical.exists()

    assert combined_builder._path_identity(canonical) == (
        combined_builder._path_identity(alias)
    )
    assert combined_builder._lock_path(canonical) == combined_builder._lock_path(alias)
    assert combined_builder._compatibility_export_paths(
        canonical
    ) == combined_builder._compatibility_export_paths(alias)


def test_lock_and_publication_identity_survive_parent_creation(
    tmp_path: Path,
) -> None:
    output = tmp_path / "new-parent" / "compatibility"
    lock_before = combined_builder._lock_path(output)
    publication_before = combined_builder._compatibility_export_paths(output)

    output.parent.mkdir()
    assert combined_builder._lock_path(output) == lock_before
    assert combined_builder._compatibility_export_paths(output) == publication_before

    output.mkdir()
    assert combined_builder._lock_path(output) == lock_before
    assert combined_builder._compatibility_export_paths(output) == publication_before


@pytest.mark.parametrize("entry_kind", ["file", "symlink"])
def test_staging_runtime_scratch_rejects_non_directory_entries(
    tmp_path: Path,
    entry_kind: str,
) -> None:
    staging = tmp_path / "staging"
    staging.mkdir()
    scratch = staging / f"{COMBINED_DUCKDB_SPILL_PREFIX}unexpected"
    if entry_kind == "file":
        scratch.write_text("must remain\n")
    else:
        target = tmp_path / "outside"
        target.mkdir()
        scratch.symlink_to(target, target_is_directory=True)

    with pytest.raises(ValueError, match="scratch must be a real directory"):
        combined_builder._remove_staging_runtime_scratch(staging)

    assert scratch.exists() or scratch.is_symlink()


def test_lock_opener_rejects_symlink_without_clobbering_target(
    tmp_path: Path,
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    lock_path = combined_builder._lock_path(root)
    target = tmp_path / "must-remain.txt"
    target.write_text("unchanged\n")
    lock_path.symlink_to(target)

    with pytest.raises(ValueError, match="lock path must be a regular file"):
        combined_builder._open_lock_file(lock_path)

    assert target.read_text() == "unchanged\n"


def test_combined_builder_rejects_path_overlap_before_location_checks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = load_config(_write_combined_config(tmp_path))
    config = replace(
        config,
        output_dir=config.work_dir,
        combined=replace(config.combined, enabled=False),
    )
    marker = config.work_dir / "must-remain.txt"
    marker.write_text("unchanged")

    monkeypatch.setattr(
        combined_builder,
        "require_safe_output_location",
        lambda *args, **kwargs: pytest.fail(
            "repository-location checks ran before path-overlap validation"
        ),
    )

    with pytest.raises(ConfigError, match="non-overlapping 'work_dir'.*'output_dir'"):
        build_preprocessed(config, strict=True, replace_existing=True)

    assert marker.read_text() == "unchanged"


def test_combined_database_session_bounds_runtime_and_cleans_spill(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "bounded.duckdb"

    with open_combined_database(database_path, memory_limit_mib=64) as connection:
        memory_limit, threads, spill_path, preserve_order = connection.execute(
            "SELECT current_setting('memory_limit'), current_setting('threads'), "
            "current_setting('temp_directory'), "
            "current_setting('preserve_insertion_order')"
        ).fetchone()
        Path(spill_path).mkdir()

    assert memory_limit == "64.0 MiB"
    assert threads == 1
    assert preserve_order is False
    assert not Path(spill_path).exists()


def test_combined_encounter_availability_is_exact_and_cleans_partitions(
    tmp_path: Path,
) -> None:
    config = load_config(_write_combined_config(tmp_path))
    pd.DataFrame(
        {"encounter_id": pd.Series(["E1", "E1", "E2", None], dtype="string")}
    ).to_parquet(config.work_dir / "analysis_diagnosis_availability.parquet")
    pd.DataFrame(
        {"encounter_id": pd.Series(["E2", "E3", "E3", None], dtype="string")}
    ).to_parquet(config.work_dir / "analysis_lab_availability.parquet")
    database_path = tmp_path / "availability.duckdb"

    with open_combined_database(database_path, memory_limit_mib=64) as connection:
        connection.execute(
            """
            CREATE TABLE source_observability_event (
                patient_id VARCHAR,
                logical_domain VARCHAR,
                event_datetime TIMESTAMP,
                timestamp_precision VARCHAR,
                event_count UBIGINT
            )
            """
        )
        connection.execute(
            """
            INSERT INTO source_observability_event
            VALUES ('P1', 'diagnosis', '2022-01-01', 'date_only', 2)
            """
        )
        _create_availability_tables(connection, config)
        rows = connection.execute(
            """
            SELECT
                encounter_id,
                has_diagnosis,
                has_lab,
                has_diagnosis_or_lab
            FROM encounter_availability
            ORDER BY encounter_id
            """
        ).fetchall()
        spill_path = Path(
            connection.execute("SELECT current_setting('temp_directory')").fetchone()[0]
        )
        observability = connection.execute(
            """
            SELECT
                patient_id,
                logical_domain,
                event_count,
                first_event_datetime,
                last_event_datetime
            FROM patient_observability
            """
        ).fetchone()

        assert rows == [
            ("E1", True, False, True),
            ("E2", True, True, True),
            ("E3", False, True, True),
        ]
        assert observability == (
            "P1",
            "diagnosis",
            2,
            pd.Timestamp("2022-01-01"),
            pd.Timestamp("2022-01-01"),
        )
        assert not (spill_path / "encounter-availability").exists()

    assert not spill_path.exists()


def _write_combined_config(
    tmp_path: Path,
    *,
    data_dir: Path | None = None,
    intermediate_format: str = "parquet",
) -> Path:
    work_dir = tmp_path / "work"
    output_dir = tmp_path / "output"
    work_dir.mkdir()
    output_dir.mkdir()
    path = tmp_path / "config.yaml"
    source_root = data_dir or REPOSITORY_ROOT / "tests/fixtures/example_data"
    path.write_text(
        "\n".join(
            [
                f'data_dir: "{source_root}"',
                f'work_dir: "{work_dir}"',
                f'output_dir: "{output_dir}"',
                "chunking:",
                "  enabled: true",
                "  lines_per_chunk: 2",
                "storage:",
                f"  intermediate_format: {intermediate_format}",
                "  emit_legacy_csv_intermediates: false",
                "  parquet_row_group_size: 10",
                "  analysis_bucket_count: 2",
                "combined:",
                "  enabled: true",
                "  database_name: trinetx_preprocessed.duckdb",
                f'  concept_sets_dir: "{REPOSITORY_ROOT / "config/concept_sets"}"',
                "domains:",
                "  encounter:",
                '    pattern: "Encounter/encounter*.csv"',
                "  diagnosis:",
                '    pattern: "Diagnosis/diagnosis*.csv"',
                "  labs:",
                '    pattern: "Lab Results/lab_result*.csv"',
                "  meds:",
                '    pattern: "Medications/medication*.csv"',
                "  procedure:",
                '    pattern: "Procedure/procedure*.csv"',
                "  vitals:",
                '    pattern: "Vital Signs/vital*_signs*.csv"',
                "  patient:",
                '    pattern: "Patient/patient*.csv"',
                "rfs:",
                "  enabled: true",
                "",
            ]
        )
    )
    return path


def _copy_glp1_fixture_for_combined(tmp_path: Path) -> Path:
    source_root = REPOSITORY_ROOT / "tests/fixtures/glp1_synthetic"
    destination_root = tmp_path / "glp1_input"
    required_defaults = {
        "Encounter/encounter.csv": {
            "start_date_derived_by_TriNetX": "",
            "end_date_derived_by_TriNetX": "",
            "derived_by_TriNetX": "N",
        },
        "Diagnosis/diagnosis.csv": {
            "derived_by_TriNetX": "N",
            "source_id": "synthetic",
        },
        "Lab Results/lab_results.csv": {
            "derived_by_TriNetX": "N",
            "source_id": "synthetic",
        },
        "Medications/medication.csv": {
            "unique_id": "synthetic",
            "derived_by_TriNetX": "N",
            "source_id": "synthetic",
        },
        "Procedure/procedure.csv": {
            "derived_by_TriNetX": "N",
            "source_id": "synthetic",
        },
        "Vital Signs/vital_signs.csv": {
            "derived_by_TriNetX": "N",
            "source_id": "synthetic",
        },
        "Patient/patient.csv": {},
    }
    for relative, defaults in required_defaults.items():
        frame = pd.read_csv(source_root / relative, dtype="string")
        for column, value in defaults.items():
            if column not in frame:
                frame[column] = value
        destination = destination_root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        frame.to_csv(destination, index=False)
    return destination_root


def _append_pre2022_non_gas_encounter(input_root: Path) -> None:
    patient_path = input_root / "Patient/patient.csv"
    patients = pd.read_csv(patient_path, dtype="string")
    patient = {column: "" for column in patients.columns}
    patient.update(
        {
            "patient_id": "flow-only-patient",
            "sex": "M",
            "race": "Unknown",
            "ethnicity": "Unknown",
            "year_of_birth": "1980",
            "patient_regional_location": "Unknown",
        }
    )
    pd.concat([patients, pd.DataFrame([patient])], ignore_index=True).to_csv(
        patient_path,
        index=False,
    )

    encounter_path = input_root / "Encounter/encounter.csv"
    encounters = pd.read_csv(encounter_path, dtype="string")
    flow_only_encounter = {column: "" for column in encounters.columns}
    flow_only_encounter.update(
        {
            "encounter_id": "flow-only-encounter",
            "patient_id": "flow-only-patient",
            "start_date": "2020-01-01",
            "end_date": "2020-01-02",
            "type": "EMER",
            "derived_by_TriNetX": "N",
        }
    )
    unused_invalid_encounter = {column: "" for column in encounters.columns}
    unused_invalid_encounter.update(
        {
            "encounter_id": "unused-invalid-encounter",
            "patient_id": "flow-only-patient",
            "start_date": "not-a-date",
            "end_date": "also-not-a-date",
            "type": "OTHER",
            "derived_by_TriNetX": "N",
        }
    )
    pd.concat(
        [
            encounters,
            pd.DataFrame([flow_only_encounter, unused_invalid_encounter]),
        ],
        ignore_index=True,
    ).to_csv(
        encounter_path,
        index=False,
    )


def test_element_capture_preserves_duplicate_source_rows_and_membership(
    tmp_path: Path,
) -> None:
    config = load_config(_write_combined_config(tmp_path))
    config = replace(
        config,
        combined=CombinedPreprocessingConfig(
            enabled=True,
            concept_sets_dir=REPOSITORY_ROOT / "config/concept_sets",
        ),
    )
    source_path = config.data_dir / "Lab Results" / "lab_results0001.csv"
    rows = pd.DataFrame(
        [
            {
                "patient_id": "P1",
                "encounter_id": "E1",
                "code_system": "LOINC",
                "code": "2019-8",
                "date": "20220101",
                "lab_result_num_val": "55.0",
                "lab_result_text_val": "",
                "units_of_measure": "mm[Hg]",
                "derived_by_TriNetX": "N",
                "source_id": "S1",
            },
            {
                "patient_id": "P1",
                "encounter_id": "E1",
                "code_system": "LOINC",
                "code": "2019-8",
                "date": "20220101",
                "lab_result_num_val": "55.0",
                "lab_result_text_val": "",
                "units_of_measure": "mm[Hg]",
                "derived_by_TriNetX": "N",
                "source_id": "S1",
            },
            {
                "patient_id": "P2",
                "encounter_id": "E2",
                "code_system": "LOINC",
                "code": "2019-8",
                "date": "2022-01-01 01:00:00",
                "lab_result_num_val": "56.0",
                "lab_result_text_val": "",
                "units_of_measure": "mm[Hg]",
                "derived_by_TriNetX": "N",
                "source_id": "S1",
            },
        ]
    )

    with ElementCaptureWriter(
        config,
        "labs",
        catalog=load_combined_catalog(config),
    ) as writer:
        writer.add_chunk(rows, source_path=source_path)

    source = pd.read_parquet(
        config.work_dir / "combined_source_lab_measurement.parquet"
    )
    membership = pd.read_parquet(
        config.work_dir / "combined_element_membership_labs.parquet"
    )
    assert len(source) == 3
    assert source["source_record_id"].nunique() == 3
    assert source["timestamp_precision"].tolist() == [
        "date_only",
        "date_only",
        "timestamp",
    ]
    assert source["event_datetime"].notna().all()
    assert source["numeric_value"].tolist() == [55.0, 55.0, 56.0]
    assert set(membership["element_id"]) == {"source.arterial_pco2"}
    assert len(membership) == 3


def test_element_capture_retains_only_rows_with_included_membership(
    tmp_path: Path,
) -> None:
    config = load_config(_write_combined_config(tmp_path))
    concepts = (
        Concept(
            concept_set_id="arterial_pco2",
            domain="lab",
            code_system="LOINC",
            code="EXCLUDED",
            match_type="exact",
            include=False,
            description="Excluded only",
            source_authority="test",
            source_version="1",
            effective_start=None,
            effective_end=None,
            notes="",
            source_file="test.csv",
            source_row=1,
        ),
        Concept(
            concept_set_id="included_measure",
            domain="lab",
            code_system="LOINC",
            code="OVERLAP",
            match_type="exact",
            include=True,
            description="Included",
            source_authority="test",
            source_version="1",
            effective_start=None,
            effective_end=None,
            notes="",
            source_file="test.csv",
            source_row=2,
        ),
        Concept(
            concept_set_id="arterial_pco2",
            domain="lab",
            code_system="LOINC",
            code="OVERLAP",
            match_type="exact",
            include=False,
            description="Overlapping exclusion",
            source_authority="test",
            source_version="1",
            effective_start=None,
            effective_end=None,
            notes="",
            source_file="test.csv",
            source_row=3,
        ),
    )
    catalog = ConceptSetCatalog(
        concepts=concepts,
        phenotype_rules={"required_concept_sets": []},
    )
    rows = pd.DataFrame(
        {
            "patient_id": ["P1", "P2"],
            "encounter_id": ["E1", "E2"],
            "code_system": ["LOINC", "LOINC"],
            "code": ["EXCLUDED", "OVERLAP"],
            "date": ["2022-01-01", "2022-01-02"],
            "lab_result_num_val": ["55", "56"],
            "lab_result_text_val": ["", ""],
            "units_of_measure": ["mm[Hg]", "mm[Hg]"],
        }
    )

    with ElementCaptureWriter(config, "labs", catalog=catalog) as writer:
        writer.add_chunk(
            rows,
            source_path=config.data_dir / "Lab Results/lab_results0001.csv",
        )

    source = pd.read_parquet(
        config.work_dir / "combined_source_lab_measurement.parquet"
    )
    membership = pd.read_parquet(
        config.work_dir / "combined_element_membership_labs.parquet"
    )
    gas_candidates = pd.read_parquet(
        config.work_dir / "combined_gas_candidate_id.parquet"
    )
    assert source["patient_id"].tolist() == ["P2"]
    assert set(membership["element_id"]) == {
        "source.included_measure",
        "source.arterial_pco2",
    }
    assert gas_candidates.empty


def test_combined_build_exports_exact_historical_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = load_config(_write_combined_config(tmp_path))
    isolated_phases: list[str] = []

    def run_phase_locally(
        phase: str,
        target: Callable[..., None],
        args: tuple[object, ...],
        *,
        lock_file_descriptors: tuple[int, ...],
    ) -> None:
        isolated_phases.append(phase)
        _run_isolated_phase_locally(
            phase,
            target,
            args,
            lock_file_descriptors=lock_file_descriptors,
        )

    monkeypatch.setattr(
        combined_builder,
        "_run_isolated_phase_process",
        run_phase_locally,
    )
    real_open_combined_database = combined_database.open_combined_database
    write_session_tables: list[set[str]] = []
    write_session_memory_limits: list[int] = []
    explicit_spill_roots: list[Path] = []

    @contextmanager
    def track_write_session(*args, **kwargs) -> Iterator[duckdb.DuckDBPyConnection]:
        if not kwargs.get("read_only", False):
            write_session_memory_limits.append(int(kwargs["memory_limit_mib"]))
        if kwargs.get("spill_root") is not None:
            explicit_spill_roots.append(Path(kwargs["spill_root"]))
        with real_open_combined_database(*args, **kwargs) as connection:
            yield connection
            if not kwargs.get("read_only", False):
                write_session_tables.append(
                    {
                        str(row[0])
                        for row in connection.execute(
                            "SELECT table_name FROM information_schema.tables "
                            "WHERE table_schema = 'main'"
                        ).fetchall()
                    }
                )

    monkeypatch.setattr(
        combined_database,
        "open_combined_database",
        track_write_session,
    )
    result = build_preprocessed(config, strict=True)

    assert isolated_phases == [
        "pre-final",
        "final-assembly",
        "database-core",
        "database-observability",
        "database-membership",
        "database-finalize",
        "compatibility-export",
        "validation",
    ]
    assert result.database_path.is_file()
    assert result.manifest_path.is_file()
    assert len(result.compatibility_paths) == 36
    assert result.validation.valid
    manifest = json.loads(result.manifest_path.read_text())
    assert manifest["status"] == "complete"
    assert manifest["run_id"] == result.run_id
    assert manifest["schema_version"] == 2
    assert manifest["duckdb_memory_limit_mib"] == 3072
    assert manifest["duckdb_core_memory_limit_mib"] == 2816
    assert manifest["duckdb_threads"] == 1
    assert write_session_memory_limits[:4] == [2816, 3072, 3072, 3072]
    assert "source_observability_event" not in write_session_tables[0]
    assert "element_membership" not in write_session_tables[0]
    assert "source_observability_event" in write_session_tables[1]
    assert "element_membership" not in write_session_tables[1]
    assert "element_membership" in write_session_tables[2]
    assert "rfs_membership" in write_session_tables[2]
    assert "encounter_availability" not in write_session_tables[2]
    assert "encounter_availability" in write_session_tables[3]
    assert "patient_observability" in write_session_tables[3]
    work_manifest = json.loads(
        (config.work_dir / "pipeline_work_manifest.json").read_text()
    )
    assert len(work_manifest["combined_element_catalog_sha256"]) == 64
    require_current_work(config, required_stages=["final_assembly"])

    validation = validate_preprocessed_database(
        result.database_path,
        compatibility_output_dir=config.output_dir,
    )
    assert validation.valid, validation.errors
    status = inspect_combined_database(result.database_path)
    assert status["status"] == "complete"
    assert status["duckdb_memory_limit_mib"] == 3072
    assert status["duckdb_core_memory_limit_mib"] == 2816
    assert status["duckdb_threads"] == 1
    assert status["counts"]["element_catalog"] > len(final_output_columns())

    connection = duckdb.connect(str(result.database_path), read_only=True)
    try:
        runtime = connection.execute(
            """
            SELECT
                duckdb_memory_limit_mib,
                duckdb_core_memory_limit_mib,
                duckdb_threads
            FROM preprocessing_manifest
            """
        ).fetchone()
        assert runtime == (3072, 2816, 1)
        duplicate_observability_keys = connection.execute(
            """
            SELECT count(*)
            FROM (
                SELECT
                    patient_id,
                    logical_domain,
                    event_datetime,
                    timestamp_precision
                FROM source_observability_event
                GROUP BY ALL
                HAVING count(*) > 1
            )
            """
        ).fetchone()[0]
        assert duplicate_observability_keys == 0
    finally:
        connection.close()

    connection = duckdb.connect(str(result.database_path), read_only=True)
    try:
        for output in compatibility_outputs():
            columns = tuple(
                row[1]
                for row in connection.execute(
                    f"PRAGMA table_info('{output.view_name}')"
                ).fetchall()
            )
            assert columns == final_output_columns()
    finally:
        connection.close()

    before = {
        output.key: hash_csv_with_metadata(config.output_dir / output.relative_path)
        for output in compatibility_outputs()
    }
    regenerated_root = tmp_path / "regenerated"
    regenerated_paths = combined_builder._compatibility_export_paths(regenerated_root)
    source_entries_before = {
        path.relative_to(config.output_dir) for path in config.output_dir.rglob("*")
    }
    regenerated = export_legacy_compatibility_outputs(
        result.database_path,
        regenerated_root,
    )
    assert len(regenerated) == 36
    after = {
        output.key: hash_csv_with_metadata(regenerated_root / output.relative_path)
        for output in compatibility_outputs()
    }
    assert before == after
    assert explicit_spill_roots[-2:] == [
        regenerated_paths.staging_output,
        regenerated_paths.staging_output,
    ]
    assert {
        path.relative_to(config.output_dir) for path in config.output_dir.rglob("*")
    } == source_entries_before

    baseline_path = tmp_path / "combined_baseline.json"
    write_evidence(
        baseline_path,
        capture_compatibility_evidence(config.output_dir),
    )
    parity = verify_compatibility_evidence(
        result.database_path,
        config.output_dir,
        baseline_path,
    )
    assert parity["ready"] is True
    completeness = inspect_element_completeness(result.database_path)
    assert completeness["complete"] is True
    assert completeness["historical_element_count"] == len(final_output_columns())
    assert completeness["source_rule_count"] > completeness["source_element_count"]

    tampered_output = compatibility_outputs()[0]
    tampered_path = config.output_dir / tampered_output.relative_path
    with tampered_path.open("a", newline="") as handle:
        csv.writer(handle).writerow(
            ["synthetic-tamper", *([""] * (len(final_output_columns()) - 1))]
        )

    tampered_validation = validate_preprocessed_database(
        result.database_path,
        compatibility_output_dir=config.output_dir,
    )
    assert not tampered_validation.valid
    assert f"Compatibility CSV hash mismatch: {tampered_output.key}" in (
        tampered_validation.errors
    )
    parity = verify_compatibility_evidence(
        result.database_path,
        config.output_dir,
        baseline_path,
    )
    assert parity["ready"] is False
    assert parity["hash_mismatched"] == [tampered_output.key]
    assert parity["row_count_mismatched"] == [tampered_output.key]


@pytest.mark.parametrize("intermediate_format", ["parquet", "csv"])
def test_combined_source_tables_have_stable_typed_schema(
    tmp_path: Path,
    intermediate_format: str,
) -> None:
    config = load_config(
        _write_combined_config(
            tmp_path,
            intermediate_format=intermediate_format,
        )
    )
    result = build_preprocessed(config, strict=True)
    connection = duckdb.connect(str(result.database_path), read_only=True)
    try:
        schema = tuple(
            (str(row[1]), str(row[2]).upper())
            for row in connection.execute(
                "PRAGMA table_info('source_lab_measurement')"
            ).fetchall()
        )
        assert schema == tuple(
            (column, SOURCE_EVENT_DUCKDB_TYPES[column])
            for column in SOURCE_EVENT_COLUMNS
        )
    finally:
        connection.close()


def test_combined_patient_source_preserves_raw_string_values(tmp_path: Path) -> None:
    input_root = _copy_glp1_fixture_for_combined(tmp_path)
    patient_path = input_root / "Patient/patient.csv"
    patients = pd.read_csv(patient_path, dtype="string")
    patients.loc[0, "year_of_birth"] = "0001"
    patients.loc[0, "month_year_death"] = "202001"
    patients["source_id"] = "001"
    patients.to_csv(patient_path, index=False)
    config = load_config(_write_combined_config(tmp_path, data_dir=input_root))

    result = build_preprocessed(config, strict=True)
    connection = duckdb.connect(str(result.database_path), read_only=True)
    try:
        row = connection.execute(
            "SELECT year_of_birth, month_year_death, source_id "
            "FROM source_patient ORDER BY source_row_number LIMIT 1"
        ).fetchone()
    finally:
        connection.close()
    assert row == ("0001", "202001", "001")


def test_combined_source_tables_preserve_literal_na_tokens(tmp_path: Path) -> None:
    input_root = _copy_glp1_fixture_for_combined(tmp_path)
    token_by_source = {
        "Lab Results/lab_results.csv": "NA",
        "Encounter/encounter.csv": "N/A",
        "Patient/patient.csv": "NULL",
        "Vital Signs/vital_signs.csv": "NA",
        "Diagnosis/diagnosis.csv": "N/A",
        "Procedure/procedure.csv": "NULL",
        "Medications/medication.csv": "NA",
    }
    table_by_source = {
        "Lab Results/lab_results.csv": "source_lab_measurement",
        "Encounter/encounter.csv": "source_encounter",
        "Patient/patient.csv": "source_patient",
        "Vital Signs/vital_signs.csv": "source_vital_measurement",
        "Diagnosis/diagnosis.csv": "source_diagnosis",
        "Procedure/procedure.csv": "source_procedure",
        "Medications/medication.csv": "source_medication",
    }
    for relative_path, token in token_by_source.items():
        source_path = input_root / relative_path
        frame = pd.read_csv(
            source_path,
            dtype="string",
            keep_default_na=False,
        )
        frame["source_id"] = token
        frame.to_csv(source_path, index=False)

    config = load_config(_write_combined_config(tmp_path, data_dir=input_root))
    result = build_preprocessed(config, strict=True)
    connection = duckdb.connect(str(result.database_path), read_only=True)
    try:
        for relative_path, table_name in table_by_source.items():
            observed = {
                str(row[0])
                for row in connection.execute(
                    f"SELECT DISTINCT source_id FROM {table_name}"
                ).fetchall()
            }
            assert observed == {token_by_source[relative_path]}, table_name
    finally:
        connection.close()


def test_failed_replacement_preserves_published_product(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = load_config(_write_combined_config(tmp_path))
    monkeypatch.setattr(
        combined_builder,
        "_run_isolated_phase_process",
        _run_isolated_phase_locally,
    )
    first = build_preprocessed(config, strict=True)
    original_database = first.database_path.read_bytes()
    original_hashes = _output_hashes(config.output_dir)
    build_identity = combined_builder._combined_build_identity(config, strict=True)
    paths = combined_builder._combined_build_paths(
        config.output_dir,
        build_identity=build_identity,
    )
    real_validation = combined_builder.validate_preprocessed_database

    monkeypatch.setattr(
        combined_builder,
        "validate_preprocessed_database",
        lambda *args, **kwargs: CombinedValidationResult(
            valid=False,
            errors=("injected failure",),
            warnings=(),
            counts={},
        ),
    )
    with pytest.raises(RuntimeError, match="injected failure"):
        build_preprocessed(config, strict=True, replace_existing=True)

    assert first.database_path.read_bytes() == original_database
    assert _output_hashes(config.output_dir) == original_hashes
    assert paths.staging_output.is_dir()
    assert paths.state_path.is_file()
    interrupted_hash_scratch = (
        paths.staging_output
        / compatibility_outputs()[0].relative_path.parent
        / f"{HASH_SCRATCH_PREFIX}interrupted"
    )
    interrupted_hash_scratch.mkdir()
    (interrupted_hash_scratch / "chunk.csv").write_text(
        "confidential staged hash data\n"
    )
    interrupted_duckdb_spill = (
        paths.staging_output / f"{COMBINED_DUCKDB_SPILL_PREFIX}interrupted"
    )
    interrupted_duckdb_spill.mkdir()
    (interrupted_duckdb_spill / "row-level.tmp").write_text(
        "confidential staged spill data\n"
    )

    monkeypatch.setattr(
        combined_builder,
        "validate_preprocessed_database",
        real_validation,
    )

    def unexpected_rebuild(*args, **kwargs):
        raise AssertionError("late retry rebuilt completed preprocessing work")

    monkeypatch.setattr(
        combined_builder,
        "_run_combined_pipeline_isolated",
        unexpected_rebuild,
    )
    monkeypatch.setattr(
        combined_builder,
        "initialize_combined_database",
        unexpected_rebuild,
    )
    resumed = build_preprocessed(config, strict=True, replace_existing=True)

    assert resumed.validation.valid
    assert not interrupted_hash_scratch.exists()
    assert not interrupted_duckdb_spill.exists()
    assert not paths.staging_output.exists()
    assert not paths.state_path.exists()


def test_failed_database_session_restarts_incomplete_database(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = load_config(_write_combined_config(tmp_path))
    monkeypatch.setattr(
        combined_builder,
        "_run_isolated_phase_process",
        _run_isolated_phase_locally,
    )
    real_initialize = combined_builder.initialize_combined_database
    real_load_memberships = combined_builder.load_combined_memberships
    initialize_calls = 0

    def track_initialize(*args, **kwargs):
        nonlocal initialize_calls
        initialize_calls += 1
        return real_initialize(*args, **kwargs)

    def fail_memberships(*args, **kwargs):
        raise RuntimeError("injected membership failure")

    monkeypatch.setattr(
        combined_builder,
        "initialize_combined_database",
        track_initialize,
    )
    monkeypatch.setattr(
        combined_builder,
        "load_combined_memberships",
        fail_memberships,
    )

    with pytest.raises(RuntimeError, match="injected membership failure"):
        build_preprocessed(config, strict=True)

    build_identity = combined_builder._combined_build_identity(config, strict=True)
    paths = combined_builder._combined_build_paths(
        config.output_dir,
        build_identity=build_identity,
    )
    failed_state = json.loads(paths.state_path.read_text())
    assert failed_state["phase"] == "pipeline"
    assert failed_state["database_progress"] == "observability"
    assert (paths.staging_output / config.combined.database_name).is_file()

    monkeypatch.setattr(
        combined_builder,
        "load_combined_memberships",
        real_load_memberships,
    )
    resumed = build_preprocessed(config, strict=True)

    assert resumed.validation.valid
    assert initialize_calls == 2
    assert not paths.staging_output.exists()
    assert not paths.state_path.exists()


@pytest.mark.parametrize("stale_mode", ["missing-file", "missing-staging"])
def test_stale_pre_database_checkpoint_rebuilds_pipeline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    stale_mode: str,
) -> None:
    config = load_config(_write_combined_config(tmp_path))
    monkeypatch.setattr(
        combined_builder,
        "_run_isolated_phase_process",
        _run_isolated_phase_locally,
    )
    real_pipeline = combined_builder._run_combined_pipeline_isolated
    real_initialize = combined_builder.initialize_combined_database
    pipeline_calls = 0

    def track_pipeline(*args, **kwargs):
        nonlocal pipeline_calls
        pipeline_calls += 1
        return real_pipeline(*args, **kwargs)

    def fail_before_database(*args, **kwargs):
        raise RuntimeError("injected pre-database interruption")

    monkeypatch.setattr(
        combined_builder,
        "_run_combined_pipeline_isolated",
        track_pipeline,
    )
    monkeypatch.setattr(
        combined_builder,
        "initialize_combined_database",
        fail_before_database,
    )

    with pytest.raises(RuntimeError, match="pre-database interruption"):
        build_preprocessed(config, strict=True)

    build_identity = combined_builder._combined_build_identity(config, strict=True)
    paths = combined_builder._combined_build_paths(
        config.output_dir,
        build_identity=build_identity,
    )
    interrupted_state = json.loads(paths.state_path.read_text())
    assert interrupted_state["phase"] == "pipeline"
    if stale_mode == "missing-file":
        stale_output = paths.staging_output / compatibility_outputs()[0].relative_path
        stale_output.unlink()
    else:
        combined_builder.remove_tree_strict(
            paths.staging_output,
            context="Synthetic interrupted staging directory",
        )

    monkeypatch.setattr(
        combined_builder,
        "initialize_combined_database",
        real_initialize,
    )
    resumed = build_preprocessed(config, strict=True)

    assert resumed.validation.valid
    assert pipeline_calls == 2
    assert not paths.staging_output.exists()
    assert not paths.state_path.exists()


def test_export_checkpoint_recovers_after_database_fingerprint_refresh(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = load_config(_write_combined_config(tmp_path))
    monkeypatch.setattr(
        combined_builder,
        "_run_isolated_phase_process",
        _run_isolated_phase_locally,
    )
    real_write_build_state = combined_builder._write_build_state
    real_fsync_checkpoint_inputs = combined_builder._fsync_export_checkpoint_inputs
    fail_final_export_checkpoint = True
    durability_barrier_completed = False

    def track_durability_barrier(*args, **kwargs):
        nonlocal durability_barrier_completed
        real_fsync_checkpoint_inputs(*args, **kwargs)
        durability_barrier_completed = True

    def write_state_with_injected_failure(path, payload):
        nonlocal fail_final_export_checkpoint
        if payload.get("phase") == "pipeline":
            assert durability_barrier_completed
        if "export_progress" in payload:
            assert durability_barrier_completed
        if (
            fail_final_export_checkpoint
            and payload.get("phase") == "compatibility_export"
            and "export_progress" not in payload
        ):
            fail_final_export_checkpoint = False
            raise RuntimeError("injected final export checkpoint failure")
        real_write_build_state(path, payload)

    monkeypatch.setattr(
        combined_builder,
        "_write_build_state",
        write_state_with_injected_failure,
    )
    monkeypatch.setattr(
        combined_builder,
        "_fsync_export_checkpoint_inputs",
        track_durability_barrier,
    )
    with pytest.raises(
        RuntimeError,
        match="injected final export checkpoint failure",
    ):
        build_preprocessed(config, strict=True)

    build_identity = combined_builder._combined_build_identity(config, strict=True)
    paths = combined_builder._combined_build_paths(
        config.output_dir,
        build_identity=build_identity,
    )
    failed_state = json.loads(paths.state_path.read_text())
    assert failed_state["phase"] == "database"
    assert failed_state["export_progress"]["status"] == "database_fingerprint_pending"
    staged_database = paths.staging_output / config.combined.database_name
    database_status = inspect_combined_database(staged_database)
    assert database_status["source_work_manifest_sha256"] == (
        combined_database.current_work_manifest_sha256(config)
    )

    monkeypatch.setattr(
        combined_builder,
        "_write_build_state",
        real_write_build_state,
    )

    def unexpected_export(*args, **kwargs):
        raise AssertionError("prepared compatibility export ran again")

    monkeypatch.setattr(
        combined_builder,
        "export_compatibility_outputs",
        unexpected_export,
    )
    resumed = build_preprocessed(config, strict=True)

    assert resumed.validation.valid
    assert not paths.staging_output.exists()
    assert not paths.state_path.exists()


def _write_synthetic_compatibility_tree(root: Path, value: str) -> tuple[Path, ...]:
    paths = tuple(root / output.relative_path for output in compatibility_outputs())
    for path in paths:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value)
    return paths


def _verify_synthetic_compatibility_tree(
    database_path: Path,
    staging_dir: Path,
    *,
    spill_root: Path,
) -> tuple[Path, ...]:
    del database_path
    assert spill_root == staging_dir
    return tuple(
        staging_dir / output.relative_path for output in compatibility_outputs()
    )


def test_legacy_export_rejects_managed_directory_symlink(
    tmp_path: Path,
) -> None:
    database = tmp_path / "source" / "trinetx_preprocessed.duckdb"
    database.parent.mkdir()
    database.write_bytes(b"synthetic database")
    output_dir = tmp_path / "export"
    output_dir.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (output_dir / "AMBULATORY").symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError, match="unmanaged entries: AMBULATORY"):
        export_legacy_compatibility_outputs(
            database,
            output_dir,
            replace_existing=True,
        )

    assert list(outside.iterdir()) == []


def test_failed_legacy_export_preserves_existing_generation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = tmp_path / "source" / "trinetx_preprocessed.duckdb"
    database.parent.mkdir()
    database.write_bytes(b"synthetic database")
    output_dir = tmp_path / "export"
    existing_paths = _write_synthetic_compatibility_tree(output_dir, "old\n")

    def fail_after_one_file(
        database_path: Path,
        staging_dir: Path,
        *,
        spill_root: Path,
    ) -> list[Path]:
        del database_path
        assert spill_root == staging_dir
        first = staging_dir / compatibility_outputs()[0].relative_path
        first.parent.mkdir(parents=True)
        first.write_text("new\n")
        raise RuntimeError("synthetic export failure")

    monkeypatch.setattr(
        combined_builder,
        "export_compatibility_outputs",
        fail_after_one_file,
    )

    with pytest.raises(RuntimeError, match="synthetic export failure"):
        export_legacy_compatibility_outputs(
            database,
            output_dir,
            replace_existing=True,
        )

    assert all(path.read_text() == "old\n" for path in existing_paths)
    publication_paths = combined_builder._compatibility_export_paths(output_dir)
    assert not publication_paths.staging_output.exists()
    assert not publication_paths.backup_output.exists()
    assert not publication_paths.publication_journal.exists()


def test_legacy_export_recovers_interrupted_hash_scratch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = tmp_path / "source" / "trinetx_preprocessed.duckdb"
    database.parent.mkdir()
    database.write_bytes(b"synthetic database")
    output_dir = tmp_path / "export"
    publication_paths = combined_builder._compatibility_export_paths(output_dir)
    stale_hash_scratch = (
        publication_paths.staging_output / "AMBULATORY" / ".trinetx-hash-interrupted"
    )
    stale_hash_scratch.mkdir(parents=True)
    (stale_hash_scratch / "chunk.csv").write_text("confidential staging data\n")

    def write_new_export(
        database_path: Path,
        staging_dir: Path,
        *,
        spill_root: Path,
    ) -> list[Path]:
        del database_path
        assert spill_root == staging_dir
        assert not stale_hash_scratch.exists()
        return list(_write_synthetic_compatibility_tree(staging_dir, "new\n"))

    monkeypatch.setattr(
        combined_builder,
        "export_compatibility_outputs",
        write_new_export,
    )
    monkeypatch.setattr(
        combined_builder,
        "verify_compatibility_outputs",
        _verify_synthetic_compatibility_tree,
    )

    written = export_legacy_compatibility_outputs(database, output_dir)

    assert len(written) == 36
    assert all(path.read_text() == "new\n" for path in written)
    assert not publication_paths.staging_output.exists()


def test_legacy_export_atomically_replaces_complete_compatibility_tree(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = tmp_path / "source" / "trinetx_preprocessed.duckdb"
    database.parent.mkdir()
    database.write_bytes(b"synthetic database")
    output_dir = tmp_path / "export"
    _write_synthetic_compatibility_tree(output_dir, "old\n")
    publication_paths = combined_builder._compatibility_export_paths(output_dir)
    publication_paths.state_path.write_text("user-owned sentinel\n")

    def write_new_export(
        database_path: Path,
        staging_dir: Path,
        *,
        spill_root: Path,
    ) -> list[Path]:
        del database_path
        assert spill_root == staging_dir
        return list(_write_synthetic_compatibility_tree(staging_dir, "new\n"))

    monkeypatch.setattr(
        combined_builder,
        "export_compatibility_outputs",
        write_new_export,
    )
    monkeypatch.setattr(
        combined_builder,
        "verify_compatibility_outputs",
        _verify_synthetic_compatibility_tree,
    )

    written = export_legacy_compatibility_outputs(
        database,
        output_dir,
        replace_existing=True,
    )

    assert len(written) == 36
    assert all(path.read_text() == "new\n" for path in written)
    assert not publication_paths.staging_output.exists()
    assert not publication_paths.backup_output.exists()
    assert not publication_paths.publication_journal.exists()
    assert publication_paths.state_path.read_text() == "user-owned sentinel\n"


def test_legacy_export_publication_failure_rolls_back_existing_tree(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = tmp_path / "source" / "trinetx_preprocessed.duckdb"
    database.parent.mkdir()
    database.write_bytes(b"synthetic database")
    output_dir = tmp_path / "export"
    existing_paths = _write_synthetic_compatibility_tree(output_dir, "old\n")
    publication_paths = combined_builder._compatibility_export_paths(output_dir)

    def write_new_export(
        database_path: Path,
        staging_dir: Path,
        *,
        spill_root: Path,
    ) -> list[Path]:
        del database_path
        assert spill_root == staging_dir
        return list(_write_synthetic_compatibility_tree(staging_dir, "new\n"))

    monkeypatch.setattr(
        combined_builder,
        "export_compatibility_outputs",
        write_new_export,
    )
    monkeypatch.setattr(
        combined_builder,
        "verify_compatibility_outputs",
        _verify_synthetic_compatibility_tree,
    )
    real_replace = combined_builder.os.replace

    def fail_staging_publish(source: Path, destination: Path) -> None:
        if (
            Path(source) == publication_paths.staging_output
            and Path(destination) == output_dir
        ):
            raise OSError("synthetic publication failure")
        real_replace(source, destination)

    monkeypatch.setattr(combined_builder.os, "replace", fail_staging_publish)

    with pytest.raises(OSError, match="synthetic publication failure"):
        export_legacy_compatibility_outputs(
            database,
            output_dir,
            replace_existing=True,
        )

    assert all(path.read_text() == "old\n" for path in existing_paths)
    assert not publication_paths.staging_output.exists()
    assert not publication_paths.backup_output.exists()
    assert not publication_paths.publication_journal.exists()


def test_legacy_export_rejects_late_unmanaged_destination_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = tmp_path / "source" / "trinetx_preprocessed.duckdb"
    database.parent.mkdir()
    database.write_bytes(b"synthetic database")
    output_dir = tmp_path / "export"
    existing_paths = _write_synthetic_compatibility_tree(output_dir, "old\n")
    publication_paths = combined_builder._compatibility_export_paths(output_dir)
    late_file = output_dir / "notes.txt"

    def write_new_export(
        database_path: Path,
        staging_dir: Path,
        *,
        spill_root: Path,
    ) -> list[Path]:
        del database_path
        assert spill_root == staging_dir
        late_file.write_text("user-owned late file\n")
        return list(_write_synthetic_compatibility_tree(staging_dir, "new\n"))

    monkeypatch.setattr(
        combined_builder,
        "export_compatibility_outputs",
        write_new_export,
    )
    monkeypatch.setattr(
        combined_builder,
        "verify_compatibility_outputs",
        _verify_synthetic_compatibility_tree,
    )

    with pytest.raises(ValueError, match="unmanaged entries: notes.txt"):
        export_legacy_compatibility_outputs(
            database,
            output_dir,
            replace_existing=True,
        )

    assert all(path.read_text() == "old\n" for path in existing_paths)
    assert late_file.read_text() == "user-owned late file\n"
    assert not publication_paths.staging_output.exists()
    assert not publication_paths.backup_output.exists()
    assert not publication_paths.publication_journal.exists()


def test_legacy_export_requires_explicit_replacement(
    tmp_path: Path,
) -> None:
    database = tmp_path / "source" / "trinetx_preprocessed.duckdb"
    database.parent.mkdir()
    database.write_bytes(b"synthetic database")
    output_dir = tmp_path / "export"
    existing_paths = _write_synthetic_compatibility_tree(output_dir, "old\n")

    with pytest.raises(FileExistsError, match="use --replace"):
        export_legacy_compatibility_outputs(database, output_dir)

    assert all(path.read_text() == "old\n" for path in existing_paths)


def test_legacy_export_rejects_in_place_canonical_product_mutation(
    tmp_path: Path,
) -> None:
    product_dir = tmp_path / "product"
    product_dir.mkdir()
    database = product_dir / "trinetx_preprocessed.duckdb"
    database.write_bytes(b"synthetic database")

    with pytest.raises(ValueError, match="separate destination"):
        export_legacy_compatibility_outputs(
            database,
            product_dir,
            replace_existing=True,
        )

    assert database.read_bytes() == b"synthetic database"


def test_legacy_export_rejects_destination_nested_in_canonical_product(
    tmp_path: Path,
) -> None:
    product_dir = tmp_path / "product"
    product_dir.mkdir()
    database = product_dir / "trinetx_preprocessed.duckdb"
    database.write_bytes(b"synthetic database")

    with pytest.raises(ValueError, match="separate destination"):
        export_legacy_compatibility_outputs(
            database,
            product_dir / "compatibility-export",
        )

    assert not (product_dir / "compatibility-export").exists()


def test_legacy_export_rejects_case_alias_inside_canonical_product(
    tmp_path: Path,
) -> None:
    product_dir = tmp_path / "Product"
    product_dir.mkdir()
    alias = tmp_path / "product"
    if not alias.exists() or not alias.samefile(product_dir):
        pytest.skip("requires a case-insensitive filesystem")
    database = product_dir / "trinetx_preprocessed.duckdb"
    database.write_bytes(b"synthetic database")

    with pytest.raises(ValueError, match="separate destination"):
        export_legacy_compatibility_outputs(
            database,
            alias / "compatibility-export",
        )

    assert not (product_dir / "compatibility-export").exists()


def test_export_checkpoint_durability_barrier_fsyncs_files_and_directories(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_dir = tmp_path / "staging"
    compatibility_paths = tuple(
        output_dir / output.relative_path for output in compatibility_outputs()
    )
    for path in compatibility_paths:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("synthetic\n")
    work_manifest = tmp_path / "work" / "pipeline_work_manifest.json"
    work_manifest.parent.mkdir()
    work_manifest.write_text("{}\n")

    synced_files: list[Path] = []
    synced_directories: list[Path] = []
    real_fsync_file = combined_builder._fsync_file_strict
    real_fsync_directory = combined_builder._fsync_directory_strict

    def track_file(path: Path) -> None:
        synced_files.append(path)
        real_fsync_file(path)

    def track_directory(path: Path) -> None:
        synced_directories.append(path)
        real_fsync_directory(path)

    monkeypatch.setattr(combined_builder, "_fsync_file_strict", track_file)
    monkeypatch.setattr(
        combined_builder,
        "_fsync_directory_strict",
        track_directory,
    )

    combined_builder._fsync_export_checkpoint_inputs(
        output_dir,
        work_manifest=work_manifest,
    )

    assert set(synced_files) == {*compatibility_paths, work_manifest}
    expected_directories = {
        output_dir,
        work_manifest.parent,
        *(path.parent for path in compatibility_paths),
    }
    assert set(synced_directories) == expected_directories
    for compatibility_directory in {path.parent for path in compatibility_paths}:
        assert synced_directories.index(compatibility_directory) < (
            synced_directories.index(output_dir)
        )


@pytest.mark.parametrize("relative_path", ["notes.txt", "AMBULATORY/notes.txt"])
def test_replacement_rejects_unmanaged_output_entries(
    tmp_path: Path,
    relative_path: str,
) -> None:
    config = load_config(_write_combined_config(tmp_path))
    unmanaged = config.output_dir / relative_path
    unmanaged.parent.mkdir(parents=True, exist_ok=True)
    unmanaged.write_text("not part of the combined product")

    with pytest.raises(ValueError, match=f"unmanaged entries: {relative_path}"):
        build_preprocessed(config, strict=True, replace_existing=True)

    assert unmanaged.read_text() == "not part of the combined product"


def test_replacement_rejects_nested_output_symlinks(tmp_path: Path) -> None:
    config = load_config(_write_combined_config(tmp_path))
    managed_directory = config.output_dir / "AMBULATORY"
    managed_directory.mkdir()
    target = tmp_path / "outside.txt"
    target.write_text("outside")
    (managed_directory / "linked.csv").symlink_to(target)

    with pytest.raises(ValueError, match="unmanaged entries"):
        build_preprocessed(config, strict=True, replace_existing=True)

    assert target.read_text() == "outside"


def test_publication_removes_appledouble_sidecars(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = load_config(_write_combined_config(tmp_path))
    monkeypatch.setattr(
        combined_builder,
        "_run_isolated_phase_process",
        _run_isolated_phase_locally,
    )
    real_write_manifest = combined_builder.write_combined_manifest

    def write_manifest_with_sidecar(*args, **kwargs):
        manifest_path = real_write_manifest(*args, **kwargs)
        (manifest_path.parent / "._confidential.csv").write_bytes(b"metadata")
        return manifest_path

    monkeypatch.setattr(
        combined_builder,
        "write_combined_manifest",
        write_manifest_with_sidecar,
    )

    build_preprocessed(config, strict=True)

    assert not list(config.output_dir.rglob("._*"))


def test_publish_rename_failure_rolls_back_existing_product(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = load_config(_write_combined_config(tmp_path))
    build_preprocessed(config, strict=True)
    original_hashes = _output_hashes(config.output_dir)
    paths = combined_builder._combined_build_paths(
        config.output_dir,
        build_identity=combined_builder._combined_build_identity(
            config,
            strict=True,
        ),
    )
    real_replace = combined_builder.os.replace

    def fail_staging_publish(source: Path, destination: Path) -> None:
        if (
            Path(source) == paths.staging_output
            and Path(destination) == config.output_dir
        ):
            raise OSError("injected publication failure")
        real_replace(source, destination)

    monkeypatch.setattr(combined_builder.os, "replace", fail_staging_publish)
    with pytest.raises(OSError, match="injected publication failure"):
        build_preprocessed(config, strict=True, replace_existing=True)

    assert _output_hashes(config.output_dir) == original_hashes
    assert paths.staging_output.is_dir()
    assert paths.state_path.is_file()
    assert not paths.backup_output.exists()
    assert not paths.publication_journal.exists()


def test_combined_build_lock_rejects_overlapping_builds(tmp_path: Path) -> None:
    config = load_config(_write_combined_config(tmp_path))

    with combined_builder._canonical_build_lock(config):
        with pytest.raises(RuntimeError, match="holds the canonical"):
            build_preprocessed(config, strict=True)


def test_publication_journal_recovers_old_product_after_interruption(
    tmp_path: Path,
) -> None:
    config = load_config(_write_combined_config(tmp_path))
    result = build_preprocessed(config, strict=True)
    original_database = result.database_path.read_bytes()
    original_hashes = _output_hashes(config.output_dir)
    paths = combined_builder._combined_build_paths(
        config.output_dir,
        build_identity=combined_builder._combined_build_identity(
            config,
            strict=True,
        ),
    )
    assert paths.staging_output.name.startswith(COMBINED_BUILD_PREFIX)
    paths.staging_output.mkdir()
    paths.state_path.write_text("{}\n")
    os.replace(config.output_dir, paths.backup_output)
    combined_builder._write_publication_journal(
        paths.publication_journal,
        {
            "schema_version": 1,
            "state": "old_moved",
            "had_existing": True,
            "published_output": str(config.output_dir),
            "staging_output": str(paths.staging_output),
            "backup_output": str(paths.backup_output),
            "build_state_path": str(paths.state_path),
        },
    )

    combined_builder._recover_interrupted_publication(
        config.output_dir,
        publication_journal=paths.publication_journal,
        backup_output=paths.backup_output,
        database_name=config.combined.database_name,
    )

    assert result.database_path.read_bytes() == original_database
    assert _output_hashes(config.output_dir) == original_hashes
    assert paths.staging_output.is_dir()
    assert paths.state_path.is_file()
    assert not paths.backup_output.exists()
    assert not paths.publication_journal.exists()


def test_compatibility_publication_recovers_old_tree_without_touching_state(
    tmp_path: Path,
) -> None:
    output_dir = tmp_path / "compatibility"
    original_paths = _write_synthetic_compatibility_tree(output_dir, "old\n")
    paths = combined_builder._compatibility_export_paths(output_dir)
    _write_synthetic_compatibility_tree(paths.staging_output, "new\n")
    paths.state_path.write_text("user-owned sentinel\n")
    os.replace(output_dir, paths.backup_output)
    combined_builder._write_publication_journal(
        paths.publication_journal,
        {
            "schema_version": 1,
            "state": "old_moved",
            "had_existing": True,
            "published_output": str(output_dir),
            "staging_output": str(paths.staging_output),
            "backup_output": str(paths.backup_output),
        },
    )

    combined_builder._recover_interrupted_publication(
        output_dir,
        publication_journal=paths.publication_journal,
        backup_output=paths.backup_output,
        database_name="trinetx_preprocessed.duckdb",
        compatibility_only=True,
    )

    assert all(path.read_text() == "old\n" for path in original_paths)
    assert paths.staging_output.is_dir()
    assert paths.state_path.read_text() == "user-owned sentinel\n"
    assert not paths.backup_output.exists()
    assert not paths.publication_journal.exists()


def test_compatibility_publication_recovers_through_case_alias(
    tmp_path: Path,
) -> None:
    canonical_parent = tmp_path / "Parent"
    canonical_parent.mkdir()
    alias_parent = tmp_path / "parent"
    if not alias_parent.exists() or not alias_parent.samefile(canonical_parent):
        pytest.skip("requires a case-insensitive filesystem")
    output_dir = canonical_parent / "Export"
    alias_output = alias_parent / "export"
    original_paths = _write_synthetic_compatibility_tree(output_dir, "old\n")
    paths = combined_builder._compatibility_export_paths(output_dir)
    _write_synthetic_compatibility_tree(paths.staging_output, "new\n")
    os.replace(output_dir, paths.backup_output)
    alias_staging = alias_parent / paths.staging_output.name
    alias_backup = alias_parent / paths.backup_output.name
    combined_builder._write_publication_journal(
        paths.publication_journal,
        {
            "schema_version": 1,
            "state": "old_moved",
            "had_existing": True,
            "published_output": str(alias_output),
            "staging_output": str(alias_staging),
            "backup_output": str(alias_backup),
        },
    )

    combined_builder._recover_interrupted_publication(
        output_dir,
        publication_journal=paths.publication_journal,
        backup_output=paths.backup_output,
        database_name="trinetx_preprocessed.duckdb",
        compatibility_only=True,
    )

    assert all(path.read_text() == "old\n" for path in original_paths)
    assert paths.staging_output.is_dir()
    assert not paths.backup_output.exists()
    assert not paths.publication_journal.exists()


def test_synthetic_example_is_rerunnable(tmp_path: Path) -> None:
    output_root = tmp_path / "synthetic-example"
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(REPOSITORY_ROOT / "src")
    command = [
        sys.executable,
        str(REPOSITORY_ROOT / "scripts/run_synthetic_example.py"),
        "--output-root",
        str(output_root),
    ]

    for _ in range(2):
        completed = subprocess.run(
            command,
            cwd=REPOSITORY_ROOT,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
        assert completed.returncode == 0, completed.stderr

    assert (output_root / "output/trinetx_preprocessed.duckdb").is_file()
    assert len(list((output_root / "output").rglob("RFS_*_ENC_*.csv"))) == 36


@pytest.mark.parametrize(
    "relative_path",
    [
        "private/combined_source_lab_measurement.csv",
        "private/combined_element_membership_labs.csv",
        "private/combined_observability_labs.csv",
        "private/combined_gas_candidate_id.csv",
        "private/combined_encounter_flow.csv",
    ],
)
def test_confidential_combined_csv_intermediates_are_ignored(
    relative_path: str,
) -> None:
    completed = subprocess.run(
        ["git", "check-ignore", relative_path],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, relative_path


def _output_hashes(output_dir: Path) -> dict[str, object]:
    return {
        output.key: hash_csv_with_metadata(output_dir / output.relative_path)
        for output in compatibility_outputs()
    }


def test_combined_validation_fails_when_manifest_is_incomplete(tmp_path: Path) -> None:
    config = load_config(_write_combined_config(tmp_path))
    result = build_preprocessed(config, strict=True)
    connection = duckdb.connect(str(result.database_path))
    try:
        connection.execute("UPDATE preprocessing_manifest SET status = 'building'")
    finally:
        connection.close()

    validation = validate_preprocessed_database(result.database_path)
    assert not validation.valid
    assert any("status is not complete" in error for error in validation.errors)

    export_dir = tmp_path / "incomplete-export"
    with pytest.raises(ValueError, match="status is not complete"):
        export_legacy_compatibility_outputs(result.database_path, export_dir)
    export_paths = combined_builder._compatibility_export_paths(export_dir)
    assert not export_dir.exists()
    assert not export_paths.staging_output.exists()
    assert not export_paths.publication_journal.exists()


def test_compatibility_manifest_duplicate_key_fails_all_gates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = load_config(_write_combined_config(tmp_path))
    result = build_preprocessed(config, strict=True)
    connection = duckdb.connect(str(result.database_path))
    try:
        connection.execute(
            "INSERT INTO compatibility_output_manifest "
            "SELECT * FROM compatibility_output_manifest LIMIT 1"
        )
        connection.execute("CHECKPOINT")
    finally:
        connection.close()

    monkeypatch.setattr(
        combined_database,
        "hash_csv_with_metadata",
        lambda *args, **kwargs: pytest.fail(
            "duplicate manifest must fail before output hashing"
        ),
    )
    with pytest.raises(ValueError, match="exactly 36 outputs"):
        combined_database.verify_compatibility_outputs(
            result.database_path,
            config.output_dir,
        )

    validation = validate_preprocessed_database(result.database_path)
    assert not validation.valid
    assert (
        "compatibility_output_manifest does not contain exactly 36 outputs."
        in validation.errors
    )


def test_combined_validation_requires_and_reconciles_product_sidecar(
    tmp_path: Path,
) -> None:
    config = load_config(_write_combined_config(tmp_path))
    result = build_preprocessed(config, strict=True)
    sidecar_path = result.manifest_path
    sidecar = json.loads(sidecar_path.read_text())

    sidecar_path.unlink()
    missing = validate_preprocessed_database(result.database_path)
    assert not missing.valid
    assert any(
        error.startswith("Missing combined product sidecar:")
        for error in missing.errors
    )

    sidecar["counts"]["source_encounter"] += 1
    sidecar_path.write_text(json.dumps(sidecar))
    mismatched = validate_preprocessed_database(result.database_path)
    assert not mismatched.valid
    assert (
        "Combined product sidecar counts do not match the database tables."
        in mismatched.errors
    )


def test_combined_validation_rejects_exclude_only_source_elements(
    tmp_path: Path,
) -> None:
    config = load_config(_write_combined_config(tmp_path))
    result = build_preprocessed(config, strict=True)
    connection = duckdb.connect(str(result.database_path))
    try:
        element_id = str(
            connection.execute(
                """
                SELECT catalog.element_id
                FROM element_catalog AS catalog
                JOIN element_rule AS rule USING (element_id)
                WHERE catalog.element_kind = 'source_concept'
                  AND rule.include
                ORDER BY catalog.element_id
                LIMIT 1
                """
            ).fetchone()[0]
        )
        connection.execute(
            "UPDATE element_rule SET include = false WHERE element_id = ?",
            [element_id],
        )
        connection.execute("CHECKPOINT")
    finally:
        connection.close()

    validation = validate_preprocessed_database(result.database_path)
    assert not validation.valid
    assert any(
        "source elements without an included rule" in error
        for error in validation.errors
    )
    completeness = inspect_element_completeness(result.database_path)
    assert completeness["complete"] is False
    assert element_id in completeness["elements_without_included_rules"]


def test_element_completeness_bounds_distinct_membership_counts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "membership.duckdb"
    cleanup_contexts: list[str] = []
    real_remove_tree = combined_evidence.remove_tree_strict

    def record_cleanup(path: Path, *, context: str) -> None:
        cleanup_contexts.append(context)
        real_remove_tree(path, context=context)

    monkeypatch.setattr(
        combined_evidence,
        "_DIRECT_ELEMENT_MEMBERSHIP_MAX_ROWS",
        0,
    )
    monkeypatch.setattr(combined_evidence, "_ELEMENT_MEMBERSHIP_BUCKET_COUNT", 2)
    monkeypatch.setattr(combined_evidence, "remove_tree_strict", record_cleanup)

    with open_combined_database(database_path) as connection:
        connection.execute(
            "CREATE TABLE element_membership "
            "(element_id VARCHAR, source_record_id VARCHAR)"
        )
        connection.executemany(
            "INSERT INTO element_membership VALUES (?, ?)",
            [
                ("element-a", "source-1"),
                ("element-a", "source-1"),
                ("element-a", "source-2"),
                ("element-b", "source-1"),
                ("element-b", None),
            ],
        )
        counts = combined_evidence._count_distinct_membership_sources(
            connection,
            membership_row_count=5,
        )

    assert counts == {"element-a": 2, "element-b": 1}
    assert cleanup_contexts == ["Combined element-completeness scratch"]


def test_combined_validation_checks_source_integrity_by_domain(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_root = _copy_glp1_fixture_for_combined(tmp_path)
    config = load_config(_write_combined_config(tmp_path, data_dir=input_root))
    result = build_preprocessed(config, strict=True)
    connection = duckdb.connect(str(result.database_path))
    try:
        procedure_source_ids = [
            str(row[0])
            for row in connection.execute(
                "SELECT source_record_id FROM source_procedure "
                "ORDER BY source_record_id LIMIT 2"
            ).fetchall()
        ]
        assert len(procedure_source_ids) == 2
        wrong_domain_source_id = "synthetic-wrong-domain-source"
        historical_element_id = str(
            connection.execute(
                "SELECT element_id FROM element_catalog "
                "WHERE element_kind = 'historical_derived' "
                "ORDER BY element_id LIMIT 1"
            ).fetchone()[0]
        )
        wrong_domain_element_id = str(
            connection.execute(
                "SELECT element_id FROM element_catalog "
                "WHERE element_kind = 'source_concept' AND domain = 'lab' "
                "ORDER BY element_id LIMIT 1"
            ).fetchone()[0]
        )
        connection.execute(
            "UPDATE element_membership SET include = false "
            "WHERE source_record_id = ? AND logical_domain = 'procedure'",
            [procedure_source_ids[0]],
        )
        connection.execute(
            "UPDATE element_membership SET element_id = ? "
            "WHERE source_record_id = ? AND logical_domain = 'procedure'",
            [historical_element_id, procedure_source_ids[1]],
        )
        connection.execute(
            "INSERT INTO source_procedure "
            "SELECT * REPLACE (? AS source_record_id) "
            "FROM source_procedure LIMIT 1",
            [wrong_domain_source_id],
        )
        connection.execute(
            "INSERT INTO element_membership VALUES (?, ?, 'procedure', true, "
            "'exact', 'LOINC', 'synthetic')",
            [wrong_domain_source_id, wrong_domain_element_id],
        )
        connection.execute(
            """
            INSERT INTO element_membership
            SELECT
                'missing.csv#1', element_id, 'labs', true,
                'exact', 'LOINC', 'synthetic'
            FROM element_catalog
            WHERE domain = 'lab'
            LIMIT 1
            """
        )
        connection.execute(
            "INSERT INTO source_lab_measurement "
            "SELECT * FROM source_lab_measurement LIMIT 1"
        )
        connection.execute(
            "UPDATE source_vital_measurement SET logical_domain = 'diagnosis' "
            "WHERE source_record_id = ("
            "SELECT source_record_id FROM source_vital_measurement LIMIT 1)"
        )
    finally:
        connection.close()

    cleanup_contexts: list[str] = []
    real_remove_tree = combined_validation.remove_tree_strict

    def record_cleanup(path: Path, *, context: str) -> None:
        cleanup_contexts.append(context)
        real_remove_tree(path, context=context)

    monkeypatch.setattr(
        combined_validation,
        "_DIRECT_DUPLICATE_SOURCE_MAX_ROWS",
        0,
    )
    monkeypatch.setattr(combined_validation, "remove_tree_strict", record_cleanup)
    validation = validate_preprocessed_database(result.database_path)

    assert not validation.valid
    assert "element_membership contains 1 orphan rows." in validation.errors
    membership_error = (
        "source_procedure contains 3 retained rows without an included "
        "source-concept membership."
    )
    assert membership_error in validation.errors
    corrupted_source_ids = [*procedure_source_ids, wrong_domain_source_id]
    assert not any(
        source_record_id in error
        for source_record_id in corrupted_source_ids
        for error in validation.errors
    )
    assert "Source tables contain 1 duplicate record IDs." in validation.errors
    assert (
        "Source tables contain 1 rows assigned to the wrong logical domain."
        in validation.errors
    )
    assert "Combined labs duplicate-source scratch" in cleanup_contexts
    assert "Combined duplicate-source validation scratch" in cleanup_contexts


@pytest.mark.parametrize("intermediate_format", ["parquet", "csv"])
def test_glp1_source_adapter_matches_direct_synthetic_ingestion(
    tmp_path: Path,
    intermediate_format: str,
) -> None:
    input_root = _copy_glp1_fixture_for_combined(tmp_path)
    _append_pre2022_non_gas_encounter(input_root)
    config = load_config(
        _write_combined_config(
            tmp_path,
            data_dir=input_root,
            intermediate_format=intermediate_format,
        )
    )
    combined = build_preprocessed(config, strict=True)
    combined_connection = duckdb.connect(
        str(combined.database_path),
        read_only=True,
    )
    try:
        assert (
            combined_connection.execute(
                "SELECT count(*) FROM source_encounter "
                "WHERE encounter_id = 'flow-only-encounter'"
            ).fetchone()[0]
            == 0
        )
        assert (
            combined_connection.execute(
                "SELECT count(*) FROM source_encounter_flow "
                "WHERE encounter_id = 'flow-only-encounter'"
            ).fetchone()[0]
            == 1
        )
        assert combined_connection.execute(
            "SELECT start_datetime FROM source_encounter_flow "
            "WHERE encounter_id = 'unused-invalid-encounter'"
        ).fetchone() == (None,)
    finally:
        combined_connection.close()
    glp1_config = load_glp1_config(REPOSITORY_ROOT / "config/glp1_eligibility.yml")
    catalog = load_concept_sets(glp1_config.concept_sets_dir)
    report = validate_export(config.data_dir)
    assert report.valid, report.errors
    inventory = build_input_inventory(config.data_dir, report, catalog=catalog)

    direct_path = tmp_path / "direct.duckdb"
    direct = initialize_database(
        direct_path,
        run_id="direct-test",
        input_root=config.data_dir,
        config=glp1_config,
        inventory=inventory,
        catalog=catalog,
        git_sha="test",
        concept_catalog_sha256=catalog.sha256,
    )
    try:
        direct_counts = ingest_core_sources(
            direct,
            input_root=config.data_dir,
            inventory=inventory,
            config=glp1_config,
        )
    finally:
        direct.close()

    adapted_path = tmp_path / "adapted.duckdb"
    adapted = initialize_database(
        adapted_path,
        run_id="direct-test",
        input_root=config.data_dir,
        config=glp1_config,
        inventory=inventory,
        catalog=catalog,
        git_sha="test",
        concept_catalog_sha256=catalog.sha256,
    )
    try:
        adapted_counts = materialize_glp1_sources_from_preprocessed(
            adapted,
            combined.database_path,
            config=glp1_config,
        )
    finally:
        adapted.close()

    assert adapted_counts == {table: direct_counts[table] for table in adapted_counts}
    direct = duckdb.connect(str(direct_path), read_only=True)
    adapted = duckdb.connect(str(adapted_path), read_only=True)
    try:
        direct_flow = direct.execute(
            "SELECT * FROM source_cohort_flow_base ORDER BY stage_order"
        ).fetchall()
        adapted_flow = adapted.execute(
            "SELECT * FROM source_cohort_flow_base ORDER BY stage_order"
        ).fetchall()
        assert adapted_flow == direct_flow
        columns_by_table = {
            "source_lab_measurement": (
                "patient_id",
                "encounter_id",
                "date",
                "code_system",
                "code",
                "lab_result_num_val",
                "units_of_measure",
            ),
            "source_encounter": (
                "patient_id",
                "encounter_id",
                "start_date",
                "end_date",
                "type",
            ),
            "source_patient": (
                "patient_id",
                "sex",
                "race",
                "ethnicity",
                "year_of_birth",
            ),
            "source_vital_measurement": (
                "patient_id",
                "encounter_id",
                "date",
                "code_system",
                "code",
                "value",
                "units_of_measure",
            ),
            "source_diagnosis": (
                "patient_id",
                "encounter_id",
                "date",
                "code_system",
                "code",
            ),
            "source_procedure": (
                "patient_id",
                "encounter_id",
                "date",
                "code_system",
                "code",
            ),
            "source_medication": (
                "patient_id",
                "encounter_id",
                "start_date",
                "code_system",
                "code",
            ),
        }
        for table, columns in columns_by_table.items():
            projection = ", ".join(columns)
            direct_rows = direct.execute(
                f"SELECT {projection} FROM {table} ORDER BY ALL"
            ).fetchall()
            adapted_rows = adapted.execute(
                f"SELECT {projection} FROM {table} ORDER BY ALL"
            ).fetchall()
            assert adapted_rows == direct_rows, table
    finally:
        direct.close()
        adapted.close()

    direct = duckdb.connect(str(direct_path))
    adapted = duckdb.connect(str(adapted_path))
    try:
        build_core_cohort(
            direct,
            config=glp1_config,
            run_id="direct-test",
            git_sha="test",
        )
        build_raw_observability_summaries(
            direct,
            input_root=config.data_dir,
            inventory=inventory,
        )
        build_eligibility_phenotypes(direct, glp1_config)
        build_cohort_flow(direct, glp1_config)

        build_core_cohort(
            adapted,
            config=glp1_config,
            run_id="direct-test",
            git_sha="test",
        )
        materialize_glp1_observability_from_preprocessed(
            adapted,
            combined.database_path,
        )
        build_eligibility_phenotypes(adapted, glp1_config)
        build_cohort_flow(adapted, glp1_config)

        for table in (
            "analysis_glp1_eligibility",
            "cohort_flow",
            "eligibility_evidence_long",
        ):
            direct_rows = direct.execute(
                f"SELECT * FROM {table} ORDER BY ALL"
            ).fetchall()
            adapted_rows = adapted.execute(
                f"SELECT * FROM {table} ORDER BY ALL"
            ).fetchall()
            assert adapted_rows == direct_rows, table
    finally:
        direct.close()
        adapted.close()


def test_glp1_adapter_rejects_mismatched_element_catalog(tmp_path: Path) -> None:
    config = load_config(_write_combined_config(tmp_path))
    combined = build_preprocessed(config, strict=True)
    connection = duckdb.connect(str(combined.database_path))
    try:
        connection.execute(
            "UPDATE preprocessing_manifest SET element_catalog_sha256 = ?",
            ["0" * 64],
        )
        connection.execute("CHECKPOINT")
    finally:
        connection.close()

    target = duckdb.connect()
    try:
        glp1_config = load_glp1_config(REPOSITORY_ROOT / "config/glp1_eligibility.yml")
        with pytest.raises(ValueError, match="concept catalog does not match"):
            materialize_glp1_sources_from_preprocessed(
                target,
                combined.database_path,
                config=glp1_config,
            )
    finally:
        target.close()


def test_glp1_observability_filtered_counts_are_zero_not_null(
    tmp_path: Path,
) -> None:
    preprocessed_path = tmp_path / "preprocessed.duckdb"
    preprocessed = duckdb.connect(str(preprocessed_path))
    try:
        preprocessed.execute(
            """
            CREATE TABLE source_observability_event (
                patient_id VARCHAR,
                logical_domain VARCHAR,
                event_datetime TIMESTAMP,
                timestamp_precision VARCHAR,
                event_count UBIGINT
            )
            """
        )
        preprocessed.execute(
            """
            INSERT INTO source_observability_event
            VALUES ('patient-1', 'diagnosis', TIMESTAMP '2020-01-01',
                    'timestamp', 2)
            """
        )
        preprocessed.execute("CHECKPOINT")
    finally:
        preprocessed.close()

    target = duckdb.connect()
    try:
        target.execute(
            """
            CREATE TABLE analysis_glp1_eligibility (
                index_event_id VARCHAR,
                patient_id VARCHAR,
                index_date TIMESTAMP
            )
            """
        )
        target.execute(
            """
            INSERT INTO analysis_glp1_eligibility
            VALUES ('index-1', 'patient-1', TIMESTAMP '2025-01-01')
            """
        )
        materialize_glp1_observability_from_preprocessed(
            target,
            preprocessed_path,
        )
        assert (
            target.execute(
                "SELECT event_count FROM raw_diagnosis_observability"
            ).fetchone()[0]
            == 0
        )
    finally:
        target.close()

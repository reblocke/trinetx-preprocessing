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
import trinetx_preprocessing.combined_preprocessing.validation as combined_validation
from trinetx_preprocessing.combined_preprocessing.builder import (
    build_preprocessed,
    require_safe_output_location,
)
from trinetx_preprocessing.combined_preprocessing.contract import (
    compatibility_outputs,
    final_output_columns,
)
from trinetx_preprocessing.combined_preprocessing.database import (
    _combined_run_id,
    _create_availability_tables,
    export_compatibility_outputs,
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
)
from trinetx_preprocessing.combined_preprocessing.validation import (
    CombinedValidationResult,
    validate_preprocessed_database,
)
from trinetx_preprocessing.config import CombinedPreprocessingConfig, load_config
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
from trinetx_preprocessing.regression import CsvHashResult, hash_csv_with_metadata
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


def test_combined_resumable_identity_includes_duckdb_memory_limit(
    tmp_path: Path,
) -> None:
    config = load_config(_write_combined_config(tmp_path))
    changed = replace(
        config,
        combined=replace(
            config.combined,
            duckdb_memory_limit_mib=config.combined.duckdb_memory_limit_mib + 1,
        ),
    )

    assert combined_builder._combined_build_identity(
        config,
        strict=False,
    ) != combined_builder._combined_build_identity(
        changed,
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
    encounter = {column: "" for column in encounters.columns}
    encounter.update(
        {
            "encounter_id": "flow-only-encounter",
            "patient_id": "flow-only-patient",
            "start_date": "2020-01-01",
            "end_date": "2020-01-02",
            "type": "EMER",
            "derived_by_TriNetX": "N",
        }
    )
    pd.concat([encounters, pd.DataFrame([encounter])], ignore_index=True).to_csv(
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

    @contextmanager
    def track_write_session(*args, **kwargs) -> Iterator[duckdb.DuckDBPyConnection]:
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
    assert manifest["duckdb_memory_limit_mib"] == 3072
    assert manifest["duckdb_threads"] == 1
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
    assert status["duckdb_threads"] == 1
    assert status["counts"]["element_catalog"] > len(final_output_columns())

    connection = duckdb.connect(str(result.database_path), read_only=True)
    try:
        runtime = connection.execute(
            """
            SELECT duckdb_memory_limit_mib, duckdb_threads
            FROM preprocessing_manifest
            """
        ).fetchone()
        assert runtime == (3072, 1)
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
    regenerated = export_compatibility_outputs(
        result.database_path,
        regenerated_root,
    )
    assert len(regenerated) == 36
    after = {
        output.key: hash_csv_with_metadata(regenerated_root / output.relative_path)
        for output in compatibility_outputs()
    }
    assert before == after

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


def test_combined_validation_checks_source_integrity_by_domain(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_root = _copy_glp1_fixture_for_combined(tmp_path)
    config = load_config(_write_combined_config(tmp_path, data_dir=input_root))
    result = build_preprocessed(config, strict=True)
    connection = duckdb.connect(str(result.database_path))
    try:
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

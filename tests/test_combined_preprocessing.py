from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import duckdb
import pandas as pd
import pytest

import trinetx_preprocessing.combined_preprocessing.builder as combined_builder
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
from trinetx_preprocessing.regression import hash_csv_with_metadata
from trinetx_preprocessing.work_manifest import require_current_work

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def test_combined_run_id_ignores_volatile_work_status() -> None:
    identity = {
        "schema_version": 5,
        "intermediate_schema_version": 6,
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


def test_combined_build_exports_exact_historical_contract(tmp_path: Path) -> None:
    config = load_config(_write_combined_config(tmp_path))
    result = build_preprocessed(config, strict=True)

    assert result.database_path.is_file()
    assert result.manifest_path.is_file()
    assert len(result.compatibility_paths) == 36
    assert result.validation.valid
    manifest = json.loads(result.manifest_path.read_text())
    assert manifest["status"] == "complete"
    assert manifest["run_id"] == result.run_id
    assert manifest["duckdb_memory_limit_mib"] == 3072
    assert manifest["duckdb_threads"] == 1
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


def test_failed_replacement_preserves_published_product(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = load_config(_write_combined_config(tmp_path))
    first = build_preprocessed(config, strict=True)
    original_database = first.database_path.read_bytes()
    original_hashes = _output_hashes(config.output_dir)

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
    assert not list(tmp_path.glob(".output.combined-*"))


def test_replacement_rejects_unmanaged_output_entries(tmp_path: Path) -> None:
    config = load_config(_write_combined_config(tmp_path))
    unmanaged = config.output_dir / "notes.txt"
    unmanaged.write_text("not part of the combined product")

    with pytest.raises(ValueError, match="unmanaged entries: notes.txt"):
        build_preprocessed(config, strict=True, replace_existing=True)

    assert unmanaged.read_text() == "not part of the combined product"


def test_publication_removes_appledouble_sidecars(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = load_config(_write_combined_config(tmp_path))
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
    real_replace = combined_builder.os.replace

    def fail_staging_publish(source: Path, destination: Path) -> None:
        if Path(source).name.startswith(".output.combined-build-"):
            raise OSError("injected publication failure")
        real_replace(source, destination)

    monkeypatch.setattr(combined_builder.os, "replace", fail_staging_publish)
    with pytest.raises(OSError, match="injected publication failure"):
        build_preprocessed(config, strict=True, replace_existing=True)

    assert _output_hashes(config.output_dir) == original_hashes
    assert not list(tmp_path.glob(".output.combined-*"))


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

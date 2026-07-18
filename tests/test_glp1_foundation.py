from __future__ import annotations

import csv
import hashlib
import json
import shutil
import subprocess
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import duckdb
import pytest

import trinetx_preprocessing.glp1_eligibility.ingestion as ingestion_module
import trinetx_preprocessing.glp1_eligibility.terminology_qa as terminology_qa_module
from trinetx_preprocessing.glp1_eligibility.builder import (
    _require_safe_output_location,
    build_glp1_eligibility,
)
from trinetx_preprocessing.glp1_eligibility.cli import main
from trinetx_preprocessing.glp1_eligibility.cohort import build_core_cohort
from trinetx_preprocessing.glp1_eligibility.concept_sets import load_concept_sets
from trinetx_preprocessing.glp1_eligibility.config import (
    GLP1ConfigError,
    load_glp1_config,
)
from trinetx_preprocessing.glp1_eligibility.database import (
    initialize_database,
    mark_database_complete,
)
from trinetx_preprocessing.glp1_eligibility.discovery import (
    ExportDiscoveryError,
    discover_export_files,
    validate_export,
)
from trinetx_preprocessing.glp1_eligibility.ingestion import (
    _concept_membership_sql,
    _create_candidate_membership_tables,
    _encounter_membership_sql,
    _partition_parquet_files,
    _patient_membership_sql,
    ingest_core_sources,
)
from trinetx_preprocessing.glp1_eligibility.monitoring import (
    RUN_STATE_FILENAME,
    RunStateWriter,
    process_appears_active,
    read_run_state,
    state_path_for_output,
)
from trinetx_preprocessing.glp1_eligibility.outputs import (
    summarize_database,
    write_build_outputs,
)
from trinetx_preprocessing.glp1_eligibility.provenance import (
    _BoundedFrequencyCounter,
    build_input_inventory,
    current_git_sha,
    deterministic_run_id,
)
from trinetx_preprocessing.glp1_eligibility.terminology_qa import (
    build_concept_match_summary,
)
from trinetx_preprocessing.glp1_eligibility.workspace import (
    prepare_workspace,
    publish_workspace,
)

ROOT = Path(__file__).resolve().parents[1]
GLP1_CONFIG = ROOT / "config" / "glp1_eligibility.yml"

DOMAIN_HEADERS = {
    "Patient/patient.csv": (
        "patient_id,sex,race,ethnicity,year_of_birth,month_year_death,"
        "patient_regional_location\n"
    ),
    "Encounter/encounter.csv": (
        "encounter_id,patient_id,start_date,end_date,type,source_id\n"
    ),
    "Diagnosis/diagnosis.csv": (
        "patient_id,encounter_id,date,code_system,code,"
        "principal_diagnosis_indicator,admitting_diagnosis,reason_for_visit\n"
    ),
    "Lab Results/lab_results.csv": (
        "patient_id,encounter_id,date,code_system,code,lab_result_num_val,"
        "lab_result_text_val,units_of_measure\n"
    ),
    "Vital Signs/vital_signs.csv": (
        "patient_id,encounter_id,date,code_system,code,value,text_value,"
        "units_of_measure\n"
    ),
    "Procedure/procedure.csv": (
        "patient_id,encounter_id,date,code_system,code,"
        "principal_procedure_indicator\n"
    ),
    "Medications/medication.csv": (
        "patient_id,encounter_id,code_system,code,start_date,route,brand,strength\n"
    ),
}


def _write_export(root: Path) -> None:
    for relative, header in DOMAIN_HEADERS.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(header)


def _append_rows(path: Path, *rows: str) -> None:
    with path.open("a") as handle:
        for row in rows:
            handle.write(row.rstrip("\n") + "\n")


def _append_primary_cases(root: Path, bmi_by_patient: dict[str, float]) -> None:
    """Add the minimum strict hypercapnia rows for named synthetic patients."""

    patients = tuple(bmi_by_patient)
    _append_rows(
        root / "Patient" / "patient.csv",
        *(f"{patient},F,White,Not Hispanic or Latino,1970,," for patient in patients),
    )
    _append_rows(
        root / "Encounter" / "encounter.csv",
        *(
            f"e_{patient},{patient},2024-01-01 00:00:00,"
            "2024-01-02 00:00:00,IMP,s1"
            for patient in patients
        ),
    )
    lab_rows: list[str] = []
    vital_rows: list[str] = []
    for patient, bmi in bmi_by_patient.items():
        encounter = f"e_{patient}"
        lab_rows.extend(
            (
                f"{patient},{encounter},2024-01-01 01:00:00,"
                "LOINC,2019-8,55,,mmHg",
                f"{patient},{encounter},2024-01-01 01:00:00,"
                "LOINC,2744-1,7.40,,pH",
            )
        )
        vital_rows.append(
            f"{patient},{encounter},2023-12-15,LOINC,39156-5,{bmi},,kg/m2"
        )
    _append_rows(root / "Lab Results" / "lab_results.csv", *lab_rows)
    _append_rows(root / "Vital Signs" / "vital_signs.csv", *vital_rows)


def test_default_glp1_config_and_concept_sets_are_valid() -> None:
    config = load_glp1_config(GLP1_CONFIG)
    catalog = load_concept_sets(config.concept_sets_dir)

    assert config.schema_version == "1.0"
    assert config.study.study_start is None
    assert config.study.index_encounter_types == ("EMER", "IMP")
    assert config.obesity.thresholds == (27.0, 30.0, 35.0, 40.0)
    assert config.hypercapnia.hco3_plausible_max_mmol_l == 80
    assert config.hypercapnia.po2_plausible_max_mm_hg == 800
    assert config.hypercapnia.sao2_plausible_max_percent == 100
    assert "major_trauma_context" in config.exclusions.cleaned_view_excludes
    assert config.runtime.duckdb_memory_limit_mib == 4096
    assert config.runtime.duckdb_threads == 1
    assert "arterial_pco2" in catalog.concept_set_ids
    assert catalog.required_concept_set_ids == (
        "arterial_pco2",
        "arterial_ph",
        "bmi",
    )

    arterial_codes = {
        concept.code
        for concept in catalog.concepts
        if concept.concept_set_id == "arterial_pco2" and concept.include
    }
    assert arterial_codes == {"2019-8", "32771-8"}
    assert "2026-3" not in arterial_codes
    assert {
        concept.concept_set_id
        for concept in catalog.concepts
        if concept.code in {"1960-4", "2703-7", "2708-6"}
    } == {"arterial_hco3", "arterial_po2", "arterial_sao2"}


def test_glp1_config_rejects_threshold_not_above_primary(tmp_path: Path) -> None:
    raw = GLP1_CONFIG.read_text().replace(
        "pco2_sensitivity_thresholds_mm_hg: [50, 52]",
        "pco2_sensitivity_thresholds_mm_hg: [45, 52]",
    )
    path = tmp_path / "config.yml"
    path.write_text(raw)

    with pytest.raises(GLP1ConfigError, match="must exceed"):
        load_glp1_config(path)


@pytest.mark.parametrize(
    ("old", "new", "message"),
    (
        (
            "pco2_sensitivity_thresholds_mm_hg: [50, 52]",
            "pco2_sensitivity_thresholds_mm_hg: [60, 70]",
            r"must be \[50, 52\]",
        ),
        (
            "primary_requires_arterial_specimen: true",
            "primary_requires_arterial_specimen: false",
            "must be true",
        ),
        (
            "thresholds: [27, 30, 35, 40]",
            "thresholds: [25, 30, 35, 40]",
            r"must be \[27, 30, 35, 40\]",
        ),
    ),
)
def test_glp1_config_rejects_unsupported_fixed_contract_options(
    tmp_path: Path,
    old: str,
    new: str,
    message: str,
) -> None:
    path = tmp_path / "config.yml"
    path.write_text(GLP1_CONFIG.read_text().replace(old, new))

    with pytest.raises(GLP1ConfigError, match=message):
        load_glp1_config(path)


def test_glp1_config_uses_bounded_runtime_defaults_when_omitted(
    tmp_path: Path,
) -> None:
    raw = GLP1_CONFIG.read_text()
    runtime = "runtime:\n  duckdb_memory_limit_mib: 4096\n  duckdb_threads: 1\n\n"
    path = tmp_path / "config.yml"
    path.write_text(raw.replace(runtime, ""))

    config = load_glp1_config(path)

    assert config.runtime.duckdb_memory_limit_mib == 4096
    assert config.runtime.duckdb_threads == 1


@pytest.mark.parametrize(
    ("runtime", "message"),
    (
        (
            "runtime:\n  duckdb_memory_limit_mib: 0\n  duckdb_threads: 2",
            "duckdb_memory_limit_mib must be greater than zero",
        ),
        (
            "runtime:\n  duckdb_memory_limit_mib: 4096\n  duckdb_threads: 0",
            "duckdb_threads must be greater than zero",
        ),
        (
            "runtime:\n  duckdb_memory_limit_mib: 4096\n  duckdb_threads: 1\n  x: 1",
            "Unknown runtime configuration key",
        ),
    ),
)
def test_glp1_config_rejects_invalid_runtime_settings(
    tmp_path: Path,
    runtime: str,
    message: str,
) -> None:
    raw = GLP1_CONFIG.read_text()
    current = "runtime:\n  duckdb_memory_limit_mib: 4096\n  duckdb_threads: 1"
    path = tmp_path / "config.yml"
    path.write_text(raw.replace(current, runtime))

    with pytest.raises(GLP1ConfigError, match=message):
        load_glp1_config(path)


def test_export_discovery_prefers_canonical_unsplit_file(tmp_path: Path) -> None:
    _write_export(tmp_path)
    unsplit = tmp_path / "Encounter" / "encounter.csv"
    split_1 = tmp_path / "Encounter" / "encounter0001.csv"
    split_2 = tmp_path / "Encounter" / "encounter0002.csv"
    split_1.write_text(unsplit.read_text())
    split_2.write_text(unsplit.read_text())

    discovered = discover_export_files(tmp_path)

    assert [path.name for path in discovered["encounter"]] == ["encounter.csv"]


def test_export_discovery_allows_hidden_export_root(tmp_path: Path) -> None:
    export_root = tmp_path / ".private_export"
    _write_export(export_root)

    discovered = discover_export_files(export_root)

    assert [path.name for path in discovered["encounter"]] == ["encounter.csv"]


def test_export_discovery_falls_back_to_split_files(tmp_path: Path) -> None:
    _write_export(tmp_path)
    unsplit = tmp_path / "Encounter" / "encounter.csv"
    split_1 = tmp_path / "Encounter" / "encounter0001.csv"
    split_2 = tmp_path / "Encounter" / "encounter0002.csv"
    split_1.write_text(unsplit.read_text())
    split_2.write_text(unsplit.read_text())
    unsplit.unlink()

    discovered = discover_export_files(tmp_path)

    assert [path.name for path in discovered["encounter"]] == [
        "encounter0001.csv",
        "encounter0002.csv",
    ]


def test_export_discovery_rejects_tied_nearest_roots(tmp_path: Path) -> None:
    _write_export(tmp_path / "first_export")
    _write_export(tmp_path / "second_export")

    with pytest.raises(ExportDiscoveryError, match="Ambiguous nearest source"):
        discover_export_files(tmp_path)


def test_validate_export_reports_tied_nearest_roots(tmp_path: Path) -> None:
    _write_export(tmp_path / "first_export")
    _write_export(tmp_path / "second_export")

    report = validate_export(tmp_path)

    assert report.valid is False
    assert report.files == ()
    assert len(report.errors) == 1
    assert "Pass the root of exactly one TriNetX export" in report.errors[0]
    assert "first_export/Patient/patient.csv" in report.errors[0]
    assert "second_export/Patient/patient.csv" in report.errors[0]
    assert str(tmp_path) not in report.errors[0]


@pytest.mark.parametrize(
    ("nested_layout", "shallow_patient_relative", "nested_encounter_relative"),
    (
        (
            "domain_folders",
            "Patient/patient.csv",
            "complete_export/Encounter/encounter.csv",
        ),
        ("flat", "patient.csv", "complete_export/encounter.csv"),
    ),
)
def test_validate_export_rejects_mixed_domain_export_roots(
    tmp_path: Path,
    nested_layout: str,
    shallow_patient_relative: str,
    nested_encounter_relative: str,
) -> None:
    nested_export = tmp_path / "complete_export"
    if nested_layout == "domain_folders":
        _write_export(nested_export)
    else:
        nested_export.mkdir()
        for relative, header in DOMAIN_HEADERS.items():
            (nested_export / Path(relative).name).write_text(header)
    shallow_patient = tmp_path / shallow_patient_relative
    shallow_patient.parent.mkdir(parents=True, exist_ok=True)
    shallow_patient.write_text(DOMAIN_HEADERS["Patient/patient.csv"])

    report = validate_export(tmp_path)

    assert report.valid is False
    assert len(report.errors) == 1
    assert "do not share one export root" in report.errors[0]
    assert f"patient={shallow_patient_relative}" in report.errors[0]
    assert f"encounter={nested_encounter_relative}" in report.errors[0]
    assert str(tmp_path) not in report.errors[0]


def test_validate_export_rejects_sibling_flat_export_as_domain_folder(
    tmp_path: Path,
) -> None:
    _write_export(tmp_path)
    sibling_export = tmp_path / "complete_export"
    sibling_export.mkdir()
    (tmp_path / "Encounter" / "encounter.csv").replace(
        sibling_export / "encounter.csv"
    )

    report = validate_export(tmp_path)

    assert report.valid is False
    assert len(report.errors) == 1
    assert "do not share one export root" in report.errors[0]
    assert "patient=Patient/patient.csv" in report.errors[0]
    assert "encounter=complete_export/encounter.csv" in report.errors[0]
    assert str(tmp_path) not in report.errors[0]


def test_validate_export_accepts_flat_export_layout(tmp_path: Path) -> None:
    for relative, header in DOMAIN_HEADERS.items():
        (tmp_path / Path(relative).name).write_text(header)

    report = validate_export(tmp_path)

    assert report.valid is True
    assert report.errors == ()


def test_ingredient_only_export_satisfies_medication_source_contract(
    tmp_path: Path,
) -> None:
    _write_export(tmp_path)
    (tmp_path / "Medications" / "medication.csv").unlink()
    ingredient = tmp_path / "Medications" / "medication_ingredient.csv"
    ingredient.write_text(
        "patient_id,encounter_id,unique_id,code_system,code,start_date,route,"
        "brand,strength,derived_by_TriNetX,source_id\n"
    )

    report = validate_export(tmp_path)

    assert report.valid is True
    assert report.domain_file_counts["medication"] == 0
    assert report.domain_file_counts["medication_ingredient"] == 1


def test_ingredient_source_rejects_missing_medication_fields(tmp_path: Path) -> None:
    _write_export(tmp_path)
    (tmp_path / "Medications" / "medication.csv").unlink()
    ingredient = tmp_path / "Medications" / "medication_ingredient.csv"
    ingredient.write_text("patient_id\np1\n")

    report = validate_export(tmp_path)

    assert report.valid is False
    assert any(
        "medication_ingredient.csv is missing required column(s): "
        "code_system, code, start_date" in error
        for error in report.errors
    )


def test_headerless_medication_split_artifact_is_not_discovered(
    tmp_path: Path,
) -> None:
    _write_export(tmp_path)
    medication = tmp_path / "Medications" / "medication.csv"
    medication.unlink()
    content = (
        "patient_id,encounter_id,unique_id,code_system,code,start_date,route,"
        "brand,strength,derived_by_TriNetX,source_id\n"
        "p1,e1,u1,RXNORM,1991302,2024-01-01,oral,Wegovy,2.4mg,,s1\n"
    )
    ingredient = tmp_path / "Medications" / "medication_ingredient.csv"
    ingredient.write_text(content)
    (tmp_path / "Medications" / "medication0001.csv").write_text(content)
    (tmp_path / "Medications" / "medication0002.csv").write_text(
        "p2,e2,u2,RXNORM,1991302,2024-01-02,oral,Wegovy,2.4mg,,s1\n"
    )

    discovered = discover_export_files(tmp_path)

    assert discovered["medication"] == ()
    assert discovered["medication_ingredient"] == (ingredient,)


def test_single_headerless_medication_chunk_is_not_discovered(
    tmp_path: Path,
) -> None:
    _write_export(tmp_path)
    (tmp_path / "Medications" / "medication.csv").unlink()
    ingredient = tmp_path / "Medications" / "medication_ingredient.csv"
    ingredient.write_text(
        "patient_id,encounter_id,code_system,code,start_date\n"
        "p1,e1,RXNORM,1991302,2024-01-01\n"
    )
    (tmp_path / "Medications" / "medication0001.csv").write_text(
        "p2,e2,RXNORM,1991302,2024-01-02\n"
    )

    report = validate_export(tmp_path)

    assert report.valid is True
    assert report.domain_file_counts["medication"] == 0
    assert report.domain_file_counts["medication_ingredient"] == 1
    assert report.errors == ()


def test_same_size_distinct_medication_split_is_retained(tmp_path: Path) -> None:
    _write_export(tmp_path)
    (tmp_path / "Medications" / "medication.csv").unlink()
    header = (
        "patient_id,encounter_id,unique_id,code_system,code,start_date,route,"
        "brand,strength,derived_by_TriNetX,source_id\n"
    )
    ingredient_content = (
        header + "p1,e1,u1,RXNORM,1991302,2024-01-01,oral,Wegovy,2.4mg,,s1\n"
    )
    medication_content = (
        header + "p1,e1,u1,RXNORM,1991303,2024-01-01,oral,Wegovy,2.4mg,,s1\n"
    )
    assert len(ingredient_content) == len(medication_content)
    ingredient = tmp_path / "Medications" / "medication_ingredient.csv"
    medication = tmp_path / "Medications" / "medication0001.csv"
    ingredient.write_text(ingredient_content)
    medication.write_text(medication_content)

    discovered = discover_export_files(tmp_path)

    assert discovered["medication"] == (medication,)
    assert discovered["medication_ingredient"] == (ingredient,)


def test_medication_chunks_allow_different_valid_header_order(tmp_path: Path) -> None:
    _write_export(tmp_path)
    (tmp_path / "Medications" / "medication.csv").unlink()
    ingredient = tmp_path / "Medications" / "medication_ingredient.csv"
    ingredient.write_text(
        "patient_id,encounter_id,code_system,code,start_date\n"
    )
    first = tmp_path / "Medications" / "medication0001.csv"
    second = tmp_path / "Medications" / "medication0002.csv"
    first.write_text(
        "patient_id,encounter_id,code_system,code,start_date,route\n"
        "p1,e1,RXNORM,1991302,2024-01-01,oral\n"
    )
    second.write_text(
        "code,start_date,patient_id,code_system,encounter_id,brand\n"
        "1991303,2024-01-02,p2,RXNORM,e2,Wegovy\n"
    )

    discovered = discover_export_files(tmp_path)

    assert discovered["medication"] == (first, second)
    assert discovered["medication_ingredient"] == (ingredient,)


def test_validate_export_reports_only_relative_paths(tmp_path: Path) -> None:
    _write_export(tmp_path)

    report = validate_export(tmp_path)

    assert report.valid is True
    assert report.domain_file_counts["labs"] == 1
    assert len(report.files) == len(DOMAIN_HEADERS)
    assert all(not Path(file.source_file).is_absolute() for file in report.files)
    assert str(tmp_path) not in json.dumps(report.to_dict())


def test_validate_export_fails_for_missing_required_column(tmp_path: Path) -> None:
    _write_export(tmp_path)
    (tmp_path / "Lab Results" / "lab_results.csv").write_text(
        "patient_id,encounter_id,date,code_system,code,lab_result_num_val\n"
    )

    report = validate_export(tmp_path)

    assert report.valid is False
    assert any("units_of_measure" in error for error in report.errors)


def test_validate_export_cli_writes_atomic_json_report(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    export_root = tmp_path / "export"
    report_path = tmp_path / "reports" / "validation.json"
    _write_export(export_root)

    result = main(
        [
            "validate-export",
            "--input",
            str(export_root),
            "--json-out",
            str(report_path),
        ]
    )

    assert result == 0
    assert json.loads(report_path.read_text())["valid"] is True
    assert json.loads(capsys.readouterr().out)["valid"] is True


def test_run_state_is_atomic_and_monitorable(tmp_path: Path) -> None:
    writer = RunStateWriter(tmp_path, "synthetic-run")
    writer.update(
        phase="ingestion",
        current_domain="labs",
        completed_units=2,
        total_units=7,
        rows_processed=250_000,
        bytes_processed=10_000_000,
    )

    state = read_run_state(tmp_path)

    assert (tmp_path / RUN_STATE_FILENAME).is_file()
    assert state.phase == "ingestion"
    assert state.current_domain == "labs"
    assert state.rows_processed == 250_000
    assert process_appears_active(state) is True
    assert not list(tmp_path.glob(f".{RUN_STATE_FILENAME}.tmp-*"))


def test_status_watch_stops_on_completed_state(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    writer = RunStateWriter(tmp_path, "synthetic-run")
    writer.complete(message="done")

    result = main(
        ["status", "--output", str(tmp_path), "--watch", "--json"]
    )

    assert result == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "completed"
    assert payload["phase"] == "complete"


def test_input_inventory_is_deterministic_and_counts_data_rows(tmp_path: Path) -> None:
    _write_export(tmp_path)
    encounter = tmp_path / "Encounter" / "encounter.csv"
    encounter.write_text(encounter.read_text() + "e1,p1,2024-01-01,2024-01-02,IMP,s1\n")
    report = validate_export(tmp_path)

    first = build_input_inventory(tmp_path, report, block_size=11)
    second = build_input_inventory(tmp_path, report, block_size=29)

    assert first.sha256 == second.sha256
    encounter_inventory = next(
        item for item in first.files if item.logical_domain == "encounter"
    )
    assert encounter_inventory.row_count == 1
    assert encounter_inventory.source_file == "Encounter/encounter.csv"


def test_export_metadata_is_inventoried_and_invalidates_input_identity(
    tmp_path: Path,
) -> None:
    _write_export(tmp_path)
    metadata = tmp_path / "export_manifest.json"
    dictionary = tmp_path / "Data Dictionary.csv"
    metadata.write_text('{"export": "synthetic-v1"}\n')
    dictionary.write_text("field,description\npatient_id,Synthetic identifier\n")

    report = validate_export(tmp_path)
    first = build_input_inventory(tmp_path, report)
    metadata_rows = tuple(
        item for item in first.files if item.logical_domain == "export_metadata"
    )

    assert report.domain_file_counts["export_metadata"] == 2
    assert {item.source_file for item in metadata_rows} == {
        "Data Dictionary.csv",
        "export_manifest.json",
    }
    assert {
        item.source_file: item.row_count for item in metadata_rows
    } == {"Data Dictionary.csv": 1, "export_manifest.json": 0}
    metadata.write_text('{"export": "synthetic-v2"}\n')
    second = build_input_inventory(tmp_path, validate_export(tmp_path))
    assert second.sha256 != first.sha256


def test_input_inventory_collects_bounded_unmapped_code_frequencies(
    tmp_path: Path,
) -> None:
    _write_export(tmp_path)
    _append_rows(
        tmp_path / "Diagnosis" / "diagnosis.csv",
        "p1,e1,2024-01-01,ICD10CM,E11.9,,,",
        "p1,e1,2024-01-01,LOCAL,UNMAPPED_A,,,",
        "p2,e2,2024-01-01,LOCAL,UNMAPPED_A,,,",
        "p3,e3,2024-01-01,LOCAL,UNMAPPED_B,,,",
    )
    report = validate_export(tmp_path)
    catalog = load_concept_sets(load_glp1_config(GLP1_CONFIG).concept_sets_dir)

    inventory = build_input_inventory(
        tmp_path,
        report,
        catalog=catalog,
        block_size=1_024,
    )

    frequencies = {
        (row.logical_domain, row.code_system, row.code): (
            row.estimated_count,
            row.max_error,
        )
        for row in inventory.unmapped_code_frequencies
    }
    assert frequencies[("diagnosis", "LOCAL", "UNMAPPED_A")] == (2, 0)
    assert frequencies[("diagnosis", "LOCAL", "UNMAPPED_B")] == (1, 0)
    assert ("diagnosis", "ICD10CM", "E11.9") not in frequencies


def test_multifile_unmapped_sketch_preserves_cross_file_error_bound(
    tmp_path: Path,
) -> None:
    _write_export(tmp_path)
    diagnosis = tmp_path / "Diagnosis" / "diagnosis.csv"
    header = diagnosis.read_text()
    first = tmp_path / "Diagnosis" / "diagnosis0001.csv"
    second = tmp_path / "Diagnosis" / "diagnosis0002.csv"
    first.write_text(
        header
        + "".join(
            f"p{index},e{index},2024-01-01,LOCAL,CODE_{index:04d},,,\n"
            for index in range(2_002)
        )
        + "p_target,e_target,2024-01-01,LOCAL,TARGET,,,\n"
    )
    second.write_text(
        header
        + "".join(
            "p_target,e_target,2024-01-01,LOCAL,TARGET,,,\n"
            for _ in range(100)
        )
    )
    diagnosis.unlink()
    report = validate_export(tmp_path)
    catalog = load_concept_sets(load_glp1_config(GLP1_CONFIG).concept_sets_dir)

    inventory = build_input_inventory(tmp_path, report, catalog=catalog)
    target = next(
        row
        for row in inventory.unmapped_code_frequencies
        if row.logical_domain == "diagnosis" and row.code == "TARGET"
    )

    assert target.estimated_count - target.max_error <= 101
    assert 101 <= target.estimated_count


def test_bounded_frequency_counter_preserves_error_bounds_across_checkpoints() -> None:
    counter = _BoundedFrequencyCounter(capacity=2)
    first_counts = {
        ("LOCAL", "A"): 5,
        ("LOCAL", "B"): 4,
        ("LOCAL", "C"): 3,
    }
    second_counts = {
        ("LOCAL", "C"): 3,
        ("LOCAL", "D"): 2,
    }
    exact_counts = first_counts | second_counts
    exact_counts[("LOCAL", "C")] = 6
    for key, count in first_counts.items():
        counter.update(key, count)
    checkpoint = counter.copy()
    for key, count in second_counts.items():
        checkpoint.update(key, count)

    for frequency in checkpoint.frequencies("diagnosis", limit=2):
        exact = exact_counts[(frequency.code_system, frequency.code)]
        assert frequency.estimated_count - frequency.max_error <= exact
        assert exact <= frequency.estimated_count


def test_git_fingerprint_changes_with_dirty_content(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repository, check=True)
    subprocess.run(
        ["git", "config", "user.name", "Synthetic Test"],
        cwd=repository,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "synthetic@example.invalid"],
        cwd=repository,
        check=True,
    )
    tracked = repository / "tracked.txt"
    (repository / ".gitignore").write_text("._*\n")
    tracked.write_text("clean\n")
    subprocess.run(
        ["git", "add", ".gitignore", "tracked.txt"],
        cwd=repository,
        check=True,
    )
    subprocess.run(
        ["git", "commit", "-q", "-m", "synthetic baseline"],
        cwd=repository,
        check=True,
    )
    monkeypatch.chdir(tmp_path)

    clean = current_git_sha(repository)
    assert len(clean) == 40
    tracked.write_text("dirty one\n")
    dirty_one = current_git_sha(repository)
    tracked.write_text("dirty two\n")
    dirty_two = current_git_sha(repository)
    (repository / "untracked.txt").write_text("additional content\n")
    dirty_with_untracked = current_git_sha(repository)

    assert dirty_one.startswith(f"{clean}-dirty-")
    assert dirty_two.startswith(f"{clean}-dirty-")
    assert len({dirty_one, dirty_two, dirty_with_untracked}) == 3


def test_git_fingerprint_ignores_callers_working_repository(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package_identity = current_git_sha()
    unrelated = tmp_path / "unrelated"
    unrelated.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=unrelated, check=True)
    monkeypatch.chdir(unrelated)

    assert current_git_sha() == package_identity


def test_concept_catalog_content_changes_build_identity(tmp_path: Path) -> None:
    config = load_glp1_config(GLP1_CONFIG)
    copied_catalog = tmp_path / "concept_sets"
    shutil.copytree(config.concept_sets_dir, copied_catalog)
    first = load_concept_sets(copied_catalog)
    first_run = deterministic_run_id(
        config_sha256="config",
        input_manifest_sha256="input",
        concept_catalog_sha256=first.sha256,
        code_fingerprint="code",
    )
    medications = copied_catalog / "medications.csv"
    medications.write_text(medications.read_text().replace(
        "Semaglutide ingredient", "Semaglutide revised ingredient", 1
    ))
    second = load_concept_sets(copied_catalog)
    second_run = deterministic_run_id(
        config_sha256="config",
        input_manifest_sha256="input",
        concept_catalog_sha256=second.sha256,
        code_fingerprint="code",
    )

    assert first.sha256 != second.sha256
    assert first_run != second_run


def test_workspace_publishes_atomically_and_status_uses_stable_sibling(
    tmp_path: Path,
) -> None:
    output = tmp_path / "glp1_eligibility"
    workspace = prepare_workspace(
        output,
        run_id="run-1",
        config_sha256="config-hash",
        input_manifest_sha256="input-hash",
        concept_catalog_sha256="catalog-hash",
        git_sha="git-hash",
    )
    (workspace.staging_dir / "artifact.txt").write_text("complete")

    assert not output.exists()
    assert state_path_for_output(output).is_file()

    publish_workspace(workspace)

    assert (output / "artifact.txt").read_text() == "complete"
    assert not workspace.staging_dir.exists()
    assert read_run_state(output).status == "completed"


def test_duckdb_metadata_bootstrap_preserves_relative_source_inventory(
    tmp_path: Path,
) -> None:
    export_root = tmp_path / "export"
    _write_export(export_root)
    report = validate_export(export_root)
    inventory = build_input_inventory(export_root, report)
    config = load_glp1_config(GLP1_CONFIG)
    catalog = load_concept_sets(config.concept_sets_dir)
    git_sha = current_git_sha()
    run_id = deterministic_run_id(
        config_sha256=config.sha256,
        input_manifest_sha256=inventory.sha256,
        concept_catalog_sha256=catalog.sha256,
        code_fingerprint=git_sha,
    )
    database_path = tmp_path / "work" / "glp1_hypercapnia.duckdb"

    connection = initialize_database(
        database_path,
        run_id=run_id,
        input_root=export_root,
        config=config,
        inventory=inventory,
        catalog=catalog,
        git_sha=git_sha,
        concept_catalog_sha256=catalog.sha256,
    )
    try:
        assert connection.execute("SELECT COUNT(*) FROM concept_set").fetchone() == (
            len(catalog.concepts),
        )
        source_files = connection.execute(
            "SELECT source_file FROM source_file_inventory ORDER BY source_file"
        ).fetchall()
        assert len(source_files) == len(DOMAIN_HEADERS)
        assert all(not Path(row[0]).is_absolute() for row in source_files)
        assert connection.execute(
            "SELECT concept_catalog_sha256 FROM run_manifest"
        ).fetchone() == (catalog.sha256,)
        assert connection.execute(
            """
            SELECT duckdb_memory_limit_mib, duckdb_threads
            FROM run_manifest
            """
        ).fetchone() == (4096, 1)
        assert connection.execute(
            "SELECT current_setting('memory_limit'), current_setting('threads')"
        ).fetchone() == ("4.0 GiB", 1)
        mark_database_complete(connection)
        assert connection.execute(
            "SELECT status FROM run_manifest"
        ).fetchone() == ("complete",)
    finally:
        connection.close()


def test_core_ingestion_retains_relevant_rows_and_excludes_total_co2_as_gas(
    tmp_path: Path,
) -> None:
    export_root = tmp_path / "export"
    _write_export(export_root)
    _append_rows(
        export_root / "Patient" / "patient.csv",
        "p1,F,White,Not Hispanic or Latino,1970,,",
        "p2,M,White,Not Hispanic or Latino,1975,,",
    )
    _append_rows(
        export_root / "Encounter" / "encounter.csv",
        "e1,p1,2024-01-01 00:00:00,2024-01-02 00:00:00,IMP,s1",
        "e1,p1,2024-01-01 00:00:00,2024-01-02 00:00:00,IMP,s1",
        "e_patient,p1,2024-01-03 00:00:00,2024-01-04 00:00:00,IMP,s1",
        "e1,p_other,2024-01-05 00:00:00,2024-01-06 00:00:00,IMP,s1",
        "e2,p2,2024-01-01 00:00:00,2024-01-02 00:00:00,IMP,s1",
    )
    _append_rows(
        export_root / "Lab Results" / "lab_results.csv",
        "p1,e1,2024-01-01 01:00:00,LOINC,2019-8,55,,mmHg",
        "p1,e1,2024-01-01 01:00:00,LOINC,2744-1,7.40,,pH",
        "p1,e1,2024-01-01 01:00:00,LOINC,2026-3,60,,mmol/L",
        "p2,e2,2024-01-01 01:00:00,LOINC,2026-3,60,,mmol/L",
    )
    _append_rows(
        export_root / "Vital Signs" / "vital_signs.csv",
        "p1,e1,2023-12-15,LOINC,39156-5,36,,kg/m2",
        "p1,e1,2023-12-15,LOINC,39156-5,36,,kg/m2",
        "p2,e2,2023-12-15,LOINC,39156-5,32,,kg/m2",
    )

    report = validate_export(export_root)
    inventory = build_input_inventory(export_root, report)
    config = load_glp1_config(GLP1_CONFIG)
    catalog = load_concept_sets(config.concept_sets_dir)
    connection = initialize_database(
        tmp_path / "glp1.duckdb",
        run_id="synthetic-run",
        input_root=export_root,
        config=config,
        inventory=inventory,
        catalog=catalog,
        git_sha="test-sha",
        concept_catalog_sha256=catalog.sha256,
    )
    try:
        counts = ingest_core_sources(
            connection,
            input_root=export_root,
            inventory=inventory,
            config=config,
        )
        assert counts["source_lab_measurement"] == 4
        assert counts["gas_candidate_id"] == 1
        assert connection.execute(
            "SELECT patient_id, encounter_id FROM gas_candidate_id"
        ).fetchall() == [("p1", "e1")]
        assert connection.execute(
            """
            SELECT patient_id, encounter_id, count(*)
            FROM source_encounter
            GROUP BY patient_id, encounter_id
            ORDER BY patient_id, encounter_id
            """
        ).fetchall() == [
            ("p1", "e1", 2),
            ("p1", "e_patient", 1),
            ("p_other", "e1", 1),
        ]
        assert connection.execute(
            "SELECT patient_id FROM source_patient"
        ).fetchall() == [("p1",)]
        assert connection.execute(
            """
            SELECT patient_id, value, count(*), count(DISTINCT source_record_hash)
            FROM source_vital_measurement
            GROUP BY patient_id, value
            """
        ).fetchall() == [("p1", "36", 2, 1)]
        expected_vital_hash = hashlib.sha256(
            "\x1f".join(
                (
                    "Vital Signs/vital_signs.csv",
                    "p1",
                    "e1",
                    "2023-12-15",
                    "LOINC",
                    "39156-5",
                    "36",
                    "",
                    "kg/m2",
                    "",
                    "",
                )
            ).encode()
        ).hexdigest()
        assert connection.execute(
            "SELECT DISTINCT source_record_hash FROM source_vital_measurement"
        ).fetchall() == [(expected_vital_hash,)]
        assert not list(
            (tmp_path / ".duckdb_tmp").glob(
                f"{ingestion_module._VITAL_INGEST_SCRATCH_PREFIX}*"
            )
        )
        assert connection.execute(
            """
            SELECT COUNT(*) FROM source_lab_measurement
            WHERE code = '2026-3'
            """
        ).fetchone() == (2,)
        assert build_concept_match_summary(
            connection, catalog.required_concept_set_ids
        ) == ()
        assert connection.execute(
            """
            SELECT duplicate_rows FROM source_duplicate_summary
            WHERE domain = 'vital'
            """
        ).fetchone() == (1,)
        assert connection.execute(
            """
            SELECT matched_rows FROM concept_match_summary
            WHERE concept_set_id = 'bmi'
            """
        ).fetchone() == (1,)
        assert not list(
            (tmp_path / ".duckdb_tmp").glob(
                f"{terminology_qa_module._TERMINOLOGY_QA_SCRATCH_PREFIX}*"
            )
        )
        connection.execute("DELETE FROM source_vital_measurement")
        warnings = build_concept_match_summary(
            connection, catalog.required_concept_set_ids
        )
        assert warnings == (
            "Required concept set 'bmi' matched no retained source rows.",
        )
        assert connection.execute(
            "SELECT warning_count FROM run_manifest"
        ).fetchone() == (1,)
    finally:
        connection.close()


def test_terminology_qa_cleanup_failure_is_not_suppressed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    export_root = tmp_path / "export"
    _write_export(export_root)
    _append_primary_cases(export_root, {"p1": 36.0})

    report = validate_export(export_root)
    inventory = build_input_inventory(export_root, report)
    config = load_glp1_config(GLP1_CONFIG)
    catalog = load_concept_sets(config.concept_sets_dir)
    connection = initialize_database(
        tmp_path / "glp1.duckdb",
        run_id="terminology-cleanup-failure",
        input_root=export_root,
        config=config,
        inventory=inventory,
        catalog=catalog,
        git_sha="test-sha",
        concept_catalog_sha256=catalog.sha256,
    )
    try:
        ingest_core_sources(
            connection,
            input_root=export_root,
            inventory=inventory,
            config=config,
        )
        original_remove = terminology_qa_module.remove_tree_strict

        def fail_lab_cleanup(path: Path, *, context: str) -> None:
            if context == "GLP-1 terminology QA lab scratch":
                raise OSError("simulated terminology cleanup failure")
            original_remove(path, context=context)

        monkeypatch.setattr(
            terminology_qa_module,
            "remove_tree_strict",
            fail_lab_cleanup,
        )
        monkeypatch.setattr(
            terminology_qa_module,
            "_DIRECT_CONCEPT_MATCH_MAX_ROWS",
            0,
        )

        with pytest.raises(OSError, match="simulated terminology cleanup failure"):
            build_concept_match_summary(
                connection,
                catalog.required_concept_set_ids,
            )
        assert not list(
            (tmp_path / ".duckdb_tmp").glob(
                f"{terminology_qa_module._TERMINOLOGY_QA_SCRATCH_PREFIX}*"
            )
        )
    finally:
        connection.close()


def test_partitioned_terminology_qa_matches_direct_reduction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = duckdb.connect(str(tmp_path / "terminology.duckdb"))
    temp_dir = tmp_path / "tmp"
    temp_dir.mkdir()
    connection.execute("SET temp_directory = ?", [str(temp_dir)])
    connection.execute(
        """
        CREATE TABLE concept_set (
            concept_set_id VARCHAR,
            domain VARCHAR,
            code_system VARCHAR,
            code VARCHAR,
            match_type VARCHAR,
            include BOOLEAN
        );
        INSERT INTO concept_set VALUES
            ('overlap', 'lab', 'LOINC', '1234-5', 'exact', true),
            ('overlap', 'lab', 'LOINC', '123', 'prefix', true),
            ('other', 'lab', 'LOINC', '9999-9', 'exact', true);
        CREATE TABLE run_manifest (run_id VARCHAR, warning_count BIGINT);
        INSERT INTO run_manifest VALUES ('test-run', 0);
        CREATE TABLE build_warning (
            run_id VARCHAR,
            warning_code VARCHAR,
            message VARCHAR,
            details_json JSON
        );
        """
    )
    for table in terminology_qa_module._SOURCE_TABLE_BY_DOMAIN.values():
        connection.execute(
            f"""
            CREATE TABLE {table} (
                code_system VARCHAR,
                code VARCHAR,
                source_record_hash VARCHAR
            )
            """
        )
    connection.execute(
        """
        INSERT INTO source_lab_measurement VALUES
            ('LOINC', '1234-5', 'hash-a'),
            ('LOINC', '1234-5', 'hash-a'),
            ('LOINC', '1234-5', 'hash-b'),
            ('LOINC', '9999-9', 'hash-c'),
            ('LOINC', '9999-9', NULL),
            ('LOINC', '9999-9', NULL)
        """
    )
    try:
        assert build_concept_match_summary(connection, ("overlap",)) == ()
        direct = connection.execute(
            """
            SELECT concept_set_id, domain, matched_rows, required
            FROM concept_match_summary ORDER BY concept_set_id
            """
        ).fetchall()
        assert direct == [
            ("other", "lab", 1, False),
            ("overlap", "lab", 2, True),
        ]
        direct_duplicates = connection.execute(
            """
            SELECT domain, duplicate_rows
            FROM source_duplicate_summary ORDER BY domain
            """
        ).fetchall()
        assert direct_duplicates == [
            ("diagnosis", 0),
            ("lab", 2),
            ("medication", 0),
            ("procedure", 0),
            ("vital", 0),
        ]

        monkeypatch.setattr(
            terminology_qa_module,
            "_DIRECT_CONCEPT_MATCH_MAX_ROWS",
            0,
        )
        assert build_concept_match_summary(connection, ("overlap",)) == ()
        partitioned = connection.execute(
            """
            SELECT concept_set_id, domain, matched_rows, required
            FROM concept_match_summary ORDER BY concept_set_id
            """
        ).fetchall()
        assert partitioned == direct
        assert connection.execute(
            """
            SELECT domain, duplicate_rows
            FROM source_duplicate_summary ORDER BY domain
            """
        ).fetchall() == direct_duplicates
        assert not list(
            temp_dir.glob(
                f"{terminology_qa_module._TERMINOLOGY_QA_SCRATCH_PREFIX}*"
            )
        )
    finally:
        connection.close()


def test_vital_ingestion_cleanup_failure_is_not_suppressed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    export_root = tmp_path / "export"
    _write_export(export_root)
    _append_primary_cases(export_root, {"p1": 36.0})

    report = validate_export(export_root)
    inventory = build_input_inventory(export_root, report)
    config = load_glp1_config(GLP1_CONFIG)
    catalog = load_concept_sets(config.concept_sets_dir)
    connection = initialize_database(
        tmp_path / "glp1.duckdb",
        run_id="cleanup-failure",
        input_root=export_root,
        config=config,
        inventory=inventory,
        catalog=catalog,
        git_sha="test-sha",
        concept_catalog_sha256=catalog.sha256,
    )
    cleanup_paths: list[Path] = []

    def fail_cleanup(path: Path, *, context: str) -> None:
        cleanup_paths.append(path)
        raise OSError(f"{context} failed")

    monkeypatch.setattr(ingestion_module, "remove_tree_strict", fail_cleanup)
    try:
        with pytest.raises(OSError, match="GLP-1 vital ingestion scratch failed"):
            ingest_core_sources(
                connection,
                input_root=export_root,
                inventory=inventory,
                config=config,
            )
        assert len(cleanup_paths) == 1
        assert cleanup_paths[0].exists()
    finally:
        connection.close()
        for path in cleanup_paths:
            shutil.rmtree(path, ignore_errors=True)


def test_vital_ingestion_preserves_empty_output_schema(tmp_path: Path) -> None:
    export_root = tmp_path / "export"
    _write_export(export_root)
    _append_rows(
        export_root / "Patient" / "patient.csv",
        "p1,F,White,Not Hispanic or Latino,1970,,",
    )
    _append_rows(
        export_root / "Encounter" / "encounter.csv",
        "e1,p1,2024-01-01 00:00:00,2024-01-02 00:00:00,IMP,s1",
    )
    _append_rows(
        export_root / "Lab Results" / "lab_results.csv",
        "p1,e1,2024-01-01 01:00:00,LOINC,2019-8,55,,mmHg",
        "p1,e1,2024-01-01 01:00:00,LOINC,2744-1,7.40,,pH",
    )

    report = validate_export(export_root)
    inventory = build_input_inventory(export_root, report)
    config = load_glp1_config(GLP1_CONFIG)
    catalog = load_concept_sets(config.concept_sets_dir)
    connection = initialize_database(
        tmp_path / "glp1.duckdb",
        run_id="empty-vitals",
        input_root=export_root,
        config=config,
        inventory=inventory,
        catalog=catalog,
        git_sha="test-sha",
        concept_catalog_sha256=catalog.sha256,
    )
    try:
        counts = ingest_core_sources(
            connection,
            input_root=export_root,
            inventory=inventory,
            config=config,
        )

        assert counts["source_vital_measurement"] == 0
        assert connection.execute(
            """
            SELECT column_name, data_type
            FROM information_schema.columns
            WHERE table_name = 'source_vital_measurement'
            ORDER BY ordinal_position
            """
        ).fetchall()[-3:] == [
            ("event_datetime", "TIMESTAMP"),
            ("source_file", "VARCHAR"),
            ("source_record_hash", "VARCHAR"),
        ]
        assert not list(
            (tmp_path / ".duckdb_tmp").glob(
                f"{ingestion_module._VITAL_INGEST_SCRATCH_PREFIX}*"
            )
        )
    finally:
        connection.close()


def test_partitioned_concept_ingestion_preserves_duplicates_and_timestamps(
    tmp_path: Path,
) -> None:
    export_root = tmp_path / "export"
    _write_export(export_root)
    _append_primary_cases(export_root, {"p1": 36.0})
    _append_rows(
        export_root / "Diagnosis" / "diagnosis.csv",
        "p1,e_p1,2023-12-01,ICD10CM,E11.9,P,Y,N",
        "p1,e_p1,2023-12-01,ICD10CM,E11.9,P,Y,N",
    )
    _append_rows(
        export_root / "Procedure" / "procedure.csv",
        "p1,e_p1,2023-12-02,CPT,95811,P",
        "p1,e_p1,2023-12-02,CPT,95811,P",
    )
    _append_rows(
        export_root / "Medications" / "medication.csv",
        "p1,e_p1,RXNORM,1991302,2023-12-03,oral,Wegovy,2.4mg",
        "p1,e_p1,RXNORM,1991302,2023-12-03,oral,Wegovy,2.4mg",
    )

    report = validate_export(export_root)
    inventory = build_input_inventory(export_root, report)
    config = load_glp1_config(GLP1_CONFIG)
    catalog = load_concept_sets(config.concept_sets_dir)
    connection = initialize_database(
        tmp_path / "glp1.duckdb",
        run_id="partitioned-concepts",
        input_root=export_root,
        config=config,
        inventory=inventory,
        catalog=catalog,
        git_sha="test-sha",
        concept_catalog_sha256=catalog.sha256,
    )
    try:
        counts = ingest_core_sources(
            connection,
            input_root=export_root,
            inventory=inventory,
            config=config,
        )

        assert counts["source_diagnosis"] == 2
        assert counts["source_procedure"] == 2
        assert counts["source_medication"] == 2
        for table_name in (
            "source_diagnosis",
            "source_procedure",
            "source_medication",
        ):
            assert connection.execute(
                f"""
                SELECT count(*), count(DISTINCT source_record_hash)
                FROM {table_name}
                """
            ).fetchone() == (2, 1)
        assert connection.execute(
            """
            SELECT event_datetime, end_datetime
            FROM source_medication
            LIMIT 1
            """
        ).fetchone() == (datetime(2023, 12, 3), None)
        assert not list(
            (tmp_path / ".duckdb_tmp").glob(
                f"{ingestion_module._PATIENT_CONCEPT_INGEST_SCRATCH_PREFIX}*"
            )
        )
    finally:
        connection.close()


def test_glp1_build_parses_compact_trinetx_dates_across_domains(
    tmp_path: Path,
) -> None:
    export_root = tmp_path / "export"
    output_root = tmp_path / "output" / "glp1_eligibility"
    _write_export(export_root)
    (export_root / "Medications" / "medication.csv").write_text(
        "patient_id,encounter_id,code_system,code,start_date,end_date,route,"
        "brand,strength\n"
    )
    _append_rows(
        export_root / "Patient" / "patient.csv",
        "p1,F,White,Not Hispanic or Latino,1970,,",
    )
    _append_rows(
        export_root / "Encounter" / "encounter.csv",
        "e1,p1,20240101,20240102,IMP,s1",
    )
    _append_rows(
        export_root / "Lab Results" / "lab_results.csv",
        "p1,e1,20240101,LOINC,2019-8,55,,mmHg",
        "p1,e1,20240101,LOINC,2744-1,7.40,,pH",
    )
    _append_rows(
        export_root / "Vital Signs" / "vital_signs.csv",
        "p1,e1,20231215,LOINC,39156-5,36,,kg/m2",
    )
    _append_rows(
        export_root / "Diagnosis" / "diagnosis.csv",
        "p1,e1,20231201,ICD10CM,E11.9,P,Y,N",
    )
    _append_rows(
        export_root / "Procedure" / "procedure.csv",
        "p1,e1,20231202,CPT,95811,P",
    )
    _append_rows(
        export_root / "Medications" / "medication.csv",
        "p1,e1,RXNORM,1991302,20231203,20240201123045,oral,Wegovy,2.4mg",
    )

    build_glp1_eligibility(
        input_root=export_root,
        output_dir=output_root,
        config_path=GLP1_CONFIG,
    )

    connection = duckdb.connect(
        str(output_root / "glp1_hypercapnia.duckdb"),
        read_only=True,
    )
    try:
        assert connection.execute(
            "SELECT encounter_start, encounter_end FROM source_encounter"
        ).fetchone() == (datetime(2024, 1, 1), datetime(2024, 1, 2))
        expected_event_dates = {
            "source_lab_measurement": datetime(2024, 1, 1),
            "source_vital_measurement": datetime(2023, 12, 15),
            "source_diagnosis": datetime(2023, 12, 1),
            "source_procedure": datetime(2023, 12, 2),
            "source_medication": datetime(2023, 12, 3),
        }
        for table_name, expected in expected_event_dates.items():
            assert connection.execute(
                f"SELECT min(event_datetime) FROM {table_name}"
            ).fetchone() == (expected,)
        assert connection.execute(
            "SELECT end_datetime FROM source_medication"
        ).fetchone() == (datetime(2024, 2, 1, 12, 30, 45),)
        assert connection.execute(
            """
            SELECT row_count, unique_patient_count
            FROM cohort_flow
            WHERE stage = 'adult_candidate_emergency_inpatient_encounters'
            """
        ).fetchone() == (1, 1)
        assert connection.execute(
            """
            SELECT first_observed_event_date
            FROM raw_diagnosis_observability
            """
        ).fetchone() == (datetime(2023, 12, 1),)
        assert connection.execute(
            """
            SELECT first_observed_event_date
            FROM raw_medication_observability
            """
        ).fetchone() == (datetime(2023, 12, 3),)
    finally:
        connection.close()


def test_patient_concept_ingestion_cleanup_failure_is_not_suppressed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    export_root = tmp_path / "export"
    _write_export(export_root)
    _append_primary_cases(export_root, {"p1": 36.0})
    _append_rows(
        export_root / "Diagnosis" / "diagnosis.csv",
        "p1,e_p1,2023-12-01,ICD10CM,E11.9,P,Y,N",
    )

    report = validate_export(export_root)
    inventory = build_input_inventory(export_root, report)
    config = load_glp1_config(GLP1_CONFIG)
    catalog = load_concept_sets(config.concept_sets_dir)
    connection = initialize_database(
        tmp_path / "glp1.duckdb",
        run_id="concept-cleanup-failure",
        input_root=export_root,
        config=config,
        inventory=inventory,
        catalog=catalog,
        git_sha="test-sha",
        concept_catalog_sha256=catalog.sha256,
    )
    original_remove_tree_strict = ingestion_module.remove_tree_strict
    cleanup_paths: list[Path] = []

    def fail_diagnosis_cleanup(path: Path, *, context: str) -> None:
        if context != "GLP-1 diagnosis ingestion scratch":
            original_remove_tree_strict(path, context=context)
            return
        cleanup_paths.append(path)
        raise OSError(f"{context} failed")

    monkeypatch.setattr(
        ingestion_module,
        "remove_tree_strict",
        fail_diagnosis_cleanup,
    )
    try:
        with pytest.raises(OSError, match="GLP-1 diagnosis ingestion scratch failed"):
            ingest_core_sources(
                connection,
                input_root=export_root,
                inventory=inventory,
                config=config,
            )
        assert len(cleanup_paths) == 1
        assert cleanup_paths[0].exists()
    finally:
        connection.close()
        for path in cleanup_paths:
            shutil.rmtree(path, ignore_errors=True)


def test_encounter_membership_uses_hash_mark_joins() -> None:
    connection = duckdb.connect()
    try:
        connection.execute(
            "CREATE TEMP TABLE gas_candidate_patient (patient_id VARCHAR)"
        )
        connection.execute(
            "CREATE TEMP TABLE gas_candidate_encounter (encounter_id VARCHAR)"
        )
        connection.execute(
            """
            CREATE TEMP TABLE raw_encounter (
                patient_id VARCHAR,
                encounter_id VARCHAR
            )
            """
        )

        plan_rows = connection.execute(
            "EXPLAIN SELECT * FROM raw_encounter AS raw WHERE "
            + _encounter_membership_sql()
        ).fetchall()
        plan = "\n".join(str(value) for row in plan_rows for value in row)

        assert "BLOCKWISE_NL_JOIN" not in plan
        assert plan.count("Join Type: MARK") == 2
    finally:
        connection.close()


def test_candidate_membership_tables_deduplicate_keys() -> None:
    connection = duckdb.connect()
    try:
        connection.execute(
            "CREATE TABLE gas_candidate_id (patient_id VARCHAR, encounter_id VARCHAR)"
        )
        connection.execute(
            """
            INSERT INTO gas_candidate_id VALUES
                ('p1', 'e1'), ('p1', 'e1'), ('p1', 'e2'),
                ('p2', NULL), (NULL, 'e3')
            """
        )

        _create_candidate_membership_tables(connection)

        assert connection.execute(
            "SELECT patient_id FROM gas_candidate_patient ORDER BY patient_id"
        ).fetchall() == [("p1",), ("p2",)]
        assert connection.execute(
            "SELECT encounter_id FROM gas_candidate_encounter ORDER BY encounter_id"
        ).fetchall() == [("e1",), ("e2",), ("e3",)]
    finally:
        connection.close()


def test_vital_partition_discovery_ignores_appledouble_sidecars(
    tmp_path: Path,
) -> None:
    partition = tmp_path / "patient_bucket=5"
    partition.mkdir()
    data_file = partition / "data_0.parquet"
    data_file.write_bytes(b"PAR1")
    (partition / "._data_0.parquet").write_bytes(b"appledouble")

    assert _partition_parquet_files(partition) == (data_file,)


def test_compiled_concept_membership_preserves_rule_semantics() -> None:
    connection = duckdb.connect()
    try:
        connection.execute(
            """
            CREATE TABLE concept_set (
                domain VARCHAR,
                include BOOLEAN,
                match_type VARCHAR,
                code_system VARCHAR,
                code VARCHAR
            )
            """
        )
        connection.execute(
            """
            INSERT INTO concept_set VALUES
                ('vital', true, 'exact', 'LOINC', '39156-5'),
                ('vital', true, 'exact', 'LOINC', '39156-5'),
                ('vital', true, 'prefix', 'LOINC', '391'),
                ('vital', true, 'prefix', 'ICD10CM', 'J12'),
                ('vital', true, 'regex', 'LOCAL', '^RX[0-9]+$'),
                ('vital', false, 'exact', 'LOINC', '99999-9')
            """
        )
        connection.execute(
            "CREATE TEMP TABLE gas_candidate_patient (patient_id VARCHAR)"
        )
        connection.execute("INSERT INTO gas_candidate_patient VALUES ('p1')")
        connection.execute(
            """
            CREATE TEMP TABLE raw_code (
                row_id INTEGER,
                patient_id VARCHAR,
                code_system VARCHAR,
                code VARCHAR
            )
            """
        )
        connection.execute(
            """
            INSERT INTO raw_code VALUES
                (1, 'p1', 'loinc', '39156-5'),
                (2, 'p1', 'ICD-10-CM', 'J123'),
                (3, 'p1', 'local', 'rx42'),
                (4, 'p1', 'LOINC', '99999-9'),
                (5, 'p2', 'LOINC', '39156-5')
            """
        )

        predicate = (
            _patient_membership_sql("raw")
            + " AND "
            + _concept_membership_sql(connection, "vital", "raw")
        )
        observed = connection.execute(
            "SELECT row_id FROM raw_code AS raw WHERE " + predicate + " ORDER BY row_id"
        ).fetchall()

        assert observed == [(1,), (2,), (3,)]

        mixed_plan_rows = connection.execute(
            "EXPLAIN SELECT * FROM raw_code AS raw WHERE " + predicate
        ).fetchall()
        mixed_plan = "\n".join(str(value) for row in mixed_plan_rows for value in row)
        assert "LEFT_DELIM_JOIN" not in mixed_plan
        assert "BLOCKWISE_NL_JOIN" not in mixed_plan
        assert "concept_set" not in mixed_plan

        connection.execute("DELETE FROM concept_set WHERE match_type != 'exact'")
        plan_rows = connection.execute(
            "EXPLAIN SELECT * FROM raw_code AS raw WHERE "
            + _patient_membership_sql("raw")
            + " AND "
            + _concept_membership_sql(connection, "vital", "raw")
        ).fetchall()
        plan = "\n".join(str(value) for row in plan_rows for value in row)
        assert "LEFT_DELIM_JOIN" not in plan
        assert "BLOCKWISE_NL_JOIN" not in plan
        assert "concept_set" not in plan
    finally:
        connection.close()


def test_core_cohort_uses_first_arterial_result_and_keeps_sensitivities(
    tmp_path: Path,
) -> None:
    export_root = tmp_path / "export"
    _write_export(export_root)
    _append_rows(
        export_root / "Patient" / "patient.csv",
        "p1,F,White,Not Hispanic or Latino,1970,,",
        "p2,M,White,Not Hispanic or Latino,1975,,",
        "p3,F,Black,Hispanic or Latino,1980,,",
        "p4,M,Asian,Unknown,1985,,",
        "p5,F,White,Unknown,1985,,",
    )
    _append_rows(
        export_root / "Encounter" / "encounter.csv",
        "e1,p1,2024-01-01 00:00:00,2024-01-02 00:00:00,IMP,s1",
        "e2,p2,2024-01-01 00:00:00,2024-01-02 00:00:00,IMP,s1",
        "e3,p3,2024-01-01 00:00:00,2024-01-03 12:00:00,EMER,s1",
        "e4,p4,2024-01-01 00:00:00,2024-01-02 00:00:00,EMER,s1",
        "e5,p5,2024-01-01 00:00:00,2024-01-02 00:00:00,EMER,s1",
    )
    _append_rows(
        export_root / "Lab Results" / "lab_results.csv",
        "p1,e1,2024-01-01 01:00:00,LOINC,2019-8,55,,mmHg",
        "p1,e1,2024-01-01 01:00:00,LOINC,2744-1,7.40,,pH",
        "p1,e1,2024-01-01 01:00:00,LOINC,1960-4,30,,mmol/L",
        "p1,e1,2024-01-01 01:00:00,LOINC,1960-4,99,,mg/dL",
        "p1,e1,2024-01-01 01:00:00,LOINC,2703-7,10,,kPa",
        "p1,e1,2024-01-01 01:15:00,LOINC,2703-7,100,,mmHg",
        "p1,e1,2024-01-01 01:00:00,LOINC,2708-6,0.94,,1",
        "p1,e1,2024-01-20 01:00:00,LOINC,2019-8,40,,mmHg",
        "p1,e1,2024-02-01 01:00:00,LOINC,2019-8,55,,mmHg",
        "p2,e2,2024-01-01 01:00:00,LOINC,2026-3,60,,mmol/L",
        "p3,e3,2024-01-01 01:00:00,LOINC,2019-8,40,,mmHg",
        "p3,e3,2024-01-01 01:00:00,LOINC,2744-1,7.40,,pH",
        "p3,e3,2024-01-02 06:00:00,LOINC,2019-8,55,,mmHg",
        "p4,e4,2024-01-01 01:00:00,LOINC,2021-4,55,,mmHg",
        "p4,e4,2024-01-01 01:00:00,LOINC,2746-6,7.40,,pH",
        "p5,e5,2024-01-01 01:00:00,LOINC,11557-6,55,,mmHg",
        "p5,e5,2024-01-01 01:00:00,LOINC,2744-1,7.40,,pH",
    )
    _append_rows(
        export_root / "Vital Signs" / "vital_signs.csv",
        "p1,e1,2023-12-15,LOINC,39156-5,36,,kg/m2",
        "p3,e3,2023-12-15,LOINC,39156-5,32,,kg/m2",
        "p4,e4,2023-12-15,LOINC,39156-5,31,,kg/m2",
        "p5,e5,2023-12-15,LOINC,39156-5,31,,kg/m2",
    )

    report = validate_export(export_root)
    inventory = build_input_inventory(export_root, report)
    config = load_glp1_config(GLP1_CONFIG)
    catalog = load_concept_sets(config.concept_sets_dir)
    connection = initialize_database(
        tmp_path / "glp1.duckdb",
        run_id="synthetic-run",
        input_root=export_root,
        config=config,
        inventory=inventory,
        catalog=catalog,
        git_sha="test-sha",
        concept_catalog_sha256=catalog.sha256,
    )
    try:
        ingest_core_sources(
            connection,
            input_root=export_root,
            inventory=inventory,
            config=config,
        )
        counts = build_core_cohort(
            connection,
            config=config,
            run_id="synthetic-run",
            git_sha="test-sha",
        )

        assert counts.hypercapnia_encounters == 3
        assert counts.patient_index_events == 1
        assert counts.primary_obesity_hypercapnia == 1
        assert counts.evidence_rows == 2
        primary = connection.execute(
            """
            SELECT patient_id, abg_pco2_mm_hg, abg_ph,
                   abg_hco3, abg_po2, abg_sao2,
                   abg_pairing_method, bmi_value,
                   persistent_hypercapnia_14_84d
            FROM analysis_glp1_eligibility
            """
        ).fetchone()
        assert primary == (
            "p1",
            55.0,
            7.4,
            30.0,
            pytest.approx(75.006168270417),
            94.0,
            "exact_timestamp",
            36.0,
            True,
        )
        repeat = connection.execute(
            """
            SELECT repeat_pco2_date, repeat_pco2_value
            FROM cohort_hypercapnia_patient_index
            WHERE patient_id = 'p1'
            """
        ).fetchone()
        assert repeat[0].isoformat() == "2024-02-01T01:00:00"
        assert repeat[1] == 55.0
        later = connection.execute(
            """
            SELECT later_hypercapnia_sensitivity_case,
                   primary_cohort_exclusion_reason,
                   maximum_pco2_in_encounter
            FROM cohort_hypercapnia_encounter WHERE patient_id = 'p3'
            """
        ).fetchone()
        assert later == (True, "first_arterial_pco2_not_elevated", 55.0)
        vbg_only = connection.execute(
            """
            SELECT vbg_only_sensitivity_case,
                   primary_cohort_exclusion_reason
            FROM cohort_hypercapnia_encounter WHERE patient_id = 'p4'
            """
        ).fetchone()
        assert vbg_only == (True, "no_arterial_pco2")
        assert connection.execute(
            "SELECT COUNT(*) FROM cohort_hypercapnia_encounter WHERE patient_id = 'p2'"
        ).fetchone() == (0,)
        assert connection.execute(
            "SELECT COUNT(*) FROM cohort_hypercapnia_encounter WHERE patient_id = 'p5'"
        ).fetchone() == (0,)

        without_vbg = replace(
            config,
            hypercapnia=replace(
                config.hypercapnia,
                include_vbg_secondary_cohort=False,
            ),
        )
        disabled_counts = build_core_cohort(
            connection,
            config=without_vbg,
            run_id="synthetic-run",
            git_sha="test-sha",
        )
        assert disabled_counts.hypercapnia_encounters == 2
        assert connection.execute(
            "SELECT COUNT(*) FROM cohort_hypercapnia_encounter WHERE patient_id = 'p4'"
        ).fetchone() == (0,)
    finally:
        connection.close()


def test_core_cohort_accepts_canonical_ucum_gas_units(tmp_path: Path) -> None:
    export_root = tmp_path / "export"
    _write_export(export_root)
    _append_rows(
        export_root / "Patient" / "patient.csv",
        "p1,F,White,Not Hispanic or Latino,1970,,",
    )
    _append_rows(
        export_root / "Encounter" / "encounter.csv",
        "e1,p1,2024-01-01 00:00:00,2024-01-02 00:00:00,IMP,s1",
    )
    _append_rows(
        export_root / "Lab Results" / "lab_results.csv",
        "p1,e1,2024-01-01 01:00:00,LOINC,2019-8,55,,mm[Hg]",
        "p1,e1,2024-01-01 01:00:00,LOINC,2744-1,7.40,,[pH]",
        "p1,e1,2024-01-01 01:00:00,LOINC,2703-7,75,,mm[Hg]",
    )
    _append_rows(
        export_root / "Vital Signs" / "vital_signs.csv",
        "p1,e1,2023-12-15,LOINC,39156-5,36,,kg/m2",
    )

    report = validate_export(export_root)
    inventory = build_input_inventory(export_root, report)
    config = load_glp1_config(GLP1_CONFIG)
    catalog = load_concept_sets(config.concept_sets_dir)
    connection = initialize_database(
        tmp_path / "glp1.duckdb",
        run_id="ucum-gas-units",
        input_root=export_root,
        config=config,
        inventory=inventory,
        catalog=catalog,
        git_sha="test-sha",
        concept_catalog_sha256=catalog.sha256,
    )
    try:
        ingest_core_sources(
            connection,
            input_root=export_root,
            inventory=inventory,
            config=config,
        )
        counts = build_core_cohort(
            connection,
            config=config,
            run_id="ucum-gas-units",
            git_sha="test-sha",
        )

        assert counts.primary_obesity_hypercapnia == 1
        assert connection.execute(
            """
            SELECT concept_set_id, unit_key, normalized_numeric_value, unit_usable
            FROM normalized_gas_measurement
            ORDER BY concept_set_id
            """
        ).fetchall() == [
            ("arterial_pco2", "mm[hg]", 55.0, True),
            ("arterial_ph", "[ph]", 7.4, True),
            ("arterial_po2", "mm[hg]", 75.0, True),
        ]
        assert connection.execute(
            """
            SELECT abg_pco2_mm_hg, abg_ph, abg_po2
            FROM analysis_glp1_eligibility
            """
        ).fetchone() == (55.0, 7.4, 75.0)
    finally:
        connection.close()


def test_date_only_repeat_pco2_uses_calendar_day_window(tmp_path: Path) -> None:
    export_root = tmp_path / "export"
    _write_export(export_root)
    _append_rows(
        export_root / "Patient" / "patient.csv",
        "p1,F,White,Not Hispanic or Latino,1970,,",
    )
    _append_rows(
        export_root / "Encounter" / "encounter.csv",
        "e1,p1,2024-01-01 12:00:00,2024-01-02 12:00:00,IMP,s1",
    )
    _append_rows(
        export_root / "Lab Results" / "lab_results.csv",
        "p1,e1,2024-01-01 13:00:00,LOINC,2019-8,55,,mmHg",
        "p1,e1,2024-01-01 13:00:00,LOINC,2744-1,7.40,,pH",
        "p1,e1,2024-01-15,LOINC,2019-8,60,,mmHg",
    )
    _append_rows(
        export_root / "Vital Signs" / "vital_signs.csv",
        "p1,e1,2023-12-15,LOINC,39156-5,31,,kg/m2",
    )

    report = validate_export(export_root)
    inventory = build_input_inventory(export_root, report)
    config = load_glp1_config(GLP1_CONFIG)
    catalog = load_concept_sets(config.concept_sets_dir)
    connection = initialize_database(
        tmp_path / "glp1.duckdb",
        run_id="synthetic-run",
        input_root=export_root,
        config=config,
        inventory=inventory,
        catalog=catalog,
        git_sha="test-sha",
        concept_catalog_sha256=catalog.sha256,
    )
    try:
        ingest_core_sources(
            connection,
            input_root=export_root,
            inventory=inventory,
            config=config,
        )
        build_core_cohort(
            connection,
            config=config,
            run_id="synthetic-run",
            git_sha="test-sha",
        )

        repeat = connection.execute(
            """
            SELECT repeat_pco2_date, repeat_pco2_value,
                   persistent_hypercapnia_14_84d
            FROM cohort_hypercapnia_patient_index
            """
        ).fetchone()
        assert repeat[0].isoformat() == "2024-01-15T00:00:00"
        assert repeat[1:] == (60.0, True)
    finally:
        connection.close()


def test_same_encounter_bmi_fallback_handles_missing_encounter_end(
    tmp_path: Path,
) -> None:
    export_root = tmp_path / "export"
    _write_export(export_root)
    _append_rows(
        export_root / "Patient" / "patient.csv",
        "p1,F,White,Not Hispanic or Latino,1970,,",
    )
    _append_rows(
        export_root / "Encounter" / "encounter.csv",
        "e1,p1,2024-01-01 00:00:00,,IMP,s1",
    )
    _append_rows(
        export_root / "Lab Results" / "lab_results.csv",
        "p1,e1,2024-01-01 01:00:00,LOINC,2019-8,55,,mmHg",
        "p1,e1,2024-01-01 01:00:00,LOINC,2744-1,7.40,,pH",
    )
    _append_rows(
        export_root / "Vital Signs" / "vital_signs.csv",
        "p1,e1,2024-01-01 12:00:00,LOINC,39156-5,36,,kg/m2",
    )

    report = validate_export(export_root)
    inventory = build_input_inventory(export_root, report)
    config = load_glp1_config(GLP1_CONFIG)
    catalog = load_concept_sets(config.concept_sets_dir)
    connection = initialize_database(
        tmp_path / "glp1.duckdb",
        run_id="synthetic-run",
        input_root=export_root,
        config=config,
        inventory=inventory,
        catalog=catalog,
        git_sha="test-sha",
        concept_catalog_sha256=catalog.sha256,
    )
    try:
        ingest_core_sources(
            connection,
            input_root=export_root,
            inventory=inventory,
            config=config,
        )
        counts = build_core_cohort(
            connection,
            config=config,
            run_id="synthetic-run",
            git_sha="test-sha",
        )

        assert counts.patient_index_events == 1
        assert counts.primary_obesity_hypercapnia == 1
        assert connection.execute(
            """
            SELECT bmi_source, bmi_value
            FROM analysis_glp1_eligibility
            """
        ).fetchone() == ("measured_index_encounter", 36.0)
    finally:
        connection.close()


def test_first_arterial_gas_is_selected_before_unit_and_plausibility_filters(
    tmp_path: Path,
) -> None:
    export_root = tmp_path / "export"
    _write_export(export_root)
    _append_rows(
        export_root / "Patient" / "patient.csv",
        "bad_unit,F,White,Unknown,1970,,",
        "bad_value,F,White,Unknown,1970,,",
    )
    _append_rows(
        export_root / "Encounter" / "encounter.csv",
        "e_bad_unit,bad_unit,2024-01-01,2024-01-02,IMP,s1",
        "e_bad_value,bad_value,2024-01-01,2024-01-02,IMP,s1",
    )
    _append_rows(
        export_root / "Lab Results" / "lab_results.csv",
        "bad_unit,e_bad_unit,2024-01-01 01:00:00,LOINC,2019-8,55,,mmol/L",
        "bad_unit,e_bad_unit,2024-01-01 01:00:00,LOINC,2744-1,7.40,,pH",
        "bad_unit,e_bad_unit,2024-01-01 02:00:00,LOINC,2019-8,60,,mmHg",
        "bad_value,e_bad_value,2024-01-01 01:00:00,LOINC,2019-8,500,,mmHg",
        "bad_value,e_bad_value,2024-01-01 01:00:00,LOINC,2744-1,7.40,,pH",
        "bad_value,e_bad_value,2024-01-01 02:00:00,LOINC,2019-8,60,,mmHg",
    )

    report = validate_export(export_root)
    inventory = build_input_inventory(export_root, report)
    config = load_glp1_config(GLP1_CONFIG)
    catalog = load_concept_sets(config.concept_sets_dir)
    connection = initialize_database(
        tmp_path / "glp1.duckdb",
        run_id="synthetic-run",
        input_root=export_root,
        config=config,
        inventory=inventory,
        catalog=catalog,
        git_sha="test-sha",
        concept_catalog_sha256=catalog.sha256,
    )
    try:
        ingest_core_sources(
            connection,
            input_root=export_root,
            inventory=inventory,
            config=config,
        )
        counts = build_core_cohort(
            connection,
            config=config,
            run_id="synthetic-run",
            git_sha="test-sha",
        )

        assert counts.hypercapnia_encounters == 2
        assert counts.patient_index_events == 0
        observed = connection.execute(
            """
            SELECT patient_id, abg_pco2_raw, abg_pco2_mm_hg,
                   maximum_pco2_in_encounter, implausible_value,
                   primary_cohort_exclusion_reason
            FROM cohort_hypercapnia_encounter
            ORDER BY patient_id
            """
        ).fetchall()
        assert observed == [
            (
                "bad_unit",
                "55",
                None,
                60.0,
                True,
                "first_arterial_pco2_unit_unusable",
            ),
            (
                "bad_value",
                "500",
                500.0,
                60.0,
                True,
                "first_arterial_pco2_implausible",
            ),
        ]
    finally:
        connection.close()


def test_component_phenotypes_are_temporal_and_evidence_based(
    tmp_path: Path,
) -> None:
    export_root = tmp_path / "export"
    output_root = tmp_path / "output" / "glp1_eligibility"
    _write_export(export_root)
    patients = (
        "t2d",
        "post_only",
        "htn_one",
        "htn_two",
        "ckd_single",
        "ckd_persistent",
        "osa_code",
        "osa_ahi",
        "antipsychotic_only",
        "antipsychotic_metabolic",
    )
    _append_rows(
        export_root / "Patient" / "patient.csv",
        *(f"{patient},F,White,Not Hispanic or Latino,1970,," for patient in patients),
    )
    _append_rows(
        export_root / "Encounter" / "encounter.csv",
        *(
            f"e_{patient},{patient},2024-01-01 00:00:00,"
            "2024-01-02 00:00:00,IMP,s1"
            for patient in patients
        ),
    )
    lab_rows: list[str] = []
    vital_rows: list[str] = []
    for patient in patients:
        encounter = f"e_{patient}"
        lab_rows.extend(
            (
                f"{patient},{encounter},2024-01-01 01:00:00,"
                "LOINC,2019-8,55,,mmHg",
                f"{patient},{encounter},2024-01-01 01:00:00,"
                "LOINC,2744-1,7.40,,pH",
            )
        )
        bmi = 25 if patient == "antipsychotic_only" else 31
        vital_rows.append(
            f"{patient},{encounter},2023-12-15,LOINC,39156-5,{bmi},,kg/m2"
        )
    lab_rows.extend(
        (
            "ckd_single,e_ckd_single,2023-12-01,LOINC,77147-7,45,,"
            "mL/min/1.73m2",
            "ckd_persistent,e_ckd_persistent,2023-05-01,LOINC,77147-7,45,,"
            "mL/min/1.73m2",
            "ckd_persistent,e_ckd_persistent,2023-12-01,LOINC,77147-7,50,,"
            "mL/min/1.73m2",
            "osa_ahi,e_osa_ahi,2023-12-01,LOINC,69990-9,20,,events/hour",
        )
    )
    vital_rows.extend(
        (
            "htn_one,e_htn_one,2023-12-20,LOINC,8480-6,150,,mmHg",
            "htn_one,e_htn_one,2023-12-20,LOINC,8462-4,95,,mmHg",
            "htn_two,e_htn_two,2023-12-20,LOINC,8480-6,150,,mmHg",
            "htn_two,e_htn_two,2023-12-20,LOINC,8462-4,95,,mmHg",
        )
    )
    _append_rows(export_root / "Lab Results" / "lab_results.csv", *lab_rows)
    _append_rows(export_root / "Vital Signs" / "vital_signs.csv", *vital_rows)
    _append_rows(
        export_root / "Diagnosis" / "diagnosis.csv",
        "t2d,e_t2d,2023-12-01,ICD-10-CM,E11.9,,,,",
        "post_only,e_post_only,2024-01-02,ICD10CM,E11.9,,,,",
        "osa_code,e_osa_code,2023-12-01,ICD10CM,G47.33,,,,",
    )
    _append_rows(
        export_root / "Medications" / "medication.csv",
        "htn_one,e_htn_one,RXNORM,29046,2023-01-01,oral,,",
        "htn_two,e_htn_two,RXNORM,29046,2023-01-01,oral,,",
        "htn_two,e_htn_two,RXNORM,17767,2023-01-01,oral,,",
        "antipsychotic_only,e_antipsychotic_only,RXNORM,2626,"
        "2023-01-01,oral,,",
        "antipsychotic_metabolic,e_antipsychotic_metabolic,RXNORM,2626,"
        "2023-01-01,oral,,",
    )

    build_glp1_eligibility(
        input_root=export_root,
        output_dir=output_root,
        config_path=GLP1_CONFIG,
    )
    connection = duckdb.connect(
        str(output_root / "glp1_hypercapnia.duckdb"), read_only=True
    )
    try:
        rows = connection.execute(
            """
            SELECT patient_id, t2d_status, payer_route_model,
                   uncontrolled_hypertension_two_meds_status,
                   bridge_clinical_criteria_status,
                   egfr_persistent_lt60, ckd_stage_3a_plus_status,
                   osa_any_status, osa_moderate_severe_status,
                   ind_fda_moderate_severe_osa,
                   metabolic_dysfunction_status,
                   ind_rct_antipsychotic_metabolic
            FROM analysis_glp1_eligibility
            """
        ).fetchall()
        by_patient = {row[0]: row[1:] for row in rows}

        assert by_patient["t2d"][:2] == ("met", "part_d_disease_route")
        assert by_patient["post_only"][0] == "indeterminate"
        assert by_patient["htn_one"][2:4] == ("not_met", "indeterminate")
        assert by_patient["htn_two"][2:4] == ("met", "met")
        assert by_patient["ckd_single"][4:6] == (False, "indeterminate")
        assert by_patient["ckd_persistent"][4:6] == (True, "met")
        assert by_patient["osa_code"][6:9] == (
            "met",
            "indeterminate",
            None,
        )
        assert by_patient["osa_ahi"][6:9] == ("indeterminate", "met", True)
        assert by_patient["antipsychotic_only"][9:] == ("not_met", None)
        assert by_patient["antipsychotic_metabolic"][9:] == ("met", True)
        assert by_patient["antipsychotic_only"][1] == "no_documented_route"

        indication_columns = [
            row[0]
            for row in connection.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = 'analysis_glp1_eligibility'
                  AND starts_with(column_name, 'ind_')
                  AND data_type = 'BOOLEAN'
                ORDER BY ordinal_position
                """
            ).fetchall()
        ]
        for column in indication_columns:
            nonnull_rows = connection.execute(
                f'SELECT COUNT(*) FROM analysis_glp1_eligibility '
                f'WHERE "{column}" IS NOT NULL'
            ).fetchone()[0]
            evidence_rows = connection.execute(
                """
                SELECT COUNT(*) FROM eligibility_evidence_long
                WHERE rule_id = ?
                """,
                [column],
            ).fetchone()[0]
            assert evidence_rows == nonnull_rows, column
        assert connection.execute(
            """
            SELECT COUNT(*) FROM eligibility_evidence_long
            WHERE patient_id = 'post_only'
              AND rule_id = 'source:type_2_diabetes'
            """
        ).fetchone() == (0,)
    finally:
        connection.close()


def test_medication_ingredients_and_unmapped_raw_history_are_observable(
    tmp_path: Path,
) -> None:
    export_root = tmp_path / "export"
    output_root = tmp_path / "output" / "glp1_eligibility"
    _write_export(export_root)
    ingredient_path = export_root / "Medications" / "medication_ingredient.csv"
    ingredient_path.write_text(
        "patient_id,encounter_id,unique_id,code_system,code,start_date,route,"
        "brand,strength,derived_by_TriNetX,source_id\n"
    )
    _append_primary_cases(export_root, {"ingredient": 31, "unmapped": 31})
    _append_rows(
        ingredient_path,
        "ingredient,e_ingredient,uid-1,RXNORM,1991302,2023-12-01,oral,"
        "Wegovy,2.4mg,,s1",
    )
    _append_rows(
        export_root / "Diagnosis" / "diagnosis.csv",
        "unmapped,e_unmapped,2023-12-01,LOCAL,UNMAPPED_DIAGNOSIS,,,,",
    )
    _append_rows(
        export_root / "Lab Results" / "lab_results.csv",
        "unmapped,e_unmapped,2023-12-02,LOCAL,UNMAPPED_LAB,1,,arbitrary",
    )
    _append_rows(
        export_root / "Medications" / "medication.csv",
        "unmapped,e_unmapped,LOCAL,UNMAPPED_MEDICATION,2023-12-03,oral,,",
    )

    build_glp1_eligibility(
        input_root=export_root,
        output_dir=output_root,
        config_path=GLP1_CONFIG,
    )

    connection = duckdb.connect(str(output_root / "glp1_hypercapnia.duckdb"))
    try:
        ingredient = connection.execute(
            """
            SELECT glp1_ever_ordered_pre_index, glp1_ingredient_at_index
            FROM analysis_glp1_eligibility
            WHERE patient_id = 'ingredient'
            """
        ).fetchone()
        assert ingredient == (True, "semaglutide")
        assert connection.execute(
            """
            SELECT source_file FROM source_medication
            WHERE patient_id = 'ingredient'
            """
        ).fetchone() == ("Medications/medication_ingredient.csv",)

        observability = connection.execute(
            """
            SELECT diagnosis_event_count_730d, lab_event_count_365d,
                   medication_event_count_730d, has_medication_history
            FROM analysis_glp1_eligibility
            WHERE patient_id = 'unmapped'
            """
        ).fetchone()
        assert observability == (1, 1, 1, True)
        assert connection.execute(
            "SELECT COUNT(*) FROM source_medication WHERE patient_id = 'unmapped'"
        ).fetchone() == (0,)
    finally:
        connection.close()


def test_component_history_excludes_events_before_configured_lookbacks(
    tmp_path: Path,
) -> None:
    export_root = tmp_path / "export"
    output_root = tmp_path / "output" / "glp1_eligibility"
    _write_export(export_root)
    _append_primary_cases(export_root, {"stale_history": 31})
    _append_rows(
        export_root / "Diagnosis" / "diagnosis.csv",
        "stale_history,e_stale_history,2020-01-01,ICD10CM,E11.9,,,,",
    )
    _append_rows(
        export_root / "Procedure" / "procedure.csv",
        "stale_history,e_stale_history,2020-01-01,CPT,95811,",
    )
    _append_rows(
        export_root / "Lab Results" / "lab_results.csv",
        "stale_history,e_stale_history,2022-12-01,LOINC,4548-4,8,,%",
        "stale_history,e_stale_history,2022-09-01,LOINC,77147-7,45,,"
        "mL/min/1.73m2",
        "stale_history,e_stale_history,2022-12-15,LOINC,77147-7,50,,"
        "mL/min/1.73m2",
        "stale_history,e_stale_history,2022-12-01,LOINC,69990-9,20,,"
        "events/hour",
        "stale_history,e_stale_history,2022-12-01,LOINC,10230-1,55,,%",
        "stale_history,e_stale_history,2022-12-01,LOINC,48794-2,,F2,stage",
    )
    _append_rows(
        export_root / "Medications" / "medication.csv",
        "stale_history,e_stale_history,RXNORM,29046,2020-01-01,oral,,",
        "stale_history,e_stale_history,RXNORM,2626,2020-01-01,oral,,",
    )

    build_glp1_eligibility(
        input_root=export_root,
        output_dir=output_root,
        config_path=GLP1_CONFIG,
    )
    connection = duckdb.connect(
        str(output_root / "glp1_hypercapnia.duckdb"), read_only=True
    )
    try:
        row = connection.execute(
            """
            SELECT t2d_status, pap_evidence,
                   active_antihypertensive_ingredient_count,
                   antipsychotic_active, a1c_latest, egfr_latest,
                   ahi_rei_value, lvef, fibrosis_stage,
                   has_a1c, has_egfr_history, has_ahi_rei, has_lvef,
                   has_liver_fibrosis_staging
            FROM analysis_glp1_eligibility
            WHERE patient_id = 'stale_history'
            """
        ).fetchone()
        assert row == (
            "indeterminate",
            False,
            0,
            False,
            None,
            None,
            None,
            None,
            None,
            False,
            False,
            False,
            False,
            False,
        )
    finally:
        connection.close()


def test_mash_strict_status_requires_f2_f3_and_no_cirrhosis(
    tmp_path: Path,
) -> None:
    export_root = tmp_path / "export"
    output_root = tmp_path / "output" / "glp1_eligibility"
    _write_export(export_root)
    _append_primary_cases(
        export_root,
        {"mash_f2": 31, "mash_f3_cirrhosis": 31, "mash_unstaged": 31},
    )
    _append_rows(
        export_root / "Diagnosis" / "diagnosis.csv",
        "mash_f2,e_mash_f2,2023-12-01,ICD10CM,K75.81,,,,",
        "mash_f3_cirrhosis,e_mash_f3_cirrhosis,2023-12-01,"
        "ICD10CM,K75.81,,,,",
        "mash_f3_cirrhosis,e_mash_f3_cirrhosis,2023-12-01,"
        "ICD10CM,K74.60,,,,",
        "mash_unstaged,e_mash_unstaged,2023-12-01,ICD10CM,K75.81,,,,",
    )
    _append_rows(
        export_root / "Procedure" / "procedure.csv",
        "mash_f2,e_mash_f2,2023-12-01,CPT,47000,",
        "mash_f3_cirrhosis,e_mash_f3_cirrhosis,2023-12-01,CPT,47000,",
    )
    _append_rows(
        export_root / "Lab Results" / "lab_results.csv",
        "mash_f2,e_mash_f2,2023-12-01,LOINC,48794-2,,F2,stage",
        "mash_f3_cirrhosis,e_mash_f3_cirrhosis,2023-12-01,"
        "LOINC,48794-2,,F3,stage",
    )

    build_glp1_eligibility(
        input_root=export_root,
        output_dir=output_root,
        config_path=GLP1_CONFIG,
    )
    connection = duckdb.connect(
        str(output_root / "glp1_hypercapnia.duckdb"), read_only=True
    )
    try:
        rows = connection.execute(
            """
            SELECT patient_id, mash_f2_f3_status, mash_f2_f3_certainty,
                   fibrosis_stage, fibrosis_method,
                   ind_fda_noncirrhotic_mash_f2_f3
            FROM analysis_glp1_eligibility
            """
        ).fetchall()
        by_patient = {row[0]: row[1:] for row in rows}
        assert by_patient["mash_f2"] == (
            "met",
            "strict",
            "F2",
            "biopsy",
            True,
        )
        assert by_patient["mash_f3_cirrhosis"] == (
            "not_met",
            "strict",
            "F3",
            "biopsy",
            None,
        )
        assert by_patient["mash_unstaged"] == (
            "indeterminate",
            "not_applicable",
            None,
            None,
            None,
        )
    finally:
        connection.close()


def test_bridge_branches_missing_bmi_and_glp1_order_timing(
    tmp_path: Path,
) -> None:
    export_root = tmp_path / "export"
    output_root = tmp_path / "output" / "glp1_eligibility"
    _write_export(export_root)
    _append_primary_cases(
        export_root,
        {
            "bmi35": 36,
            "hfpef": 31,
            "hfpef_code_only": 31,
            "prediabetes": 28,
            "weight_only": 31,
        },
    )
    _append_rows(
        export_root / "Patient" / "patient.csv",
        "missing_bmi,F,White,Not Hispanic or Latino,1970,,",
    )
    _append_rows(
        export_root / "Encounter" / "encounter.csv",
        "e_missing_bmi,missing_bmi,2024-01-01 00:00:00,"
        "2024-01-02 00:00:00,IMP,s1",
    )
    _append_rows(
        export_root / "Lab Results" / "lab_results.csv",
        "missing_bmi,e_missing_bmi,2024-01-01 01:00:00,"
        "LOINC,2019-8,55,,mmHg",
        "missing_bmi,e_missing_bmi,2024-01-01 01:00:00,"
        "LOINC,2744-1,7.40,,pH",
        "hfpef,e_hfpef,2023-12-01,LOINC,10230-1,55,,%",
        "prediabetes,e_prediabetes,2023-12-01,LOINC,4548-4,6.0,,%",
    )
    _append_rows(
        export_root / "Diagnosis" / "diagnosis.csv",
        "hfpef,e_hfpef,2023-12-01,ICD10CM,I50.3,,,,",
        "hfpef_code_only,e_hfpef_code_only,2023-12-01,ICD10CM,I50.3,,,,",
    )
    _append_rows(
        export_root / "Medications" / "medication.csv",
        "bmi35,e_bmi35,RXNORM,1991302,2023-12-01,"
        "subcutaneous,Wegovy,2.4mg",
        "bmi35,e_bmi35,RXNORM,1991302,2024-01-15,"
        "subcutaneous,Ozempic,1mg",
    )

    build_glp1_eligibility(
        input_root=export_root,
        output_dir=output_root,
        config_path=GLP1_CONFIG,
    )
    connection = duckdb.connect(
        str(output_root / "glp1_hypercapnia.duckdb"), read_only=True
    )
    try:
        rows = connection.execute(
            """
            SELECT patient_id, bridge_clinical_criteria_status,
                   bridge_qualifying_branch, payer_route_model,
                   hfpef_status, hfpef_certainty, prediabetes_status,
                   obesity_status, ind_fda_weight_management,
                   glp1_ever_ordered_pre_index, glp1_active_at_index,
                   glp1_ingredient_at_index, glp1_product_at_index,
                   glp1_new_order_30d, glp1_new_order_90d,
                   glp1_new_order_365d
            FROM analysis_glp1_eligibility
            """
        ).fetchall()
        by_patient = {row[0]: row[1:] for row in rows}
        assert by_patient["bmi35"][:3] == (
            "met",
            "bmi_ge35",
            "bridge_clinical_route",
        )
        assert by_patient["hfpef"][:5] == (
            "met",
            "bmi_ge30_comorbidity",
            "bridge_clinical_route",
            "met",
            "strict",
        )
        code_only_hfpef = connection.execute(
            """
            SELECT hfpef_status, hfpef_certainty,
                   ind_guideline_obesity_related_hfpef,
                   ind_rct_obesity_related_hfpef,
                   bridge_clinical_criteria_status,
                   bridge_qualifying_components,
                   payer_route_model
            FROM analysis_glp1_eligibility
            WHERE patient_id = 'hfpef_code_only'
            """
        ).fetchone()
        assert code_only_hfpef == (
            "met",
            "code_only",
            None,
            None,
            "indeterminate",
            "",
            "weight_label_only",
        )
        assert by_patient["prediabetes"][:7] == (
            "met",
            "bmi_ge27_comorbidity",
            "bridge_clinical_route",
            "indeterminate",
            "not_applicable",
            "met",
            "not_met",
        )
        assert by_patient["prediabetes"][7] is True
        assert by_patient["missing_bmi"][6:8] == ("indeterminate", None)
        assert by_patient["weight_only"][:3] == (
            "indeterminate",
            None,
            "weight_label_only",
        )
        assert by_patient["bmi35"][8:] == (
            True,
            True,
            "semaglutide",
            "Wegovy",
            True,
            True,
            True,
        )
        observability = connection.execute(
            """
            SELECT first_observed_event_date, lookback_observation_days,
                   encounter_count_365d, diagnosis_event_count_730d,
                   lab_event_count_365d, medication_event_count_730d
            FROM analysis_glp1_eligibility
            WHERE patient_id = 'bmi35'
            """
        ).fetchone()
        assert observability[0].isoformat() == "2023-12-01T00:00:00"
        assert observability[1:] == (31, 1, 0, 0, 1)
    finally:
        connection.close()


def test_latest_lab_values_break_timestamp_ties_by_source_hash(
    tmp_path: Path,
) -> None:
    tied_rows = (
        "ties,e_ties,2023-12-01,LOINC,4548-4,6.0,,%",
        "ties,e_ties,2023-12-01,LOINC,4548-4,8.0,,%",
        "ties,e_ties,2023-12-01,LOINC,69990-9,10,,events/hour",
        "ties,e_ties,2023-12-01,LOINC,69990-9,20,,events/hour",
        "ties,e_ties,2023-12-01,LOINC,10230-1,45,,%",
        "ties,e_ties,2023-12-01,LOINC,10230-1,55,,%",
        "ties,e_ties,2023-12-01,LOINC,48794-2,,F1,stage",
        "ties,e_ties,2023-12-01,LOINC,48794-2,,F3,stage",
    )
    results: list[tuple[object, ...]] = []
    for run_name, rows in (("forward", tied_rows), ("reverse", tied_rows[::-1])):
        export_root = tmp_path / run_name / "export"
        output_root = tmp_path / run_name / "output" / "glp1_eligibility"
        _write_export(export_root)
        _append_primary_cases(export_root, {"ties": 31})
        _append_rows(export_root / "Lab Results" / "lab_results.csv", *rows)

        build_glp1_eligibility(
            input_root=export_root,
            output_dir=output_root,
            config_path=GLP1_CONFIG,
        )
        connection = duckdb.connect(
            str(output_root / "glp1_hypercapnia.duckdb"), read_only=True
        )
        try:
            results.append(
                connection.execute(
                    """
                    SELECT a1c_latest, ahi_rei_value, lvef, fibrosis_stage,
                           hfpef_status, hfpef_certainty
                    FROM analysis_glp1_eligibility
                    WHERE patient_id = 'ties'
                    """
                ).fetchone()
            )
        finally:
            connection.close()

    assert results[0] == results[1]
    assert results[0][0] in (6.0, 8.0)
    assert results[0][1] in (10.0, 20.0)
    assert results[0][2] in (45.0, 55.0)
    assert results[0][3] in ("F1", "F3")


def test_active_glp1_selection_breaks_timestamp_ties_by_source_hash(
    tmp_path: Path,
) -> None:
    tied_rows = (
        "ties,e_ties,RXNORM,1991302,2023-12-01,subcutaneous,Wegovy,2.4mg",
        "ties,e_ties,RXNORM,475968,2023-12-01,subcutaneous,Saxenda,3mg",
    )
    results: list[tuple[str, str]] = []
    for run_name, rows in (("forward", tied_rows), ("reverse", tied_rows[::-1])):
        export_root = tmp_path / run_name / "export"
        output_root = tmp_path / run_name / "output" / "glp1_eligibility"
        _write_export(export_root)
        _append_primary_cases(export_root, {"ties": 31})
        _append_rows(export_root / "Medications" / "medication.csv", *rows)

        build_glp1_eligibility(
            input_root=export_root,
            output_dir=output_root,
            config_path=GLP1_CONFIG,
        )
        connection = duckdb.connect(
            str(output_root / "glp1_hypercapnia.duckdb"), read_only=True
        )
        try:
            results.append(
                connection.execute(
                    """
                    SELECT glp1_ingredient_at_index, glp1_product_at_index
                    FROM analysis_glp1_eligibility
                    WHERE patient_id = 'ties'
                    """
                ).fetchone()
            )
        finally:
            connection.close()

    assert results[0] == results[1]
    assert results[0] in (("semaglutide", "Wegovy"), ("liraglutide", "Saxenda"))


def test_index_context_is_separate_from_pre_index_history(tmp_path: Path) -> None:
    export_root = tmp_path / "export"
    output_root = tmp_path / "output" / "glp1_eligibility"
    _write_export(export_root)
    _append_primary_cases(export_root, {"context": 31})
    _append_rows(
        export_root / "Diagnosis" / "diagnosis.csv",
        "context,e_context,2023-12-01,ICD10CM,J18.9,,,,",
        "context,e_context,2024-01-01 12:00:00,ICD10CM,I46.9,,,,",
        "context,e_context,2024-01-01 12:00:00,ICD10CM,I50.9,,,,",
        "context,e_context,2024-01-01 12:00:00,ICD10CM,T07.XXXA,,,,",
    )
    _append_rows(
        export_root / "Procedure" / "procedure.csv",
        "context,e_context,2024-01-01 00:30:00,CPT,99152,",
        "context,e_context,2024-01-01 00:45:00,CPT,00100,",
        "context,e_context,2024-01-01 12:00:00,CPT,94002,",
    )

    build_glp1_eligibility(
        input_root=export_root,
        output_dir=output_root,
        config_path=GLP1_CONFIG,
    )
    connection = duckdb.connect(
        str(output_root / "glp1_hypercapnia.duckdb"), read_only=True
    )
    try:
        context = connection.execute(
            """
            SELECT cardiac_arrest_context, major_trauma_context,
                   procedure_sedation_context, postoperative_context,
                   pneumonia_lri_at_index,
                   heart_failure_at_index, invasive_ventilation_at_index,
                   heart_failure_status
            FROM analysis_glp1_eligibility
            """
        ).fetchone()
        assert context == (
            True,
            True,
            True,
            True,
            False,
            True,
            True,
            "indeterminate",
        )
        assert connection.execute(
            """
            SELECT cardiac_arrest_context
            FROM cohort_hypercapnia_encounter
            """
        ).fetchone() == (True,)
    finally:
        connection.close()


def test_date_only_context_rows_match_same_encounter_date(tmp_path: Path) -> None:
    export_root = tmp_path / "export"
    output_root = tmp_path / "output" / "glp1_eligibility"
    _write_export(export_root)
    _append_rows(
        export_root / "Patient" / "patient.csv",
        "date_only,F,White,Not Hispanic or Latino,1970,,",
    )
    _append_rows(
        export_root / "Encounter" / "encounter.csv",
        "e_date_only,date_only,2024-01-01 12:00:00,"
        "2024-01-02 12:00:00,IMP,s1",
    )
    _append_rows(
        export_root / "Lab Results" / "lab_results.csv",
        "date_only,e_date_only,2024-01-01 13:00:00,LOINC,2019-8,55,,mmHg",
        "date_only,e_date_only,2024-01-01 13:00:00,LOINC,2744-1,7.40,,pH",
    )
    _append_rows(
        export_root / "Vital Signs" / "vital_signs.csv",
        "date_only,e_date_only,2023-12-15,LOINC,39156-5,31,,kg/m2",
    )
    _append_rows(
        export_root / "Diagnosis" / "diagnosis.csv",
        "date_only,e_date_only,2024-01-01,ICD10CM,I46.9,,,,",
        "date_only,e_date_only,2024-01-01,ICD10CM,T07.XXXA,,,,",
    )
    _append_rows(
        export_root / "Procedure" / "procedure.csv",
        "date_only,e_date_only,2024-01-01,CPT,99152,",
        "date_only,e_date_only,2024-01-01,CPT,00100,",
        "date_only,e_date_only,2024-01-01,CPT,94002,",
    )

    build_glp1_eligibility(
        input_root=export_root,
        output_dir=output_root,
        config_path=GLP1_CONFIG,
    )
    connection = duckdb.connect(
        str(output_root / "glp1_hypercapnia.duckdb"), read_only=True
    )
    try:
        assert connection.execute(
            """
            SELECT cardiac_arrest_context, major_trauma_context,
                   procedure_sedation_context, postoperative_context,
                   invasive_ventilation_at_index
            FROM analysis_glp1_eligibility
            """
        ).fetchone() == (True, True, True, True, True)
        assert connection.execute(
            "SELECT count(*) FROM analysis_primary_cleaned_obesity_hypercapnia"
        ).fetchone() == (0,)
    finally:
        connection.close()


def test_probable_venous_specimen_is_retained_but_excluded_from_cleaned_view(
    tmp_path: Path,
) -> None:
    export_root = tmp_path / "export"
    output_root = tmp_path / "output" / "glp1_eligibility"
    _write_export(export_root)
    (export_root / "Lab Results" / "lab_results.csv").write_text(
        "patient_id,encounter_id,date,code_system,code,lab_result_num_val,"
        "lab_result_text_val,units_of_measure,specimen\n"
    )
    _append_primary_cases(export_root, {"venous_label": 31})
    lab_path = export_root / "Lab Results" / "lab_results.csv"
    rows = lab_path.read_text().splitlines()
    lab_path.write_text(
        "\n".join(
            [rows[0]]
            + [
                row + (",Venous blood" if ",2019-8," in row else ",Arterial blood")
                for row in rows[1:]
            ]
        )
        + "\n"
    )

    build_glp1_eligibility(
        input_root=export_root,
        output_dir=output_root,
        config_path=GLP1_CONFIG,
    )
    connection = duckdb.connect(
        str(output_root / "glp1_hypercapnia.duckdb"), read_only=True
    )
    try:
        assert connection.execute(
            """
            SELECT probable_venous_specimen
            FROM analysis_glp1_eligibility
            """
        ).fetchone() == (True,)
        assert connection.execute(
            "SELECT count(*) FROM analysis_primary_obesity_hypercapnia"
        ).fetchone() == (1,)
        assert connection.execute(
            "SELECT count(*) FROM analysis_primary_cleaned_obesity_hypercapnia"
        ).fetchone() == (0,)
    finally:
        connection.close()


def test_build_publishes_required_core_outputs_and_reuses_identical_run(
    tmp_path: Path,
) -> None:
    export_root = tmp_path / "export"
    output_root = tmp_path / "output" / "glp1_eligibility"
    _write_export(export_root)
    _append_rows(
        export_root / "Patient" / "patient.csv",
        "p1,F,White,Not Hispanic or Latino,1970,,",
    )
    _append_rows(
        export_root / "Encounter" / "encounter.csv",
        "e1,p1,2024-01-01 00:00:00,2024-01-02 00:00:00,IMP,s1",
    )
    _append_rows(
        export_root / "Lab Results" / "lab_results.csv",
        "p1,e1,2024-01-01 01:00:00,LOINC,2019-8,55,,mmHg",
        "p1,e1,2024-01-01 01:00:00,LOINC,2744-1,7.40,,pH",
    )
    _append_rows(
        export_root / "Vital Signs" / "vital_signs.csv",
        "p1,e1,2023-12-15,LOINC,39156-5,36,,kg/m2",
    )
    _append_rows(
        export_root / "Diagnosis" / "diagnosis.csv",
        "p1,e1,2023-12-15,LOCAL,UNMAPPED_BUILD_CODE,,,",
    )

    first = build_glp1_eligibility(
        input_root=export_root,
        output_dir=output_root,
        config_path=GLP1_CONFIG,
    )

    required = {
        "glp1_hypercapnia.duckdb",
        "analysis_glp1_eligibility.parquet",
        "eligibility_evidence_long.parquet",
        "cohort_hypercapnia_encounter.parquet",
        "cohort_flow.csv",
        "data_dictionary.csv",
        "data_quality_report.html",
        "run_manifest.json",
    }
    assert required <= {path.name for path in output_root.iterdir()}
    assert required == {path.name for path in first.output_paths}
    assert not (output_root / "glp1_hypercapnia.duckdb.wal").exists()
    manifest = json.loads((output_root / "run_manifest.json").read_text())
    assert manifest["duckdb_memory_limit_mib"] == 4096
    assert manifest["duckdb_threads"] == 1
    assert first.counts.patient_index_events == 1
    summary = summarize_database(output_root / "glp1_hypercapnia.duckdb")
    assert summary["primary_obesity_hypercapnia"] == 1
    assert summary["warning_count"] == 0
    dictionary_rows = list(
        csv.DictReader((output_root / "data_dictionary.csv").open())
    )
    assert dictionary_rows
    assert all(row["description"].strip() for row in dictionary_rows)
    qa_text = (output_root / "data_quality_report.html").read_text()
    for section in (
        "Retained source date coverage",
        "Concept-matched code systems",
        "High-frequency unmapped source codes",
        "Blood-gas pairing",
        "BMI source distribution",
        "Phenotype missingness",
        "Concept-set match coverage",
        "Build warnings",
        "Sensitivity cohorts",
    ):
        assert section in qa_text
    connection = duckdb.connect(
        str(output_root / "glp1_hypercapnia.duckdb"), read_only=True
    )
    try:
        database_rows = connection.execute(
            "SELECT COUNT(*) FROM analysis_glp1_eligibility"
        ).fetchone()[0]
        parquet_rows = connection.execute(
            "SELECT COUNT(*) FROM read_parquet(?)",
            [str(output_root / "analysis_glp1_eligibility.parquet")],
        ).fetchone()[0]
        assert database_rows == parquet_rows == 1
        manifest_dates = connection.execute(
            "SELECT source_min_date, source_max_date FROM run_manifest"
        ).fetchone()
        assert all(value is not None for value in manifest_dates)
        assert connection.execute(
            """
            SELECT logical_domain, code_system, code, estimated_count, max_error
            FROM unmapped_code_frequency
            WHERE code = 'UNMAPPED_BUILD_CODE'
            """
        ).fetchone() == (
            "diagnosis",
            "LOCAL",
            "UNMAPPED_BUILD_CODE",
            1,
            0,
        )
        expected_views = {
            "analysis_primary_obesity_hypercapnia",
            "analysis_primary_cleaned_obesity_hypercapnia",
            "analysis_documented_indication_prevalence",
            "analysis_evaluable_indication_prevalence",
            "analysis_indication_overlap",
            "analysis_treatment_gap",
            "analysis_missingness",
        }
        actual_views = {
            row[0]
            for row in connection.execute(
                """
                SELECT table_name FROM information_schema.tables
                WHERE table_schema = 'main' AND table_type = 'VIEW'
                """
            ).fetchall()
        }
        assert expected_views <= actual_views
        flow = connection.execute(
            "SELECT stage_order, stage FROM cohort_flow ORDER BY stage_order"
        ).fetchall()
        assert flow == [
            (1, "source_patients"),
            (2, "adult_candidate_emergency_inpatient_encounters"),
            (3, "arterial_pco2_first_24h"),
            (4, "valid_arterial_pco2_units"),
            (5, "paired_ph"),
            (6, "first_pco2_gt45_ph_le7_45"),
            (7, "post_context_exclusions"),
            (8, "unique_patients"),
            (9, "valid_bmi"),
            (10, "bmi_ge30"),
            (11, "disease_specific_fda_documented"),
            (12, "guideline_society_documented"),
            (13, "rct_supported_documented"),
            (14, "existing_glp1_order"),
            (15, "payer_route_categories"),
        ]
        for view in expected_views:
            assert connection.execute(f'SELECT COUNT(*) FROM "{view}"').fetchone()
        minimal_output = tmp_path / "minimal-output"
        minimal_paths = write_build_outputs(
            connection,
            minimal_output,
            write_parquet=False,
            write_html_qa=False,
        )
        assert {path.name for path in minimal_paths} == {
            "cohort_flow.csv",
            "data_dictionary.csv",
            "run_manifest.json",
        }
    finally:
        connection.close()

    (output_root / "._filesystem_metadata").write_text("not a public artifact")
    second = build_glp1_eligibility(
        input_root=export_root,
        output_dir=output_root,
        config_path=GLP1_CONFIG,
    )
    assert second.reused_existing is True
    assert second.run_id == first.run_id
    assert second.output_paths == first.output_paths
    assert read_run_state(output_root).status == "completed"


def test_repository_local_glp1_output_is_rejected(tmp_path: Path) -> None:
    unsafe_output = ROOT / "results" / "unsafe-glp1-output"

    with pytest.raises(ValueError, match="outside the Git worktree"):
        build_glp1_eligibility(
            input_root=tmp_path / "unused-input",
            output_dir=unsafe_output,
            config_path=GLP1_CONFIG,
        )

    with pytest.raises(ValueError, match="outside the Git worktree"):
        _require_safe_output_location(ROOT / "results" / "glp1_eligibility")


def test_output_outside_git_worktree_is_allowed(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    subprocess.run(
        ["git", "init", "--quiet", str(repository)],
        check=True,
    )
    output = repository / "results" / "custom"
    output.parent.mkdir()
    output.write_text("not a directory\n")

    with pytest.raises(ValueError, match="exists and is not a directory"):
        _require_safe_output_location(output)

    output.unlink()
    (repository / ".gitignore").write_text("/results/custom/\n")

    with pytest.raises(ValueError, match="outside the Git worktree"):
        _require_safe_output_location(output)

    _require_safe_output_location(tmp_path / "external-output")


@pytest.mark.parametrize(
    "relative_path",
    (
        "results/glp1_eligibility/glp1_hypercapnia.duckdb",
        "results/custom-name.duckdb",
        "results/custom-name.duckdb.wal",
        "results/private/analysis_glp1_eligibility.parquet",
        "results/private/eligibility_evidence_long.parquet",
        "results/private/cohort_hypercapnia_encounter.parquet",
        "results/.glp1_eligibility.glp1_build_state.json",
    ),
)
def test_gitignore_protects_glp1_row_level_artifacts(relative_path: str) -> None:
    result = subprocess.run(
        [
            "git",
            "check-ignore",
            "--quiet",
            "--no-index",
            "--",
            str(ROOT / relative_path),
        ],
        cwd=ROOT,
        check=False,
    )

    assert result.returncode == 0


def test_gitignore_does_not_hide_glp1_source_package() -> None:
    result = subprocess.run(
        [
            "git",
            "check-ignore",
            "--quiet",
            "--no-index",
            "--",
            str(ROOT / "src" / "trinetx_preprocessing" / "glp1_eligibility"),
        ],
        cwd=ROOT,
        check=False,
    )

    assert result.returncode == 1

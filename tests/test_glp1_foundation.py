from __future__ import annotations

import json
from pathlib import Path

import pytest

from trinetx_preprocessing.glp1_eligibility.cli import main
from trinetx_preprocessing.glp1_eligibility.concept_sets import load_concept_sets
from trinetx_preprocessing.glp1_eligibility.config import (
    GLP1ConfigError,
    load_glp1_config,
)
from trinetx_preprocessing.glp1_eligibility.discovery import (
    discover_export_files,
    validate_export,
)
from trinetx_preprocessing.glp1_eligibility.monitoring import (
    RUN_STATE_FILENAME,
    RunStateWriter,
    process_appears_active,
    read_run_state,
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


def test_default_glp1_config_and_concept_sets_are_valid() -> None:
    config = load_glp1_config(GLP1_CONFIG)
    catalog = load_concept_sets(config.concept_sets_dir)

    assert config.schema_version == "1.0"
    assert config.study.study_start is None
    assert config.study.index_encounter_types == ("EMER", "IMP")
    assert config.obesity.thresholds == (27.0, 30.0, 35.0, 40.0)
    assert "arterial_pco2" in catalog.concept_set_ids

    arterial_codes = {
        concept.code
        for concept in catalog.concepts
        if concept.concept_set_id == "arterial_pco2" and concept.include
    }
    assert arterial_codes == {"2019-8", "32771-8"}
    assert "2026-3" not in arterial_codes


def test_glp1_config_rejects_threshold_not_above_primary(tmp_path: Path) -> None:
    raw = GLP1_CONFIG.read_text().replace(
        "pco2_sensitivity_thresholds_mm_hg: [50, 52]",
        "pco2_sensitivity_thresholds_mm_hg: [45, 52]",
    )
    path = tmp_path / "config.yml"
    path.write_text(raw)

    with pytest.raises(GLP1ConfigError, match="must exceed"):
        load_glp1_config(path)


def test_export_discovery_prefers_split_files(tmp_path: Path) -> None:
    _write_export(tmp_path)
    unsplit = tmp_path / "Encounter" / "encounter.csv"
    split_1 = tmp_path / "Encounter" / "encounter0001.csv"
    split_2 = tmp_path / "Encounter" / "encounter0002.csv"
    split_1.write_text(unsplit.read_text())
    split_2.write_text(unsplit.read_text())

    discovered = discover_export_files(tmp_path)

    assert [path.name for path in discovered["encounter"]] == [
        "encounter0001.csv",
        "encounter0002.csv",
    ]


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

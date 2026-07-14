from __future__ import annotations

import json
from pathlib import Path

import duckdb
import pytest

from trinetx_preprocessing.glp1_eligibility.builder import build_glp1_eligibility
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
    discover_export_files,
    validate_export,
)
from trinetx_preprocessing.glp1_eligibility.ingestion import ingest_core_sources
from trinetx_preprocessing.glp1_eligibility.monitoring import (
    RUN_STATE_FILENAME,
    RunStateWriter,
    process_appears_active,
    read_run_state,
    state_path_for_output,
)
from trinetx_preprocessing.glp1_eligibility.outputs import summarize_database
from trinetx_preprocessing.glp1_eligibility.provenance import (
    build_input_inventory,
    current_git_sha,
    deterministic_run_id,
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


def test_workspace_publishes_atomically_and_status_uses_stable_sibling(
    tmp_path: Path,
) -> None:
    output = tmp_path / "glp1_eligibility"
    workspace = prepare_workspace(
        output,
        run_id="run-1",
        config_sha256="config-hash",
        input_manifest_sha256="input-hash",
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
        git_sha=git_sha,
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
    )
    try:
        assert connection.execute("SELECT COUNT(*) FROM concept_set").fetchone() == (
            21,
        )
        source_files = connection.execute(
            "SELECT source_file FROM source_file_inventory ORDER BY source_file"
        ).fetchall()
        assert len(source_files) == len(DOMAIN_HEADERS)
        assert all(not Path(row[0]).is_absolute() for row in source_files)
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
    )
    try:
        counts = ingest_core_sources(
            connection,
            input_root=export_root,
            inventory=inventory,
        )
        assert counts["source_lab_measurement"] == 4
        assert counts["gas_candidate_id"] == 1
        assert connection.execute(
            "SELECT patient_id, encounter_id FROM gas_candidate_id"
        ).fetchall() == [("p1", "e1")]
        assert connection.execute(
            "SELECT patient_id FROM source_patient"
        ).fetchall() == [("p1",)]
        assert connection.execute(
            "SELECT patient_id, value FROM source_vital_measurement"
        ).fetchall() == [("p1", "36")]
        assert connection.execute(
            """
            SELECT COUNT(*) FROM source_lab_measurement
            WHERE code = '2026-3'
            """
        ).fetchone() == (2,)
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
    )
    _append_rows(
        export_root / "Encounter" / "encounter.csv",
        "e1,p1,2024-01-01 00:00:00,2024-01-02 00:00:00,IMP,s1",
        "e2,p2,2024-01-01 00:00:00,2024-01-02 00:00:00,IMP,s1",
        "e3,p3,2024-01-01 00:00:00,2024-01-02 00:00:00,EMER,s1",
        "e4,p4,2024-01-01 00:00:00,2024-01-02 00:00:00,EMER,s1",
    )
    _append_rows(
        export_root / "Lab Results" / "lab_results.csv",
        "p1,e1,2024-01-01 01:00:00,LOINC,2019-8,55,,mmHg",
        "p1,e1,2024-01-01 01:00:00,LOINC,2744-1,7.40,,pH",
        "p2,e2,2024-01-01 01:00:00,LOINC,2026-3,60,,mmol/L",
        "p3,e3,2024-01-01 01:00:00,LOINC,2019-8,40,,mmHg",
        "p3,e3,2024-01-01 01:00:00,LOINC,2744-1,7.40,,pH",
        "p3,e3,2024-01-01 02:00:00,LOINC,2019-8,55,,mmHg",
        "p4,e4,2024-01-01 01:00:00,LOINC,2021-4,55,,mmHg",
        "p4,e4,2024-01-01 01:00:00,LOINC,2746-6,7.40,,pH",
    )
    _append_rows(
        export_root / "Vital Signs" / "vital_signs.csv",
        "p1,e1,2023-12-15,LOINC,39156-5,36,,kg/m2",
        "p3,e3,2023-12-15,LOINC,39156-5,32,,kg/m2",
        "p4,e4,2023-12-15,LOINC,39156-5,31,,kg/m2",
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
    )
    try:
        ingest_core_sources(
            connection,
            input_root=export_root,
            inventory=inventory,
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
                   abg_pairing_method, bmi_value
            FROM analysis_glp1_eligibility
            """
        ).fetchone()
        assert primary == ("p1", 55.0, 7.4, "exact_timestamp", 36.0)
        later = connection.execute(
            """
            SELECT later_hypercapnia_sensitivity_case,
                   primary_cohort_exclusion_reason
            FROM cohort_hypercapnia_encounter WHERE patient_id = 'p3'
            """
        ).fetchone()
        assert later == (True, "first_arterial_pco2_not_elevated")
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
    assert first.counts.patient_index_events == 1
    summary = summarize_database(output_root / "glp1_hypercapnia.duckdb")
    assert summary["primary_obesity_hypercapnia"] == 1
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
    finally:
        connection.close()

    second = build_glp1_eligibility(
        input_root=export_root,
        output_dir=output_root,
        config_path=GLP1_CONFIG,
    )
    assert second.reused_existing is True
    assert second.run_id == first.run_id
    assert read_run_state(output_root).status == "completed"

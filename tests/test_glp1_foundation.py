from __future__ import annotations

import csv
import json
import subprocess
from dataclasses import replace
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
from trinetx_preprocessing.glp1_eligibility.outputs import (
    summarize_database,
    write_build_outputs,
)
from trinetx_preprocessing.glp1_eligibility.provenance import (
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
    monkeypatch.chdir(repository)

    clean = current_git_sha()
    assert len(clean) == 40
    tracked.write_text("dirty one\n")
    dirty_one = current_git_sha()
    tracked.write_text("dirty two\n")
    dirty_two = current_git_sha()
    (repository / "untracked.txt").write_text("additional content\n")
    dirty_with_untracked = current_git_sha()

    assert dirty_one.startswith(f"{clean}-dirty-")
    assert dirty_two.startswith(f"{clean}-dirty-")
    assert len({dirty_one, dirty_two, dirty_with_untracked}) == 3


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
            len(catalog.concepts),
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
        assert build_concept_match_summary(
            connection, catalog.required_concept_set_ids
        ) == ()
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
        "e3,p3,2024-01-01 00:00:00,2024-01-02 00:00:00,EMER,s1",
        "e4,p4,2024-01-01 00:00:00,2024-01-02 00:00:00,EMER,s1",
        "e5,p5,2024-01-01 00:00:00,2024-01-02 00:00:00,EMER,s1",
    )
    _append_rows(
        export_root / "Lab Results" / "lab_results.csv",
        "p1,e1,2024-01-01 01:00:00,LOINC,2019-8,55,,mmHg",
        "p1,e1,2024-01-01 01:00:00,LOINC,2744-1,7.40,,pH",
        "p1,e1,2024-01-20 01:00:00,LOINC,2019-8,40,,mmHg",
        "p1,e1,2024-02-01 01:00:00,LOINC,2019-8,55,,mmHg",
        "p2,e2,2024-01-01 01:00:00,LOINC,2026-3,60,,mmol/L",
        "p3,e3,2024-01-01 01:00:00,LOINC,2019-8,40,,mmHg",
        "p3,e3,2024-01-01 01:00:00,LOINC,2744-1,7.40,,pH",
        "p3,e3,2024-01-01 02:00:00,LOINC,2019-8,55,,mmHg",
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
                   abg_pairing_method, bmi_value,
                   persistent_hypercapnia_14_84d
            FROM analysis_glp1_eligibility
            """
        ).fetchone()
        assert primary == (
            "p1",
            55.0,
            7.4,
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
        {"bmi35": 36, "hfpef": 31, "prediabetes": 28, "weight_only": 31},
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
    )
    _append_rows(
        export_root / "Procedure" / "procedure.csv",
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
            SELECT cardiac_arrest_context, pneumonia_lri_at_index,
                   heart_failure_at_index, invasive_ventilation_at_index,
                   heart_failure_status
            FROM analysis_glp1_eligibility
            """
        ).fetchone()
        assert context == (True, False, True, True, "indeterminate")
        assert connection.execute(
            """
            SELECT cardiac_arrest_context
            FROM cohort_hypercapnia_encounter
            """
        ).fetchone() == (True,)
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
    assert required == {path.name for path in first.output_paths}
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
        expected_views = {
            "analysis_primary_obesity_hypercapnia",
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

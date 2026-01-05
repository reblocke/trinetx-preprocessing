from __future__ import annotations

from pathlib import Path

import pandas as pd

from trinetx_preprocessing.cli import main as cli_main
from trinetx_preprocessing.pipeline.final_assembly import (
    FINAL_OUTPUT_COLUMNS,
    SETTING_OUTPUT_DIRS,
)
from trinetx_preprocessing.transform.rfs import RFS_CATEGORIES


def _write_config(path: Path, data_dir: Path, work_dir: Path, output_dir: Path) -> None:
    content = (
        f'data_dir: "{data_dir}"\n'
        f'work_dir: "{work_dir}"\n'
        f'output_dir: "{output_dir}"\n'
        "domains:\n"
        "  encounter:\n"
        '    pattern: "Encounter/encounter*.csv"\n'
        "  diagnosis:\n"
        '    pattern: "Diagnosis/diagnosis*.csv"\n'
        "  labs:\n"
        '    pattern: "Lab Results/lab_results*.csv"\n'
        "  meds:\n"
        '    pattern: "Medications/medication*.csv"\n'
        "  procedure:\n"
        '    pattern: "Procedure/procedure*.csv"\n'
        "  vitals:\n"
        '    pattern: "Vital Signs/vital_signs*.csv"\n'
        "  patient:\n"
        '    pattern: "Patient/patient*.csv"\n'
        "\n"
        "rfs:\n"
        "  enabled: true\n"
    )
    path.write_text(content)


def _write_csv(path: Path, df: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)


def _write_synthetic_inputs(data_dir: Path) -> None:
    encounter = pd.DataFrame(
        [
            {
                "encounter_id": "E1",
                "patient_id": "P1",
                "start_date": "2022-06-01",
                "end_date": "2022-06-03",
                "type": "AMB",
                "start_date_derived_by_TriNetX": "",
                "end_date_derived_by_TriNetX": "",
                "derived_by_TriNetX": "N",
                "source_id": "S1",
            },
            {
                "encounter_id": "E2",
                "patient_id": "P2",
                "start_date": "2022-03-10",
                "end_date": "2022-03-10",
                "type": "EMER",
                "start_date_derived_by_TriNetX": "",
                "end_date_derived_by_TriNetX": "",
                "derived_by_TriNetX": "N",
                "source_id": "S2",
            },
            {
                "encounter_id": "E3",
                "patient_id": "P3",
                "start_date": "2022-05-15",
                "end_date": "2022-05-20",
                "type": "IMP",
                "start_date_derived_by_TriNetX": "",
                "end_date_derived_by_TriNetX": "",
                "derived_by_TriNetX": "N",
                "source_id": "S3",
            },
        ]
    )
    _write_csv(data_dir / "Encounter" / "encounter0001.csv", encounter)

    labs = pd.DataFrame(
        [
            {
                "patient_id": "P1",
                "encounter_id": "E1",
                "code_system": "LOINC",
                "code": "2019-8",
                "date": "2022-06-01",
                "lab_result_num_val": 55.0,
                "lab_result_text_val": "",
                "units_of_measure": "",
                "derived_by_TriNetX": "N",
                "source_id": "L1",
            },
            {
                "patient_id": "P2",
                "encounter_id": "E2",
                "code_system": "LOINC",
                "code": "2021-4",
                "date": "2022-03-10",
                "lab_result_num_val": 60.0,
                "lab_result_text_val": "",
                "units_of_measure": "",
                "derived_by_TriNetX": "N",
                "source_id": "L2",
            },
        ]
    )
    _write_csv(data_dir / "Lab Results" / "lab_results0001.csv", labs)

    diagnosis = pd.DataFrame(
        [
            {
                "patient_id": "P3",
                "encounter_id": "E3",
                "code_system": "ICD10",
                "code": "J96.00",
                "principal_diagnosis_indicator": "Y",
                "admitting_diagnosis": "N",
                "reason_for_visit": "N",
                "date": "2022-05-16",
                "derived_by_TriNetX": "N",
                "source_id": "D1",
            },
            {
                "patient_id": "P1",
                "encounter_id": "E1",
                "code_system": "ICD10",
                "code": "E66.01",
                "principal_diagnosis_indicator": "N",
                "admitting_diagnosis": "N",
                "reason_for_visit": "N",
                "date": "2022-06-01",
                "derived_by_TriNetX": "N",
                "source_id": "D2",
            },
            {
                "patient_id": "P2",
                "encounter_id": "E2",
                "code_system": "ICD10",
                "code": "I27.1",
                "principal_diagnosis_indicator": "N",
                "admitting_diagnosis": "N",
                "reason_for_visit": "N",
                "date": "2022-03-10",
                "derived_by_TriNetX": "N",
                "source_id": "D3",
            },
        ]
    )
    _write_csv(data_dir / "Diagnosis" / "diagnosis0001.csv", diagnosis)

    meds = pd.DataFrame(
        [
            {
                "patient_id": "P1",
                "encounter_id": "E1",
                "unique_id": "M1",
                "code_system": "RXNORM",
                "code": "1808",
                "start_date": "2022-06-01",
                "route": "",
                "brand": "",
                "strength": "",
                "derived_by_TriNetX": "N",
                "source_id": "M1",
            }
        ]
    )
    _write_csv(data_dir / "Medications" / "medication0001.csv", meds)

    procedure = pd.DataFrame(
        [
            {
                "patient_id": "P3",
                "encounter_id": "E3",
                "code_system": "CPT",
                "code": "5A09459",
                "principal_procedure_indicator": "Y",
                "date": "2022-05-17",
                "derived_by_TriNetX": "N",
                "source_id": "P1",
            }
        ]
    )
    _write_csv(data_dir / "Procedure" / "procedure0001.csv", procedure)

    vitals = pd.DataFrame(
        [
            {
                "patient_id": "P1",
                "encounter_id": "E1",
                "code_system": "LOINC",
                "code": "39156-5",
                "date": "2022-06-01",
                "value": 45.0,
                "text_value": "",
                "units_of_measure": "kg/m2",
                "derived_by_TriNetX": "N",
                "source_id": "V1",
            }
        ]
    )
    _write_csv(data_dir / "Vital Signs" / "vital_signs0001.csv", vitals)

    patient = pd.DataFrame(
        [
            {
                "patient_id": "P1",
                "sex": "M",
                "race": "White",
                "ethnicity": "Non-Hispanic",
                "year_of_birth": 1980,
                "patient_regional_location": "Midwest",
                "month_year_death": "",
            },
            {
                "patient_id": "P2",
                "sex": "F",
                "race": "Black",
                "ethnicity": "Non-Hispanic",
                "year_of_birth": 1975,
                "patient_regional_location": "South",
                "month_year_death": "",
            },
            {
                "patient_id": "P3",
                "sex": "M",
                "race": "Asian",
                "ethnicity": "Non-Hispanic",
                "year_of_birth": 1965,
                "patient_regional_location": "Northeast",
                "month_year_death": 202401,
            },
        ]
    )
    _write_csv(data_dir / "Patient" / "patient.csv", patient)


def test_run_pipeline_end_to_end(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    work_dir = tmp_path / "work"
    output_dir = tmp_path / "output"
    data_dir.mkdir()
    work_dir.mkdir()
    output_dir.mkdir()

    _write_synthetic_inputs(data_dir)

    config_path = tmp_path / "config.yaml"
    _write_config(config_path, data_dir, work_dir, output_dir)

    result = cli_main(["run", "--config", str(config_path)])
    assert result == 0

    expected_non_empty = {
        ("ABG", "AMB"),
        ("VBG", "EMER"),
        ("RESPFAIL", "INPAT"),
        ("OBESITY", "AMB"),
        ("PREDISPOSITION", "EMER"),
        ("VENTSUPPORT", "INPAT"),
    }

    for setting, output_dir_name in SETTING_OUTPUT_DIRS.items():
        setting_dir = output_dir / output_dir_name
        for category in RFS_CATEGORIES:
            before_path = setting_dir / f"RFS_{category}_ENC_{setting}_BEFORE.csv"
            after_path = setting_dir / f"RFS_{category}_ENC_{setting}_AFTER.csv"
            assert before_path.exists()
            assert after_path.exists()

            after = pd.read_csv(after_path)
            assert list(after.columns) == FINAL_OUTPUT_COLUMNS
            if (category, setting) in expected_non_empty:
                assert not after.empty
            else:
                assert after.empty

    sample_path = output_dir / SETTING_OUTPUT_DIRS["AMB"] / "RFS_ABG_ENC_AMB_AFTER.csv"
    first_bytes = sample_path.read_bytes()
    rerun_result = cli_main(["run", "--config", str(config_path)])
    assert rerun_result == 0
    second_bytes = sample_path.read_bytes()
    assert first_bytes == second_bytes

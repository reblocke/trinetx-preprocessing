from __future__ import annotations

import warnings
from pathlib import Path

import pandas as pd

from trinetx_preprocessing.transform.clinical_rules import CodeRule
from trinetx_preprocessing.transform.rfs import (
    RFS_OUTPUT_COLUMNS,
    derive_diagnosis_rfs_event_frames,
    derive_lab_rfs_event_frames_with_audit,
    derive_rfs_encounter_flags,
    derive_rfs_encounter_sets,
    derive_vitals_rfs_event_frames,
)

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "rfs"


def _load(name: str) -> pd.DataFrame:
    return pd.read_csv(FIXTURE_DIR / name)


def test_derive_rfs_encounter_sets() -> None:
    labs = _load("lab_results_NEW_0001.csv")
    diagnosis = _load("diagnosis_NEW_0001.csv")
    procedure = _load("procedure_NEW_0001.csv")
    vitals = _load("vital_signs_NEW_0001.csv")

    rfs_sets = derive_rfs_encounter_sets(
        labs=labs,
        diagnosis=diagnosis,
        procedure=procedure,
        vitals=vitals,
    )

    assert rfs_sets["ABG"] == {"E1"}
    assert rfs_sets["VBG"] == {"E2"}
    assert rfs_sets["RESPFAIL"] == {"E3"}
    assert rfs_sets["OBESITY"] == {"E4"}
    assert rfs_sets["VENTSUPPORT"] == {"E5"}
    assert rfs_sets["PREDISPOSITION"] == {"E6"}


def test_obesity_bmi_rfs_filters_in_float64_before_storage_downcast() -> None:
    vitals = pd.DataFrame(
        {
            "patient_id": ["P1", "P2", "P3", "P4"],
            "encounter_id": ["E1", "E2", "E3", "E4"],
            "code": ["39156-5", "39156-5", "39156-5", "39156-5"],
            "date": ["2022-01-01", "2022-01-02", "2022-01-03", "2022-01-04"],
            "value": ["39.99", "100.01", "1e100", "42.0"],
        }
    )

    with warnings.catch_warnings():
        warnings.simplefilter("error", RuntimeWarning)
        obesity = derive_vitals_rfs_event_frames(vitals)["OBESITY"]

    assert obesity["encounter_id"].tolist() == ["E4"]


def test_gas_rules_are_specimen_specific_unit_aware_and_strictly_above_45() -> None:
    labs = pd.DataFrame(
        {
            "patient_id": [f"P{i}" for i in range(1, 8)],
            "encounter_id": [f"E{i}" for i in range(1, 8)],
            "code_system": ["LOINC"] * 6 + ["LOCAL"],
            "code": [
                "2019-8",
                "32771-8",
                "2021-4",
                "11557-6",
                "2026-3",
                "2019-8",
                "2019-8",
            ],
            "date": ["2022-01-01"] * 7,
            "lab_result_num_val": [46, 6.2, 45, 80, 80, 46, 46],
            "units_of_measure": [
                "mmHg",
                "kPa",
                "mmHg",
                "mmHg",
                "mmol/L",
                "unknown",
                "mmHg",
            ],
        }
    )

    frames, audits = derive_lab_rfs_event_frames_with_audit(labs)

    assert frames["ABG"]["encounter_id"].tolist() == ["E1", "E2"]
    assert frames["VBG"].empty
    assert audits["ABG"].rejected_unit == 1
    assert audits["ABG"].rejected_code_system == 1


def test_gas_audit_counts_missing_units_as_rejected() -> None:
    labs = pd.DataFrame(
        {
            "patient_id": ["P1"],
            "encounter_id": ["E1"],
            "code_system": ["LOINC"],
            "code": ["2019-8"],
            "date": ["2022-01-01"],
            "lab_result_num_val": [55.0],
            "units_of_measure": [pd.NA],
        }
    )

    _, audits = derive_lab_rfs_event_frames_with_audit(labs)
    audit = audits["ABG"]

    assert audit.rejected_unit == 1
    assert (
        audit.accepted
        + audit.rejected_code_system
        + audit.rejected_unit
        + audit.rejected_non_numeric
        + audit.rejected_range
        == audit.considered
    )


def test_predisposition_uses_literal_prefixes_not_regex_stars() -> None:
    diagnosis = pd.DataFrame(
        {
            "patient_id": ["P1", "P2", "P3"],
            "encounter_id": ["E1", "E2", "E3"],
            "code": ["F11.20", "F17.210", "G47.00"],
            "principal_diagnosis_indicator": ["U"] * 3,
            "admitting_diagnosis": ["U"] * 3,
            "reason_for_visit": ["U"] * 3,
            "date": ["2022-01-01"] * 3,
        }
    )

    result = derive_diagnosis_rfs_event_frames(diagnosis)["PREDISPOSITION"]

    assert result["encounter_id"].tolist() == ["E1"]


def test_typed_rules_normalize_codes_and_systems_once() -> None:
    rule = CodeRule(
        name="normalized",
        exact_codes=("abc.1",),
        prefixes=("def",),
        allowed_code_systems=("icd-10-cm",),
    )

    assert rule.exact_codes == ("ABC.1",)
    assert rule.matches(" abc.1 ", "ICD-10-CM")
    assert rule.matches("def99", "icd-10-cm")


def test_derive_rfs_encounter_flags() -> None:
    encounters = _load("encounter_NEW_0001.csv")
    labs = _load("lab_results_NEW_0001.csv")
    diagnosis = _load("diagnosis_NEW_0001.csv")
    procedure = _load("procedure_NEW_0001.csv")
    vitals = _load("vital_signs_NEW_0001.csv")

    flags = derive_rfs_encounter_flags(
        encounters,
        labs=labs,
        diagnosis=diagnosis,
        procedure=procedure,
        vitals=vitals,
    )

    assert list(flags.columns) == RFS_OUTPUT_COLUMNS

    indexed = flags.set_index("encounter_id")
    assert indexed.loc["E1", "rfs_abg"]
    assert indexed.loc["E2", "rfs_vbg"]
    assert indexed.loc["E3", "rfs_respfail"]
    assert indexed.loc["E4", "rfs_obesity"]
    assert indexed.loc["E5", "rfs_ventsupport"]
    assert indexed.loc["E6", "rfs_predisposition"]
    assert not indexed.loc["E7", "rfs_abg"]
    assert not indexed.loc["E7", "rfs_vbg"]
    assert not indexed.loc["E7", "rfs_respfail"]
    assert not indexed.loc["E7", "rfs_obesity"]
    assert not indexed.loc["E7", "rfs_ventsupport"]
    assert not indexed.loc["E7", "rfs_predisposition"]
    assert indexed.loc["E4", "patient_id"] == "P4"

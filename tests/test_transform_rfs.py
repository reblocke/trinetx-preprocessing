from __future__ import annotations

from pathlib import Path

import pandas as pd

from trinetx_preprocessing.transform.rfs import (
    RFS_OUTPUT_COLUMNS,
    derive_rfs_encounter_flags,
    derive_rfs_encounter_sets,
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

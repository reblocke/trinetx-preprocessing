from __future__ import annotations

from pathlib import Path

import pandas as pd

from trinetx_preprocessing.transform.diagnosis import (
    DIAGNOSIS_COLUMNS,
    normalize_diagnosis_chunk,
    split_diagnosis_by_code,
)

FIXTURE_PATH = (
    Path(__file__).resolve().parent / "fixtures" / "diagnosis" / "diagnosis0001.csv"
)


def _load_fixture() -> pd.DataFrame:
    return pd.read_csv(FIXTURE_PATH, parse_dates=["date"])


def test_normalize_diagnosis_chunk_structure() -> None:
    df = _load_fixture()

    normalized = normalize_diagnosis_chunk(df)

    assert list(normalized.columns) == DIAGNOSIS_COLUMNS
    assert len(normalized) == 9
    assert "code_system" not in normalized.columns
    assert normalized.loc[0, "principal_diagnosis_indicator"] == "U"
    assert normalized.loc[0, "admitting_diagnosis"] == "U"
    assert normalized.loc[0, "reason_for_visit"] == "U"


def test_split_diagnosis_by_code_groups() -> None:
    df = normalize_diagnosis_chunk(_load_fixture())

    groups = split_diagnosis_by_code(df)

    assert groups["HAS_J9612"]["code"].tolist() == ["J96.12"]
    assert set(groups["HAS_G473"]["code"].tolist()) == {"G47.30", "G47.34"}
    assert groups["HAS_G4734"]["code"].tolist() == ["G47.34"]
    assert groups["HAS_J44"]["code"].tolist() == ["J44.1"]
    assert groups["HAS_J441"]["code"].tolist() == ["J44.1"]
    assert groups["HAS_I50_acute"]["code"].tolist() == ["I50.33"]
    assert groups["HAS_I50"]["code"].tolist() == ["I50.33"]
    assert groups["HAS_E11"]["code"].tolist() == ["E11.9"]
    assert groups["HAS_R0602"]["code"].tolist() == ["R06.02"]
    assert groups["HAS_Z79891"]["code"].tolist() == ["Z79.891"]
    assert groups["HAS_headache"].empty

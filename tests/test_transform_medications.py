from __future__ import annotations

from pathlib import Path

import pandas as pd

from trinetx_preprocessing.transform.medications import (
    MEDICATION_COLUMNS,
    normalize_medications_chunk,
    split_medications_by_code,
)

FIXTURE_PATH = (
    Path(__file__).resolve().parent / "fixtures" / "medications" / "medication0001.csv"
)


def _load_fixture() -> pd.DataFrame:
    return pd.read_csv(FIXTURE_PATH, parse_dates=["start_date"])


def test_normalize_medications_chunk_structure() -> None:
    df = _load_fixture()

    normalized = normalize_medications_chunk(df)

    assert list(normalized.columns) == MEDICATION_COLUMNS
    assert len(normalized) == 12
    assert "code_system" not in normalized.columns
    assert pd.isna(normalized.loc[10, "start_date"])


def test_split_medications_by_code_groups() -> None:
    df = normalize_medications_chunk(_load_fixture())

    groups = split_medications_by_code(df)

    assert groups["IPmed_list1"]["code"].tolist() == ["6902"]
    assert groups["IPmed_list3"]["code"].tolist() == ["7213"]
    assert groups["OPmed_list5"]["code"].tolist() == ["7213"]
    assert groups["OPmed_list6"]["code"].tolist() == ["21949"]
    assert groups["OPmed_list3"]["code"].tolist() == ["6813"]

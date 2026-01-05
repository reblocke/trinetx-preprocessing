from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from trinetx_preprocessing.transform.vitals import (
    VITALS_COLUMNS,
    normalize_vitals_chunk,
    split_vitals_by_rule,
)

FIXTURE_PATH = (
    Path(__file__).resolve().parent / "fixtures" / "vitals" / "vital_signs0001.csv"
)


def _load_fixture() -> pd.DataFrame:
    return pd.read_csv(FIXTURE_PATH, parse_dates=["date"])


def test_normalize_vitals_chunk_structure() -> None:
    df = _load_fixture()

    normalized = normalize_vitals_chunk(df)

    assert list(normalized.columns) == VITALS_COLUMNS
    assert len(normalized) == 18
    assert "code_system" not in normalized.columns


def test_split_vitals_by_rule_filters() -> None:
    df = normalize_vitals_chunk(_load_fixture())

    groups = split_vitals_by_rule(df)

    temp = groups["value_759878"]
    assert len(temp) == 1
    assert temp["value"].iloc[0] == pytest.approx(40.0, rel=1e-3)

    new_temp = groups["value_New_Temp"]
    assert len(new_temp) == 1
    assert new_temp["value"].iloc[0] == pytest.approx(98.6, rel=1e-3)

    weight = groups["value_Weight"]
    assert weight["value"].tolist() == [180.0]

    rr = groups["value_RR"]
    assert rr["value"].tolist() == [20.0]

    spo2 = groups["value_SPO2"]
    assert spo2["value"].tolist() == [95.0]

    height = groups["value_Height"]
    assert height["value"].tolist() == [70.0]

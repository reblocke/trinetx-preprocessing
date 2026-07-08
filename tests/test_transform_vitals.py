from __future__ import annotations

import warnings
from pathlib import Path

import pandas as pd
import pytest

from trinetx_preprocessing.transform.vitals import (
    VITALS_COLUMNS,
    VitalSignRule,
    apply_vital_sign_rule,
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


def test_new_temperature_preserves_legacy_half_precision_values() -> None:
    df = pd.DataFrame(
        {
            "patient_id": ["P1"],
            "encounter_id": ["E1"],
            "code": ["8310-5"],
            "date": pd.to_datetime(["2022-01-01"]),
            "value": ["98.3"],
        }
    )
    result = split_vitals_by_rule(df)["value_New_Temp"]

    assert result["value"].dtype == "float32"
    assert result["value"].iloc[0] == pytest.approx(98.3125)


def test_fahrenheit_to_celsius_temperature_uses_legacy_float32_input() -> None:
    df = pd.DataFrame(
        {
            "patient_id": ["P1"],
            "encounter_id": ["E1"],
            "code": ["60835-6"],
            "date": pd.to_datetime(["2022-01-01"]),
            "value": ["98.3"],
        }
    )
    result = split_vitals_by_rule(df)["value_608356"]

    assert result["value"].dtype == "float32"
    assert result["value"].iloc[0] == pytest.approx(36.833336)


def test_new_temperature_drops_extreme_values_without_overflow_warning() -> None:
    df = pd.DataFrame(
        {
            "patient_id": ["P1", "P2"],
            "encounter_id": ["E1", "E2"],
            "code": ["8310-5", "8310-5"],
            "date": pd.to_datetime(["2022-01-01", "2022-01-02"]),
            "value": ["98.3", "1e100"],
        }
    )

    with warnings.catch_warnings():
        warnings.simplefilter("error", RuntimeWarning)
        result = split_vitals_by_rule(df)["value_New_Temp"]

    assert result["encounter_id"].tolist() == ["E1"]
    assert result["value"].iloc[0] == pytest.approx(98.3125)


def test_apply_vital_sign_rule_filters_before_float16_downcast() -> None:
    df = pd.DataFrame(
        {
            "patient_id": ["P1", "P2", "P3", "P4"],
            "encounter_id": ["E1", "E2", "E3", "E4"],
            "code": ["8480-6", "8480-6", "8480-6", "8480-6"],
            "date": pd.to_datetime(
                ["2022-01-01", "2022-01-02", "2022-01-03", "2022-01-04"]
            ),
            "value": ["349.99", "350.0", "29.99", "1e100"],
        }
    )
    rule = VitalSignRule(
        name="value_SysBP",
        regex=r"^8480-6$",
        dtype="float16",
        min_value=30,
        max_value=350,
    )

    with warnings.catch_warnings():
        warnings.simplefilter("error", RuntimeWarning)
        result = apply_vital_sign_rule(df, rule)

    assert result["encounter_id"].tolist() == ["E1"]
    assert result["value"].dtype == "float16"

from __future__ import annotations

import warnings

import pandas as pd
import pytest

from trinetx_preprocessing.transform.vitals import (
    VitalSignRule,
    apply_vital_sign_rule,
    split_vitals_by_rule,
)


def test_new_temperature_preserves_float64_value_before_output_cast() -> None:
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
    assert result["value"].iloc[0] == pytest.approx(98.3)


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
    assert result["value"].iloc[0] == pytest.approx(98.3)


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
        exact_codes=("8480-6",),
        dtype="float16",
        min_value=30,
        max_value=350,
    )

    with warnings.catch_warnings():
        warnings.simplefilter("error", RuntimeWarning)
        result = apply_vital_sign_rule(df, rule)

    assert result["encounter_id"].tolist() == ["E1"]
    assert result["value"].dtype == "float16"

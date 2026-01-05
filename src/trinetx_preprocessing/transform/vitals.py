"""Pure vital-sign transforms derived from legacy notebooks."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from ..validation import require_columns

RAW_VITALS_COLUMNS = [
    "patient_id",
    "encounter_id",
    "code_system",
    "code",
    "date",
    "value",
    "text_value",
    "units_of_measure",
    "derived_by_TriNetX",
    "source_id",
]

VITALS_COLUMNS = [
    "patient_id",
    "encounter_id",
    "code",
    "date",
    "value",
]

DROP_COLUMNS = [
    "code_system",
    "text_value",
    "units_of_measure",
    "derived_by_TriNetX",
    "source_id",
]

FAHRENHEIT_TO_CELSIUS = "fahrenheit_to_celsius"
CELSIUS_TO_FAHRENHEIT = "celsius_to_fahrenheit"


@dataclass(frozen=True)
class VitalSignRule:
    """Definition of a vital-sign code extract and filter rule."""

    name: str
    regex: str
    dtype: str
    min_value: float | None = None
    max_value: float | None = None
    conversion: str | None = None
    dropna: bool = False


VITAL_SIGN_RULES = [
    VitalSignRule(
        "value_759878",
        r"^75987-8$",
        "float32",
        min_value=20,
        max_value=43,
        conversion=FAHRENHEIT_TO_CELSIUS,
    ),
    VitalSignRule(
        "value_608356",
        r"^60835-6$",
        "float32",
        min_value=20,
        max_value=43.3,
        conversion=FAHRENHEIT_TO_CELSIUS,
    ),
    VitalSignRule(
        "value_27110",
        r"^74105-8$|^51731-8$|^19224-5$|^2711-0$",
        "float32",
        min_value=0,
        max_value=100,
    ),
    VitalSignRule(
        "value_27086",
        r"^2708-6$|^51733-4$",
        "float32",
        min_value=0,
        max_value=100,
    ),
    VitalSignRule(
        "value_205641",
        r"^2713-6$|^20564-1$",
        "float16",
        min_value=0,
        max_value=100,
    ),
    VitalSignRule(
        "value_Weight",
        r"^29463-7$|^3141-9$|^3142-7$|^8335-2$",
        "float16",
        min_value=10,
        max_value=450,
    ),
    VitalSignRule(
        "value_New_Temp",
        r"^8310-5$|^8331-1$|^75539-7$|^8333-7$",
        "float16",
        min_value=43.3,
        max_value=110,
        conversion=CELSIUS_TO_FAHRENHEIT,
    ),
    VitalSignRule(
        "value_BMI",
        r"^39156-5$",
        "float16",
        min_value=10,
        max_value=100,
    ),
    VitalSignRule(
        "value_RR",
        r"^9279-1$",
        "float16",
        min_value=2,
        max_value=75,
    ),
    VitalSignRule(
        "value_SysBP",
        r"^8480-6$",
        "float16",
        min_value=30,
        max_value=350,
    ),
    VitalSignRule(
        "value_DiaBP",
        r"^8462-4$",
        "float16",
        min_value=15,
        max_value=250,
    ),
    VitalSignRule(
        "value_SPO2",
        r"^59408-5$|^20564-1$",
        "float16",
        min_value=30,
        max_value=100,
    ),
    VitalSignRule(
        "value_HR",
        r"^8893-0$|^8867-4$",
        "float16",
        min_value=15,
        max_value=300,
    ),
    VitalSignRule(
        "value_Height",
        r"^8302-2$|^8306-3$|^8301-4$|^3138-5$|^8308-9$|^8305-5$|^3137-7$",
        "float16",
        min_value=54,
        max_value=84,
        dropna=True,
    ),
]


def normalize_vitals_chunk(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize raw vital-sign exports for downstream processing.

    Args:
        df: Raw vital-sign DataFrame with TriNetX export columns.

    Returns:
        DataFrame with normalized vital-sign columns.
    """

    require_columns(df, RAW_VITALS_COLUMNS, context="Vital signs raw input")

    normalized = df.drop(columns=DROP_COLUMNS).copy()
    normalized = normalized.loc[:, VITALS_COLUMNS]
    normalized["patient_id"] = normalized["patient_id"].astype("string")
    normalized["encounter_id"] = normalized["encounter_id"].astype("string")
    normalized["code"] = normalized["code"].astype("string")
    normalized["date"] = pd.to_datetime(normalized["date"])
    return normalized.reset_index(drop=True)


def filter_vitals_by_code(df: pd.DataFrame, regex: str) -> pd.DataFrame:
    """Filter vital-sign rows by a code pattern.

    Args:
        df: Normalized vital-sign DataFrame.
        regex: Regex pattern matching vital-sign codes to retain.

    Returns:
        Filtered vital-sign DataFrame.
    """

    require_columns(df, VITALS_COLUMNS, context="Vital signs normalized input")

    codes = df["code"].astype("string")
    mask = codes.str.match(regex, na=False)
    filtered = df.loc[mask, VITALS_COLUMNS].copy()
    return filtered.reset_index(drop=True)


def apply_vital_sign_rule(df: pd.DataFrame, rule: VitalSignRule) -> pd.DataFrame:
    """Apply a vital-sign rule to normalized rows."""

    filtered = filter_vitals_by_code(df, rule.regex)
    if filtered.empty:
        return filtered

    values = pd.to_numeric(filtered["value"], errors="coerce").astype(rule.dtype)
    values = _apply_temperature_conversion(values, rule.conversion)

    mask = pd.Series(True, index=values.index)
    if rule.max_value is not None:
        mask &= values < rule.max_value
    if rule.min_value is not None:
        mask &= values >= rule.min_value

    filtered["value"] = values
    filtered = filtered.loc[mask]
    if rule.dropna:
        filtered = filtered.dropna()
    return filtered.reset_index(drop=True)


def split_vitals_by_rule(
    df: pd.DataFrame,
    rules: list[VitalSignRule] | None = None,
) -> dict[str, pd.DataFrame]:
    """Split vital-sign rows into code-group extracts."""

    selected_rules = rules or VITAL_SIGN_RULES
    return {rule.name: apply_vital_sign_rule(df, rule) for rule in selected_rules}


def _apply_temperature_conversion(
    values: pd.Series,
    conversion: str | None,
) -> pd.Series:
    if conversion == FAHRENHEIT_TO_CELSIUS:
        return values.where(values <= 43.3, (values - 32) * (5 / 9))
    if conversion == CELSIUS_TO_FAHRENHEIT:
        return values.where(values >= 43.3, values * (9 / 5) + 32)
    return values

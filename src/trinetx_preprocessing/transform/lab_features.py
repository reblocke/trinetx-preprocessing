"""Typed rules and pure classification for final analytic lab features."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from ..validation import require_columns
from .clinical_rules import NumericCodeRule
from .labs import LAB_COLUMNS

LAB_FEATURE_SOURCE_COLUMN = "source_name"
LAB_CODE_PRIORITY_COLUMN = "_code_priority"


@dataclass(frozen=True)
class LabFeatureRule(NumericCodeRule):
    """A final-output lab rule with deterministic conversion and tie priority."""

    include_highest: bool = False
    value_dtype: str = "float16"
    value_divisors_by_code: tuple[tuple[str, float], ...] = ()
    code_priority_by_code: tuple[tuple[str, int], ...] = ()


def _lab_rule(
    name: str,
    codes: tuple[str, ...],
    min_value: float,
    max_value: float,
    *,
    include_highest: bool = False,
    min_inclusive: bool = False,
    value_dtype: str = "float16",
    value_divisors_by_code: tuple[tuple[str, float], ...] = (),
    code_priority_by_code: tuple[tuple[str, int], ...] = (),
) -> LabFeatureRule:
    return LabFeatureRule(
        name=name,
        exact_codes=codes,
        min_value=min_value,
        max_value=max_value,
        min_inclusive=min_inclusive,
        include_highest=include_highest,
        value_dtype=value_dtype,
        value_divisors_by_code=value_divisors_by_code,
        code_priority_by_code=code_priority_by_code,
    )


LAB_VALUE_RULES = (
    _lab_rule("value_20198", ("2019-8",), 5, 200, include_highest=True),
    _lab_rule("value_115576", ("11557-6",), 2, 250, include_highest=True),
    _lab_rule("value_327718", ("32771-8",), 2, 250, include_highest=True),
    _lab_rule(
        "value_VBG_CO2",
        ("2021-4", "40619-9"),
        10,
        250,
        include_highest=True,
    ),
    _lab_rule(
        "value_PCO2_Unspec_blood",
        ("34705-4", "11557-6"),
        10,
        250,
        include_highest=True,
    ),
    _lab_rule("value_27441", ("2744-1",), 6.5, 7.8),
    _lab_rule("value_27466", ("2746-6",), 6.4, 7.7),
    _lab_rule("value_19604_20263", ("1960-4", "2026-3"), 0.5, 60),
    _lab_rule("value_146274", ("14627-4",), 0.5, 60),
    _lab_rule("value_29512", ("2951-2", "2947-0", "77139-4"), 80, 190),
    _lab_rule("value_21600", ("2160-0", "38483-4"), 0.1, 20),
    _lab_rule("value_7187", ("718-7",), 3, 25),
    _lab_rule(
        "value_serum_bicarb",
        ("20565-8", "1963-8", "1959-6", "1962-0", "2028-9"),
        0.5,
        60,
    ),
    _lab_rule("value_serum_chloride", ("77138-6", "2069-3", "2075-0"), 50, 150),
    _lab_rule("value_serum_lactate", ("32693-4", "2524-7"), 0.1, 50),
    _lab_rule(
        "value_potassium",
        ("6298-4", "2823-3", "77142-8"),
        1.8,
        12,
        min_inclusive=True,
    ),
    _lab_rule("value_192583", ("19258-3",), 10, 300),
    _lab_rule("value_394866", ("39486-6",), 6.4, 7.7),
    _lab_rule("value_27052", ("2705-2",), 10, 300),
    _lab_rule(
        "value_Lactate_Venous_Blood",
        ("30241-4", "2519-7"),
        0.1,
        50,
        value_divisors_by_code=(("30241-4", 9.008),),
        code_priority_by_code=(("30241-4", 0), ("2519-7", 1)),
    ),
    _lab_rule("value_483917", ("48391-7",), 2, 60),
    _lab_rule("value_27037", ("2703-7",), 20, 500),
    _lab_rule("value_192559", ("19255-9",), 20, 500),
    _lab_rule("value_332544", ("33254-4",), 6.5, 7.8),
    _lab_rule("value_25189", ("2518-9",), 0.1, 50),
    _lab_rule("value_115584", ("11558-4",), 6.5, 7.8),
    _lab_rule("value_115568", ("11556-8",), 5, 500),
    _lab_rule(
        "value_264648",
        ("26464-8", "49498-9", "6690-2", "804-5"),
        0,
        500000,
        value_dtype="float64",
    ),
    _lab_rule(
        "value_265157",
        ("26515-7", "778-1", "777-3", "49497-1"),
        0,
        5000,
    ),
    _lab_rule(
        "value_bnp",
        ("42637-9", "30934-4"),
        0,
        500000,
        value_dtype="float64",
    ),
    _lab_rule("value_phos", ("2774-8", "2777-1"), 0, 30),
    _lab_rule("value_ca", ("49765-1", "17861-6"), 4, 30),
    _lab_rule("value_albumin", ("2862-1", "1751-7", "61152-5", "61151-7"), 0.5, 6),
    _lab_rule("value_tprot", ("2885-2",), 2, 12),
)


def classify_lab_feature_rows(
    frame: pd.DataFrame,
) -> dict[str, pd.DataFrame]:
    """Classify and convert final-feature lab candidates in one chunk."""

    require_columns(frame, LAB_COLUMNS, context="Lab feature input")
    codes = frame["code"].astype("string").str.strip().str.upper()
    raw_values = pd.to_numeric(
        frame["lab_result_num_val"], errors="coerce"
    ).astype("float64")
    grouped: dict[str, pd.DataFrame] = {}
    for rule in LAB_VALUE_RULES:
        code_mask = codes.isin(rule.exact_codes)
        if rule.prefixes:
            code_mask |= codes.str.startswith(rule.prefixes, na=False)
        code_mask = code_mask.fillna(False)
        if not code_mask.any():
            continue

        matching_codes = codes.loc[code_mask]
        values = legacy_lab_feature_values(
            rule,
            matching_codes,
            raw_values.loc[code_mask],
        )
        visible_values = legacy_csv_visible_numeric_series(values)
        value_mask = pd.Series(True, index=visible_values.index)
        if rule.max_value is not None:
            value_mask &= visible_values < rule.max_value
        if rule.min_value is not None:
            if rule.min_inclusive:
                value_mask &= visible_values >= rule.min_value
            else:
                value_mask &= visible_values > rule.min_value
        value_mask = value_mask.fillna(False)
        rows = frame.loc[value_mask.index[value_mask], LAB_COLUMNS].copy()
        if rows.empty:
            continue
        rows["lab_result_num_val"] = float32_series(
            visible_values.loc[value_mask]
        )
        grouped[rule.name] = rows.reset_index(drop=True)
    return grouped


def stack_lab_feature_rows(grouped: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Stack classified lab candidates with their final feature source name."""

    frames: list[pd.DataFrame] = []
    for name, frame in grouped.items():
        indexed = frame.loc[:, LAB_COLUMNS].copy()
        indexed.insert(0, LAB_FEATURE_SOURCE_COLUMN, name)
        frames.append(indexed)
    if not frames:
        return pd.DataFrame(columns=[LAB_FEATURE_SOURCE_COLUMN, *LAB_COLUMNS])
    return pd.concat(frames, ignore_index=True)


def legacy_lab_feature_values(
    rule: LabFeatureRule,
    codes: pd.Series,
    values: pd.Series,
) -> pd.Series:
    """Apply the established output precision and code-specific conversions."""

    converted = legacy_lab_dtype_series(values, dtype=rule.value_dtype)
    for code, divisor in rule.value_divisors_by_code:
        converted.loc[codes.eq(code)] = converted.loc[codes.eq(code)] / divisor
    return converted


def legacy_lab_dtype_series(series: pd.Series, *, dtype: str) -> pd.Series:
    """Downcast safely to the historical feature precision."""

    values = pd.to_numeric(series, errors="coerce").astype("float64")
    if dtype != "float16":
        return values.astype(dtype)
    info = np.finfo(np.float16)
    finite = np.isfinite(values)
    safe = finite & (values >= info.min) & (values <= info.max)
    rounded = pd.Series(np.nan, index=values.index, dtype="float16")
    if safe.any():
        rounded.loc[safe] = values.loc[safe].astype("float16")
    return rounded


def lab_code_priority(rule: LabFeatureRule, codes: pd.Series) -> pd.Series:
    """Return stable code priority for a multi-code feature rule."""

    priorities = dict(rule.code_priority_by_code)
    if not priorities:
        return pd.Series(0, index=codes.index, dtype="int16")
    return (
        codes.astype("string").map(priorities).fillna(len(priorities)).astype("int16")
    )


def float32_series(series: pd.Series) -> pd.Series:
    """Return values using NumPy/pandas float32 output semantics."""

    return pd.Series(
        np.asarray(series, dtype=np.float32),
        index=series.index,
        dtype="float32",
    )


def legacy_csv_visible_numeric_series(series: pd.Series) -> pd.Series:
    """Reproduce the established CSV-visible numeric round trip."""

    return pd.to_numeric(series.astype("string"), errors="coerce")

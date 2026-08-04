"""Pure diagnosis transforms derived from legacy notebooks."""

from __future__ import annotations

import pandas as pd

from ..io.csv import coerce_legacy_na_tokens
from ..validation import require_columns
from .clinical_rules import CodeRule, exact_code_rule, prefix_code_rule
from .code_groups import split_rows_by_code_groups
from .datetimes import parse_trinetx_datetime

RAW_DIAGNOSIS_COLUMNS = [
    "patient_id",
    "encounter_id",
    "code_system",
    "code",
    "principal_diagnosis_indicator",
    "admitting_diagnosis",
    "reason_for_visit",
    "date",
    "derived_by_TriNetX",
    "source_id",
]

DIAGNOSIS_COLUMNS = [
    "patient_id",
    "encounter_id",
    "code",
    "principal_diagnosis_indicator",
    "admitting_diagnosis",
    "reason_for_visit",
    "date",
]

NORMALIZED_DIAGNOSIS_COLUMNS = [
    "patient_id",
    "encounter_id",
    "code_system",
    "code",
    "principal_diagnosis_indicator",
    "admitting_diagnosis",
    "reason_for_visit",
    "date",
]

DROP_COLUMNS = [
    "derived_by_TriNetX",
    "source_id",
]

INDICATOR_COLUMNS = [
    "principal_diagnosis_indicator",
    "admitting_diagnosis",
    "reason_for_visit",
]


DiagnosisCodeGroup = CodeRule


PRIOR_DIAGNOSIS_CODE_GROUPS = [
    prefix_code_rule("HAS_G473", "G47.3"),
    prefix_code_rule("HAS_J45", "J45"),
    prefix_code_rule("HAS_J43", "J43"),
    prefix_code_rule("HAS_J44", "J44"),
    prefix_code_rule("HAS_I50", "I50"),
    prefix_code_rule("HAS_I63", "I63"),
    prefix_code_rule("HAS_N18", "N18"),
    *[
        prefix_code_rule(f"HAS_M{code}", f"M{code}")
        for code in ("05", "06", "30", "31", "32", "33", "34", "35", "36")
    ],
    *[
        prefix_code_rule(f"HAS_F{code}", f"F{code}")
        for code in ("01", "02", "03", "04", "05", "06", "07", "08", "09")
    ],
    *[
        prefix_code_rule(f"HAS_E{code}", f"E{code}")
        for code in ("08", "09", "10", "11", "12", "13")
    ],
    prefix_code_rule("HAS_I70", "I70"),
    prefix_code_rule("HAS_F11", "F11"),
    prefix_code_rule("HAS_F13", "F13"),
    prefix_code_rule("HAS_E84", "E84"),
    prefix_code_rule("HAS_I27", "I27"),
    prefix_code_rule("HAS_D751", "D75.1"),
    *[
        prefix_code_rule(f"HAS_G{code}", f"G{code}")
        for code in ("12", "14", "70", "35", "71", "95", "36", "37")
    ],
    prefix_code_rule("HAS_F17", "F17"),
    prefix_code_rule("HAS_F12", "F12"),
    prefix_code_rule("HAS_F18", "F18"),
]

CURRENT_DIAGNOSIS_CODE_GROUPS = [
    *[
        exact_code_rule(f"HAS_{name}", code)
        for name, code in (
            ("J9612", "J96.12"),
            ("J9622", "J96.22"),
            ("J9602", "J96.02"),
            ("J9692", "J96.92"),
            ("E662", "E66.2"),
            ("J9600", "J96.00"),
            ("J9601", "J96.01"),
            ("J961", "J96.1"),
            ("J9610", "J96.10"),
            ("J9611", "J96.11"),
            ("J962", "J96.2"),
            ("J9620", "J96.20"),
            ("J9621", "J96.21"),
            ("J9690", "J96.90"),
            ("J9691", "J96.91"),
            ("R06", "R06"),
            ("R060", "R06.0"),
            ("R0600", "R06.00"),
            ("R0601", "R06.01"),
            ("R0602", "R06.02"),
            ("R0603", "R06.03"),
            ("R0609", "R06.09"),
            ("R061", "R06.1"),
            ("R062", "R06.2"),
            ("R063", "R06.3"),
            ("R064", "R06.4"),
            ("R065", "R06.5"),
            ("R066", "R06.6"),
            ("R067", "R06.7"),
            ("R068", "R06.8"),
            ("R0681", "R06.81"),
            ("R0682", "R06.82"),
            ("R0683", "R06.83"),
            ("R0689", "R06.89"),
            ("R069", "R06.9"),
        )
    ],
    *[
        prefix_code_rule(f"HAS_J{code}", f"J{code}")
        for code in ("81", "09", "10", "11", "12", "13", "14", "15", "16", "17", "18")
    ],
    prefix_code_rule("HAS_E84", "E84"),
    exact_code_rule(
        "HAS_I50_acute", "I50.33", "I50.31", "I50.23", "I50.21", "I50.43", "I50.41"
    ),
    exact_code_rule("HAS_J440", "J44.0"),
    exact_code_rule("HAS_J441", "J44.1"),
    prefix_code_rule("HAS_J21", "J21"),
    exact_code_rule(
        "HAS_J46",
        "J45.91",
        "J45.92",
        "J45.21",
        "J45.22",
        "J45.31",
        "J45.32",
        "J45.41",
        "J45.42",
        "J45.51",
        "J45.52",
    ),
    exact_code_rule("HAS_Z79891", "Z79.891"),
    exact_code_rule("HAS_E9352", "E935.2"),
    exact_code_rule("HAS_F1110", "F11.10"),
    prefix_code_rule("HAS_T40", "T40"),
    exact_code_rule("HAS_F19982", "F19.982"),
    *[
        prefix_code_rule(f"HAS_{prefix}", prefix)
        for prefix in ("G61", "A41", "R40", "R41", "R53")
    ],
    exact_code_rule("HAS_E8729", "E87.29"),
    exact_code_rule("HAS_G4734", "G47.34"),
    exact_code_rule("HAS_G4735", "G47.35"),
    exact_code_rule("HAS_G4736", "G47.36"),
    exact_code_rule("HAS_E8720", "E87.20"),
    prefix_code_rule("HAS_headache", "R51", "G44"),
]


def _merge_code_groups(
    *groups: list[DiagnosisCodeGroup],
) -> list[DiagnosisCodeGroup]:
    merged: list[DiagnosisCodeGroup] = []
    seen: set[str] = set()
    for group_list in groups:
        for group in group_list:
            if group.name in seen:
                continue
            merged.append(group)
            seen.add(group.name)
    return merged


DIAGNOSIS_CODE_GROUPS = _merge_code_groups(
    PRIOR_DIAGNOSIS_CODE_GROUPS,
    CURRENT_DIAGNOSIS_CODE_GROUPS,
)


def normalize_diagnosis_chunk(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize raw diagnosis exports for downstream processing.

    Args:
        df: Raw diagnosis DataFrame with TriNetX export columns.

    Returns:
        DataFrame with normalized diagnosis columns.
    """

    require_columns(df, RAW_DIAGNOSIS_COLUMNS, context="Diagnosis raw input")

    normalized = coerce_legacy_na_tokens(df.drop(columns=DROP_COLUMNS))
    normalized = normalized.loc[:, NORMALIZED_DIAGNOSIS_COLUMNS]
    normalized["patient_id"] = normalized["patient_id"].astype("string")
    normalized["encounter_id"] = normalized["encounter_id"].astype("string")
    normalized["code_system"] = normalized["code_system"].astype("string")
    normalized["code"] = normalized["code"].astype("string")
    for column in INDICATOR_COLUMNS:
        normalized[column] = (
            normalized[column].replace({"Unknown": "U"}).astype("string")
        )
    normalized["date"] = parse_trinetx_datetime(normalized["date"])
    return normalized.reset_index(drop=True)


def filter_diagnosis_codes(df: pd.DataFrame, rule: CodeRule) -> pd.DataFrame:
    """Filter diagnosis rows by a typed code rule.

    Args:
        df: Normalized diagnosis DataFrame.
        rule: Exact-code and prefix rule to apply.

    Returns:
        Filtered diagnosis DataFrame.
    """

    require_columns(df, DIAGNOSIS_COLUMNS, context="Diagnosis normalized input")

    mask = rule.mask(df["code"])
    filtered = df.loc[mask, DIAGNOSIS_COLUMNS].copy()
    return filtered.reset_index(drop=True)


def split_diagnosis_by_code(
    df: pd.DataFrame,
    code_groups: list[DiagnosisCodeGroup] | None = None,
) -> dict[str, pd.DataFrame]:
    """Split diagnosis rows into code-group extracts.

    Args:
        df: Normalized diagnosis DataFrame.
        code_groups: Optional list of code groups to apply.

    Returns:
        Mapping of code-group name to filtered DataFrame.
    """

    groups = code_groups or DIAGNOSIS_CODE_GROUPS
    return split_rows_by_code_groups(
        df,
        columns=DIAGNOSIS_COLUMNS,
        code_groups=groups,
        context="Diagnosis normalized input",
    )

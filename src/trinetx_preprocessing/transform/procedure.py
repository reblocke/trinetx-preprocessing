"""Pure procedure transforms derived from legacy notebooks."""

from __future__ import annotations

import pandas as pd

from ..validation import require_columns
from .clinical_rules import CodeRule, exact_code_rule
from .code_groups import split_rows_by_code_groups
from .datetimes import parse_trinetx_datetime

RAW_PROCEDURE_COLUMNS = [
    "patient_id",
    "encounter_id",
    "code_system",
    "code",
    "principal_procedure_indicator",
    "date",
    "derived_by_TriNetX",
    "source_id",
]

PROCEDURE_COLUMNS = [
    "patient_id",
    "encounter_id",
    "code",
    "date",
]

NORMALIZED_PROCEDURE_COLUMNS = [
    "patient_id",
    "encounter_id",
    "code_system",
    "code",
    "date",
]

DROP_COLUMNS = [
    "principal_procedure_indicator",
    "derived_by_TriNetX",
    "source_id",
]


ProcedureCodeGroup = CodeRule


PROCEDURE_CODE_GROUPS = [
    exact_code_rule("HAS_94660", "94660"),
    exact_code_rule(
        "HAS_TTE",
        "93303",
        "93304",
        "93306",
        "93307",
        "93308",
        "93356",
    ),
    *[
        exact_code_rule(f"HAS_{code}", code)
        for code in (
            "94640",
            "94664",
            "71045",
            "71046",
            "71250",
            "71260",
            "5A09458",
            "430191008",
            "5A09358",
            "5A09558",
            "94002",
            "94003",
            "5A1945Z",
            "5A1935Z",
            "5A1955Z",
            "5A19054",
            "5A09357",
            "5A09457",
            "5A09557",
            "61911006",
            "91308007",
            "87040",
            "36600",
        )
    ],
    exact_code_rule("HAS_99291", "99291", "99292", "1013729", "1014309"),
    exact_code_rule(
        "HAS_CT_ABDM",
        "74150",
        "74176",
        "74160",
        "74170",
        "36813-4",
        "36267-3",
        "169070004",
        "419394006",
        "BW20ZZZ",
    ),
]


def normalize_procedure_chunk(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize raw procedure exports for downstream processing.

    Args:
        df: Raw procedure DataFrame with TriNetX export columns.

    Returns:
        DataFrame with normalized procedure columns.
    """

    require_columns(df, RAW_PROCEDURE_COLUMNS, context="Procedure raw input")

    normalized = df.drop(columns=DROP_COLUMNS).copy()
    normalized = normalized.loc[:, NORMALIZED_PROCEDURE_COLUMNS]
    normalized["patient_id"] = normalized["patient_id"].astype("string")
    normalized["encounter_id"] = normalized["encounter_id"].astype("string")
    normalized["code_system"] = normalized["code_system"].astype("string")
    normalized["code"] = normalized["code"].astype("string")
    normalized["date"] = parse_trinetx_datetime(normalized["date"])
    return normalized.reset_index(drop=True)


def filter_procedure_by_code(df: pd.DataFrame, rule: CodeRule) -> pd.DataFrame:
    """Filter procedure rows by a typed code rule.

    Args:
        df: Normalized procedure DataFrame.
        rule: Exact-code and prefix rule to apply.

    Returns:
        Filtered procedure DataFrame.
    """

    require_columns(df, PROCEDURE_COLUMNS, context="Procedure normalized input")

    mask = rule.mask(df["code"])
    filtered = df.loc[mask, PROCEDURE_COLUMNS].copy()
    return filtered.reset_index(drop=True)


def split_procedure_by_code(
    df: pd.DataFrame,
    code_groups: list[ProcedureCodeGroup] | None = None,
) -> dict[str, pd.DataFrame]:
    """Split procedure rows into code-group extracts.

    Args:
        df: Normalized procedure DataFrame.
        code_groups: Optional list of code groups to apply.

    Returns:
        Mapping of code-group name to filtered DataFrame.
    """

    groups = code_groups or PROCEDURE_CODE_GROUPS
    return split_rows_by_code_groups(
        df,
        columns=PROCEDURE_COLUMNS,
        code_groups=groups,
        context="Procedure normalized input",
    )

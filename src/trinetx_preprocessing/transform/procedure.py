"""Pure procedure transforms derived from legacy notebooks."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from ..validation import require_columns

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

DROP_COLUMNS = [
    "code_system",
    "principal_procedure_indicator",
    "derived_by_TriNetX",
    "source_id",
]


@dataclass(frozen=True)
class ProcedureCodeGroup:
    """Definition of a procedure code extract."""

    name: str
    regex: str


PROCEDURE_CODE_GROUPS = [
    ProcedureCodeGroup("HAS_94660", r"^94660$"),
    ProcedureCodeGroup(
        "HAS_TTE",
        (
            "^99303$|^99304$|^93306$|^93312$|^93320$|^93321$|^93350$|"
            "^93351$|^93307$|^93308$|^93325$|^93356$"
        ),
    ),
    ProcedureCodeGroup("HAS_94640", r"^94640$"),
    ProcedureCodeGroup("HAS_94664", r"^94664$"),
    ProcedureCodeGroup("HAS_71045", r"^71045$"),
    ProcedureCodeGroup("HAS_71046", r"^71046$"),
    ProcedureCodeGroup("HAS_71250", r"^71250$"),
    ProcedureCodeGroup("HAS_71260", r"^71260$"),
    ProcedureCodeGroup("HAS_99291", r"^99291$|^99292$|^1013729$|^1014309$"),
    ProcedureCodeGroup("HAS_5A09458", r"^5A09458$"),
    ProcedureCodeGroup("HAS_430191008", r"^430191008$"),
    ProcedureCodeGroup("HAS_5A09358", r"^5A09358$"),
    ProcedureCodeGroup("HAS_5A09558", r"^5A09558$"),
    ProcedureCodeGroup("HAS_94002", r"^94002$"),
    ProcedureCodeGroup("HAS_94003", r"^94003$"),
    ProcedureCodeGroup("HAS_5A1945Z", r"^5A1945Z$"),
    ProcedureCodeGroup("HAS_5A1935Z", r"^5A1935Z$"),
    ProcedureCodeGroup("HAS_5A1955Z", r"^5A1955Z$"),
    ProcedureCodeGroup("HAS_5A19054", r"^5A19054$"),
    ProcedureCodeGroup("HAS_5A09357", r"^5A09357$"),
    ProcedureCodeGroup("HAS_5A09457", r"^5A09457$"),
    ProcedureCodeGroup("HAS_5A09557", r"^5A09557$"),
    ProcedureCodeGroup("HAS_61911006", r"^61911006$"),
    ProcedureCodeGroup("HAS_91308007", r"^91308007$"),
    ProcedureCodeGroup("HAS_87040", r"^87040$"),
    ProcedureCodeGroup("HAS_36600", r"^36600$"),
    ProcedureCodeGroup(
        "HAS_CT_ABDM",
        (
            "^74150$|^74176$|^74160$|^74170$|^36813-4$|^36267-3$|"
            "^169070004$|^419394006$|^BW20ZZZ$"
        ),
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
    normalized = normalized.loc[:, PROCEDURE_COLUMNS]
    normalized["patient_id"] = normalized["patient_id"].astype("string")
    normalized["encounter_id"] = normalized["encounter_id"].astype("string")
    normalized["code"] = normalized["code"].astype("string")
    normalized["date"] = pd.to_datetime(normalized["date"])
    return normalized.reset_index(drop=True)


def filter_procedure_by_code(df: pd.DataFrame, regex: str) -> pd.DataFrame:
    """Filter procedure rows by a code pattern.

    Args:
        df: Normalized procedure DataFrame.
        regex: Regex pattern matching procedure codes to retain.

    Returns:
        Filtered procedure DataFrame.
    """

    require_columns(df, PROCEDURE_COLUMNS, context="Procedure normalized input")

    codes = df["code"].astype("string")
    mask = codes.str.match(regex, na=False)
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
    return {group.name: filter_procedure_by_code(df, group.regex) for group in groups}

"""Pure medication transforms derived from legacy notebooks."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from ..validation import require_columns

RAW_MEDICATION_COLUMNS = [
    "patient_id",
    "encounter_id",
    "unique_id",
    "code_system",
    "code",
    "start_date",
    "route",
    "brand",
    "strength",
    "derived_by_TriNetX",
    "source_id",
]

MEDICATION_COLUMNS = [
    "patient_id",
    "encounter_id",
    "code",
    "start_date",
]

DROP_COLUMNS = [
    "unique_id",
    "code_system",
    "route",
    "brand",
    "strength",
    "derived_by_TriNetX",
    "source_id",
]


@dataclass(frozen=True)
class MedicationCodeGroup:
    """Definition of a medication code extract."""

    name: str
    regex: str


MEDICATION_CODE_GROUPS = [
    MedicationCodeGroup("IPmed_list1", r"^6902$|^3264$|^8640$|^5492$|^4452$|^8638$"),
    MedicationCodeGroup("IPmed_list2", r"^7242$|^197$|^4457$"),
    MedicationCodeGroup(
        "IPmed_list3",
        (
            "^7213$|^41126$|^19831$|^10759$|^69120$|^1514$|"
            "^1487514$|^108118$|^25255$|^36117$|^435$|^1424884$"
        ),
    ),
    MedicationCodeGroup("IPmed_list4", r"^4917$|^6057$|^6058$"),
    MedicationCodeGroup("IPmed_list5", r"^4603$|^1808$|^38413$"),
    MedicationCodeGroup(
        "IPmed_list6",
        (
            "^2193$|^18631$|^3640$|^8339$|^20481$|^29561$|"
            "^11124$|^190376$|^82122$|^2180$|^723$|^733$|"
            "^7980$|^7984$"
        ),
    ),
    MedicationCodeGroup(
        "IPmed_list7",
        "^68139$|^10154$|^71535$|^7883$|^319864$|^8782$|^4177$",
    ),
    MedicationCodeGroup(
        "OPmed_list1",
        "^1808$|^2396$|^2409$|^4603$|^5487$|^6916$|^9997$|^38413$",
    ),
    MedicationCodeGroup(
        "OPmed_list2",
        (
            "^817579$|^352362$|^135095$|^1819$|^1841$|^2588474$|"
            "^710303$|^3290$|^22713$|^23088$|^4337$|^3423$|"
            "^484259$|^6754$|^6761$|^7052$|^7238$|^1545902$|"
            "^1007909$|^1806700$|^2392230$|^7676$|^7804$|^7814$|"
            "^7894$|^8001$|^8119$|^8354$|^8785$|^787390$|^10597$|"
            "^10689$"
        ),
    ),
    MedicationCodeGroup("OPmed_list3", r"^6813$|^1819$"),
    MedicationCodeGroup("OPmed_list4", r"^7407$|^591622$"),
    MedicationCodeGroup(
        "OPmed_list5",
        (
            "^7213$|^41126$|^19831$|^10759$|^69120$|^1514$|"
            "^1487514$|^108118$|^25255$|^36117$|^435$|^1424884$"
        ),
    ),
    MedicationCodeGroup("OPmed_list6", r"^21949$|^6845$|^1292$|^2101$"),
]


def normalize_medications_chunk(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize raw medications exports for downstream processing.

    Args:
        df: Raw medications DataFrame with TriNetX export columns.

    Returns:
        DataFrame with normalized medication columns.
    """

    require_columns(df, RAW_MEDICATION_COLUMNS, context="Medications raw input")

    normalized = df.drop(columns=DROP_COLUMNS).copy()
    normalized = normalized.loc[:, MEDICATION_COLUMNS]
    normalized["patient_id"] = normalized["patient_id"].astype("string")
    normalized["encounter_id"] = normalized["encounter_id"].astype("string")
    normalized["code"] = normalized["code"].astype("string")
    normalized["start_date"] = pd.to_datetime(normalized["start_date"])
    return normalized.reset_index(drop=True)


def filter_medications_by_code(df: pd.DataFrame, regex: str) -> pd.DataFrame:
    """Filter medication rows by a code pattern.

    Args:
        df: Normalized medications DataFrame.
        regex: Regex pattern matching medication codes to retain.

    Returns:
        Filtered medications DataFrame.
    """

    require_columns(df, MEDICATION_COLUMNS, context="Medications normalized input")

    codes = df["code"].astype("string")
    mask = codes.str.match(regex, na=False)
    filtered = df.loc[mask, MEDICATION_COLUMNS].copy()
    return filtered.reset_index(drop=True)


def split_medications_by_code(
    df: pd.DataFrame,
    code_groups: list[MedicationCodeGroup] | None = None,
) -> dict[str, pd.DataFrame]:
    """Split medications rows into code-group extracts.

    Args:
        df: Normalized medications DataFrame.
        code_groups: Optional list of code groups to apply.

    Returns:
        Mapping of code-group name to filtered DataFrame.
    """

    groups = code_groups or MEDICATION_CODE_GROUPS
    return {group.name: filter_medications_by_code(df, group.regex) for group in groups}

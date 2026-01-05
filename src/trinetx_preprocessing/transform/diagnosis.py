"""Pure diagnosis transforms derived from legacy notebooks."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from ..validation import require_columns

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

DROP_COLUMNS = [
    "code_system",
    "derived_by_TriNetX",
    "source_id",
]

INDICATOR_COLUMNS = [
    "principal_diagnosis_indicator",
    "admitting_diagnosis",
    "reason_for_visit",
]


@dataclass(frozen=True)
class DiagnosisCodeGroup:
    """Definition of a diagnosis code extract."""

    name: str
    regex: str


PRIOR_DIAGNOSIS_CODE_GROUPS = [
    DiagnosisCodeGroup("HAS_G473", r"^G47.3.*"),
    DiagnosisCodeGroup("HAS_J45", r"^J45.*"),
    DiagnosisCodeGroup("HAS_J43", r"^J43.*"),
    DiagnosisCodeGroup("HAS_J44", r"^J44.*"),
    DiagnosisCodeGroup("HAS_I50", r"^I50.*"),
    DiagnosisCodeGroup("HAS_I63", r"^I63.*"),
    DiagnosisCodeGroup("HAS_N18", r"^N18.*"),
    DiagnosisCodeGroup("HAS_M05", r"^M05.*"),
    DiagnosisCodeGroup("HAS_M06", r"^M06.*"),
    DiagnosisCodeGroup("HAS_M30", r"^M30.*"),
    DiagnosisCodeGroup("HAS_M31", r"^M31.*"),
    DiagnosisCodeGroup("HAS_M32", r"^M32.*"),
    DiagnosisCodeGroup("HAS_M33", r"^M33.*"),
    DiagnosisCodeGroup("HAS_M34", r"^M34.*"),
    DiagnosisCodeGroup("HAS_M35", r"^M35.*"),
    DiagnosisCodeGroup("HAS_M36", r"^M36.*"),
    DiagnosisCodeGroup("HAS_F01", r"^F01.*"),
    DiagnosisCodeGroup("HAS_F02", r"^F02.*"),
    DiagnosisCodeGroup("HAS_F03", r"^F03.*"),
    DiagnosisCodeGroup("HAS_F04", r"^F04.*"),
    DiagnosisCodeGroup("HAS_F05", r"^F05.*"),
    DiagnosisCodeGroup("HAS_F06", r"^F06.*"),
    DiagnosisCodeGroup("HAS_F07", r"^F07.*"),
    DiagnosisCodeGroup("HAS_F08", r"^F08.*"),
    DiagnosisCodeGroup("HAS_F09", r"^F09.*"),
    DiagnosisCodeGroup("HAS_E08", r"^E08.*"),
    DiagnosisCodeGroup("HAS_E09", r"^E09.*"),
    DiagnosisCodeGroup("HAS_E10", r"^E10.*"),
    DiagnosisCodeGroup("HAS_E11", r"^E11.*"),
    DiagnosisCodeGroup("HAS_E12", r"^E12.*"),
    DiagnosisCodeGroup("HAS_E13", r"^E13.*"),
    DiagnosisCodeGroup("HAS_I70", r"^I70.*"),
    DiagnosisCodeGroup("HAS_F11", r"^F11.*"),
    DiagnosisCodeGroup("HAS_F13", r"^F13.*"),
    DiagnosisCodeGroup("HAS_E84", r"^E84.*"),
    DiagnosisCodeGroup("HAS_I27", r"^I27.*"),
    DiagnosisCodeGroup("HAS_D751", r"^D75.1.*"),
    DiagnosisCodeGroup("HAS_G12", r"^G12.*"),
    DiagnosisCodeGroup("HAS_G14", r"^G14.*"),
    DiagnosisCodeGroup("HAS_G70", r"^G70.*"),
    DiagnosisCodeGroup("HAS_G35", r"^G35.*"),
    DiagnosisCodeGroup("HAS_G71", r"^G71.*"),
    DiagnosisCodeGroup("HAS_G95", r"^G95.*"),
    DiagnosisCodeGroup("HAS_G36", r"^G36.*"),
    DiagnosisCodeGroup("HAS_G37", r"^G37.*"),
    DiagnosisCodeGroup("HAS_F17", r"^F17.*"),
    DiagnosisCodeGroup("HAS_F12", r"^F12.*"),
    DiagnosisCodeGroup("HAS_F18", r"^F18.*"),
]

CURRENT_DIAGNOSIS_CODE_GROUPS = [
    DiagnosisCodeGroup("HAS_J9612", r"^J96.12$"),
    DiagnosisCodeGroup("HAS_J9622", r"^J96.22$"),
    DiagnosisCodeGroup("HAS_J9602", r"^J96.02$"),
    DiagnosisCodeGroup("HAS_J9692", r"^J96.92$"),
    DiagnosisCodeGroup("HAS_E662", r"^E66.2$"),
    DiagnosisCodeGroup("HAS_J9600", r"^J96.00$"),
    DiagnosisCodeGroup("HAS_J9601", r"^J96.01$"),
    DiagnosisCodeGroup("HAS_J961", r"^J96.1$"),
    DiagnosisCodeGroup("HAS_J9610", r"^J96.10$"),
    DiagnosisCodeGroup("HAS_J9611", r"^J96.11$"),
    DiagnosisCodeGroup("HAS_J962", r"^J96.2$"),
    DiagnosisCodeGroup("HAS_J9620", r"^J96.20$"),
    DiagnosisCodeGroup("HAS_J9621", r"^J96.21$"),
    DiagnosisCodeGroup("HAS_J9690", r"^J96.90$"),
    DiagnosisCodeGroup("HAS_J9691", r"^J96.91$"),
    DiagnosisCodeGroup("HAS_R06", r"^R06$"),
    DiagnosisCodeGroup("HAS_R060", r"^R06.0$"),
    DiagnosisCodeGroup("HAS_R0600", r"^R06.00$"),
    DiagnosisCodeGroup("HAS_R0601", r"^R06.01$"),
    DiagnosisCodeGroup("HAS_R0602", r"^R06.02$"),
    DiagnosisCodeGroup("HAS_R0603", r"^R06.03$"),
    DiagnosisCodeGroup("HAS_R0609", r"^R06.09$"),
    DiagnosisCodeGroup("HAS_R061", r"^R06.1$"),
    DiagnosisCodeGroup("HAS_R062", r"^R06.2$"),
    DiagnosisCodeGroup("HAS_R063", r"^R06.3$"),
    DiagnosisCodeGroup("HAS_R064", r"^R06.4$"),
    DiagnosisCodeGroup("HAS_R065", r"^R06.5$"),
    DiagnosisCodeGroup("HAS_R066", r"^R06.6$"),
    DiagnosisCodeGroup("HAS_R067", r"^R06.7$"),
    DiagnosisCodeGroup("HAS_R068", r"^R06.8$"),
    DiagnosisCodeGroup("HAS_R0681", r"^R06.81$"),
    DiagnosisCodeGroup("HAS_R0682", r"^R06.82$"),
    DiagnosisCodeGroup("HAS_R0683", r"^R06.83$"),
    DiagnosisCodeGroup("HAS_R0689", r"^R06.89$"),
    DiagnosisCodeGroup("HAS_R069", r"^R06.9$"),
    DiagnosisCodeGroup("HAS_J81", r"^J81.*"),
    DiagnosisCodeGroup("HAS_J09", r"^J09.*"),
    DiagnosisCodeGroup("HAS_J10", r"^J10.*"),
    DiagnosisCodeGroup("HAS_J11", r"^J11.*"),
    DiagnosisCodeGroup("HAS_J12", r"^J12.*"),
    DiagnosisCodeGroup("HAS_J13", r"^J13.*"),
    DiagnosisCodeGroup("HAS_J14", r"^J14.*"),
    DiagnosisCodeGroup("HAS_J15", r"^J15.*"),
    DiagnosisCodeGroup("HAS_J16", r"^J16.*"),
    DiagnosisCodeGroup("HAS_J17", r"^J17.*"),
    DiagnosisCodeGroup("HAS_J18", r"^J18.*"),
    DiagnosisCodeGroup("HAS_E84", r"^E84.*"),
    DiagnosisCodeGroup(
        "HAS_I50_acute",
        ("^I50.33$|^I50.31$|^I50.23$|^I50.21$|^I50.43$|^I50.41$"),
    ),
    DiagnosisCodeGroup("HAS_J440", r"^J44.0$"),
    DiagnosisCodeGroup("HAS_J441", r"^J44.1$"),
    DiagnosisCodeGroup("HAS_J21", r"^J21.*"),
    DiagnosisCodeGroup(
        "HAS_J46",
        (
            "^J45.91$|"
            "^J45.92$|"
            "^J45.21$|"
            "^J45.22$|"
            "^J45.31$|"
            "^J45.32$|"
            "^J45.41$|"
            "^J45.32$|"
            "^J45.51$|"
            "^J45.52$"
        ),
    ),
    DiagnosisCodeGroup("HAS_Z79891", r"^Z79.891$"),
    DiagnosisCodeGroup("HAS_E9352", r"^E935.2$"),
    DiagnosisCodeGroup("HAS_F1110", r"^F11.10$"),
    DiagnosisCodeGroup("HAS_T40", r"^T40.*"),
    DiagnosisCodeGroup("HAS_F19982", r"^F19.982$"),
    DiagnosisCodeGroup("HAS_G61", r"^G61.*"),
    DiagnosisCodeGroup("HAS_A41", r"^A41.*"),
    DiagnosisCodeGroup("HAS_R40", r"^R40.*"),
    DiagnosisCodeGroup("HAS_R41", r"^R41.*"),
    DiagnosisCodeGroup("HAS_R53", r"^R53.*"),
    DiagnosisCodeGroup("HAS_E8729", r"^E87.29$"),
    DiagnosisCodeGroup("HAS_G4734", r"^G47.34$"),
    DiagnosisCodeGroup("HAS_G4735", r"^G47.35$"),
    DiagnosisCodeGroup("HAS_G4736", r"^G47.36$"),
    DiagnosisCodeGroup("HAS_E8720", r"^E87.20$"),
    DiagnosisCodeGroup("HAS_headache", r"^R51.*|^G44.*"),
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

    normalized = df.drop(columns=DROP_COLUMNS).copy()
    normalized = normalized.loc[:, DIAGNOSIS_COLUMNS]
    normalized["patient_id"] = normalized["patient_id"].astype("string")
    normalized["encounter_id"] = normalized["encounter_id"].astype("string")
    normalized["code"] = normalized["code"].astype("string")
    for column in INDICATOR_COLUMNS:
        normalized[column] = (
            normalized[column].replace({"Unknown": "U"}).astype("string")
        )
    normalized["date"] = pd.to_datetime(normalized["date"])
    return normalized.reset_index(drop=True)


def filter_diagnosis_codes(df: pd.DataFrame, regex: str) -> pd.DataFrame:
    """Filter diagnosis rows by an ICD regex pattern.

    Args:
        df: Normalized diagnosis DataFrame.
        regex: Regex pattern matching diagnosis codes to retain.

    Returns:
        Filtered diagnosis DataFrame.
    """

    require_columns(df, DIAGNOSIS_COLUMNS, context="Diagnosis normalized input")

    codes = df["code"].astype("string")
    mask = codes.str.match(regex, na=False)
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
    return {group.name: filter_diagnosis_codes(df, group.regex) for group in groups}

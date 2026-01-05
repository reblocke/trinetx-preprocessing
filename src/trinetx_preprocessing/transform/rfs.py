"""Pure RFS derivations derived from legacy notebooks."""

from __future__ import annotations

from collections.abc import Mapping

import pandas as pd

from ..validation import require_columns
from .diagnosis import DIAGNOSIS_COLUMNS
from .labs import LAB_COLUMNS
from .procedure import PROCEDURE_COLUMNS
from .vitals import VITALS_COLUMNS

RFS_LEGACY_SOURCES = {
    "ABG": "Hypercapnia NEW DATA - RFS Processing.ipynb:51",
    "VBG": "Hypercapnia NEW DATA - RFS Processing.ipynb:122",
    "RESPFAIL": "Hypercapnia NEW DATA - RFS Processing.ipynb:188",
    "OBESITY": "Hypercapnia NEW DATA - RFS Processing.ipynb:247",
    "VENTSUPPORT": "Hypercapnia NEW DATA - RFS Processing.ipynb:341",
    "PREDISPOSITION": "Hypercapnia NEW DATA - RFS Processing.ipynb:1928",
}

ABG_CODE_REGEX = r"^2019-8$|^2026-3$|^32771-8$"
ABG_VALUE_MIN = 5.0
ABG_VALUE_MAX = 200.0

VBG_CODE_REGEX = r"^11557-6$|^2021-4$"
VBG_VALUE_MIN = 5.0
VBG_VALUE_MAX = 200.0

RESPFAIL_CODE_REGEX = r"^J96.*|^E66.2$"

OBESITY_DIAGNOSIS_REGEX = r"^E66.01$|^Z68.41$|^Z68.42$"
OBESITY_BMI_CODE_REGEX = r"^39156-5$"
OBESITY_BMI_MIN = 40.0
OBESITY_BMI_MAX = 100.0

VENTSUPPORT_CODES = [
    "5A09459",
    "5A0945B",
    "5A09559",
    "5A0955B",
    "5A09359",
    "5A0935B",
    "5A09358",
    "5A09458",
    "5A09558",
    "5A09357",
    "5A09457",
    "5A09557",
    "5A0935Z",
    "5A0945Z",
    "5A0955Z",
    "5A1945Z",
    "5A1935Z",
    "5A1955Z",
    "1015098",
    "1014859",
    "94002",
    "94003",
    "94660",
]
VENTSUPPORT_CODE_REGEX = "|".join(f"^{code}$" for code in VENTSUPPORT_CODES)

PREDISPOSITION_CODE_REGEX = (
    "I27.1*|I27.9*|I27.81*|I27.2*|G47.3*|G95*|G71*|G35*|G36*|"
    "G37*|G70*|G12.21*|S14.101*|S14.102*|S14.103*|S14.104*|S14.105*|"
    "S14.106*|S14.107*|S14.15*|S14.12*|S14.109*|S14.10*|S14.1*|D75.1*|"
    "F11*|T40*|E84*|J45*|J44*|J43*|I50*"
)

RFS_FLAG_COLUMNS = [
    ("ABG", "rfs_abg"),
    ("VBG", "rfs_vbg"),
    ("RESPFAIL", "rfs_respfail"),
    ("OBESITY", "rfs_obesity"),
    ("VENTSUPPORT", "rfs_ventsupport"),
    ("PREDISPOSITION", "rfs_predisposition"),
]

RFS_CATEGORIES = [category for category, _ in RFS_FLAG_COLUMNS]

RFS_EVENT_COLUMNS = ["patient_id", "encounter_id", "date"]

RFS_OUTPUT_COLUMNS = ["patient_id", "encounter_id"] + [
    column for _, column in RFS_FLAG_COLUMNS
]

ENCOUNTER_ID_COLUMNS = ["patient_id", "encounter_id"]


def derive_rfs_encounter_sets(
    *,
    labs: pd.DataFrame,
    diagnosis: pd.DataFrame,
    procedure: pd.DataFrame,
    vitals: pd.DataFrame,
) -> dict[str, set[str]]:
    """Derive encounter-id sets for each RFS category.

    Args:
        labs: Normalized lab-results DataFrame.
        diagnosis: Normalized diagnosis DataFrame.
        procedure: Normalized procedure DataFrame.
        vitals: Normalized vital-signs DataFrame.

    Returns:
        Mapping of RFS category name to encounter-id set.
    """
    events = derive_rfs_event_frames(
        labs=labs,
        diagnosis=diagnosis,
        procedure=procedure,
        vitals=vitals,
    )
    return {category: _encounter_ids(frame) for category, frame in events.items()}


def derive_rfs_encounter_sets_from_domains(
    domains: Mapping[str, pd.DataFrame],
) -> dict[str, set[str]]:
    """Derive encounter-id sets using a domain mapping."""

    return derive_rfs_encounter_sets(
        labs=domains["labs"],
        diagnosis=domains["diagnosis"],
        procedure=domains["procedure"],
        vitals=domains["vitals"],
    )


def derive_rfs_event_frames(
    *,
    labs: pd.DataFrame,
    diagnosis: pd.DataFrame,
    procedure: pd.DataFrame,
    vitals: pd.DataFrame,
) -> dict[str, pd.DataFrame]:
    """Derive event-level RFS rows with encounter dates.

    Args:
        labs: Normalized lab-results DataFrame.
        diagnosis: Normalized diagnosis DataFrame.
        procedure: Normalized procedure DataFrame.
        vitals: Normalized vital-signs DataFrame.

    Returns:
        Mapping of RFS category name to event DataFrame with ``date``.
    """

    abg = _select_event_columns(
        _filter_lab_results(labs, ABG_CODE_REGEX, ABG_VALUE_MIN, ABG_VALUE_MAX)
    )
    vbg = _select_event_columns(
        _filter_lab_results(labs, VBG_CODE_REGEX, VBG_VALUE_MIN, VBG_VALUE_MAX)
    )
    respfail = _select_event_columns(_filter_diagnosis(diagnosis, RESPFAIL_CODE_REGEX))
    obesity_dx = _select_event_columns(
        _filter_diagnosis(diagnosis, OBESITY_DIAGNOSIS_REGEX)
    )
    obesity_vitals = _select_event_columns(
        _filter_vitals(vitals, OBESITY_BMI_CODE_REGEX, OBESITY_BMI_MIN, OBESITY_BMI_MAX)
    )
    ventsupport = _select_event_columns(
        _filter_procedure(procedure, VENTSUPPORT_CODE_REGEX)
    )
    predisposition = _select_event_columns(
        _filter_diagnosis(diagnosis, PREDISPOSITION_CODE_REGEX)
    )

    obesity = pd.concat([obesity_dx, obesity_vitals], ignore_index=True)
    if obesity.empty:
        obesity = pd.DataFrame(columns=RFS_EVENT_COLUMNS)

    return {
        "ABG": abg,
        "VBG": vbg,
        "RESPFAIL": respfail,
        "OBESITY": obesity,
        "VENTSUPPORT": ventsupport,
        "PREDISPOSITION": predisposition,
    }


def build_rfs_flags(
    encounters: pd.DataFrame,
    rfs_sets: Mapping[str, set[str]],
) -> pd.DataFrame:
    """Build encounter-level RFS flag table.

    Args:
        encounters: Encounter DataFrame containing patient/encounter identifiers.
        rfs_sets: Mapping of RFS category name to encounter-id set.

    Returns:
        DataFrame with one row per encounter and boolean RFS flags.
    """

    require_columns(encounters, ENCOUNTER_ID_COLUMNS, context="Encounter inputs")
    base = encounters.loc[:, ENCOUNTER_ID_COLUMNS].drop_duplicates().copy()
    base["patient_id"] = base["patient_id"].astype("string")
    base["encounter_id"] = base["encounter_id"].astype("string")

    for category, column in RFS_FLAG_COLUMNS:
        encounter_ids = rfs_sets.get(category, set())
        base[column] = base["encounter_id"].isin(encounter_ids)

    return base.loc[:, RFS_OUTPUT_COLUMNS].reset_index(drop=True)


def derive_rfs_encounter_flags(
    encounters: pd.DataFrame,
    *,
    labs: pd.DataFrame,
    diagnosis: pd.DataFrame,
    procedure: pd.DataFrame,
    vitals: pd.DataFrame,
) -> pd.DataFrame:
    """Derive encounter-level RFS flags from normalized inputs."""

    rfs_sets = derive_rfs_encounter_sets(
        labs=labs,
        diagnosis=diagnosis,
        procedure=procedure,
        vitals=vitals,
    )
    return build_rfs_flags(encounters, rfs_sets)


def _select_event_columns(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=RFS_EVENT_COLUMNS)
    return df.loc[:, RFS_EVENT_COLUMNS].copy()


def _filter_lab_results(
    labs: pd.DataFrame,
    regex: str,
    min_value: float,
    max_value: float,
) -> pd.DataFrame:
    require_columns(labs, LAB_COLUMNS, context="Lab results normalized input")
    codes = labs["code"].astype("string")
    mask = codes.str.match(regex, na=False)
    filtered = labs.loc[mask, LAB_COLUMNS].copy()
    if filtered.empty:
        return filtered
    values = pd.to_numeric(filtered["lab_result_num_val"], errors="coerce")
    mask = (values > min_value) & (values < max_value)
    filtered["lab_result_num_val"] = values
    return filtered.loc[mask].reset_index(drop=True)


def _filter_diagnosis(diagnosis: pd.DataFrame, regex: str) -> pd.DataFrame:
    require_columns(diagnosis, DIAGNOSIS_COLUMNS, context="Diagnosis normalized input")
    codes = diagnosis["code"].astype("string")
    mask = codes.str.match(regex, na=False)
    return diagnosis.loc[mask, DIAGNOSIS_COLUMNS].reset_index(drop=True)


def _filter_procedure(procedure: pd.DataFrame, regex: str) -> pd.DataFrame:
    require_columns(procedure, PROCEDURE_COLUMNS, context="Procedure normalized input")
    codes = procedure["code"].astype("string")
    mask = codes.str.match(regex, na=False)
    return procedure.loc[mask, PROCEDURE_COLUMNS].reset_index(drop=True)


def _filter_vitals(
    vitals: pd.DataFrame,
    regex: str,
    min_value: float,
    max_value: float,
) -> pd.DataFrame:
    require_columns(vitals, VITALS_COLUMNS, context="Vitals normalized input")
    codes = vitals["code"].astype("string")
    mask = codes.str.match(regex, na=False)
    filtered = vitals.loc[mask, VITALS_COLUMNS].copy()
    if filtered.empty:
        return filtered
    values = pd.to_numeric(filtered["value"], errors="coerce")
    mask = (values >= min_value) & (values < max_value)
    filtered["value"] = values
    return filtered.loc[mask].reset_index(drop=True)


def _encounter_ids(df: pd.DataFrame) -> set[str]:
    if df.empty:
        return set()
    return set(df["encounter_id"].dropna().astype("string"))


def _encounter_ids_from_frames(frames: list[pd.DataFrame]) -> set[str]:
    encounter_ids: set[str] = set()
    for frame in frames:
        encounter_ids.update(_encounter_ids(frame))
    return encounter_ids

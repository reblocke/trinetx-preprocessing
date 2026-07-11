"""Orchestrate domain feature enrichment for final analytic outputs."""

from __future__ import annotations

import logging

import pandas as pd

from ..config import Config
from ..guardrails import log_row_count
from ..transform.procedure import PROCEDURE_CODE_GROUPS, PROCEDURE_COLUMNS
from . import final_diagnosis_features as _diagnosis
from . import final_lab_features as _labs
from . import final_medication_features as _medications
from . import final_procedure_features as _procedures
from . import final_vital_features as _vitals
from .final_feature_common import _string_id_set
from .final_feature_sources import FinalFeatureBucket

DIAGNOSIS_COLUMNS = _diagnosis.DIAGNOSIS_COLUMNS
LAB_COLUMNS = _labs.LAB_COLUMNS
LAB_VALUE_RULES = _labs.LAB_VALUE_RULES
MEDICATION_COLUMNS = _medications.MEDICATION_COLUMNS
VITALS_COLUMNS = _vitals.VITALS_COLUMNS

_FinalLabCandidateStore = _labs._FinalLabCandidateStore
_FinalPreviousVitalCandidateStore = _vitals._FinalPreviousVitalCandidateStore
_legacy_lab_feature_values = _labs._legacy_lab_feature_values
_merge_current_diagnosis_features = _diagnosis._merge_current_diagnosis_features
_merge_encounter_first_last_features = _procedures._merge_encounter_first_last_features
_merge_lab_value_features = _labs._merge_lab_value_features
_merge_medication_features = _medications._merge_medication_features
_merge_previous_vital_features = _vitals._merge_previous_vital_features
_merge_prior_diagnosis_features = _diagnosis._merge_prior_diagnosis_features
_merge_vital_value_features = _vitals._merge_vital_value_features
_select_current_diagnosis = _diagnosis._select_current_diagnosis
_select_ip_medication = _medications._select_ip_medication

LEGACY_SEX_CODES = {"F": 0, "M": 1, "Unknown": 2}
LEGACY_RACE_CODES = {
    "White": 0,
    "Black or African American": 1,
    "Black": "Black",
    "Unknown": 2,
    "Asian": 3,
    "American Indian or Alaska Native": 4,
    "Native Hawaiian or Other Pacific Islander": 5,
}
LEGACY_ETHNICITY_CODES = {
    "Not Hispanic or Latino": 0,
    "Non-Hispanic": "Non-Hispanic",
    "Hispanic or Latino": 1,
    "Hispanic": "Hispanic",
    "Unknown": 2,
}
LEGACY_LOCATION_CODES = {"South": 0, "Northeast": 1, "Midwest": 2, "West": 3}

FINAL_EVENT_DEFAULT_CHUNK_ROWS = 500_000


def _enrich_legacy_final_features(
    df: pd.DataFrame,
    *,
    config: Config,
    chunksize: int | None,
    logger: logging.Logger,
    source_bucket: FinalFeatureBucket | None = None,
) -> pd.DataFrame:
    """Add historical analytic final-output columns from work-table extracts."""

    if df.empty:
        return df

    enriched = _recode_legacy_base_columns(df)
    patient_ids = _string_id_set(enriched["patient_id"])
    encounter_ids = _string_id_set(enriched["encounter_id"])
    effective_chunksize = chunksize or FINAL_EVENT_DEFAULT_CHUNK_ROWS

    enriched = _merge_vital_value_features(
        enriched,
        config=config,
        patient_ids=patient_ids,
        encounter_ids=encounter_ids,
        chunksize=effective_chunksize,
        source_bucket=source_bucket,
    )
    enriched = _merge_previous_vital_features(
        enriched,
        config=config,
        patient_ids=patient_ids,
        encounter_ids=encounter_ids,
        chunksize=effective_chunksize,
        source_bucket=source_bucket,
    )
    enriched = _merge_lab_value_features(
        enriched,
        config=config,
        patient_ids=patient_ids,
        encounter_ids=encounter_ids,
        chunksize=effective_chunksize,
        source_bucket=source_bucket,
    )
    enriched = _merge_current_diagnosis_features(
        enriched,
        config=config,
        patient_ids=patient_ids,
        encounter_ids=encounter_ids,
        chunksize=effective_chunksize,
        source_bucket=source_bucket,
    )
    enriched = _merge_encounter_first_last_features(
        enriched,
        config=config,
        groups=PROCEDURE_CODE_GROUPS,
        source_columns=PROCEDURE_COLUMNS,
        patient_ids=patient_ids,
        encounter_ids=encounter_ids,
        chunksize=effective_chunksize,
        source_bucket=source_bucket,
    )
    enriched = _merge_prior_diagnosis_features(
        enriched,
        config=config,
        patient_ids=patient_ids,
        encounter_ids=encounter_ids,
        chunksize=effective_chunksize,
        source_bucket=source_bucket,
    )
    enriched = _merge_medication_features(
        enriched,
        config=config,
        patient_ids=patient_ids,
        encounter_ids=encounter_ids,
        chunksize=effective_chunksize,
        source_bucket=source_bucket,
    )
    log_row_count(logger, "final analytic feature rows", len(enriched))
    return enriched


def _recode_legacy_base_columns(df: pd.DataFrame) -> pd.DataFrame:
    frame = df.copy()
    if "patient_regional_location" in frame.columns:
        frame = frame.rename(columns={"patient_regional_location": "location"})

    frame["sex"] = frame["sex"].map(
        lambda value: LEGACY_SEX_CODES.get(value, value)
        if not pd.isna(value)
        else value
    )
    frame["race"] = frame["race"].map(
        lambda value: LEGACY_RACE_CODES.get(value, value)
        if not pd.isna(value)
        else value
    )
    frame["ethnicity"] = frame["ethnicity"].map(
        lambda value: LEGACY_ETHNICITY_CODES.get(value, value)
        if not pd.isna(value)
        else value
    )
    frame["location"] = frame["location"].map(
        lambda value: LEGACY_LOCATION_CODES.get(value, value)
        if not pd.isna(value)
        else value
    )
    frame["death_year_month"] = frame["death_year_month"].fillna("").replace({"": " "})
    return frame

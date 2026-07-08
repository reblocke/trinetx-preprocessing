"""Final dataset assembly stage built from legacy notebook logic."""

from __future__ import annotations

import hashlib
import logging
import re
import sqlite3
import tempfile
from collections.abc import Collection
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from ..config import Config, ConfigError, collect_domain_paths
from ..filesystem import remove_tree_strict
from ..guardrails import (
    GuardrailConfig,
    check_join_multiplier,
    check_required_ids,
    log_row_count,
)
from ..storage import find_work_tables, iter_work_tables, resolve_work_table
from ..transform.diagnosis import (
    CURRENT_DIAGNOSIS_CODE_GROUPS,
    DIAGNOSIS_COLUMNS,
    INDICATOR_COLUMNS,
    PRIOR_DIAGNOSIS_CODE_GROUPS,
)
from ..transform.labs import LAB_COLUMNS
from ..transform.medications import MEDICATION_CODE_GROUPS, MEDICATION_COLUMNS
from ..transform.procedure import PROCEDURE_CODE_GROUPS, PROCEDURE_COLUMNS
from ..transform.rfs import RFS_CATEGORIES, RFS_EVENT_COLUMNS
from ..transform.vitals import VITAL_SIGN_RULES, VITALS_COLUMNS
from ..validation import require_columns
from .final_output_schema import FINAL_OUTPUT_COLUMNS

QUALIFY_DATE_MIN = pd.Timestamp("2022-01-01")
QUALIFY_DATE_MAX = pd.Timestamp("2022-12-31")

SETTINGS = ("AMB", "EMER", "INPAT")

SETTING_ENCOUNTER_FILES = {
    "AMB": "AMB_encounters.csv",
    "EMER": "EMER_encounters.csv",
    "INPAT": "INPAT_encounters.csv",
}

SETTING_OUTPUT_DIRS = {
    "AMB": "AMBULATORY",
    "EMER": "EMERGENCY",
    "INPAT": "INPATIENT",
}

SETTING_DATA_CHECKS = {
    "AMB": "amb_enc_screen.csv",
    "EMER": "inp_enc_screen.csv",
    "INPAT": "inp_enc_screen.csv",
}

DEMOGRAPHIC_COLUMNS = [
    "patient_id",
    "sex",
    "race",
    "ethnicity",
    "year_of_birth",
    "patient_regional_location",
    "month_year_death",
]

DEMOGRAPHIC_OUTPUT_COLUMNS = [
    "patient_id",
    "sex",
    "race",
    "ethnicity",
    "patient_regional_location",
    "birth_year",
    "death_year_month",
]

ENCOUNTER_COLUMNS = ["encounter_id", "start_date", "end_date", "LOS"]

BASE_FINAL_OUTPUT_COLUMNS = [
    "patient_id",
    "encounter_id",
    "qualify_date",
    "RFS",
    "encounter_type",
    "age_at_encounter",
    "sex",
    "race",
    "ethnicity",
    "patient_regional_location",
    "death_year_month",
    "LOS",
]

LEGACY_BASE_OUTPUT_COLUMNS = [
    "patient_id",
    "encounter_id",
    "encounter_type",
    "RFS",
    "qualify_date",
    "sex",
    "race",
    "ethnicity",
    "death_year_month",
    "location",
    "age_at_encounter",
    "LOS",
]

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

FINAL_ENCOUNTER_BUCKET_COUNT = 256
FINAL_ENCOUNTER_BUCKET_COLUMNS = ["encounter_id_key", *ENCOUNTER_COLUMNS]
FINAL_EVENT_BUCKET_COUNT = 256
FINAL_EVENT_DEFAULT_CHUNK_ROWS = 500_000
FINAL_EVENT_CANDIDATE_COLUMNS = [
    "patient_id",
    "encounter_id",
    "qualify_date",
    "RFS",
    "sex",
    "race",
    "ethnicity",
    "patient_regional_location",
    "birth_year",
    "death_year_month",
]
FINAL_EVENT_BUCKET_COLUMNS = [*FINAL_EVENT_CANDIDATE_COLUMNS, "_row_order"]
FINAL_LAB_BUCKET_COUNT = 256
FINAL_LAB_FEATURE_FIRST = "first"
FINAL_LAB_FEATURE_HIGHEST = "highest"
FINAL_LAB_CODE_PRIORITY_COLUMN = "_code_priority"
FINAL_LAB_BUCKET_COLUMNS = [
    "rule_name",
    "feature_kind",
    *LAB_COLUMNS,
    FINAL_LAB_CODE_PRIORITY_COLUMN,
]
FINAL_PREVIOUS_VITAL_BUCKET_COUNT = 256
FINAL_PREVIOUS_VITAL_BUCKET_COLUMNS = ["vital_name", *VITALS_COLUMNS]


@dataclass(frozen=True)
class _LabValueRule:
    name: str
    regex: str
    min_value: float
    max_value: float
    include_highest: bool = False
    min_inclusive: bool = False
    value_dtype: str = "float16"
    value_divisors_by_code: dict[str, float] | None = None
    code_priority_by_code: dict[str, int] | None = None


LAB_VALUE_RULES = [
    _LabValueRule("value_20198", r"^2019-8$", 5, 200, include_highest=True),
    _LabValueRule("value_115576", r"^11557-6$", 2, 250, include_highest=True),
    _LabValueRule("value_327718", r"^32771-8$", 2, 250, include_highest=True),
    _LabValueRule(
        "value_VBG_CO2",
        r"^2021-4$|^40619-9$",
        10,
        250,
        include_highest=True,
    ),
    _LabValueRule(
        "value_PCO2_Unspec_blood",
        r"^34705-4$|^11557-6$",
        10,
        250,
        include_highest=True,
    ),
    _LabValueRule("value_27441", r"^2744-1$", 6.5, 7.8),
    _LabValueRule("value_27466", r"^2746-6$", 6.4, 7.7),
    _LabValueRule("value_19604_20263", r"^1960-4$|^2026-3$", 0.5, 60),
    _LabValueRule("value_146274", r"^14627-4$", 0.5, 60),
    _LabValueRule("value_29512", r"^2951-2$|^2947-0$|^77139-4$", 80, 190),
    _LabValueRule("value_21600", r"^2160-0$|^38483-4$", 0.1, 20),
    _LabValueRule("value_7187", r"^718-7$", 3, 25),
    _LabValueRule(
        "value_serum_bicarb",
        r"^20565-8$|^1963-8$|^1959-6$|^1962-0$|^2028-9$",
        0.5,
        60,
    ),
    _LabValueRule("value_serum_chloride", r"^77138-6$|^2069-3$|^2075-0$", 50, 150),
    _LabValueRule("value_serum_lactate", r"^32693-4$|^2524-7$", 0.1, 50),
    _LabValueRule(
        "value_potassium",
        r"^6298-4$|^2823-3$|^77142-8$",
        1.8,
        12,
        min_inclusive=True,
    ),
    _LabValueRule("value_192583", r"^19258-3$", 10, 300),
    _LabValueRule("value_394866", r"^39486-6$", 6.4, 7.7),
    _LabValueRule("value_27052", r"^2705-2$", 10, 300),
    _LabValueRule(
        "value_Lactate_Venous_Blood",
        r"^30241-4$|^2519-7$",
        0.1,
        50,
        value_divisors_by_code={"30241-4": 9.008},
        code_priority_by_code={"30241-4": 0, "2519-7": 1},
    ),
    _LabValueRule("value_483917", r"^48391-7$", 2, 60),
    _LabValueRule("value_27037", r"^2703-7$", 20, 500),
    _LabValueRule("value_192559", r"^19255-9$", 20, 500),
    _LabValueRule("value_332544", r"^33254-4$", 6.5, 7.8),
    _LabValueRule("value_25189", r"^2518-9$", 0.1, 50),
    _LabValueRule("value_115584", r"^11558-4$", 6.5, 7.8),
    _LabValueRule("value_115568", r"^11556-8$", 5, 500),
    _LabValueRule(
        "value_264648",
        r"^26464-8$|^49498-9$|^6690-2$|^804-5$",
        0,
        500000,
        value_dtype="float64",
    ),
    _LabValueRule("value_265157", r"^26515-7$|^778-1$|^777-3$|^49497-1$", 0, 5000),
    _LabValueRule(
        "value_bnp",
        r"^42637-9$|^30934-4$",
        0,
        500000,
        value_dtype="float64",
    ),
    _LabValueRule("value_phos", r"^2774-8$|^2777-1$", 0, 30),
    _LabValueRule("value_ca", r"^49765-1$|^17861-6$", 4, 30),
    _LabValueRule("value_albumin", r"^2862-1$|^1751-7$|^61152-5$|^61151-7$", 0.5, 6),
    _LabValueRule("value_tprot", r"^2885-2$", 2, 12),
]


@dataclass(frozen=True)
class _SettingInputs:
    encounters: pd.DataFrame | "_EncounterLookup"
    output_dir: Path
    data_checks_path: Path | None
    allowed_encounter_ids: Collection[str] | "_EncounterIdLookup" | None


def run_final_assembly(config: Config, *, strict: bool = False) -> list[Path]:
    """Run the final dataset assembly stage.

    Args:
        config: Pipeline configuration.
        strict: Whether to enable guardrail assertions.

    Returns:
        List of written file paths.
    """

    logger = logging.getLogger(__name__)
    domain_paths = collect_domain_paths(config)
    patient_paths = domain_paths.get("patient")
    if not patient_paths:
        raise ConfigError("Patient domain is not configured.")

    chunksize = config.chunking.lines_per_chunk if config.chunking.enabled else None
    with ExitStack() as stack:
        demographics = _load_demographics_lookup(
            patient_paths,
            work_dir=config.work_dir,
            stack=stack,
            logger=logger,
            chunksize=chunksize,
        )
        setting_inputs = _load_setting_inputs(
            config,
            logger,
            chunksize=chunksize,
            stack=stack,
        )

        output_paths: dict[tuple[str, str, str], Path] = {}
        for category in RFS_CATEGORIES:
            event_candidates = _load_final_event_candidates(
                config,
                category,
                demographics,
                logger,
                chunksize=chunksize,
                guardrails=config.guardrails,
                strict=strict,
            )
            for setting in SETTINGS:
                inputs = setting_inputs[setting]
                before = build_final_dataset_from_candidates(
                    event_candidates,
                    inputs.encounters,
                    config=config,
                    rfs_category=category,
                    setting=setting,
                    guardrails=config.guardrails,
                    strict=strict,
                    logger=logger,
                )
                before_path = (
                    inputs.output_dir / f"RFS_{category}_ENC_{setting}_BEFORE.csv"
                )
                before.to_csv(before_path, index=False)
                output_paths[(setting, category, "BEFORE")] = before_path

                after = apply_data_checks(
                    before,
                    inputs.data_checks_path,
                    allowed_encounter_ids=inputs.allowed_encounter_ids,
                    data_checks_preloaded=True,
                    context=f"{category}/{setting}",
                    logger=logger,
                )
                after_path = (
                    inputs.output_dir / f"RFS_{category}_ENC_{setting}_AFTER.csv"
                )
                after.to_csv(after_path, index=False)
                output_paths[(setting, category, "AFTER")] = after_path

                logger.info(
                    "Wrote %s rows for %s/%s to %s",
                    len(after),
                    category,
                    setting,
                    after_path.name,
                )

    return _ordered_final_output_paths(output_paths)


def _load_setting_inputs(
    config: Config,
    logger: logging.Logger,
    *,
    chunksize: int | None,
    stack: ExitStack,
) -> dict[str, _SettingInputs]:
    setting_inputs: dict[str, _SettingInputs] = {}
    data_check_cache: dict[Path, _EncounterIdLookup | None] = {}
    for setting in SETTINGS:
        encounters = _load_encounter_lookup(
            config,
            setting,
            logger,
            stack=stack,
            chunksize=chunksize,
        )
        output_dir = config.output_dir / SETTING_OUTPUT_DIRS[setting]
        output_dir.mkdir(parents=True, exist_ok=True)
        data_checks_path = _data_checks_path(config.work_dir, setting)
        allowed_encounter_ids = _cached_data_check_lookup(
            data_check_cache,
            data_checks_path,
            work_dir=config.work_dir,
            stack=stack,
            logger=logger,
            chunksize=chunksize,
        )
        setting_inputs[setting] = _SettingInputs(
            encounters=encounters,
            output_dir=output_dir,
            data_checks_path=data_checks_path
            if allowed_encounter_ids is not None
            else None,
            allowed_encounter_ids=allowed_encounter_ids,
        )
    return setting_inputs


def _ordered_final_output_paths(
    output_paths: dict[tuple[str, str, str], Path],
) -> list[Path]:
    return [
        output_paths[(setting, category, suffix)]
        for setting in SETTINGS
        for category in RFS_CATEGORIES
        for suffix in ("BEFORE", "AFTER")
    ]


def build_final_dataset(
    events: pd.DataFrame,
    demographics: pd.DataFrame | _DemographicsLookup,
    encounters: pd.DataFrame | "_EncounterLookup",
    *,
    rfs_category: str,
    setting: str,
    guardrails: GuardrailConfig,
    strict: bool,
    logger: logging.Logger | None = None,
) -> pd.DataFrame:
    """Construct a final dataset for a single RFS/setting pair."""

    logger = logger or logging.getLogger(__name__)

    event_candidates = build_final_event_candidates(
        events,
        demographics,
        rfs_category=rfs_category,
        context=f"{rfs_category}/{setting}",
        guardrails=guardrails,
        strict=strict,
        logger=logger,
    )
    return build_final_dataset_from_candidates(
        event_candidates,
        encounters,
        config=None,
        rfs_category=rfs_category,
        setting=setting,
        guardrails=guardrails,
        strict=strict,
        logger=logger,
    )


def build_final_event_candidates(
    events: pd.DataFrame,
    demographics: pd.DataFrame | _DemographicsLookup,
    *,
    rfs_category: str,
    context: str,
    guardrails: GuardrailConfig,
    strict: bool,
    logger: logging.Logger | None = None,
) -> pd.DataFrame:
    """Build setting-independent final-event candidates for one RFS category."""

    logger = logger or logging.getLogger(__name__)

    if events.empty:
        return pd.DataFrame(columns=FINAL_EVENT_CANDIDATE_COLUMNS)

    require_columns(events, RFS_EVENT_COLUMNS, context="RFS events")
    if not isinstance(demographics, _DemographicsLookup):
        require_columns(
            demographics, DEMOGRAPHIC_OUTPUT_COLUMNS, context="Demographics"
        )

    assembled = events.loc[:, RFS_EVENT_COLUMNS].copy()
    assembled["patient_id"] = assembled["patient_id"].astype("string")
    assembled["encounter_id"] = assembled["encounter_id"].astype("string")
    assembled = assembled.rename(columns={"date": "qualify_date"})
    assembled["qualify_date"] = pd.to_datetime(
        assembled["qualify_date"], errors="coerce"
    )
    assembled = assembled.loc[
        assembled["qualify_date"].between(QUALIFY_DATE_MIN, QUALIFY_DATE_MAX)
    ]
    assembled = assembled.dropna(subset=["patient_id", "encounter_id", "qualify_date"])
    log_row_count(
        logger,
        f"final {context} post-filter dates",
        len(assembled),
    )
    if strict:
        check_required_ids(
            assembled,
            ["patient_id", "encounter_id"],
            context=f"final {context} events",
        )

    demographics_frame = _demographics_frame_for_merge(
        demographics,
        assembled["patient_id"],
    )
    assembled = _merge_with_guardrails(
        assembled,
        demographics_frame,
        on="patient_id",
        validate="many_to_one",
        context=f"final {context} demographics",
        guardrails=guardrails,
        strict=strict,
        logger=logger,
    )

    assembled.insert(loc=2, column="RFS", value=rfs_category)

    assembled = assembled.loc[
        ~assembled["patient_regional_location"].isin(["Ex-US", "Unknown"])
    ]
    assembled = assembled.dropna().reset_index(drop=True)
    log_row_count(
        logger,
        f"final {context} post-filter location",
        len(assembled),
    )

    assembled = assembled.sort_values(
        by=["qualify_date", "encounter_id"],
        ascending=[True, False],
        kind="mergesort",
    )
    assembled = assembled.drop_duplicates(subset=["encounter_id"], keep="first")
    assembled = assembled.drop_duplicates(subset=["patient_id"], keep="first")
    return assembled.loc[:, FINAL_EVENT_CANDIDATE_COLUMNS].reset_index(drop=True)


def build_final_dataset_from_candidates(
    event_candidates: pd.DataFrame,
    encounters: pd.DataFrame | "_EncounterLookup",
    *,
    config: Config | None = None,
    rfs_category: str,
    setting: str,
    guardrails: GuardrailConfig,
    strict: bool,
    logger: logging.Logger | None = None,
) -> pd.DataFrame:
    """Merge reduced final-event candidates with one setting encounter lookup."""

    logger = logger or logging.getLogger(__name__)

    if event_candidates.empty:
        return pd.DataFrame(columns=FINAL_OUTPUT_COLUMNS)

    require_columns(
        event_candidates,
        FINAL_EVENT_CANDIDATE_COLUMNS,
        context=f"final {rfs_category}/{setting} event candidates",
    )
    if not isinstance(encounters, _EncounterLookup):
        require_columns(encounters, ENCOUNTER_COLUMNS, context="Encounter subset")

    assembled = event_candidates.loc[:, FINAL_EVENT_CANDIDATE_COLUMNS].copy()

    encounters_frame = _encounters_frame_for_merge(
        encounters,
        assembled["encounter_id"],
    )
    assembled = _merge_with_guardrails(
        assembled,
        encounters_frame,
        on="encounter_id",
        validate="many_to_one",
        context=f"final {rfs_category}/{setting} encounters",
        guardrails=guardrails,
        strict=strict,
        logger=logger,
    )

    assembled["start_date"] = pd.to_datetime(assembled["start_date"], errors="coerce")
    assembled["end_date"] = pd.to_datetime(assembled["end_date"], errors="coerce")
    assembled = assembled.loc[
        (assembled["qualify_date"] >= assembled["start_date"])
        & (assembled["qualify_date"] <= assembled["end_date"])
    ]
    log_row_count(
        logger,
        f"final {rfs_category}/{setting} post-filter encounter dates",
        len(assembled),
    )
    assembled = assembled.drop(columns=["start_date", "end_date"])

    assembled.insert(loc=2, column="encounter_type", value=setting)

    assembled["age_at_encounter"] = (
        assembled["qualify_date"].dt.year - assembled["birth_year"]
    )
    assembled = assembled.loc[
        (assembled["age_at_encounter"] >= 18) & (assembled["age_at_encounter"] < 110)
    ]
    log_row_count(
        logger,
        f"final {rfs_category}/{setting} post-filter age",
        len(assembled),
    )
    assembled = assembled.drop(columns=["birth_year"])

    assembled = _ensure_identifiers(assembled)
    if config is not None:
        assembled = _enrich_legacy_final_features(
            assembled,
            config=config,
            chunksize=config.chunking.lines_per_chunk
            if config.chunking.enabled
            else None,
            logger=logger,
        )
    assembled = _finalize_output(assembled)
    return assembled.loc[:, FINAL_OUTPUT_COLUMNS]


def apply_data_checks(
    df: pd.DataFrame,
    data_checks_path: Path | None,
    *,
    allowed_encounter_ids: Collection[str] | "_EncounterIdLookup" | None = None,
    data_checks_preloaded: bool = False,
    chunksize: int | None = None,
    context: str,
    logger: logging.Logger | None = None,
) -> pd.DataFrame:
    """Apply encounter-level data checks if available."""

    logger = logger or logging.getLogger(__name__)

    if df.empty:
        return _finalize_output(df)

    allowed = allowed_encounter_ids
    if allowed is None and data_checks_preloaded:
        return _finalize_output(df)
    if allowed is None:
        allowed = _load_data_check_encounter_ids(
            data_checks_path,
            logger=logger,
            chunksize=chunksize,
        )
    if allowed is None:
        return _finalize_output(df)

    if isinstance(allowed, _EncounterIdLookup):
        filtered = allowed.filter_frame(df)
    else:
        filtered = df.loc[df["encounter_id"].astype("string").isin(allowed)].copy()
    log_row_count(logger, f"final {context} post-filter data checks", len(filtered))
    return _finalize_output(filtered)


def _enrich_legacy_final_features(
    df: pd.DataFrame,
    *,
    config: Config,
    chunksize: int | None,
    logger: logging.Logger,
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
    )
    enriched = _merge_previous_vital_features(
        enriched,
        config=config,
        patient_ids=patient_ids,
        encounter_ids=encounter_ids,
        chunksize=effective_chunksize,
    )
    enriched = _merge_lab_value_features(
        enriched,
        config=config,
        patient_ids=patient_ids,
        encounter_ids=encounter_ids,
        chunksize=effective_chunksize,
    )
    enriched = _merge_current_diagnosis_features(
        enriched,
        config=config,
        patient_ids=patient_ids,
        encounter_ids=encounter_ids,
        chunksize=effective_chunksize,
    )
    enriched = _merge_encounter_first_last_features(
        enriched,
        config=config,
        groups=PROCEDURE_CODE_GROUPS,
        source_columns=PROCEDURE_COLUMNS,
        patient_ids=patient_ids,
        encounter_ids=encounter_ids,
        chunksize=effective_chunksize,
    )
    enriched = _merge_prior_diagnosis_features(
        enriched,
        config=config,
        patient_ids=patient_ids,
        encounter_ids=encounter_ids,
        chunksize=effective_chunksize,
    )
    enriched = _merge_medication_features(
        enriched,
        config=config,
        patient_ids=patient_ids,
        encounter_ids=encounter_ids,
        chunksize=effective_chunksize,
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


def _merge_vital_value_features(
    df: pd.DataFrame,
    *,
    config: Config,
    patient_ids: set[str],
    encounter_ids: set[str],
    chunksize: int,
) -> pd.DataFrame:
    enriched = df
    for rule in VITAL_SIGN_RULES:
        value_name = rule.name.removeprefix("value_")
        date_column = f"date_{value_name}"
        value_column = rule.name
        if (
            date_column not in FINAL_OUTPUT_COLUMNS
            or value_column not in FINAL_OUTPUT_COLUMNS
        ):
            continue
        rows = _load_filtered_work_rows(
            config,
            f"{rule.name}.csv",
            columns=VITALS_COLUMNS,
            dtype={"patient_id": "string", "encounter_id": "string", "code": "string"},
            patient_ids=patient_ids,
            encounter_ids=encounter_ids,
            encounter_filter="include",
            chunksize=chunksize,
        )
        if not rows.empty:
            rows["value"] = _legacy_csv_visible_numeric_series(rows["value"])
        selected = _select_first_encounter_patient_value(
            rows,
            value_column="value",
            date_column=date_column,
            output_value_column=value_column,
        )
        enriched = _left_merge_new_columns(enriched, selected, on="encounter_id")
    return enriched


def _merge_previous_vital_features(
    df: pd.DataFrame,
    *,
    config: Config,
    patient_ids: set[str],
    encounter_ids: set[str],
    chunksize: int,
) -> pd.DataFrame:
    enriched = df
    for name in ("Weight", "Height", "BMI"):
        selected = _load_previous_vital_candidates(
            config,
            name,
            final_rows=enriched.loc[:, ["patient_id", "encounter_id", "qualify_date"]],
            chunksize=chunksize,
        )
        if selected.empty:
            continue
        enriched = enriched.merge(selected, on="patient_id", how="left")
        date_column = f"date_Prev_{name}"
        value_column = f"value_Prev_{name}"
        valid = pd.to_datetime(enriched[date_column], errors="coerce") < pd.to_datetime(
            enriched["qualify_date"],
            errors="coerce",
        )
        enriched.loc[~valid, [date_column]] = pd.NA
        enriched.loc[~valid, value_column] = 0
    return enriched


def _load_previous_vital_candidates(
    config: Config,
    name: str,
    *,
    final_rows: pd.DataFrame,
    chunksize: int,
) -> pd.DataFrame:
    path = resolve_work_table(config, f"value_{name}.csv")
    output_columns = ["patient_id", f"value_Prev_{name}", f"date_Prev_{name}"]
    if not path.exists():
        return pd.DataFrame(columns=output_columns)

    cohort = final_rows.loc[:, ["patient_id", "encounter_id", "qualify_date"]].copy()
    cohort["patient_id"] = cohort["patient_id"].astype("string")
    cohort["encounter_id"] = cohort["encounter_id"].astype("string")
    cohort["qualify_date"] = pd.to_datetime(cohort["qualify_date"], errors="coerce")
    cohort = cohort.dropna(subset=["patient_id", "qualify_date"])
    if cohort.empty:
        return pd.DataFrame(columns=output_columns)

    patient_ids = _string_id_set(cohort["patient_id"])
    encounter_ids = _string_id_set(cohort["encounter_id"])
    qualify_dates_by_patient = (
        cohort.drop_duplicates(subset=["patient_id"], keep="first")
        .set_index("patient_id")["qualify_date"]
        .to_dict()
    )

    with _FinalPreviousVitalCandidateStore(config.work_dir) as store:
        for chunk in iter_work_tables(
            [path],
            chunksize=chunksize,
            usecols=VITALS_COLUMNS,
            dtype={"patient_id": "string", "encounter_id": "string", "code": "string"},
        ):
            require_columns(chunk, VITALS_COLUMNS, context=str(path))
            filtered = _filter_ids(
                chunk,
                patient_ids=patient_ids,
                encounter_ids=encounter_ids,
                encounter_filter="exclude",
            )
            if filtered.empty:
                continue
            filtered["date"] = pd.to_datetime(filtered["date"], errors="coerce")
            filtered["value"] = _legacy_csv_visible_numeric_series(filtered["value"])
            filtered["_qualify_date"] = filtered["patient_id"].astype("string").map(
                qualify_dates_by_patient
            )
            filtered = filtered.loc[
                filtered["date"] < filtered["_qualify_date"]
            ].copy()
            if filtered.empty:
                continue
            store.add_frame(name, filtered.loc[:, VITALS_COLUMNS])

        selected = store.reduce().get(name)
    if selected is None:
        return pd.DataFrame(columns=output_columns)
    return selected


def _merge_lab_value_features(
    df: pd.DataFrame,
    *,
    config: Config,
    patient_ids: set[str],
    encounter_ids: set[str],
    chunksize: int,
) -> pd.DataFrame:
    lab_rows_by_name = _load_lab_rows_by_rule(
        config,
        patient_ids=patient_ids,
        encounter_ids=encounter_ids,
        chunksize=chunksize,
    )
    enriched = df
    for rule in LAB_VALUE_RULES:
        feature_rows = lab_rows_by_name.get(rule.name, {})
        rows = feature_rows.get(FINAL_LAB_FEATURE_FIRST)
        if rows is None or rows.empty:
            continue
        value_name = rule.name.removeprefix("value_")
        first = _select_first_encounter_patient_value(
            rows,
            value_column="lab_result_num_val",
            date_column=f"date_{value_name}",
            output_value_column=rule.name,
        )
        enriched = _left_merge_new_columns(enriched, first, on="encounter_id")
        if rule.include_highest:
            rows = feature_rows.get(FINAL_LAB_FEATURE_HIGHEST)
            if rows is None or rows.empty:
                continue
            highest = _select_highest_encounter_patient_value(
                rows,
                value_column="lab_result_num_val",
                date_column=f"date_highest_{value_name}",
                output_value_column=f"value_highest_{value_name}",
            )
            enriched = _left_merge_new_columns(enriched, highest, on="encounter_id")
    return enriched


def _load_lab_rows_by_rule(
    config: Config,
    *,
    patient_ids: set[str],
    encounter_ids: set[str],
    chunksize: int,
) -> dict[str, dict[str, pd.DataFrame]]:
    paths = find_work_tables(config, "lab_results_NEW_*.csv")
    if not paths:
        return {}
    compiled_rules = [
        (rule, re.compile(rule.regex))
        for rule in LAB_VALUE_RULES
        if _lab_rule_outputs_requested(rule)
    ]
    with _FinalLabCandidateStore(config.work_dir) as store:
        for chunk in iter_work_tables(
            paths,
            chunksize=chunksize,
            usecols=LAB_COLUMNS,
            dtype={"patient_id": "string", "encounter_id": "string", "code": "string"},
        ):
            require_columns(chunk, LAB_COLUMNS, context="Lab results work table")
            filtered = _filter_ids(
                chunk,
                patient_ids=patient_ids,
                encounter_ids=encounter_ids,
                encounter_filter="include",
            )
            if filtered.empty:
                continue
            filtered["date"] = pd.to_datetime(filtered["date"], errors="coerce")
            values = pd.to_numeric(filtered["lab_result_num_val"], errors="coerce")
            codes = filtered["code"].astype("string")
            for rule, pattern in compiled_rules:
                converted_values = _legacy_lab_feature_values(rule, codes, values)
                visible_values = _legacy_csv_visible_numeric_series(converted_values)
                mask = codes.str.match(pattern, na=False)
                mask &= visible_values < rule.max_value
                if rule.min_inclusive:
                    mask &= visible_values >= rule.min_value
                else:
                    mask &= visible_values > rule.min_value
                rows = filtered.loc[mask, LAB_COLUMNS].copy()
                if rows.empty:
                    continue
                rows["lab_result_num_val"] = _float32_series(visible_values.loc[mask])
                rows[FINAL_LAB_CODE_PRIORITY_COLUMN] = _lab_code_priority(
                    rule,
                    rows["code"],
                )
                store.add_frame(
                    rule.name,
                    FINAL_LAB_FEATURE_FIRST,
                    _reduce_first_lab_candidate_rows(rows),
                )
                if rule.include_highest:
                    store.add_frame(
                        rule.name,
                        FINAL_LAB_FEATURE_HIGHEST,
                        _reduce_highest_lab_candidate_rows(rows),
                    )
        return store.reduce()


def _lab_rule_outputs_requested(rule: _LabValueRule) -> bool:
    columns = _lab_output_value_columns()
    value_name = rule.name.removeprefix("value_")
    return rule.name in columns or f"value_highest_{value_name}" in columns


def _legacy_lab_feature_values(
    rule: _LabValueRule,
    codes: pd.Series,
    values: pd.Series,
) -> pd.Series:
    converted = _legacy_lab_dtype_series(values, dtype=rule.value_dtype)
    if not rule.value_divisors_by_code:
        return converted
    for code, divisor in rule.value_divisors_by_code.items():
        converted.loc[codes.eq(code)] = converted.loc[codes.eq(code)] / divisor
    return converted


def _legacy_lab_dtype_series(series: pd.Series, *, dtype: str) -> pd.Series:
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


def _lab_code_priority(rule: _LabValueRule, codes: pd.Series) -> pd.Series:
    if not rule.code_priority_by_code:
        return pd.Series(0, index=codes.index, dtype="int16")
    return (
        codes.astype("string")
        .map(rule.code_priority_by_code)
        .fillna(len(rule.code_priority_by_code))
        .astype("int16")
    )


def _float32_series(series: pd.Series) -> pd.Series:
    return pd.Series(
        np.asarray(series, dtype=np.float32),
        index=series.index,
        dtype="float32",
    )


def _legacy_csv_visible_numeric_series(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series.astype("string"), errors="coerce")


def _reduce_first_lab_candidate_rows(rows: pd.DataFrame) -> pd.DataFrame:
    if rows.empty:
        return pd.DataFrame(columns=LAB_COLUMNS)
    selected = rows.loc[:, LAB_COLUMNS].copy()
    if FINAL_LAB_CODE_PRIORITY_COLUMN in rows.columns:
        selected[FINAL_LAB_CODE_PRIORITY_COLUMN] = rows[
            FINAL_LAB_CODE_PRIORITY_COLUMN
        ].to_numpy()
    selected["date"] = pd.to_datetime(selected["date"], errors="coerce")
    selected = selected.loc[selected["date"] >= QUALIFY_DATE_MIN].copy()
    if selected.empty:
        return pd.DataFrame(columns=LAB_COLUMNS)
    selected = _sort_first_date(selected)
    selected = selected.drop_duplicates(subset=["encounter_id"], keep="first")
    selected = _sort_first_date(selected, id_column="patient_id")
    selected = selected.drop_duplicates(subset=["patient_id"], keep="first")
    columns = [*LAB_COLUMNS]
    if FINAL_LAB_CODE_PRIORITY_COLUMN in selected.columns:
        columns.append(FINAL_LAB_CODE_PRIORITY_COLUMN)
    return selected.loc[:, columns]


def _reduce_highest_lab_candidate_rows(rows: pd.DataFrame) -> pd.DataFrame:
    if rows.empty:
        return pd.DataFrame(columns=LAB_COLUMNS)
    selected = rows.loc[:, LAB_COLUMNS].copy()
    selected["date"] = pd.to_datetime(selected["date"], errors="coerce")
    selected["lab_result_num_val"] = pd.to_numeric(
        selected["lab_result_num_val"], errors="coerce"
    )
    selected = selected.loc[selected["date"] >= QUALIFY_DATE_MIN].copy()
    if selected.empty:
        return pd.DataFrame(columns=LAB_COLUMNS)
    selected = selected.sort_values(
        by=["lab_result_num_val", "encounter_id"],
        ascending=[False, False],
        kind="mergesort",
    )
    selected = selected.drop_duplicates(subset=["encounter_id"], keep="first")
    selected = selected.sort_values(
        by=["lab_result_num_val", "patient_id"],
        ascending=[False, False],
        kind="mergesort",
    )
    selected = selected.drop_duplicates(subset=["patient_id"], keep="first")
    return selected.loc[:, LAB_COLUMNS]


def _lab_output_value_columns() -> set[str]:
    return {
        column
        for column in FINAL_OUTPUT_COLUMNS
        if column.startswith("value_") or column.startswith("value_highest_")
    }


def _merge_current_diagnosis_features(
    df: pd.DataFrame,
    *,
    config: Config,
    patient_ids: set[str],
    encounter_ids: set[str],
    chunksize: int,
) -> pd.DataFrame:
    enriched = df
    for group in CURRENT_DIAGNOSIS_CODE_GROUPS:
        if group.name not in FINAL_OUTPUT_COLUMNS:
            continue
        rows = _load_filtered_work_rows(
            config,
            f"{group.name}.csv",
            columns=DIAGNOSIS_COLUMNS,
            dtype={
                "patient_id": "string",
                "encounter_id": "string",
                "code": "string",
                **{column: "string" for column in INDICATOR_COLUMNS},
            },
            patient_ids=patient_ids,
            encounter_ids=encounter_ids,
            encounter_filter="include",
            chunksize=chunksize,
        )
        if rows.empty:
            continue
        rows["date"] = pd.to_datetime(rows["date"], errors="coerce")
        rows = rows.loc[rows["date"] >= QUALIFY_DATE_MIN].copy()
        if rows.empty:
            continue
        selected = rows.drop_duplicates(
            subset=["encounter_id", "patient_id"],
            keep="first",
        ).copy()
        suffix = group.name.removeprefix("HAS_")
        if group.name in {
            "HAS_J9612",
            "HAS_J9622",
            "HAS_J9602",
            "HAS_J9692",
            "HAS_E662",
        }:
            selected = selected.rename(
                columns={
                    "principal_diagnosis_indicator": f"pcpl_dx_ind_{suffix}",
                    "admitting_diagnosis": f"adm_dx_{suffix}",
                    "reason_for_visit": f"visit_reason_{suffix}",
                    "date": f"date_{suffix}",
                }
            )
            selected[group.name] = 1
            keep_columns = [
                "encounter_id",
                group.name,
                f"pcpl_dx_ind_{suffix}",
                f"adm_dx_{suffix}",
                f"visit_reason_{suffix}",
                f"date_{suffix}",
            ]
            for column in keep_columns[2:5]:
                selected[column] = (
                    selected[column].replace({"Unknown": "U"}).fillna("U")
                )
        elif group.name == "HAS_J9600":
            selected = selected.rename(columns={"date": "date_J9600"})
            selected[group.name] = 1
            keep_columns = [
                "encounter_id",
                group.name,
                "principal_diagnosis_indicator",
                "admitting_diagnosis",
                "reason_for_visit",
                "date_J9600",
            ]
            for column in INDICATOR_COLUMNS:
                selected[column] = selected[column].replace({"Unknown": "U"})
        else:
            selected = selected.rename(columns={"date": f"date_{suffix}"})
            selected[group.name] = 1
            keep_columns = ["encounter_id", group.name, f"date_{suffix}"]
        selected = selected.loc[:, keep_columns]
        enriched = _left_merge_new_columns(enriched, selected, on="encounter_id")
    return enriched


def _merge_encounter_first_last_features(
    df: pd.DataFrame,
    *,
    config: Config,
    groups: list,
    source_columns: list[str],
    patient_ids: set[str],
    encounter_ids: set[str],
    chunksize: int,
) -> pd.DataFrame:
    enriched = df
    for group in groups:
        if group.name not in FINAL_OUTPUT_COLUMNS:
            continue
        rows = _load_filtered_work_rows(
            config,
            f"{group.name}.csv",
            columns=source_columns,
            dtype={"patient_id": "string", "encounter_id": "string", "code": "string"},
            patient_ids=patient_ids,
            encounter_ids=encounter_ids,
            encounter_filter="include",
            chunksize=chunksize,
        )
        if rows.empty:
            continue
        rows["date"] = pd.to_datetime(rows["date"], errors="coerce")
        rows = rows.loc[rows["date"] >= QUALIFY_DATE_MIN].copy()
        if rows.empty:
            continue
        suffix = group.name.removeprefix("HAS_")
        first = _select_first_encounter_patient_date(
            rows,
            date_column=f"first_date_{suffix}",
        )
        last = _select_last_encounter_patient_date(
            rows,
            date_column=f"last_date_{suffix}",
        )
        feature = first.merge(last, on="encounter_id", how="outer")
        feature[group.name] = 1
        feature = feature.loc[
            :,
            [
                "encounter_id",
                group.name,
                f"first_date_{suffix}",
                f"last_date_{suffix}",
            ],
        ]
        enriched = _left_merge_new_columns(enriched, feature, on="encounter_id")
    return enriched


def _merge_prior_diagnosis_features(
    df: pd.DataFrame,
    *,
    config: Config,
    patient_ids: set[str],
    encounter_ids: set[str],
    chunksize: int,
) -> pd.DataFrame:
    enriched = df
    for group in PRIOR_DIAGNOSIS_CODE_GROUPS:
        suffix = group.name.removeprefix("HAS_")
        if f"first_date_{suffix}" not in FINAL_OUTPUT_COLUMNS:
            continue
        rows = _load_filtered_work_rows(
            config,
            f"{group.name}.csv",
            columns=DIAGNOSIS_COLUMNS,
            dtype={
                "patient_id": "string",
                "encounter_id": "string",
                "code": "string",
                **{column: "string" for column in INDICATOR_COLUMNS},
            },
            patient_ids=patient_ids,
            encounter_ids=encounter_ids,
            encounter_filter="exclude",
            chunksize=chunksize,
        )
        if rows.empty:
            continue
        rows["date"] = pd.to_datetime(rows["date"], errors="coerce")
        rows = _filter_patient_rows_on_or_before_qualify(
            rows,
            final_rows=enriched.loc[:, ["patient_id", "qualify_date"]],
            date_column="date",
        )
        if rows.empty:
            continue
        first = _select_first_patient_date(rows, date_column="date")
        last = _select_last_patient_date(rows, date_column="date")
        feature = enriched.loc[:, ["patient_id", "qualify_date"]].merge(
            first.rename(columns={"date": f"first_date_{suffix}"}),
            on="patient_id",
            how="left",
        )
        feature = feature.merge(
            last.rename(columns={"date": f"last_date_{suffix}"}),
            on="patient_id",
            how="left",
        )
        qualify_dates = pd.to_datetime(feature["qualify_date"], errors="coerce")
        first_valid = (
            pd.to_datetime(feature[f"first_date_{suffix}"], errors="coerce")
            <= qualify_dates
        )
        last_valid = (
            pd.to_datetime(feature[f"last_date_{suffix}"], errors="coerce")
            <= qualify_dates
        )
        feature[group.name] = first_valid.astype("int32")
        feature.loc[~first_valid, f"first_date_{suffix}"] = pd.NA
        feature.loc[~last_valid, f"last_date_{suffix}"] = pd.NA
        feature = feature.drop(columns=["qualify_date"])
        enriched = _left_merge_new_columns(enriched, feature, on="patient_id")
    return enriched


def _merge_medication_features(
    df: pd.DataFrame,
    *,
    config: Config,
    patient_ids: set[str],
    encounter_ids: set[str],
    chunksize: int,
) -> pd.DataFrame:
    enriched = df
    for group in MEDICATION_CODE_GROUPS:
        rows = _load_filtered_work_rows(
            config,
            f"{group.name}.csv",
            columns=MEDICATION_COLUMNS,
            dtype={"patient_id": "string", "encounter_id": "string", "code": "string"},
            patient_ids=patient_ids,
            encounter_ids=encounter_ids,
            encounter_filter="include" if group.name.startswith("IPmed") else "exclude",
            chunksize=chunksize,
        )
        if rows.empty:
            continue
        rows["start_date"] = pd.to_datetime(rows["start_date"], errors="coerce")
        if group.name.startswith("IPmed"):
            med_index = group.name.removeprefix("IPmed_list")
            selected = _select_ip_medication(rows, med_index=med_index)
            enriched = _left_merge_new_columns(enriched, selected, on="encounter_id")
        else:
            med_index = group.name.removeprefix("OPmed_list")
            rows = _filter_patient_rows_on_or_before_qualify(
                rows,
                final_rows=enriched.loc[:, ["patient_id", "qualify_date"]],
                date_column="start_date",
            )
            selected = _select_op_medication(rows, med_index=med_index)
            if selected.empty:
                continue
            feature = enriched.loc[:, ["patient_id", "qualify_date"]].merge(
                selected,
                on="patient_id",
                how="left",
            )
            first_column = f"first_date_OP_Med_{med_index}"
            last_column = f"last_date_OP_Med_{med_index}"
            qualify_dates = pd.to_datetime(feature["qualify_date"], errors="coerce")
            first_valid = pd.to_datetime(
                feature[first_column],
                errors="coerce",
            ) <= qualify_dates
            last_valid = pd.to_datetime(
                feature[last_column],
                errors="coerce",
            ) <= qualify_dates
            feature[f"OP_Med_{med_index}"] = first_valid.astype("int32")
            feature.loc[~first_valid, first_column] = pd.NA
            feature.loc[~last_valid, last_column] = pd.NA
            feature = feature.drop(columns=["qualify_date"])
            enriched = _left_merge_new_columns(enriched, feature, on="patient_id")
    return enriched


def _load_filtered_work_rows(
    config: Config,
    logical_name: str,
    *,
    columns: list[str],
    dtype: dict[str, str],
    patient_ids: set[str],
    encounter_ids: set[str],
    encounter_filter: str,
    chunksize: int,
) -> pd.DataFrame:
    path = resolve_work_table(config, logical_name)
    if not path.exists():
        return pd.DataFrame(columns=columns)
    frames: list[pd.DataFrame] = []
    for chunk in iter_work_tables(
        [path],
        chunksize=chunksize,
        usecols=columns,
        dtype=dtype,
    ):
        require_columns(chunk, columns, context=str(path))
        filtered = _filter_ids(
            chunk,
            patient_ids=patient_ids,
            encounter_ids=encounter_ids,
            encounter_filter=encounter_filter,
        )
        if not filtered.empty:
            frames.append(filtered.loc[:, columns].copy())
    if not frames:
        return pd.DataFrame(columns=columns)
    return pd.concat(frames, ignore_index=True)


def _filter_ids(
    frame: pd.DataFrame,
    *,
    patient_ids: set[str],
    encounter_ids: set[str],
    encounter_filter: str,
) -> pd.DataFrame:
    mask = frame["patient_id"].astype("string").isin(patient_ids)
    if encounter_filter == "include":
        mask &= frame["encounter_id"].astype("string").isin(encounter_ids)
    elif encounter_filter == "exclude":
        mask &= ~frame["encounter_id"].astype("string").isin(encounter_ids)
    else:
        raise ValueError(f"Unknown encounter filter: {encounter_filter}")
    return frame.loc[mask].copy()


def _filter_patient_rows_on_or_before_qualify(
    rows: pd.DataFrame,
    *,
    final_rows: pd.DataFrame,
    date_column: str,
) -> pd.DataFrame:
    if rows.empty:
        return rows.copy()
    cohort = final_rows.loc[:, ["patient_id", "qualify_date"]].copy()
    cohort["patient_id"] = cohort["patient_id"].astype("string")
    cohort["qualify_date"] = pd.to_datetime(cohort["qualify_date"], errors="coerce")
    cohort = cohort.dropna(subset=["patient_id", "qualify_date"])
    if cohort.empty:
        return rows.iloc[0:0].copy()
    qualify_dates_by_patient = (
        cohort.drop_duplicates(subset=["patient_id"], keep="first")
        .set_index("patient_id")["qualify_date"]
        .to_dict()
    )
    filtered = rows.copy()
    filtered[date_column] = pd.to_datetime(filtered[date_column], errors="coerce")
    filtered["_qualify_date"] = filtered["patient_id"].astype("string").map(
        qualify_dates_by_patient,
    )
    filtered = filtered.loc[filtered[date_column] <= filtered["_qualify_date"]].copy()
    return filtered.drop(columns=["_qualify_date"])


def _select_first_encounter_patient_value(
    rows: pd.DataFrame,
    *,
    value_column: str,
    date_column: str,
    output_value_column: str,
) -> pd.DataFrame:
    if rows.empty:
        return pd.DataFrame(columns=["encounter_id", date_column, output_value_column])
    selected = rows.copy()
    selected["date"] = pd.to_datetime(selected["date"], errors="coerce")
    selected = selected.loc[selected["date"] >= QUALIFY_DATE_MIN].copy()
    if selected.empty:
        return pd.DataFrame(columns=["encounter_id", date_column, output_value_column])
    selected = _sort_first_date(selected)
    selected = selected.drop_duplicates(subset=["encounter_id"], keep="first")
    selected = _sort_first_date(selected, id_column="patient_id")
    selected = selected.drop_duplicates(subset=["patient_id"], keep="first")
    selected = selected.rename(
        columns={"date": date_column, value_column: output_value_column}
    )
    return selected.loc[:, ["encounter_id", date_column, output_value_column]]


def _select_highest_encounter_patient_value(
    rows: pd.DataFrame,
    *,
    value_column: str,
    date_column: str,
    output_value_column: str,
) -> pd.DataFrame:
    if rows.empty:
        return pd.DataFrame(columns=["encounter_id", date_column, output_value_column])
    selected = rows.copy()
    selected["date"] = pd.to_datetime(selected["date"], errors="coerce")
    selected[value_column] = pd.to_numeric(selected[value_column], errors="coerce")
    selected = selected.loc[selected["date"] >= QUALIFY_DATE_MIN].copy()
    if selected.empty:
        return pd.DataFrame(columns=["encounter_id", date_column, output_value_column])
    selected = selected.sort_values(
        by=[value_column, "encounter_id"],
        ascending=[False, False],
        kind="mergesort",
    )
    selected = selected.drop_duplicates(subset=["encounter_id"], keep="first")
    selected = selected.sort_values(
        by=[value_column, "patient_id"],
        ascending=[False, False],
        kind="mergesort",
    )
    selected = selected.drop_duplicates(subset=["patient_id"], keep="first")
    selected = selected.rename(
        columns={"date": date_column, value_column: output_value_column}
    )
    return selected.loc[:, ["encounter_id", date_column, output_value_column]]


def _select_previous_patient_value(
    rows: pd.DataFrame,
    *,
    value_column: str,
    output_value_column: str,
    output_date_column: str,
) -> pd.DataFrame:
    selected = rows.copy()
    selected["date"] = pd.to_datetime(selected["date"], errors="coerce")
    selected = _sort_first_date(selected)
    selected = selected.drop_duplicates(subset=["encounter_id"], keep="last")
    selected = _sort_first_date(selected, id_column="patient_id")
    selected = selected.drop_duplicates(subset=["patient_id"], keep="last")
    selected = selected.rename(
        columns={"date": output_date_column, value_column: output_value_column}
    )
    return selected.loc[:, ["patient_id", output_value_column, output_date_column]]


def _select_first_encounter_patient_date(
    rows: pd.DataFrame,
    *,
    date_column: str,
) -> pd.DataFrame:
    selected = _sort_first_date(rows.copy())
    selected = selected.drop_duplicates(subset=["encounter_id"], keep="first")
    selected = _sort_first_date(selected, id_column="patient_id")
    selected = selected.drop_duplicates(subset=["patient_id"], keep="first")
    selected = selected.rename(columns={"date": date_column})
    return selected.loc[:, ["encounter_id", date_column]]


def _select_last_encounter_patient_date(
    rows: pd.DataFrame,
    *,
    date_column: str,
) -> pd.DataFrame:
    selected = _sort_first_date(rows.copy())
    selected = selected.drop_duplicates(subset=["encounter_id"], keep="last")
    selected = _sort_first_date(selected, id_column="patient_id")
    selected = selected.drop_duplicates(subset=["patient_id"], keep="last")
    selected = selected.rename(columns={"date": date_column})
    return selected.loc[:, ["encounter_id", date_column]]


def _select_first_patient_date(rows: pd.DataFrame, *, date_column: str) -> pd.DataFrame:
    selected = _sort_first_date(rows.copy())
    selected = selected.drop_duplicates(subset=["encounter_id"], keep="first")
    selected = _sort_first_date(selected, id_column="patient_id")
    selected = selected.drop_duplicates(subset=["patient_id"], keep="first")
    return selected.loc[:, ["patient_id", date_column]]


def _select_last_patient_date(rows: pd.DataFrame, *, date_column: str) -> pd.DataFrame:
    selected = _sort_first_date(rows.copy())
    selected = selected.drop_duplicates(subset=["encounter_id"], keep="last")
    selected = _sort_first_date(selected, id_column="patient_id")
    selected = selected.drop_duplicates(subset=["patient_id"], keep="last")
    return selected.loc[:, ["patient_id", date_column]]


def _select_ip_medication(rows: pd.DataFrame, *, med_index: str) -> pd.DataFrame:
    selected = rows.loc[rows["start_date"] >= QUALIFY_DATE_MIN].copy()
    if selected.empty:
        return pd.DataFrame(
            columns=[
                "encounter_id",
                f"IP_Med_{med_index}",
                f"date_IP_Med_{med_index}",
            ]
        )
    selected = selected.drop_duplicates(subset=["encounter_id"], keep="first")
    selected = selected.drop_duplicates(subset=["patient_id"], keep="first")
    selected = selected.rename(columns={"start_date": f"date_IP_Med_{med_index}"})
    selected[f"IP_Med_{med_index}"] = 1
    return selected.loc[
        :,
        ["encounter_id", f"IP_Med_{med_index}", f"date_IP_Med_{med_index}"],
    ]


def _select_op_medication(rows: pd.DataFrame, *, med_index: str) -> pd.DataFrame:
    if rows.empty:
        return pd.DataFrame(
            columns=[
                "patient_id",
                f"first_date_OP_Med_{med_index}",
                f"last_date_OP_Med_{med_index}",
            ]
        )
    first = rows.sort_values(
        by=["start_date", "encounter_id"],
        ascending=[True, False],
        kind="mergesort",
    )
    first = first.drop_duplicates(subset=["encounter_id"], keep="first")
    first = first.sort_values(
        by=["start_date", "patient_id"],
        ascending=[True, False],
        kind="mergesort",
    )
    first = first.drop_duplicates(subset=["patient_id"], keep="first")
    first = first.rename(columns={"start_date": f"first_date_OP_Med_{med_index}"})

    last = rows.sort_values(
        by=["start_date", "encounter_id"],
        ascending=[True, False],
        kind="mergesort",
    )
    last = last.drop_duplicates(subset=["encounter_id"], keep="last")
    last = last.sort_values(
        by=["start_date", "patient_id"],
        ascending=[True, False],
        kind="mergesort",
    )
    last = last.drop_duplicates(subset=["patient_id"], keep="last")
    last = last.rename(columns={"start_date": f"last_date_OP_Med_{med_index}"})

    return first.loc[:, ["patient_id", f"first_date_OP_Med_{med_index}"]].merge(
        last.loc[:, ["patient_id", f"last_date_OP_Med_{med_index}"]],
        on="patient_id",
        how="outer",
    )


def _sort_first_date(
    rows: pd.DataFrame,
    *,
    id_column: str = "encounter_id",
) -> pd.DataFrame:
    by = ["date", id_column]
    ascending = [True, False]
    if FINAL_LAB_CODE_PRIORITY_COLUMN in rows.columns:
        by.append(FINAL_LAB_CODE_PRIORITY_COLUMN)
        ascending.append(True)
    return rows.sort_values(
        by=by,
        ascending=ascending,
        kind="mergesort",
    )


def _left_merge_new_columns(
    df: pd.DataFrame,
    feature: pd.DataFrame,
    *,
    on: str,
) -> pd.DataFrame:
    if feature.empty:
        return df
    new_columns = [column for column in feature.columns if column != on]
    existing = [column for column in new_columns if column in df.columns]
    if existing:
        df = df.drop(columns=existing)
    return df.merge(feature, on=on, how="left", validate="one_to_one")


def _string_id_set(series: pd.Series) -> set[str]:
    return set(series.dropna().astype("string"))


def _load_demographics(
    paths: list[Path],
    logger: logging.Logger,
    *,
    chunksize: int | None = None,
) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    seen_patient_ids: set[tuple[str, str]] = set()

    for path in paths:
        for raw_frame in _iter_demographic_frames(path, chunksize=chunksize):
            transformed = _transform_demographics(raw_frame, context=str(path))
            _check_unique_patient_ids(transformed["patient_id"], seen_patient_ids)
            frames.append(transformed)

    if not frames:
        return pd.DataFrame(columns=DEMOGRAPHIC_OUTPUT_COLUMNS)
    combined = pd.concat(frames, ignore_index=True) if len(frames) > 1 else frames[0]

    log_row_count(logger, "demographics read", len(combined))
    return combined.loc[:, DEMOGRAPHIC_OUTPUT_COLUMNS]


def _load_demographics_lookup(
    paths: list[Path],
    *,
    work_dir: Path,
    stack: ExitStack,
    logger: logging.Logger,
    chunksize: int | None = None,
) -> "_DemographicsLookup":
    lookup = stack.enter_context(_DemographicsLookup(work_dir))
    rows_read = 0

    for path in paths:
        for raw_frame in _iter_demographic_frames(path, chunksize=chunksize):
            transformed = _transform_demographics(raw_frame, context=str(path))
            lookup.add_frame(transformed)
            rows_read += len(transformed)

    log_row_count(logger, "demographics read", rows_read)
    return lookup


def _demographics_frame_for_merge(
    demographics: pd.DataFrame | "_DemographicsLookup",
    patient_ids: pd.Series,
) -> pd.DataFrame:
    if isinstance(demographics, _DemographicsLookup):
        return demographics.frame_for_patient_ids(patient_ids)
    return demographics


def _iter_demographic_frames(
    path: Path,
    *,
    chunksize: int | None,
):
    reader = pd.read_csv(
        path,
        usecols=DEMOGRAPHIC_COLUMNS,
        dtype={
            "patient_id": "string",
            "sex": "string",
            "race": "string",
            "ethnicity": "string",
            "patient_regional_location": "string",
        },
        chunksize=chunksize,
    )
    if chunksize is None:
        yield reader
    else:
        yield from reader


def _transform_demographics(raw_frame: pd.DataFrame, *, context: str) -> pd.DataFrame:
    require_columns(raw_frame, DEMOGRAPHIC_COLUMNS, context=context)

    frame = raw_frame.loc[:, DEMOGRAPHIC_COLUMNS].copy()
    frame["patient_id"] = frame["patient_id"].astype("string")
    frame["sex"] = frame["sex"].astype("string")
    frame["race"] = frame["race"].astype("string")
    frame["ethnicity"] = frame["ethnicity"].astype("string")
    frame["patient_regional_location"] = frame["patient_regional_location"].astype(
        "string"
    )

    frame["year_of_birth"] = (
        pd.to_numeric(frame["year_of_birth"], errors="coerce").fillna(0).astype("int32")
    )
    frame = frame.rename(columns={"year_of_birth": "birth_year"})
    frame["death_year_month"] = _format_death_year_month(frame["month_year_death"])
    frame = frame.drop(columns=["month_year_death"])

    return frame.loc[:, DEMOGRAPHIC_OUTPUT_COLUMNS]


def _check_unique_patient_ids(
    patient_ids: pd.Series,
    seen_patient_ids: set[tuple[str, str]],
) -> None:
    current: set[tuple[str, str]] = set()
    for value in patient_ids.astype("object"):
        key = _patient_id_key(value)
        if key in current or key in seen_patient_ids:
            raise ValueError(
                "Patient demographics contain duplicate patient_id values."
            )
        current.add(key)
    seen_patient_ids.update(current)


def _patient_id_key(value: object) -> tuple[str, str]:
    if pd.isna(value):
        return ("missing", "")
    return ("value", str(value))


def _patient_id_lookup_key(value: object) -> str:
    if pd.isna(value):
        return "missing:"
    return f"value:{value}"


def _encounter_id_key(value: object) -> str:
    if pd.isna(value):
        return "missing:"
    return f"value:{value}"


def _sqlite_value(value: object) -> object:
    if pd.isna(value):
        return None
    return value


def _sqlite_text_value(value: object) -> str | None:
    if pd.isna(value):
        return None
    return str(value)


def _sqlite_int_value(value: object) -> int | None:
    if pd.isna(value):
        return None
    return int(value)


def _format_death_year_month(series: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(series, errors="coerce").fillna(0).astype("int64")
    strings = numeric.astype(str)
    formatted = strings.where(numeric != 0, "")
    formatted = formatted.where(
        formatted == "",
        formatted.str.slice(0, 4) + "-" + formatted.str.slice(4, 6),
    )
    return formatted.astype("string")


def _empty_demographics_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "patient_id": pd.Series(dtype="string"),
            "sex": pd.Series(dtype="string"),
            "race": pd.Series(dtype="string"),
            "ethnicity": pd.Series(dtype="string"),
            "patient_regional_location": pd.Series(dtype="string"),
            "birth_year": pd.Series(dtype="int32"),
            "death_year_month": pd.Series(dtype="string"),
        },
        columns=DEMOGRAPHIC_OUTPUT_COLUMNS,
    )


class _DemographicsLookup:
    """Disk-backed patient demographics lookup for final assembly joins."""

    def __init__(self, work_dir: Path) -> None:
        self.work_dir = work_dir
        self.path: Path | None = None
        self.connection: sqlite3.Connection | None = None

    def __enter__(self) -> "_DemographicsLookup":
        self.work_dir.mkdir(parents=True, exist_ok=True)
        handle = tempfile.NamedTemporaryFile(
            prefix=".trinetx-demographics-",
            suffix=".sqlite",
            dir=self.work_dir,
            delete=False,
        )
        handle.close()
        self.path = Path(handle.name)
        self.connection = sqlite3.connect(self.path)
        self.connection.execute("PRAGMA journal_mode=OFF")
        self.connection.execute("PRAGMA synchronous=OFF")
        self.connection.execute("PRAGMA temp_store=FILE")
        self.connection.execute(
            """
            CREATE TABLE demographics (
                patient_id_key TEXT PRIMARY KEY,
                patient_id TEXT,
                sex TEXT,
                race TEXT,
                ethnicity TEXT,
                patient_regional_location TEXT,
                birth_year INTEGER NOT NULL,
                death_year_month TEXT
            ) WITHOUT ROWID
            """
        )
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self.connection is not None:
            self.connection.close()
            self.connection = None
        self._unlink_scratch_files()

    def add_frame(self, frame: pd.DataFrame) -> None:
        if frame.empty:
            return
        require_columns(frame, DEMOGRAPHIC_OUTPUT_COLUMNS, context="Demographics")
        keys = frame["patient_id"].astype("object").map(_patient_id_lookup_key)
        if keys.duplicated().any():
            raise ValueError(
                "Patient demographics contain duplicate patient_id values."
            )
        records = [
            (
                key,
                _sqlite_value(row.patient_id),
                _sqlite_value(row.sex),
                _sqlite_value(row.race),
                _sqlite_value(row.ethnicity),
                _sqlite_value(row.patient_regional_location),
                int(row.birth_year),
                _sqlite_value(row.death_year_month),
            )
            for key, row in zip(
                keys,
                frame.loc[:, DEMOGRAPHIC_OUTPUT_COLUMNS].itertuples(index=False),
                strict=True,
            )
        ]
        try:
            self._connection().executemany(
                """
                INSERT INTO demographics(
                    patient_id_key,
                    patient_id,
                    sex,
                    race,
                    ethnicity,
                    patient_regional_location,
                    birth_year,
                    death_year_month
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                records,
            )
        except sqlite3.IntegrityError as exc:
            raise ValueError(
                "Patient demographics contain duplicate patient_id values."
            ) from exc

    def frame_for_patient_ids(self, patient_ids: pd.Series) -> pd.DataFrame:
        keys = patient_ids.astype("object").map(_patient_id_lookup_key)
        unique_keys = list(dict.fromkeys(keys.dropna().tolist()))
        if not unique_keys:
            return _empty_demographics_frame()

        records: list[tuple[object, ...]] = []
        for start in range(0, len(unique_keys), 500):
            batch = unique_keys[start : start + 500]
            placeholders = ",".join("?" for _ in batch)
            rows = self._connection().execute(
                f"""
                SELECT
                    patient_id,
                    sex,
                    race,
                    ethnicity,
                    patient_regional_location,
                    birth_year,
                    death_year_month
                FROM demographics
                WHERE patient_id_key IN ({placeholders})
                """,
                batch,
            )
            records.extend(tuple(row) for row in rows)

        if not records:
            return _empty_demographics_frame()
        return pd.DataFrame.from_records(records, columns=DEMOGRAPHIC_OUTPUT_COLUMNS)

    def _connection(self) -> sqlite3.Connection:
        if self.connection is None:
            raise RuntimeError("Demographics lookup is not open.")
        return self.connection

    def _unlink_scratch_files(self) -> None:
        if self.path is None:
            return
        for path in [
            self.path,
            self.path.with_name(f"{self.path.name}-journal"),
            self.path.with_name(f"{self.path.name}-wal"),
            self.path.with_name(f"{self.path.name}-shm"),
        ]:
            try:
                path.unlink()
            except FileNotFoundError:
                pass


def _load_rfs_event(
    config: Config,
    category: str,
    logger: logging.Logger,
    *,
    chunksize: int | None = None,
) -> pd.DataFrame:
    path = resolve_work_table(config, f"RFS_{category}.csv")
    if not path.exists():
        raise FileNotFoundError(f"Missing RFS events file for {category}: {path}")
    events = _load_work_table_frame(
        path,
        columns=RFS_EVENT_COLUMNS,
        dtype={"patient_id": "string", "encounter_id": "string"},
        chunksize=chunksize,
    )
    log_row_count(logger, f"rfs events read {category}", len(events))
    return events


def _load_final_event_candidates(
    config: Config,
    category: str,
    demographics: "_DemographicsLookup",
    logger: logging.Logger,
    *,
    chunksize: int | None,
    guardrails: GuardrailConfig,
    strict: bool,
) -> pd.DataFrame:
    path = resolve_work_table(config, f"RFS_{category}.csv")
    if not path.exists():
        raise FileNotFoundError(f"Missing RFS events file for {category}: {path}")

    effective_chunksize = chunksize or FINAL_EVENT_DEFAULT_CHUNK_ROWS
    rows_read = 0
    post_dates = 0
    post_location = 0

    with _FinalEventCandidateStore(config.work_dir) as store:
        for events in iter_work_tables(
            [path],
            chunksize=effective_chunksize,
            usecols=RFS_EVENT_COLUMNS,
            dtype={"patient_id": "string", "encounter_id": "string"},
        ):
            require_columns(events, RFS_EVENT_COLUMNS, context=str(path))
            rows_read += len(events)
            candidates = _prepare_final_event_candidate_chunk(
                events,
                demographics,
                rfs_category=category,
                guardrails=guardrails,
                strict=strict,
                logger=logger,
            )
            post_dates += int(candidates.attrs.get("post_dates", 0))
            post_location += len(candidates)
            store.add_frame(candidates)

        log_row_count(logger, f"rfs events read {category}", rows_read)
        log_row_count(logger, f"final {category} post-filter dates", post_dates)
        log_row_count(logger, f"final {category} post-filter location", post_location)
        candidates = store.reduce()
        log_row_count(logger, f"final {category} event candidates", len(candidates))
    return candidates


def _prepare_final_event_candidate_chunk(
    events: pd.DataFrame,
    demographics: "_DemographicsLookup",
    *,
    rfs_category: str,
    guardrails: GuardrailConfig,
    strict: bool,
    logger: logging.Logger,
) -> pd.DataFrame:
    if events.empty:
        empty = pd.DataFrame(columns=FINAL_EVENT_CANDIDATE_COLUMNS)
        empty.attrs["post_dates"] = 0
        return empty

    assembled = events.loc[:, RFS_EVENT_COLUMNS].copy()
    assembled["patient_id"] = assembled["patient_id"].astype("string")
    assembled["encounter_id"] = assembled["encounter_id"].astype("string")
    assembled = assembled.rename(columns={"date": "qualify_date"})
    assembled["qualify_date"] = pd.to_datetime(
        assembled["qualify_date"], errors="coerce"
    )
    assembled = assembled.loc[
        assembled["qualify_date"].between(QUALIFY_DATE_MIN, QUALIFY_DATE_MAX)
    ]
    assembled = assembled.dropna(subset=["patient_id", "encounter_id", "qualify_date"])
    post_dates = len(assembled)
    if strict:
        check_required_ids(
            assembled,
            ["patient_id", "encounter_id"],
            context=f"final {rfs_category} events",
        )

    demographics_frame = _demographics_frame_for_merge(
        demographics,
        assembled["patient_id"],
    )
    assembled = _merge_with_guardrails(
        assembled,
        demographics_frame,
        on="patient_id",
        validate="many_to_one",
        context=f"final {rfs_category} demographics",
        guardrails=guardrails,
        strict=strict,
        logger=logger,
    )
    assembled.insert(loc=2, column="RFS", value=rfs_category)
    assembled = assembled.loc[
        ~assembled["patient_regional_location"].isin(["Ex-US", "Unknown"])
    ]
    assembled = assembled.dropna().reset_index(drop=True)
    candidates = assembled.loc[:, FINAL_EVENT_CANDIDATE_COLUMNS].reset_index(drop=True)
    candidates.attrs["post_dates"] = post_dates
    return candidates


class _FinalEventCandidateStore:
    """Bucketed event reducer for final assembly RFS candidates."""

    def __init__(self, work_dir: Path) -> None:
        self.work_dir = work_dir
        self.encounter_path: Path | None = None
        self.patient_path: Path | None = None
        self._encounter_written_paths: set[Path] = set()
        self._patient_written_paths: set[Path] = set()
        self._next_row_order = 0

    def __enter__(self) -> "_FinalEventCandidateStore":
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self.encounter_path = Path(
            tempfile.mkdtemp(prefix=".trinetx-final-events-", dir=self.work_dir)
        )
        self.patient_path = Path(
            tempfile.mkdtemp(prefix=".trinetx-final-patients-", dir=self.work_dir)
        )
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self._remove_scratch_dirs()

    def add_frame(self, frame: pd.DataFrame) -> None:
        if frame.empty:
            return
        require_columns(
            frame,
            FINAL_EVENT_CANDIDATE_COLUMNS,
            context="Final event candidates",
        )
        bucketed = frame.loc[:, FINAL_EVENT_CANDIDATE_COLUMNS].copy()
        bucketed["_row_order"] = range(
            self._next_row_order,
            self._next_row_order + len(bucketed),
        )
        self._next_row_order += len(bucketed)
        bucketed["_bucket"] = (
            bucketed["encounter_id"]
            .astype("string")
            .map(
                lambda value: _encounter_lookup_bucket(
                    str(value), FINAL_EVENT_BUCKET_COUNT
                )
            )
        )
        for bucket, bucket_frame in bucketed.groupby("_bucket", sort=False):
            _append_scratch_csv_frame(
                self._encounter_bucket_path(int(bucket)),
                bucket_frame.loc[:, FINAL_EVENT_BUCKET_COLUMNS],
                written_paths=self._encounter_written_paths,
            )

    def reduce(self) -> pd.DataFrame:
        self._reduce_encounter_buckets_to_patient_buckets()
        frames: list[pd.DataFrame] = []
        for path in sorted(self._patient_written_paths):
            frame = _read_final_event_bucket(path)
            if frame.empty:
                continue
            unique = (
                _sort_final_event_candidates(frame)
                .drop_duplicates(subset=["patient_id"], keep="first")
                .loc[:, FINAL_EVENT_CANDIDATE_COLUMNS]
                .reset_index(drop=True)
            )
            if not unique.empty:
                frames.append(unique)
        if not frames:
            return pd.DataFrame(columns=FINAL_EVENT_CANDIDATE_COLUMNS)
        return pd.concat(frames, ignore_index=True)

    def _reduce_encounter_buckets_to_patient_buckets(self) -> None:
        for path in sorted(self._encounter_written_paths):
            frame = _read_final_event_bucket(path)
            if frame.empty:
                continue
            unique = (
                _sort_final_event_candidates(frame)
                .drop_duplicates(subset=["encounter_id"], keep="first")
                .reset_index(drop=True)
            )
            if unique.empty:
                continue
            unique["_bucket"] = (
                unique["patient_id"]
                .astype("string")
                .map(
                    lambda value: _encounter_lookup_bucket(
                        str(value),
                        FINAL_EVENT_BUCKET_COUNT,
                    )
                )
            )
            for bucket, bucket_frame in unique.groupby("_bucket", sort=False):
                _append_scratch_csv_frame(
                    self._patient_bucket_path(int(bucket)),
                    bucket_frame.loc[:, FINAL_EVENT_BUCKET_COLUMNS],
                    written_paths=self._patient_written_paths,
                )

    def _encounter_bucket_path(self, bucket: int) -> Path:
        if self.encounter_path is None:
            raise RuntimeError("Final event candidate store is not open.")
        return self.encounter_path / f"encounters_{bucket:03}.csv"

    def _patient_bucket_path(self, bucket: int) -> Path:
        if self.patient_path is None:
            raise RuntimeError("Final event candidate store is not open.")
        return self.patient_path / f"patients_{bucket:03}.csv"

    def _remove_scratch_dirs(self) -> None:
        for path in [self.encounter_path, self.patient_path]:
            if path is not None:
                remove_tree_strict(path, context="Final event candidate scratch")


class _FinalLabCandidateStore:
    """Bucketed lab-feature reducer for final assembly analytic columns."""

    def __init__(self, work_dir: Path) -> None:
        self.work_dir = work_dir
        self.path: Path | None = None
        self._written_paths: set[Path] = set()

    def __enter__(self) -> "_FinalLabCandidateStore":
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self.path = Path(
            tempfile.mkdtemp(prefix=".trinetx-final-labs-", dir=self.work_dir)
        )
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self._remove_scratch_dir()

    def add_frame(
        self,
        rule_name: str,
        feature_kind: str,
        frame: pd.DataFrame,
    ) -> None:
        if frame.empty:
            return
        require_columns(frame, LAB_COLUMNS, context="Final lab candidates")
        bucketed = frame.loc[:, LAB_COLUMNS].copy()
        if FINAL_LAB_CODE_PRIORITY_COLUMN in frame.columns:
            bucketed[FINAL_LAB_CODE_PRIORITY_COLUMN] = frame[
                FINAL_LAB_CODE_PRIORITY_COLUMN
            ].to_numpy()
        else:
            bucketed[FINAL_LAB_CODE_PRIORITY_COLUMN] = 0
        bucketed.insert(0, "feature_kind", feature_kind)
        bucketed.insert(0, "rule_name", rule_name)
        bucketed["_bucket"] = bucketed["patient_id"].astype("string").map(
            lambda value: _encounter_lookup_bucket(
                f"{rule_name}|{feature_kind}|{value}",
                FINAL_LAB_BUCKET_COUNT,
            )
        )
        for bucket, bucket_frame in bucketed.groupby("_bucket", sort=False):
            _append_scratch_csv_frame(
                self._bucket_path(int(bucket)),
                bucket_frame.loc[:, FINAL_LAB_BUCKET_COLUMNS],
                written_paths=self._written_paths,
            )

    def reduce(self) -> dict[str, dict[str, pd.DataFrame]]:
        frames_by_rule: dict[str, dict[str, list[pd.DataFrame]]] = {}
        for path in sorted(self._written_paths):
            frame = _read_final_lab_bucket(path)
            if frame.empty:
                continue
            for (rule_name, feature_kind), group in frame.groupby(
                ["rule_name", "feature_kind"],
                sort=False,
            ):
                columns = [*LAB_COLUMNS]
                if FINAL_LAB_CODE_PRIORITY_COLUMN in group.columns:
                    columns.append(FINAL_LAB_CODE_PRIORITY_COLUMN)
                candidates = group.loc[:, columns].copy()
                if feature_kind == FINAL_LAB_FEATURE_FIRST:
                    reduced = _reduce_first_lab_candidate_rows(candidates)
                elif feature_kind == FINAL_LAB_FEATURE_HIGHEST:
                    reduced = _reduce_highest_lab_candidate_rows(candidates)
                else:
                    raise ValueError(f"Unknown lab feature kind: {feature_kind}")
                if reduced.empty:
                    continue
                frames_by_rule.setdefault(str(rule_name), {}).setdefault(
                    str(feature_kind),
                    [],
                ).append(reduced)

        return {
            rule_name: {
                feature_kind: pd.concat(frames, ignore_index=True)
                for feature_kind, frames in feature_frames.items()
                if frames
            }
            for rule_name, feature_frames in frames_by_rule.items()
        }

    def _bucket_path(self, bucket: int) -> Path:
        if self.path is None:
            raise RuntimeError("Final lab candidate store is not open.")
        return self.path / f"labs_{bucket:03}.csv"

    def _remove_scratch_dir(self) -> None:
        if self.path is not None:
            remove_tree_strict(self.path, context="Final lab feature scratch")


class _FinalPreviousVitalCandidateStore:
    """Patient-bucketed reducer for previous Weight/Height/BMI candidates."""

    def __init__(self, work_dir: Path) -> None:
        self.work_dir = work_dir
        self.path: Path | None = None
        self._written_paths: set[Path] = set()

    def __enter__(self) -> "_FinalPreviousVitalCandidateStore":
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self.path = Path(
            tempfile.mkdtemp(prefix=".trinetx-final-prev-vitals-", dir=self.work_dir)
        )
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self._remove_scratch_dir()

    def add_frame(self, vital_name: str, frame: pd.DataFrame) -> None:
        if frame.empty:
            return
        require_columns(
            frame,
            VITALS_COLUMNS,
            context="Final previous vital candidates",
        )
        bucketed = frame.loc[:, VITALS_COLUMNS].copy()
        bucketed.insert(0, "vital_name", vital_name)
        bucketed["_bucket"] = bucketed["patient_id"].astype("string").map(
            lambda value: _encounter_lookup_bucket(
                f"{vital_name}|{value}",
                FINAL_PREVIOUS_VITAL_BUCKET_COUNT,
            )
        )
        for bucket, bucket_frame in bucketed.groupby("_bucket", sort=False):
            _append_scratch_csv_frame(
                self._bucket_path(int(bucket)),
                bucket_frame.loc[:, FINAL_PREVIOUS_VITAL_BUCKET_COLUMNS],
                written_paths=self._written_paths,
            )

    def reduce(self) -> dict[str, pd.DataFrame]:
        frames_by_name: dict[str, list[pd.DataFrame]] = {}
        for path in sorted(self._written_paths):
            frame = _read_final_previous_vital_bucket(path)
            if frame.empty:
                continue
            for vital_name, group in frame.groupby("vital_name", sort=False):
                name = str(vital_name)
                reduced = _select_previous_patient_value(
                    group.loc[:, VITALS_COLUMNS],
                    value_column="value",
                    output_value_column=f"value_Prev_{name}",
                    output_date_column=f"date_Prev_{name}",
                )
                if not reduced.empty:
                    frames_by_name.setdefault(name, []).append(reduced)
        return {
            name: pd.concat(frames, ignore_index=True)
            for name, frames in frames_by_name.items()
            if frames
        }

    def _bucket_path(self, bucket: int) -> Path:
        if self.path is None:
            raise RuntimeError("Final previous vital candidate store is not open.")
        return self.path / f"previous_vitals_{bucket:03}.csv"

    def _remove_scratch_dir(self) -> None:
        if self.path is not None:
            remove_tree_strict(self.path, context="Final previous vital scratch")


def _read_final_event_bucket(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(
        path,
        usecols=FINAL_EVENT_BUCKET_COLUMNS,
        dtype={
            "patient_id": "string",
            "encounter_id": "string",
            "RFS": "string",
            "sex": "string",
            "race": "string",
            "ethnicity": "string",
            "patient_regional_location": "string",
            "death_year_month": "string",
        },
    )
    frame["qualify_date"] = pd.to_datetime(frame["qualify_date"], errors="coerce")
    frame["_row_order"] = pd.to_numeric(
        frame["_row_order"],
        errors="raise",
    ).astype("int64")
    return frame


def _read_final_lab_bucket(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(
        path,
        usecols=FINAL_LAB_BUCKET_COLUMNS,
        dtype={
            "rule_name": "string",
            "feature_kind": "string",
            "patient_id": "string",
            "encounter_id": "string",
            "code": "string",
            FINAL_LAB_CODE_PRIORITY_COLUMN: "int16",
        },
    )
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    frame["lab_result_num_val"] = pd.to_numeric(
        frame["lab_result_num_val"], errors="coerce"
    ).astype("float32")
    return frame


def _read_final_previous_vital_bucket(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(
        path,
        usecols=FINAL_PREVIOUS_VITAL_BUCKET_COLUMNS,
        dtype={
            "vital_name": "string",
            "patient_id": "string",
            "encounter_id": "string",
            "code": "string",
        },
    )
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    frame["value"] = pd.to_numeric(frame["value"], errors="coerce")
    return frame



def _sort_final_event_candidates(frame: pd.DataFrame) -> pd.DataFrame:
    return frame.sort_values(
        by=["qualify_date", "encounter_id", "_row_order"],
        ascending=[True, False, True],
        kind="mergesort",
    )


def _load_encounter(
    config: Config,
    setting: str,
    logger: logging.Logger,
    *,
    chunksize: int | None = None,
) -> pd.DataFrame:
    filename = SETTING_ENCOUNTER_FILES[setting]
    path = resolve_work_table(config, filename)
    if not path.exists():
        raise FileNotFoundError(f"Missing encounter file for {setting}: {path}")
    encounters = _load_work_table_frame(
        path,
        columns=ENCOUNTER_COLUMNS,
        dtype={"encounter_id": "string"},
        chunksize=chunksize,
    )
    log_row_count(logger, f"encounters read {setting}", len(encounters))
    return encounters


def _load_encounter_lookup(
    config: Config,
    setting: str,
    logger: logging.Logger,
    *,
    stack: ExitStack,
    chunksize: int | None = None,
) -> "_EncounterLookup":
    filename = SETTING_ENCOUNTER_FILES[setting]
    path = resolve_work_table(config, filename)
    if not path.exists():
        raise FileNotFoundError(f"Missing encounter file for {setting}: {path}")
    lookup = stack.enter_context(_EncounterLookup(config.work_dir))
    rows_read = 0
    for frame in iter_work_tables(
        [path],
        chunksize=chunksize,
        usecols=ENCOUNTER_COLUMNS,
        dtype={"encounter_id": "string"},
    ):
        require_columns(frame, ENCOUNTER_COLUMNS, context=str(path))
        lookup.add_frame(frame.loc[:, ENCOUNTER_COLUMNS])
        rows_read += len(frame)
    lookup.finalize()
    log_row_count(logger, f"encounters read {setting}", rows_read)
    return lookup


def _encounters_frame_for_merge(
    encounters: pd.DataFrame | "_EncounterLookup",
    encounter_ids: pd.Series,
) -> pd.DataFrame:
    if isinstance(encounters, _EncounterLookup):
        return encounters.frame_for_encounter_ids(encounter_ids)
    return encounters


def _empty_encounter_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "encounter_id": pd.Series(dtype="string"),
            "start_date": pd.Series(dtype="object"),
            "end_date": pd.Series(dtype="object"),
            "LOS": pd.Series(dtype="int64"),
        },
        columns=ENCOUNTER_COLUMNS,
    )


class _EncounterLookup:
    """Disk-backed setting encounter lookup for final assembly joins."""

    def __init__(self, work_dir: Path) -> None:
        self.work_dir = work_dir
        self.path: Path | None = None
        self._written_paths: set[Path] = set()
        self._finalized = False

    def __enter__(self) -> "_EncounterLookup":
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self.path = Path(
            tempfile.mkdtemp(prefix=".trinetx-final-encounters-", dir=self.work_dir)
        )
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self._remove_scratch_dir()

    def add_frame(self, frame: pd.DataFrame) -> None:
        if frame.empty:
            return
        require_columns(frame, ENCOUNTER_COLUMNS, context="Encounter subset")
        keys = frame["encounter_id"].astype("object").map(_encounter_id_key)
        if keys.duplicated().any():
            raise ValueError("Encounter subset contains duplicate encounter_id values.")
        bucketed = frame.loc[:, ENCOUNTER_COLUMNS].copy()
        bucketed.insert(0, "encounter_id_key", keys)
        bucketed["_bucket"] = bucketed["encounter_id_key"].map(
            lambda value: _encounter_lookup_bucket(value, FINAL_ENCOUNTER_BUCKET_COUNT)
        )
        for bucket, bucket_frame in bucketed.groupby("_bucket", sort=False):
            _append_scratch_csv_frame(
                self._bucket_path(int(bucket)),
                bucket_frame.loc[:, FINAL_ENCOUNTER_BUCKET_COLUMNS],
                written_paths=self._written_paths,
            )
        self._finalized = False

    def finalize(self) -> None:
        for path in sorted(self._written_paths):
            keys = pd.read_csv(
                path,
                usecols=["encounter_id_key"],
                dtype={"encounter_id_key": "string"},
            )
            if keys["encounter_id_key"].duplicated().any():
                raise ValueError(
                    "Encounter subset contains duplicate encounter_id values."
                )
        self._finalized = True

    def frame_for_encounter_ids(self, encounter_ids: pd.Series) -> pd.DataFrame:
        keys = encounter_ids.astype("object").map(_encounter_id_key)
        unique_keys = list(dict.fromkeys(keys.dropna().tolist()))
        if not unique_keys:
            return _empty_encounter_frame()

        keys_by_bucket: dict[int, set[str]] = {}
        for key in unique_keys:
            bucket = _encounter_lookup_bucket(key, FINAL_ENCOUNTER_BUCKET_COUNT)
            keys_by_bucket.setdefault(bucket, set()).add(key)

        frames: list[pd.DataFrame] = []
        for bucket, bucket_keys in keys_by_bucket.items():
            path = self._bucket_path(bucket)
            if not path.exists():
                continue
            bucket_frame = pd.read_csv(
                path,
                usecols=FINAL_ENCOUNTER_BUCKET_COLUMNS,
                dtype={"encounter_id_key": "string", "encounter_id": "string"},
            )
            if bucket_frame.empty:
                continue
            matches = bucket_frame.loc[
                bucket_frame["encounter_id_key"].isin(bucket_keys),
                ENCOUNTER_COLUMNS,
            ]
            if not matches.empty:
                frames.append(matches)

        if not frames:
            return _empty_encounter_frame()
        return pd.concat(frames, ignore_index=True)

    def _bucket_path(self, bucket: int) -> Path:
        if self.path is None:
            raise RuntimeError("Encounter lookup is not open.")
        return self.path / f"encounters_{bucket:03}.csv"

    def _remove_scratch_dir(self) -> None:
        if self.path is None:
            return
        remove_tree_strict(self.path, context="Final encounter lookup scratch")


def _append_scratch_csv_frame(
    path: Path,
    frame: pd.DataFrame,
    *,
    written_paths: set[Path],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    is_written = path in written_paths
    frame.to_csv(
        path,
        index=False,
        mode="a" if is_written else "w",
        header=not is_written,
    )
    written_paths.add(path)


def _encounter_lookup_bucket(encounter_id_key: str, bucket_count: int) -> int:
    digest = hashlib.blake2b(encounter_id_key.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, byteorder="big") % bucket_count


def _load_work_table_frame(
    path: Path,
    *,
    columns: list[str],
    dtype: dict[str, str],
    chunksize: int | None,
) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for frame in iter_work_tables(
        [path],
        chunksize=chunksize,
        usecols=columns,
        dtype=dtype,
    ):
        require_columns(frame, columns, context=str(path))
        frames.append(frame.loc[:, columns])

    if not frames:
        return pd.DataFrame(columns=columns)
    if len(frames) == 1:
        return frames[0]
    return pd.concat(frames, ignore_index=True)


def _data_checks_path(work_dir: Path, setting: str) -> Path | None:
    filename = SETTING_DATA_CHECKS.get(setting)
    if not filename:
        return None
    return work_dir / "data_checks" / filename


def _load_data_check_encounter_ids(
    data_checks_path: Path | None,
    *,
    logger: logging.Logger,
    chunksize: int | None = None,
) -> set[str] | None:
    if data_checks_path is None or not data_checks_path.exists():
        return None
    allowed: set[str] = set()
    for checks in _iter_data_check_frames(data_checks_path, chunksize=chunksize):
        require_columns(checks, ["encounter_id"], context=str(data_checks_path))
        allowed.update(checks["encounter_id"].dropna().astype("string"))
    log_row_count(logger, f"data checks read {data_checks_path.name}", len(allowed))
    return allowed


def _cached_data_check_lookup(
    cache: dict[Path, "_EncounterIdLookup" | None],
    data_checks_path: Path | None,
    *,
    work_dir: Path,
    stack: ExitStack,
    logger: logging.Logger,
    chunksize: int | None,
) -> "_EncounterIdLookup" | None:
    if data_checks_path is None:
        return None
    cached = cache.get(data_checks_path)
    if data_checks_path in cache:
        return cached
    lookup = _load_data_check_encounter_lookup(
        data_checks_path,
        work_dir=work_dir,
        stack=stack,
        logger=logger,
        chunksize=chunksize,
    )
    cache[data_checks_path] = lookup
    return lookup


def _load_data_check_encounter_lookup(
    data_checks_path: Path | None,
    *,
    work_dir: Path,
    stack: ExitStack,
    logger: logging.Logger,
    chunksize: int | None = None,
) -> "_EncounterIdLookup" | None:
    if data_checks_path is None or not data_checks_path.exists():
        return None
    lookup = stack.enter_context(_EncounterIdLookup(work_dir))
    for checks in _iter_data_check_frames(data_checks_path, chunksize=chunksize):
        require_columns(checks, ["encounter_id"], context=str(data_checks_path))
        lookup.add_values(checks["encounter_id"])
    log_row_count(logger, f"data checks read {data_checks_path.name}", lookup.count())
    return lookup


def _iter_data_check_frames(
    data_checks_path: Path,
    *,
    chunksize: int | None,
):
    reader = pd.read_csv(
        data_checks_path,
        usecols=["encounter_id"],
        dtype={"encounter_id": "string"},
        chunksize=chunksize,
    )
    if chunksize is None:
        yield reader
    else:
        yield from reader


class _EncounterIdLookup:
    """Disk-backed encounter-id membership lookup for final data checks."""

    def __init__(self, work_dir: Path) -> None:
        self.work_dir = work_dir
        self.path: Path | None = None
        self.connection: sqlite3.Connection | None = None

    def __enter__(self) -> "_EncounterIdLookup":
        self.work_dir.mkdir(parents=True, exist_ok=True)
        handle = tempfile.NamedTemporaryFile(
            prefix=".trinetx-data-check-ids-",
            suffix=".sqlite",
            dir=self.work_dir,
            delete=False,
        )
        handle.close()
        self.path = Path(handle.name)
        self.connection = sqlite3.connect(self.path)
        self.connection.execute("PRAGMA journal_mode=OFF")
        self.connection.execute("PRAGMA synchronous=OFF")
        self.connection.execute("PRAGMA temp_store=FILE")
        self.connection.execute(
            """
            CREATE TABLE allowed_encounter_ids (
                encounter_id_key TEXT PRIMARY KEY,
                encounter_id TEXT NOT NULL
            ) WITHOUT ROWID
            """
        )
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self.connection is not None:
            self.connection.close()
            self.connection = None
        self._unlink_scratch_files()

    def add_values(self, encounter_ids: pd.Series) -> None:
        records = [
            (_encounter_id_key(value), str(value))
            for value in encounter_ids.astype("object")
            if not pd.isna(value)
        ]
        if not records:
            return
        self._connection().executemany(
            """
            INSERT OR IGNORE INTO allowed_encounter_ids(
                encounter_id_key,
                encounter_id
            )
            VALUES (?, ?)
            """,
            records,
        )

    def filter_frame(self, df: pd.DataFrame) -> pd.DataFrame:
        if df.empty:
            return df.copy()
        keys = df["encounter_id"].astype("object").map(_encounter_id_key)
        allowed_keys = self._allowed_keys(keys.dropna().unique().tolist())
        if not allowed_keys:
            return df.iloc[0:0].copy()
        return df.loc[keys.isin(allowed_keys)].copy()

    def count(self) -> int:
        row = (
            self._connection()
            .execute("SELECT COUNT(*) FROM allowed_encounter_ids")
            .fetchone()
        )
        return int(row[0])

    def _allowed_keys(self, keys: list[str]) -> set[str]:
        if not keys:
            return set()
        allowed: set[str] = set()
        for start in range(0, len(keys), 500):
            batch = keys[start : start + 500]
            placeholders = ",".join("?" for _ in batch)
            rows = self._connection().execute(
                f"""
                SELECT encounter_id_key
                FROM allowed_encounter_ids
                WHERE encounter_id_key IN ({placeholders})
                """,
                batch,
            )
            allowed.update(row[0] for row in rows)
        return allowed

    def _connection(self) -> sqlite3.Connection:
        if self.connection is None:
            raise RuntimeError("Encounter-id lookup is not open.")
        return self.connection

    def _unlink_scratch_files(self) -> None:
        if self.path is None:
            return
        for path in [
            self.path,
            self.path.with_name(f"{self.path.name}-journal"),
            self.path.with_name(f"{self.path.name}-wal"),
            self.path.with_name(f"{self.path.name}-shm"),
        ]:
            try:
                path.unlink()
            except FileNotFoundError:
                pass


def _merge_validate(
    left: pd.DataFrame,
    right: pd.DataFrame,
    *,
    on: str,
    validate: str,
    context: str,
) -> pd.DataFrame:
    merged = left.merge(right, on=on, how="left", validate=validate)
    if merged.empty and not left.empty:
        raise ValueError(f"Merge with {context} dropped all rows.")
    return merged


def _merge_with_guardrails(
    left: pd.DataFrame,
    right: pd.DataFrame,
    *,
    on: str,
    validate: str,
    context: str,
    guardrails: GuardrailConfig,
    strict: bool,
    logger: logging.Logger,
) -> pd.DataFrame:
    left_rows = len(left)
    merged = _merge_validate(left, right, on=on, validate=validate, context=context)
    log_row_count(logger, f"{context} post-join", len(merged))
    if strict:
        check_join_multiplier(
            left_rows,
            len(merged),
            guardrails.max_join_multiplier,
            context=context,
        )
        check_required_ids(merged, [on], context=f"{context} join keys")
    return merged


def _ensure_identifiers(df: pd.DataFrame) -> pd.DataFrame:
    if df["patient_id"].isna().any() or df["encounter_id"].isna().any():
        raise ValueError("Final dataset contains missing patient_id or encounter_id.")
    if df["patient_id"].duplicated().any():
        raise ValueError("Final dataset must have unique patient_id values.")
    if df["encounter_id"].duplicated().any():
        raise ValueError("Final dataset must have unique encounter_id values.")
    return df


def _finalize_output(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=FINAL_OUTPUT_COLUMNS)
    frame = df.copy()
    if "patient_regional_location" in frame.columns and "location" not in frame.columns:
        frame = frame.rename(columns={"patient_regional_location": "location"})
    missing_defaults = {
        column: _legacy_default_value(column)
        for column in FINAL_OUTPUT_COLUMNS
        if column not in frame.columns
    }
    if missing_defaults:
        frame = pd.concat(
            [
                frame,
                pd.DataFrame(missing_defaults, index=frame.index),
            ],
            axis=1,
        )
    for column in FINAL_OUTPUT_COLUMNS:
        frame[column] = _fill_legacy_defaults(frame[column], column)
    ordered = frame.loc[:, FINAL_OUTPUT_COLUMNS].copy()
    ordered = ordered.sort_values(by=["patient_id", "encounter_id"]).reset_index(
        drop=True
    )
    return ordered


def _legacy_default_value(column: str) -> object:
    if column.startswith("value_Prev_"):
        return 0
    if column.startswith("value_"):
        return 0.0
    if column.startswith(("HAS_", "IP_Med_", "OP_Med_")):
        return 0
    if column.startswith(("pcpl_dx_ind_", "adm_dx_", "visit_reason_")):
        return "U"
    if column == "death_year_month":
        return " "
    if column.startswith(("date_", "first_date_", "last_date_")):
        return pd.NA
    return pd.NA


def _fill_legacy_defaults(series: pd.Series, column: str) -> pd.Series:
    if column in {"age_at_encounter", "LOS"}:
        return pd.to_numeric(series, errors="coerce").astype("Int32")
    if column.startswith("value_Prev_"):
        return pd.to_numeric(series, errors="coerce").fillna(0).astype("int32")
    if column.startswith("value_"):
        return pd.to_numeric(series, errors="coerce").fillna(0.0).astype("float32")
    if column.startswith(("HAS_", "IP_Med_", "OP_Med_")):
        return pd.to_numeric(series, errors="coerce").fillna(0).astype("int32")
    if column.startswith(("pcpl_dx_ind_", "adm_dx_", "visit_reason_")):
        return series.replace({"Unknown": "U"}).fillna("U")
    if column == "death_year_month":
        return series.fillna("").replace({"": " "})
    if column.startswith(("date_", "first_date_", "last_date_")):
        return pd.to_datetime(series, errors="coerce").dt.strftime("%Y-%m-%d")
    return series

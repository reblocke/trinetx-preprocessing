"""Pure cohort construction for corrected final analytic outputs."""

from __future__ import annotations

import logging

import pandas as pd

from ..guardrails import (
    GuardrailConfig,
    check_join_multiplier,
    check_required_ids,
    log_row_count,
)
from ..transform.rfs import RFS_EVENT_COLUMNS
from ..validation import require_columns

QUALIFY_DATE_MIN = pd.Timestamp("2022-01-01")
QUALIFY_DATE_MAX = pd.Timestamp("2022-12-31")

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


def prepare_event_candidates(
    events: pd.DataFrame,
    demographics: pd.DataFrame,
    *,
    rfs_category: str,
    context: str,
    guardrails: GuardrailConfig,
    strict: bool,
    logger: logging.Logger,
) -> pd.DataFrame:
    """Filter RFS events and attach eligible demographics."""

    if events.empty:
        return pd.DataFrame(columns=FINAL_EVENT_CANDIDATE_COLUMNS)
    require_columns(events, RFS_EVENT_COLUMNS, context="RFS events")
    require_columns(demographics, DEMOGRAPHIC_OUTPUT_COLUMNS, context="Demographics")

    assembled = events.loc[:, RFS_EVENT_COLUMNS].copy()
    assembled["patient_id"] = assembled["patient_id"].astype("string")
    assembled["encounter_id"] = assembled["encounter_id"].astype("string")
    assembled = assembled.rename(columns={"date": "qualify_date"})
    assembled["qualify_date"] = pd.to_datetime(
        assembled["qualify_date"], errors="coerce"
    )
    assembled = assembled.loc[
        assembled["qualify_date"].between(QUALIFY_DATE_MIN, QUALIFY_DATE_MAX)
    ].dropna(subset=["patient_id", "encounter_id", "qualify_date"])
    log_row_count(logger, f"final {context} post-filter dates", len(assembled))
    if strict:
        check_required_ids(
            assembled,
            ["patient_id", "encounter_id"],
            context=f"final {context} events",
        )

    assembled = _guarded_merge(
        assembled,
        demographics,
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
    log_row_count(logger, f"final {context} post-filter location", len(assembled))

    assembled = assembled.sort_values(
        by=["qualify_date", "encounter_id"],
        ascending=[True, False],
        kind="mergesort",
    ).drop_duplicates(subset=["encounter_id"], keep="first")
    return assembled.loc[:, FINAL_EVENT_CANDIDATE_COLUMNS].reset_index(drop=True)


def select_setting_cohort(
    event_candidates: pd.DataFrame,
    encounters: pd.DataFrame,
    *,
    rfs_category: str,
    setting: str,
    guardrails: GuardrailConfig,
    strict: bool,
    logger: logging.Logger,
) -> pd.DataFrame:
    """Select the earliest eligible event per patient within one setting."""

    if event_candidates.empty:
        return pd.DataFrame(columns=BASE_FINAL_OUTPUT_COLUMNS)
    require_columns(
        event_candidates,
        FINAL_EVENT_CANDIDATE_COLUMNS,
        context=f"final {rfs_category}/{setting} event candidates",
    )
    require_columns(encounters, ENCOUNTER_COLUMNS, context="Encounter subset")

    assembled = _guarded_merge(
        event_candidates.loc[:, FINAL_EVENT_CANDIDATE_COLUMNS].copy(),
        encounters.loc[:, ENCOUNTER_COLUMNS],
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
    return reduce_setting_cohort_rows(assembled)


def reduce_setting_cohort_rows(frame: pd.DataFrame) -> pd.DataFrame:
    """Keep the earliest deterministic row per patient in one setting cohort."""

    if frame.empty:
        return frame.reset_index(drop=True)
    selected = frame.sort_values(
        by=["qualify_date", "encounter_id"],
        ascending=[True, False],
        kind="mergesort",
    ).drop_duplicates(subset=["patient_id"], keep="first")
    _require_unique_identifiers(selected)
    return selected.reset_index(drop=True)


def _guarded_merge(
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
    merged = left.merge(right, on=on, how="left", validate=validate)
    if merged.empty and not left.empty:
        raise ValueError(f"Merge with {context} dropped all rows.")
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


def _require_unique_identifiers(frame: pd.DataFrame) -> None:
    if frame["patient_id"].isna().any() or frame["encounter_id"].isna().any():
        raise ValueError("Final dataset contains missing patient_id or encounter_id.")
    if frame["patient_id"].duplicated().any():
        raise ValueError("Final dataset must have unique patient_id values.")
    if frame["encounter_id"].duplicated().any():
        raise ValueError("Final dataset must have unique encounter_id values.")

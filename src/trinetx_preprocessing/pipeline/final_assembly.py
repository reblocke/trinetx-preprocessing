"""Final dataset assembly stage built from legacy notebook logic."""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from ..config import Config, ConfigError, collect_domain_paths
from ..guardrails import (
    GuardrailConfig,
    check_join_multiplier,
    check_required_ids,
    log_row_count,
)
from ..transform.rfs import RFS_CATEGORIES, RFS_EVENT_COLUMNS
from ..validation import require_columns

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

FINAL_OUTPUT_COLUMNS = [
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

    demographics = _load_demographics(patient_paths, logger)
    rfs_events = _load_rfs_events(config.work_dir, logger)
    encounters_by_setting = _load_encounters(config.work_dir, logger)

    output_paths: list[Path] = []
    for setting in SETTINGS:
        encounter_df = encounters_by_setting[setting]
        output_dir = config.output_dir / SETTING_OUTPUT_DIRS[setting]
        output_dir.mkdir(parents=True, exist_ok=True)
        data_checks_path = _data_checks_path(config.work_dir, setting)

        for category in RFS_CATEGORIES:
            events = rfs_events.get(category, pd.DataFrame(columns=RFS_EVENT_COLUMNS))
            before = build_final_dataset(
                events,
                demographics,
                encounter_df,
                rfs_category=category,
                setting=setting,
                guardrails=config.guardrails,
                strict=strict,
                logger=logger,
            )
            before_path = output_dir / f"RFS_{category}_ENC_{setting}_BEFORE.csv"
            before.to_csv(before_path, index=False)
            output_paths.append(before_path)

            after = apply_data_checks(
                before,
                data_checks_path,
                context=f"{category}/{setting}",
                logger=logger,
            )
            after_path = output_dir / f"RFS_{category}_ENC_{setting}_AFTER.csv"
            after.to_csv(after_path, index=False)
            output_paths.append(after_path)

            logger.info(
                "Wrote %s rows for %s/%s to %s",
                len(after),
                category,
                setting,
                after_path.name,
            )

    return output_paths


def build_final_dataset(
    events: pd.DataFrame,
    demographics: pd.DataFrame,
    encounters: pd.DataFrame,
    *,
    rfs_category: str,
    setting: str,
    guardrails: GuardrailConfig,
    strict: bool,
    logger: logging.Logger | None = None,
) -> pd.DataFrame:
    """Construct a final dataset for a single RFS/setting pair."""

    logger = logger or logging.getLogger(__name__)

    if events.empty:
        return pd.DataFrame(columns=FINAL_OUTPUT_COLUMNS)

    require_columns(events, RFS_EVENT_COLUMNS, context="RFS events")
    require_columns(demographics, DEMOGRAPHIC_OUTPUT_COLUMNS, context="Demographics")
    require_columns(encounters, ENCOUNTER_COLUMNS, context="Encounter subset")

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
        f"final {rfs_category}/{setting} post-filter dates",
        len(assembled),
    )
    if strict:
        check_required_ids(
            assembled,
            ["patient_id", "encounter_id"],
            context=f"final {rfs_category}/{setting} events",
        )

    assembled = _merge_with_guardrails(
        assembled,
        demographics,
        on="patient_id",
        validate="many_to_one",
        context=f"final {rfs_category}/{setting} demographics",
        guardrails=guardrails,
        strict=strict,
        logger=logger,
    )

    assembled.insert(loc=2, column="RFS", value=rfs_category)

    assembled = assembled.loc[
        ~assembled["patient_regional_location"].isin(["Ex-US", "Unknown"])
    ]
    log_row_count(
        logger,
        f"final {rfs_category}/{setting} post-filter location",
        len(assembled),
    )

    assembled = assembled.sort_values(
        by=["qualify_date", "encounter_id"],
        ascending=[True, False],
    )
    assembled = assembled.drop_duplicates(subset=["encounter_id"], keep="first")
    assembled = assembled.drop_duplicates(subset=["patient_id"], keep="first")

    assembled = _merge_with_guardrails(
        assembled,
        encounters,
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
    assembled = _finalize_output(assembled)
    return assembled.loc[:, FINAL_OUTPUT_COLUMNS]


def apply_data_checks(
    df: pd.DataFrame,
    data_checks_path: Path | None,
    *,
    context: str,
    logger: logging.Logger | None = None,
) -> pd.DataFrame:
    """Apply encounter-level data checks if available."""

    logger = logger or logging.getLogger(__name__)

    if df.empty or data_checks_path is None or not data_checks_path.exists():
        return _finalize_output(df)

    checks = pd.read_csv(data_checks_path, dtype={"encounter_id": "string"})
    require_columns(checks, ["encounter_id"], context=str(data_checks_path))
    allowed = set(checks["encounter_id"].dropna().astype("string"))
    filtered = df.loc[df["encounter_id"].astype("string").isin(allowed)].copy()
    log_row_count(logger, f"final {context} post-filter data checks", len(filtered))
    return _finalize_output(filtered)


def _load_demographics(paths: list[Path], logger: logging.Logger) -> pd.DataFrame:
    frames = [pd.read_csv(path, dtype={"patient_id": "string"}) for path in paths]
    if not frames:
        return pd.DataFrame(columns=DEMOGRAPHIC_OUTPUT_COLUMNS)
    combined = pd.concat(frames, ignore_index=True) if len(frames) > 1 else frames[0]
    require_columns(combined, DEMOGRAPHIC_COLUMNS, context="Patient inputs")

    combined = combined.loc[:, DEMOGRAPHIC_COLUMNS].copy()
    combined["patient_id"] = combined["patient_id"].astype("string")
    combined["sex"] = combined["sex"].astype("string")
    combined["race"] = combined["race"].astype("string")
    combined["ethnicity"] = combined["ethnicity"].astype("string")
    combined["patient_regional_location"] = combined[
        "patient_regional_location"
    ].astype("string")

    combined["year_of_birth"] = (
        pd.to_numeric(combined["year_of_birth"], errors="coerce")
        .fillna(0)
        .astype("int32")
    )
    combined = combined.rename(columns={"year_of_birth": "birth_year"})
    combined["death_year_month"] = _format_death_year_month(
        combined["month_year_death"]
    )
    combined = combined.drop(columns=["month_year_death"])

    if combined["patient_id"].duplicated().any():
        raise ValueError("Patient demographics contain duplicate patient_id values.")

    log_row_count(logger, "demographics read", len(combined))
    return combined.loc[:, DEMOGRAPHIC_OUTPUT_COLUMNS]


def _format_death_year_month(series: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(series, errors="coerce").fillna(0).astype("int64")
    strings = numeric.astype(str)
    formatted = strings.where(numeric != 0, "")
    formatted = formatted.where(
        formatted == "",
        formatted.str.slice(0, 4) + "-" + formatted.str.slice(4, 6),
    )
    return formatted.astype("string")


def _load_rfs_events(work_dir: Path, logger: logging.Logger) -> dict[str, pd.DataFrame]:
    events: dict[str, pd.DataFrame] = {}
    for category in RFS_CATEGORIES:
        path = work_dir / f"RFS_{category}.csv"
        if not path.exists():
            raise FileNotFoundError(f"Missing RFS events file for {category}: {path}")
        frame = pd.read_csv(
            path,
            usecols=RFS_EVENT_COLUMNS,
            dtype={"patient_id": "string", "encounter_id": "string"},
        )
        events[category] = frame.loc[:, RFS_EVENT_COLUMNS]
        log_row_count(logger, f"rfs events read {category}", len(events[category]))
    return events


def _load_encounters(work_dir: Path, logger: logging.Logger) -> dict[str, pd.DataFrame]:
    encounters: dict[str, pd.DataFrame] = {}
    for setting, filename in SETTING_ENCOUNTER_FILES.items():
        path = work_dir / filename
        if not path.exists():
            raise FileNotFoundError(f"Missing encounter file for {setting}: {path}")
        frame = pd.read_csv(
            path,
            usecols=ENCOUNTER_COLUMNS,
            dtype={"encounter_id": "string"},
        )
        require_columns(frame, ENCOUNTER_COLUMNS, context=str(path))
        encounters[setting] = frame.loc[:, ENCOUNTER_COLUMNS]
        log_row_count(logger, f"encounters read {setting}", len(encounters[setting]))
    return encounters


def _data_checks_path(work_dir: Path, setting: str) -> Path | None:
    filename = SETTING_DATA_CHECKS.get(setting)
    if not filename:
        return None
    return work_dir / "data_checks" / filename


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
    ordered = df.loc[:, FINAL_OUTPUT_COLUMNS].copy()
    ordered = ordered.sort_values(by=["patient_id", "encounter_id"]).reset_index(
        drop=True
    )
    return ordered

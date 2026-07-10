"""Final dataset assembly stage built from legacy notebook logic."""

from __future__ import annotations

import json
import logging
from collections.abc import Collection
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from ..config import Config, ConfigError, collect_domain_paths
from ..filesystem import write_text_atomic
from ..guardrails import (
    GuardrailConfig,
    check_join_multiplier,
    check_required_ids,
    log_row_count,
)
from ..storage import (
    PartitionedKeyLookup,
    PartitionedParquetStore,
    find_work_tables,
    iter_work_tables,
    resolve_work_table,
)
from ..transform.diagnosis import (
    CURRENT_DIAGNOSIS_CODE_GROUPS,
    DIAGNOSIS_COLUMNS,
    INDICATOR_COLUMNS,
    PRIOR_DIAGNOSIS_CODE_GROUPS,
)
from ..transform.lab_features import (
    LAB_VALUE_RULES,
    classify_lab_feature_rows,
    legacy_lab_feature_values,
)
from ..transform.lab_features import (
    LabFeatureRule as _LabValueRule,
)
from ..transform.lab_features import (
    lab_code_priority as _lab_code_priority,
)
from ..transform.lab_features import (
    legacy_csv_visible_numeric_series as _legacy_csv_visible_numeric_series,
)
from ..transform.labs import LAB_COLUMNS
from ..transform.medications import MEDICATION_CODE_GROUPS, MEDICATION_COLUMNS
from ..transform.procedure import PROCEDURE_CODE_GROUPS, PROCEDURE_COLUMNS
from ..transform.rfs import RFS_CATEGORIES, RFS_EVENT_COLUMNS
from ..transform.vitals import VITAL_SIGN_RULES, VITALS_COLUMNS
from ..validation import require_columns
from .cohort import (
    BASE_FINAL_OUTPUT_COLUMNS,
    DEMOGRAPHIC_OUTPUT_COLUMNS,
    ENCOUNTER_COLUMNS,
    FINAL_EVENT_CANDIDATE_COLUMNS,
    QUALIFY_DATE_MAX,
    QUALIFY_DATE_MIN,
    prepare_event_candidates,
    select_setting_cohort,
)
from .final_feature_sources import (
    LAB_SOURCE_NAME,
    FinalFeatureBucket,
    FinalFeatureSourceStore,
)
from .final_output_schema import FINAL_OUTPUT_COLUMNS

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
FINAL_DEMOGRAPHICS_BUCKET_COUNT = 256
FINAL_DEMOGRAPHICS_BUCKET_COLUMNS = [
    "patient_id_key",
    *DEMOGRAPHIC_OUTPUT_COLUMNS,
]
FINAL_DATA_SCREEN_BUCKET_COUNT = 256
FINAL_DATA_SCREEN_BUCKET_COLUMNS = ["encounter_id_key", "encounter_id"]
FINAL_EVENT_BUCKET_COUNT = 256
FINAL_EVENT_DEFAULT_CHUNK_ROWS = 500_000
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
            strict=strict,
        )

        output_paths = _initialize_final_output_files(config)
        cohort_store = stack.enter_context(
            PartitionedParquetStore(
                config.work_dir,
                prefix=".trinetx-final-cohorts-",
                key_columns=["patient_id"],
                bucket_count=config.storage.analysis_bucket_count,
                row_group_size=config.storage.parquet_row_group_size,
                cleanup_context="Final cohort index scratch",
            )
        )
        cohort_rows_indexed = 0
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
                base = build_final_dataset_from_candidates(
                    event_candidates,
                    inputs.encounters,
                    config=None,
                    rfs_category=category,
                    setting=setting,
                    guardrails=config.guardrails,
                    strict=strict,
                    logger=logger,
                    enrich_features=False,
                    finalize_output=False,
                )
                if base.empty:
                    continue
                base.insert(0, "_setting", setting)
                base.insert(0, "_category", category)
                cohort_store.add_frame(base)
                cohort_rows_indexed += len(base)

        feature_sources = stack.enter_context(
            FinalFeatureSourceStore(config, chunksize=chunksize)
        )
        logger.info(
            "Indexed %s final feature rows from %s work tables",
            feature_sources.rows_indexed,
            feature_sources.files_scanned,
        )
        rows_written = {key: 0 for key in output_paths}
        buckets_processed = 0
        for bucket, cohort_rows in cohort_store.iter_frames():
            buckets_processed += 1
            source_bucket = feature_sources.bucket(bucket)
            for (category, setting), group in cohort_rows.groupby(
                ["_category", "_setting"], sort=False
            ):
                base = group.drop(columns=["_category", "_setting"])
                enriched = _enrich_legacy_final_features(
                    base,
                    config=config,
                    chunksize=chunksize,
                    logger=logger,
                    source_bucket=source_bucket,
                )
                before = _finalize_output(enriched)
                _append_final_rows(
                    output_paths[(str(setting), str(category), "BEFORE")],
                    before,
                )
                rows_written[(str(setting), str(category), "BEFORE")] += len(before)

                inputs = setting_inputs[str(setting)]
                after = apply_data_checks(
                    before,
                    inputs.data_checks_path,
                    allowed_encounter_ids=inputs.allowed_encounter_ids,
                    data_checks_preloaded=True,
                    finalize_output=False,
                    context=f"{category}/{setting}",
                    logger=logger,
                )
                _append_final_rows(
                    output_paths[(str(setting), str(category), "AFTER")],
                    after,
                )
                rows_written[(str(setting), str(category), "AFTER")] += len(after)

        for key, count in rows_written.items():
            logger.info("Wrote %s rows for %s/%s/%s", count, *key)
        metrics = {
            "schema_version": 1,
            "ruleset": config.rfs.ruleset,
            "bucket_count": config.storage.analysis_bucket_count,
            "buckets_processed": buckets_processed,
            "cohort_rows_indexed": cohort_rows_indexed,
            "feature_source_files_scanned": feature_sources.files_scanned,
            "feature_source_file_names": sorted(feature_sources.source_files_scanned),
            "feature_source_rows_indexed": feature_sources.rows_indexed,
            "cohort_index_bytes": cohort_store.disk_size_bytes(),
            "feature_source_index_bytes": feature_sources.disk_size_bytes(),
            "rows_written": {
                "/".join(key): count for key, count in sorted(rows_written.items())
            },
        }
        write_text_atomic(
            config.work_dir / "final_assembly_metrics.json",
            json.dumps(metrics, indent=2, sort_keys=True),
        )

    return _ordered_final_output_paths(output_paths)


def _initialize_final_output_files(
    config: Config,
) -> dict[tuple[str, str, str], Path]:
    output_paths: dict[tuple[str, str, str], Path] = {}
    empty = pd.DataFrame(columns=FINAL_OUTPUT_COLUMNS)
    for setting in SETTINGS:
        output_dir = config.output_dir / SETTING_OUTPUT_DIRS[setting]
        output_dir.mkdir(parents=True, exist_ok=True)
        for category in RFS_CATEGORIES:
            for suffix in ("BEFORE", "AFTER"):
                path = output_dir / f"RFS_{category}_ENC_{setting}_{suffix}.csv"
                empty.to_csv(path, index=False)
                output_paths[(setting, category, suffix)] = path
    return output_paths


def _append_final_rows(path: Path, frame: pd.DataFrame) -> None:
    if frame.empty:
        return
    frame.to_csv(path, index=False, mode="a", header=False)


def _load_setting_inputs(
    config: Config,
    logger: logging.Logger,
    *,
    chunksize: int | None,
    stack: ExitStack,
    strict: bool,
) -> dict[str, _SettingInputs]:
    setting_inputs: dict[str, _SettingInputs] = {}
    data_check_cache: dict[Path, _EncounterIdLookup | None] = {}
    derived_allowed = None
    if config.data_screen.source == "derived":
        derived_allowed = _load_derived_data_screen_lookup(
            config,
            work_dir=config.work_dir,
            stack=stack,
            logger=logger,
            chunksize=chunksize,
            strict=strict,
        )
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
        data_checks_path = None
        allowed_encounter_ids = derived_allowed
        if config.data_screen.source == "legacy_files":
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
    demographics_frame = _demographics_frame_for_merge(
        demographics,
        events["patient_id"],
    )
    return prepare_event_candidates(
        events,
        demographics_frame,
        rfs_category=rfs_category,
        context=context,
        guardrails=guardrails,
        strict=strict,
        logger=logger,
    )


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
    enrich_features: bool = True,
    finalize_output: bool = True,
) -> pd.DataFrame:
    """Merge reduced final-event candidates with one setting encounter lookup."""

    logger = logger or logging.getLogger(__name__)

    if event_candidates.empty:
        if finalize_output:
            return pd.DataFrame(columns=FINAL_OUTPUT_COLUMNS)
        return pd.DataFrame(columns=BASE_FINAL_OUTPUT_COLUMNS)

    encounters_frame = _encounters_frame_for_merge(
        encounters,
        event_candidates["encounter_id"],
    )
    assembled = select_setting_cohort(
        event_candidates,
        encounters_frame,
        rfs_category=rfs_category,
        setting=setting,
        guardrails=guardrails,
        strict=strict,
        logger=logger,
    )
    if enrich_features and config is not None:
        assembled = _enrich_legacy_final_features(
            assembled,
            config=config,
            chunksize=config.chunking.lines_per_chunk
            if config.chunking.enabled
            else None,
            logger=logger,
        )
    if not finalize_output:
        return assembled.reset_index(drop=True)
    assembled = _finalize_output(assembled)
    return assembled.loc[:, FINAL_OUTPUT_COLUMNS]


def apply_data_checks(
    df: pd.DataFrame,
    data_checks_path: Path | None,
    *,
    allowed_encounter_ids: Collection[str] | "_EncounterIdLookup" | None = None,
    data_checks_preloaded: bool = False,
    finalize_output: bool = True,
    chunksize: int | None = None,
    context: str,
    logger: logging.Logger | None = None,
) -> pd.DataFrame:
    """Apply encounter-level data checks if available."""

    logger = logger or logging.getLogger(__name__)

    def finish(frame: pd.DataFrame) -> pd.DataFrame:
        if finalize_output:
            return _finalize_output(frame)
        return frame.reset_index(drop=True)

    if df.empty:
        return finish(df)

    allowed = allowed_encounter_ids
    if allowed is None and data_checks_preloaded:
        return finish(df)
    if allowed is None:
        allowed = _load_data_check_encounter_ids(
            data_checks_path,
            logger=logger,
            chunksize=chunksize,
        )
    if allowed is None:
        return finish(df)

    if isinstance(allowed, _EncounterIdLookup):
        filtered = allowed.filter_frame(df)
    else:
        filtered = df.loc[df["encounter_id"].astype("string").isin(allowed)].copy()
    log_row_count(logger, f"final {context} post-filter data checks", len(filtered))
    return finish(filtered)


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


def _merge_vital_value_features(
    df: pd.DataFrame,
    *,
    config: Config,
    patient_ids: set[str],
    encounter_ids: set[str],
    chunksize: int,
    source_bucket: FinalFeatureBucket | None = None,
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
            source_bucket=source_bucket,
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
    source_bucket: FinalFeatureBucket | None = None,
) -> pd.DataFrame:
    enriched = df
    for name in ("Weight", "Height", "BMI"):
        selected = _load_previous_vital_candidates(
            config,
            name,
            final_rows=enriched.loc[:, ["patient_id", "encounter_id", "qualify_date"]],
            chunksize=chunksize,
            source_bucket=source_bucket,
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
    source_bucket: FinalFeatureBucket | None = None,
) -> pd.DataFrame:
    logical_name = f"value_{name}.csv"
    path = resolve_work_table(config, logical_name)
    output_columns = ["patient_id", f"value_Prev_{name}", f"date_Prev_{name}"]
    if source_bucket is None and not path.exists():
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

    if source_bucket is not None:
        chunks = [source_bucket.frame(logical_name, VITALS_COLUMNS)]
        filtered_frames: list[pd.DataFrame] = []
        for chunk in chunks:
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
            filtered["_qualify_date"] = (
                filtered["patient_id"].astype("string").map(qualify_dates_by_patient)
            )
            filtered = filtered.loc[filtered["date"] < filtered["_qualify_date"]].copy()
            if filtered.empty:
                continue
            filtered_frames.append(filtered.loc[:, VITALS_COLUMNS])
        if not filtered_frames:
            return pd.DataFrame(columns=output_columns)
        rows = pd.concat(filtered_frames, ignore_index=True)
        return _select_previous_patient_value(
            rows,
            value_column="value",
            output_value_column=f"value_Prev_{name}",
            output_date_column=f"date_Prev_{name}",
        )

    with _FinalPreviousVitalCandidateStore(config.work_dir) as store:
        chunks = iter_work_tables(
            [path],
            chunksize=chunksize,
            usecols=VITALS_COLUMNS,
            dtype={
                "patient_id": "string",
                "encounter_id": "string",
                "code": "string",
            },
        )
        for chunk in chunks:
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
            filtered["_qualify_date"] = (
                filtered["patient_id"].astype("string").map(qualify_dates_by_patient)
            )
            filtered = filtered.loc[filtered["date"] < filtered["_qualify_date"]].copy()
            if not filtered.empty:
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
    source_bucket: FinalFeatureBucket | None = None,
) -> pd.DataFrame:
    lab_rows_by_name = _load_lab_rows_by_rule(
        config,
        patient_ids=patient_ids,
        encounter_ids=encounter_ids,
        chunksize=chunksize,
        source_bucket=source_bucket,
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
    source_bucket: FinalFeatureBucket | None = None,
) -> dict[str, dict[str, pd.DataFrame]]:
    paths = find_work_tables(config, "lab_results_NEW_*.csv")
    if source_bucket is None and not paths:
        return {}
    rules_by_name = {
        rule.name: rule for rule in LAB_VALUE_RULES if _lab_rule_outputs_requested(rule)
    }
    if source_bucket is not None:
        normalized = source_bucket.frame(LAB_SOURCE_NAME, LAB_COLUMNS)
        if normalized.empty:
            grouped = {
                name: source_bucket.frame(name, LAB_COLUMNS)
                for name in rules_by_name
                if source_bucket.has_source(name)
            }
        else:
            grouped = classify_lab_feature_rows(normalized)
        return _reduce_lab_candidates(
            grouped,
            rules_by_name=rules_by_name,
            patient_ids=patient_ids,
            encounter_ids=encounter_ids,
        )

    with _FinalLabCandidateStore(config.work_dir) as store:
        chunks = iter_work_tables(
            paths,
            chunksize=chunksize,
            usecols=LAB_COLUMNS,
            dtype={
                "patient_id": "string",
                "encounter_id": "string",
                "code": "string",
            },
        )
        grouped_chunks = (
            classify_lab_feature_rows(
                _filter_ids(
                    chunk,
                    patient_ids=patient_ids,
                    encounter_ids=encounter_ids,
                    encounter_filter="include",
                )
            )
            for chunk in chunks
        )
        for grouped in grouped_chunks:
            for name, candidate_rows in grouped.items():
                rule = rules_by_name.get(name)
                if rule is None or candidate_rows.empty:
                    continue
                rows = _filter_ids(
                    candidate_rows,
                    patient_ids=patient_ids,
                    encounter_ids=encounter_ids,
                    encounter_filter="include",
                )
                if rows.empty:
                    continue
                rows["date"] = pd.to_datetime(rows["date"], errors="coerce")
                rows[FINAL_LAB_CODE_PRIORITY_COLUMN] = _lab_code_priority(
                    rule, rows["code"]
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


def _reduce_lab_candidates(
    grouped: dict[str, pd.DataFrame],
    *,
    rules_by_name: dict[str, _LabValueRule],
    patient_ids: set[str],
    encounter_ids: set[str],
) -> dict[str, dict[str, pd.DataFrame]]:
    reduced: dict[str, dict[str, pd.DataFrame]] = {}
    for name, candidate_rows in grouped.items():
        rule = rules_by_name.get(name)
        if rule is None or candidate_rows.empty:
            continue
        rows = _filter_ids(
            candidate_rows,
            patient_ids=patient_ids,
            encounter_ids=encounter_ids,
            encounter_filter="include",
        )
        if rows.empty:
            continue
        rows["date"] = pd.to_datetime(rows["date"], errors="coerce")
        rows[FINAL_LAB_CODE_PRIORITY_COLUMN] = _lab_code_priority(rule, rows["code"])
        features = {FINAL_LAB_FEATURE_FIRST: _reduce_first_lab_candidate_rows(rows)}
        if rule.include_highest:
            features[FINAL_LAB_FEATURE_HIGHEST] = _reduce_highest_lab_candidate_rows(
                rows
            )
        reduced[name] = features
    return reduced


def _lab_rule_outputs_requested(rule: _LabValueRule) -> bool:
    columns = _lab_output_value_columns()
    value_name = rule.name.removeprefix("value_")
    return rule.name in columns or f"value_highest_{value_name}" in columns


def _legacy_lab_feature_values(
    rule: _LabValueRule,
    codes: pd.Series,
    values: pd.Series,
) -> pd.Series:
    """Compatibility wrapper for focused feature-precision tests."""

    return legacy_lab_feature_values(rule, codes, values)


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
    source_bucket: FinalFeatureBucket | None = None,
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
            source_bucket=source_bucket,
        )
        if rows.empty:
            continue
        rows["date"] = pd.to_datetime(rows["date"], errors="coerce")
        rows = rows.loc[rows["date"] >= QUALIFY_DATE_MIN].copy()
        if rows.empty:
            continue
        selected = _select_current_diagnosis(rows)
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
    source_bucket: FinalFeatureBucket | None = None,
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
            source_bucket=source_bucket,
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
    source_bucket: FinalFeatureBucket | None = None,
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
            source_bucket=source_bucket,
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
    source_bucket: FinalFeatureBucket | None = None,
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
            source_bucket=source_bucket,
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
            first_valid = (
                pd.to_datetime(
                    feature[first_column],
                    errors="coerce",
                )
                <= qualify_dates
            )
            last_valid = (
                pd.to_datetime(
                    feature[last_column],
                    errors="coerce",
                )
                <= qualify_dates
            )
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
    source_bucket: FinalFeatureBucket | None = None,
) -> pd.DataFrame:
    if source_bucket is not None:
        chunk = source_bucket.frame(logical_name, columns)
        if chunk.empty:
            return pd.DataFrame(columns=columns)
        filtered = _filter_ids(
            chunk,
            patient_ids=patient_ids,
            encounter_ids=encounter_ids,
            encounter_filter=encounter_filter,
        )
        return filtered.loc[:, columns].copy().reset_index(drop=True)

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
    filtered["_qualify_date"] = (
        filtered["patient_id"]
        .astype("string")
        .map(
            qualify_dates_by_patient,
        )
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
    selected = selected.sort_values(
        by=["start_date", "encounter_id"],
        ascending=[True, False],
        kind="mergesort",
    )
    selected = selected.drop_duplicates(subset=["encounter_id"], keep="first")
    selected = selected.rename(columns={"start_date": f"date_IP_Med_{med_index}"})
    selected[f"IP_Med_{med_index}"] = 1
    return selected.loc[
        :,
        ["encounter_id", f"IP_Med_{med_index}", f"date_IP_Med_{med_index}"],
    ]


def _select_current_diagnosis(rows: pd.DataFrame) -> pd.DataFrame:
    """Reduce current diagnosis rows deterministically by encounter."""

    if rows.empty:
        return pd.DataFrame(columns=DIAGNOSIS_COLUMNS)
    selected = rows.loc[:, DIAGNOSIS_COLUMNS].copy()
    selected["date"] = pd.to_datetime(selected["date"], errors="coerce")
    selected["_row_order"] = range(len(selected))
    earliest = (
        selected.sort_values(
            by=["date", "_row_order"],
            ascending=[True, True],
            kind="mergesort",
        )
        .drop_duplicates(subset=["encounter_id"], keep="first")
        .copy()
    )
    priorities = {
        "principal_diagnosis_indicator": {"P": 3, "S": 2, "U": 1},
        "admitting_diagnosis": {"Y": 3, "T": 3, "N": 2, "F": 2, "U": 1},
        "reason_for_visit": {"Y": 3, "T": 3, "N": 2, "F": 2, "U": 1},
    }
    for column, priority in priorities.items():
        reduced = selected.groupby("encounter_id", sort=False)[column].agg(
            lambda values: _highest_priority_indicator(values, priority)
        )
        earliest[column] = earliest["encounter_id"].map(reduced)
    return earliest.loc[:, DIAGNOSIS_COLUMNS].reset_index(drop=True)


def _highest_priority_indicator(
    values: pd.Series,
    priority: dict[str, int],
) -> str:
    normalized = values.astype("string").fillna("U").replace({"Unknown": "U"})
    normalized = normalized.str.strip().str.upper()
    ranks = normalized.map(priority).fillna(0)
    return str(normalized.loc[ranks.idxmax()])


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

    lookup.finalize()
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


def _lookup_key_series(values: pd.Series) -> pd.Series:
    strings = values.astype("string")
    return ("value:" + strings).where(strings.notna(), "missing:").astype("string")


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
    """Patient demographics lookup backed by bounded Parquet partitions."""

    def __init__(self, work_dir: Path) -> None:
        self._lookup = PartitionedKeyLookup(
            work_dir,
            prefix=".trinetx-demographics-",
            key_column="patient_id_key",
            stored_columns=FINAL_DEMOGRAPHICS_BUCKET_COLUMNS,
            bucket_count=FINAL_DEMOGRAPHICS_BUCKET_COUNT,
            require_unique=True,
            cleanup_context="Final demographics lookup scratch",
        )

    def __enter__(self) -> "_DemographicsLookup":
        self._lookup.__enter__()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self._lookup.__exit__(exc_type, exc, tb)

    def add_frame(self, frame: pd.DataFrame) -> None:
        if frame.empty:
            return
        require_columns(frame, DEMOGRAPHIC_OUTPUT_COLUMNS, context="Demographics")
        bucketed = frame.loc[:, DEMOGRAPHIC_OUTPUT_COLUMNS].copy()
        bucketed.insert(0, "patient_id_key", _lookup_key_series(frame["patient_id"]))
        try:
            self._lookup.add_frame(bucketed)
        except ValueError as exc:
            raise ValueError(
                "Patient demographics contain duplicate patient_id values."
            ) from exc

    def finalize(self) -> None:
        try:
            self._lookup.finalize()
        except ValueError as exc:
            raise ValueError(
                "Patient demographics contain duplicate patient_id values."
            ) from exc

    def frame_for_patient_ids(self, patient_ids: pd.Series) -> pd.DataFrame:
        matches = self._lookup.frame_for_keys(_lookup_key_series(patient_ids))
        if matches.empty:
            return _empty_demographics_frame()
        return matches.loc[:, DEMOGRAPHIC_OUTPUT_COLUMNS].reset_index(drop=True)


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
    """Bucketed event reducer retaining one event per encounter."""

    def __init__(self, work_dir: Path) -> None:
        self.work_dir = work_dir
        self._store: PartitionedParquetStore | None = None
        self._next_row_order = 0

    def __enter__(self) -> "_FinalEventCandidateStore":
        self._store = PartitionedParquetStore(
            self.work_dir,
            prefix=".trinetx-final-events-",
            key_columns=["encounter_id"],
            bucket_count=FINAL_EVENT_BUCKET_COUNT,
            cleanup_context="Final event candidate scratch",
        )
        self._store.__enter__()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._store is not None:
            self._store.__exit__(exc_type, exc, tb)

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
        self._partition_store().add_frame(bucketed.loc[:, FINAL_EVENT_BUCKET_COLUMNS])

    def reduce(self) -> pd.DataFrame:
        frames: list[pd.DataFrame] = []
        for _, frame in self._partition_store().iter_frames(
            columns=FINAL_EVENT_BUCKET_COLUMNS
        ):
            frame["qualify_date"] = pd.to_datetime(
                frame["qualify_date"], errors="coerce"
            )
            if frame.empty:
                continue
            unique = (
                _sort_final_event_candidates(frame)
                .drop_duplicates(subset=["encounter_id"], keep="first")
                .loc[:, FINAL_EVENT_CANDIDATE_COLUMNS]
                .reset_index(drop=True)
            )
            if not unique.empty:
                frames.append(unique)
        if not frames:
            return pd.DataFrame(columns=FINAL_EVENT_CANDIDATE_COLUMNS)
        return pd.concat(frames, ignore_index=True)

    def _partition_store(self) -> PartitionedParquetStore:
        if self._store is None:
            raise RuntimeError("Final event candidate store is not open.")
        return self._store


class _FinalLabCandidateStore:
    """Bucketed lab-feature reducer for final assembly analytic columns."""

    def __init__(self, work_dir: Path) -> None:
        self.work_dir = work_dir
        self._store: PartitionedParquetStore | None = None

    def __enter__(self) -> "_FinalLabCandidateStore":
        self._store = PartitionedParquetStore(
            self.work_dir,
            prefix=".trinetx-final-labs-",
            key_columns=["rule_name", "feature_kind", "patient_id"],
            bucket_count=FINAL_LAB_BUCKET_COUNT,
            cleanup_context="Final lab feature scratch",
        )
        self._store.__enter__()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._store is not None:
            self._store.__exit__(exc_type, exc, tb)

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
        self._partition_store().add_frame(bucketed.loc[:, FINAL_LAB_BUCKET_COLUMNS])

    def reduce(self) -> dict[str, dict[str, pd.DataFrame]]:
        frames_by_rule: dict[str, dict[str, list[pd.DataFrame]]] = {}
        for _, frame in self._partition_store().iter_frames(
            columns=FINAL_LAB_BUCKET_COLUMNS
        ):
            frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
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

    def _partition_store(self) -> PartitionedParquetStore:
        if self._store is None:
            raise RuntimeError("Final lab candidate store is not open.")
        return self._store


class _FinalPreviousVitalCandidateStore:
    """Patient-bucketed reducer for previous Weight/Height/BMI candidates."""

    def __init__(self, work_dir: Path) -> None:
        self.work_dir = work_dir
        self._store: PartitionedParquetStore | None = None

    def __enter__(self) -> "_FinalPreviousVitalCandidateStore":
        self._store = PartitionedParquetStore(
            self.work_dir,
            prefix=".trinetx-final-prev-vitals-",
            key_columns=["vital_name", "patient_id"],
            bucket_count=FINAL_PREVIOUS_VITAL_BUCKET_COUNT,
            cleanup_context="Final previous vital scratch",
        )
        self._store.__enter__()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._store is not None:
            self._store.__exit__(exc_type, exc, tb)

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
        self._partition_store().add_frame(
            bucketed.loc[:, FINAL_PREVIOUS_VITAL_BUCKET_COLUMNS]
        )

    def reduce(self) -> dict[str, pd.DataFrame]:
        frames_by_name: dict[str, list[pd.DataFrame]] = {}
        for _, frame in self._partition_store().iter_frames(
            columns=FINAL_PREVIOUS_VITAL_BUCKET_COLUMNS
        ):
            frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
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

    def _partition_store(self) -> PartitionedParquetStore:
        if self._store is None:
            raise RuntimeError("Final previous vital store is not open.")
        return self._store


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
        frame = encounters.frame_for_encounter_ids(encounter_ids)
    else:
        frame = encounters
    return frame.loc[:, ["encounter_id", "start_date", "end_date", "LOS"]]


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
        self._lookup = PartitionedKeyLookup(
            work_dir,
            prefix=".trinetx-final-encounters-",
            key_column="encounter_id_key",
            stored_columns=FINAL_ENCOUNTER_BUCKET_COLUMNS,
            bucket_count=FINAL_ENCOUNTER_BUCKET_COUNT,
            require_unique=True,
            cleanup_context="Final encounter lookup scratch",
        )

    def __enter__(self) -> "_EncounterLookup":
        self._lookup.__enter__()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self._lookup.__exit__(exc_type, exc, tb)

    def add_frame(self, frame: pd.DataFrame) -> None:
        if frame.empty:
            return
        require_columns(frame, ENCOUNTER_COLUMNS, context="Encounter subset")
        bucketed = frame.loc[:, ENCOUNTER_COLUMNS].copy()
        bucketed.insert(
            0, "encounter_id_key", _lookup_key_series(frame["encounter_id"])
        )
        try:
            self._lookup.add_frame(bucketed)
        except ValueError as exc:
            raise ValueError(
                "Encounter subset contains duplicate encounter_id values."
            ) from exc

    def finalize(self) -> None:
        try:
            self._lookup.finalize()
        except ValueError as exc:
            raise ValueError(
                "Encounter subset contains duplicate encounter_id values."
            ) from exc

    def frame_for_encounter_ids(self, encounter_ids: pd.Series) -> pd.DataFrame:
        matches = self._lookup.frame_for_keys(_lookup_key_series(encounter_ids))
        if matches.empty:
            return _empty_encounter_frame()
        return matches.loc[:, ENCOUNTER_COLUMNS].reset_index(drop=True)


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


def _load_derived_data_screen_lookup(
    config: Config,
    *,
    work_dir: Path,
    stack: ExitStack,
    logger: logging.Logger,
    chunksize: int | None,
    strict: bool,
) -> "_EncounterIdLookup" | None:
    """Build encounter availability from normalized diagnosis and lab tables."""

    analysis_paths = [
        resolve_work_table(config, "analysis_diagnosis_availability.csv"),
        resolve_work_table(config, "analysis_lab_availability.csv"),
    ]
    if all(path.exists() for path in analysis_paths):
        paths = analysis_paths
    elif any(path.exists() for path in analysis_paths):
        raise FileNotFoundError(
            "Derived data-screen analysis indexes are incomplete; rerun labs and "
            "diagnosis stages."
        )
    else:
        paths = []
        for pattern in ("diagnosis_NEW_*.csv", "lab_results_NEW_*.csv"):
            paths.extend(find_work_tables(config, pattern))
    if not paths:
        message = "Derived data screening requires normalized diagnosis or lab tables."
        if strict:
            raise FileNotFoundError(message)
        logger.warning(message)
        return None

    lookup = stack.enter_context(_EncounterIdLookup(work_dir))
    rows_read = 0
    for frame in iter_work_tables(
        paths,
        chunksize=chunksize,
        usecols=["encounter_id"],
        dtype={"encounter_id": "string"},
    ):
        rows_read += len(frame)
        lookup.add_values(frame["encounter_id"])
    log_row_count(logger, "derived diagnosis-or-lab screen rows", rows_read)
    log_row_count(logger, "derived diagnosis-or-lab screen encounters", lookup.count())
    return lookup


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
        self._lookup = PartitionedKeyLookup(
            work_dir,
            prefix=".trinetx-data-check-ids-",
            key_column="encounter_id_key",
            stored_columns=FINAL_DATA_SCREEN_BUCKET_COLUMNS,
            bucket_count=FINAL_DATA_SCREEN_BUCKET_COUNT,
            cleanup_context="Final data-screen lookup scratch",
        )

    def __enter__(self) -> "_EncounterIdLookup":
        self._lookup.__enter__()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self._lookup.__exit__(exc_type, exc, tb)

    def add_values(self, encounter_ids: pd.Series) -> None:
        values = encounter_ids.dropna().astype("string")
        if values.empty:
            return
        frame = pd.DataFrame(
            {
                "encounter_id_key": _lookup_key_series(values),
                "encounter_id": values.to_numpy(),
            }
        )
        frame = frame.drop_duplicates(subset=["encounter_id_key"], keep="first")
        self._lookup.add_frame(frame)

    def filter_frame(self, df: pd.DataFrame) -> pd.DataFrame:
        if df.empty:
            return df.copy()
        keys = _lookup_key_series(df["encounter_id"])
        allowed_keys = self._lookup.matching_keys(keys)
        if not allowed_keys:
            return df.iloc[0:0].copy()
        return df.loc[keys.isin(allowed_keys)].copy()

    def count(self) -> int:
        return self._lookup.unique_count()


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

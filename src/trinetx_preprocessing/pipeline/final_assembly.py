"""Final dataset assembly stage built from legacy notebook logic."""

from __future__ import annotations

import json
import logging
from collections.abc import Collection, Iterable
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
from ..transform.rfs import RFS_CATEGORIES, RFS_EVENT_COLUMNS
from ..validation import require_columns
from . import final_features as _final_features
from .cohort import (
    BASE_FINAL_OUTPUT_COLUMNS,
    DEMOGRAPHIC_OUTPUT_COLUMNS,
    ENCOUNTER_COLUMNS,
    FINAL_EVENT_CANDIDATE_COLUMNS,
    QUALIFY_DATE_MAX,
    QUALIFY_DATE_MIN,
    prepare_event_candidates,
    reduce_setting_cohort_rows,
    select_setting_cohort,
)
from .final_feature_sources import FinalFeatureSourceStore
from .final_output_schema import FINAL_OUTPUT_COLUMNS

DIAGNOSIS_COLUMNS = _final_features.DIAGNOSIS_COLUMNS
LAB_COLUMNS = _final_features.LAB_COLUMNS
LAB_VALUE_RULES = _final_features.LAB_VALUE_RULES
MEDICATION_COLUMNS = _final_features.MEDICATION_COLUMNS
PROCEDURE_CODE_GROUPS = _final_features.PROCEDURE_CODE_GROUPS
PROCEDURE_COLUMNS = _final_features.PROCEDURE_COLUMNS
VITALS_COLUMNS = _final_features.VITALS_COLUMNS

_FinalLabCandidateStore = _final_features._FinalLabCandidateStore
_FinalPreviousVitalCandidateStore = _final_features._FinalPreviousVitalCandidateStore
_enrich_legacy_final_features = _final_features._enrich_legacy_final_features
_legacy_lab_feature_values = _final_features._legacy_lab_feature_values
_merge_encounter_first_last_features = (
    _final_features._merge_encounter_first_last_features
)
_merge_lab_value_features = _final_features._merge_lab_value_features
_merge_medication_features = _final_features._merge_medication_features
_merge_prior_diagnosis_features = _final_features._merge_prior_diagnosis_features
_recode_legacy_base_columns = _final_features._recode_legacy_base_columns
_select_current_diagnosis = _final_features._select_current_diagnosis
_select_ip_medication = _final_features._select_ip_medication

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
FINAL_EVENT_REDUCED_BATCH_ROWS = 1_000_000
FINAL_EVENT_BUCKET_COLUMNS = [*FINAL_EVENT_CANDIDATE_COLUMNS, "_row_order"]
FINAL_DATA_SCREEN_ELIGIBLE_COLUMN = "_data_screen_eligible"


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
            event_candidate_frames = _iter_final_event_candidate_frames(
                config,
                category,
                demographics,
                logger,
                chunksize=chunksize,
                guardrails=config.guardrails,
                strict=strict,
            )
            for event_candidates in event_candidate_frames:
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
                    base = _mark_data_screen_eligibility(
                        base,
                        inputs.allowed_encounter_ids,
                    )
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
                base = reduce_setting_cohort_rows(
                    group.drop(columns=["_category", "_setting"])
                )
                enriched = _enrich_legacy_final_features(
                    base,
                    config=config,
                    chunksize=chunksize,
                    logger=logger,
                    source_bucket=source_bucket,
                )
                before, eligibility = _finalize_output_with_data_screen(enriched)
                _append_final_rows(
                    output_paths[(str(setting), str(category), "BEFORE")],
                    before,
                )
                rows_written[(str(setting), str(category), "BEFORE")] += len(before)

                after = _apply_precomputed_data_screen(
                    before,
                    eligibility,
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


def _mark_data_screen_eligibility(
    frame: pd.DataFrame,
    allowed_encounter_ids: Collection[str] | "_EncounterIdLookup" | None,
) -> pd.DataFrame:
    """Attach reusable encounter-screen eligibility before patient partitioning."""

    marked = frame.copy()
    if allowed_encounter_ids is None:
        marked[FINAL_DATA_SCREEN_ELIGIBLE_COLUMN] = True
        return marked

    if isinstance(allowed_encounter_ids, _EncounterIdLookup):
        probe = pd.DataFrame(
            {"encounter_id": marked["encounter_id"].astype("string").to_numpy()}
        )
        eligible = allowed_encounter_ids.filter_frame(probe)
        mask = pd.Series(False, index=probe.index, dtype="boolean")
        mask.loc[eligible.index] = True
        marked[FINAL_DATA_SCREEN_ELIGIBLE_COLUMN] = mask.to_numpy(dtype=bool)
        return marked

    marked[FINAL_DATA_SCREEN_ELIGIBLE_COLUMN] = (
        marked["encounter_id"].astype("string").isin(allowed_encounter_ids).to_numpy()
    )
    return marked


def _apply_precomputed_data_screen(
    frame: pd.DataFrame,
    eligibility: pd.Series,
    *,
    context: str,
    logger: logging.Logger,
) -> pd.DataFrame:
    """Filter an enriched bucket with eligibility computed before bucketing."""

    if len(frame) != len(eligibility):
        raise ValueError(
            "Precomputed data-screen eligibility length does not match final rows."
        )
    mask = eligibility.fillna(False).astype(bool).to_numpy()
    filtered = frame.loc[mask].copy().reset_index(drop=True)
    log_row_count(logger, f"final {context} post-filter data checks", len(filtered))
    return filtered


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
    frames = list(
        _iter_final_event_candidate_frames(
            config,
            category,
            demographics,
            logger,
            chunksize=chunksize,
            guardrails=guardrails,
            strict=strict,
        )
    )
    if not frames:
        return pd.DataFrame(columns=FINAL_EVENT_CANDIDATE_COLUMNS)
    return pd.concat(frames, ignore_index=True)


def _iter_final_event_candidate_frames(
    config: Config,
    category: str,
    demographics: "_DemographicsLookup",
    logger: logging.Logger,
    *,
    chunksize: int | None,
    guardrails: GuardrailConfig,
    strict: bool,
) -> Iterable[pd.DataFrame]:
    """Yield encounter-reduced event partitions without a full-category concat."""

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
        candidate_count = 0
        reduced_frames = store.iter_reduced()
        for candidates in _batch_final_event_candidate_frames(
            reduced_frames,
            max_rows=FINAL_EVENT_REDUCED_BATCH_ROWS,
        ):
            candidate_count += len(candidates)
            yield candidates
        log_row_count(logger, f"final {category} event candidates", candidate_count)


def _batch_final_event_candidate_frames(
    frames: Iterable[pd.DataFrame],
    *,
    max_rows: int,
) -> Iterable[pd.DataFrame]:
    """Combine small reduced partitions into bounded setting-join batches."""

    if max_rows <= 0:
        raise ValueError("max_rows must be positive.")
    pending: list[pd.DataFrame] = []
    pending_rows = 0
    for frame in frames:
        if frame.empty:
            continue
        if pending and pending_rows + len(frame) > max_rows:
            yield pd.concat(pending, ignore_index=True)
            pending = []
            pending_rows = 0
        pending.append(frame)
        pending_rows += len(frame)
    if pending:
        yield pd.concat(pending, ignore_index=True)


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
        frames = list(self.iter_reduced())
        if not frames:
            return pd.DataFrame(columns=FINAL_EVENT_CANDIDATE_COLUMNS)
        return pd.concat(frames, ignore_index=True)

    def iter_reduced(self) -> Iterable[pd.DataFrame]:
        """Yield one encounter-reduced partition at a time."""

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
                yield unique

    def _partition_store(self) -> PartitionedParquetStore:
        if self._store is None:
            raise RuntimeError("Final event candidate store is not open.")
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


def _finalize_output_with_data_screen(
    df: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.Series]:
    """Finalize rows and keep precomputed screening aligned to final order."""

    if FINAL_DATA_SCREEN_ELIGIBLE_COLUMN not in df:
        raise ValueError("Final rows are missing precomputed data-screen eligibility.")
    ordered = df.sort_values(
        by=["patient_id", "encounter_id"],
        kind="mergesort",
    ).reset_index(drop=True)
    eligibility = ordered.pop(FINAL_DATA_SCREEN_ELIGIBLE_COLUMN).reset_index(drop=True)
    return _finalize_output(ordered), eligibility


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

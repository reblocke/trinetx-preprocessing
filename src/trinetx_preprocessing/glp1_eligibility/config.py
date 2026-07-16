"""Typed configuration for the GLP-1 eligibility build."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import yaml


class GLP1ConfigError(ValueError):
    """Raised when the GLP-1 configuration is invalid."""


FIXED_PCO2_SENSITIVITY_THRESHOLDS = (50.0, 52.0)
FIXED_OBESITY_THRESHOLDS = (27.0, 30.0, 35.0, 40.0)


@dataclass(frozen=True)
class StudyConfig:
    """Study dates, encounter scope, and temporal windows."""

    study_start: date | None
    study_end: date | None
    index_encounter_types: tuple[str, ...]
    adult_age_min: int
    lookback_days: int
    measurement_lookback_days: int
    medication_lookback_days: int
    followup_days: int


@dataclass(frozen=True)
class HypercapniaConfig:
    """Blood-gas cohort thresholds and pairing behavior."""

    index_window_hours: int
    pco2_gt_mm_hg: float
    pco2_sensitivity_thresholds_mm_hg: tuple[float, ...]
    pco2_plausible_min_mm_hg: float
    pco2_plausible_max_mm_hg: float
    ph_max: float
    ph_plausible_min: float
    ph_plausible_max: float
    hco3_plausible_min_mmol_l: float
    hco3_plausible_max_mmol_l: float
    po2_plausible_min_mm_hg: float
    po2_plausible_max_mm_hg: float
    sao2_plausible_min_percent: float
    sao2_plausible_max_percent: float
    acute_acidemia_ph_lt: float
    repeat_window_days: tuple[int, int]
    pair_tolerance_minutes: int
    allow_date_only_pairing: bool
    primary_requires_arterial_specimen: bool
    include_vbg_secondary_cohort: bool


@dataclass(frozen=True)
class ObesityConfig:
    """BMI lookback and threshold configuration."""

    bmi_pre_index_days: int
    same_encounter_fallback: bool
    thresholds: tuple[float, ...]
    bmi_min_kg_m2: float
    bmi_max_kg_m2: float
    weight_min_kg: float
    weight_max_kg: float
    height_min_m: float
    height_max_m: float


@dataclass(frozen=True)
class OutputConfig:
    """Output file configuration."""

    database_name: str
    write_parquet: bool
    write_html_qa: bool


@dataclass(frozen=True)
class ExclusionConfig:
    """Documented context flags excluded from the cleaned analysis view."""

    cleaned_view_excludes: tuple[str, ...]


@dataclass(frozen=True)
class RuntimeConfig:
    """Bounded DuckDB execution settings."""

    duckdb_memory_limit_mib: int = 4096
    duckdb_threads: int = 1


@dataclass(frozen=True)
class GLP1Config:
    """Validated top-level GLP-1 eligibility configuration."""

    schema_version: str
    rule_set_version: str
    labels_as_of: date
    payer_policy_as_of: date
    study: StudyConfig
    hypercapnia: HypercapniaConfig
    obesity: ObesityConfig
    exclusions: ExclusionConfig
    output: OutputConfig
    runtime: RuntimeConfig
    concept_sets_dir: Path
    source_path: Path
    sha256: str


def load_glp1_config(path: Path) -> GLP1Config:
    """Load and validate one GLP-1 eligibility YAML configuration."""

    config_path = Path(path).resolve()
    if not config_path.is_file():
        raise FileNotFoundError(f"GLP-1 config file not found: {config_path}")

    raw_bytes = config_path.read_bytes()
    raw = yaml.safe_load(raw_bytes)
    if not isinstance(raw, dict):
        raise GLP1ConfigError("GLP-1 config must contain a top-level YAML mapping.")

    _reject_unknown_keys(
        raw,
        {
            "schema_version",
            "rule_set_version",
            "labels_as_of",
            "payer_policy_as_of",
            "concept_sets_dir",
            "study",
            "hypercapnia",
            "obesity",
            "exclusions",
            "output",
            "runtime",
        },
        context="config",
    )
    schema_version = _required_text(raw, "schema_version")
    if schema_version != "1.0":
        raise GLP1ConfigError(
            f"Unsupported GLP-1 schema_version {schema_version!r}; expected '1.0'."
        )

    study = _load_study(_required_mapping(raw, "study"))
    hypercapnia = _load_hypercapnia(_required_mapping(raw, "hypercapnia"))
    obesity = _load_obesity(_required_mapping(raw, "obesity"))
    exclusions = _load_exclusions(_required_mapping(raw, "exclusions"))
    output = _load_output(_required_mapping(raw, "output"))
    runtime = _load_runtime(raw.get("runtime", {}))

    if study.study_start and study.study_end and study.study_start > study.study_end:
        raise GLP1ConfigError("study_start must be on or before study_end.")
    if hypercapnia.ph_max <= hypercapnia.acute_acidemia_ph_lt:
        raise GLP1ConfigError("ph_max must be greater than acute_acidemia_ph_lt.")
    if any(
        threshold <= hypercapnia.pco2_gt_mm_hg
        for threshold in hypercapnia.pco2_sensitivity_thresholds_mm_hg
    ):
        raise GLP1ConfigError(
            "Every PCO2 sensitivity threshold must exceed pco2_gt_mm_hg."
        )
    if (
        hypercapnia.pco2_sensitivity_thresholds_mm_hg
        != FIXED_PCO2_SENSITIVITY_THRESHOLDS
    ):
        raise GLP1ConfigError(
            "hypercapnia.pco2_sensitivity_thresholds_mm_hg must be [50, 52] "
            "because the published columns are fixed as hypercapnia_ge50 and "
            "hypercapnia_ge52."
        )
    if not hypercapnia.primary_requires_arterial_specimen:
        raise GLP1ConfigError(
            "hypercapnia.primary_requires_arterial_specimen must be true for "
            "the fixed primary endpoint contract."
        )
    if obesity.thresholds != FIXED_OBESITY_THRESHOLDS:
        raise GLP1ConfigError(
            "obesity.thresholds must be [27, 30, 35, 40] because the published "
            "BMI threshold columns are fixed."
        )

    concept_sets_dir = Path(raw.get("concept_sets_dir", "concept_sets"))
    if not concept_sets_dir.is_absolute():
        concept_sets_dir = (config_path.parent / concept_sets_dir).resolve()

    return GLP1Config(
        schema_version=schema_version,
        rule_set_version=_required_text(raw, "rule_set_version"),
        labels_as_of=_required_date(raw, "labels_as_of"),
        payer_policy_as_of=_required_date(raw, "payer_policy_as_of"),
        study=study,
        hypercapnia=hypercapnia,
        obesity=obesity,
        exclusions=exclusions,
        output=output,
        runtime=runtime,
        concept_sets_dir=concept_sets_dir,
        source_path=config_path,
        sha256=hashlib.sha256(raw_bytes).hexdigest(),
    )


def _load_study(raw: dict[str, Any]) -> StudyConfig:
    allowed = {
        "study_start",
        "study_end",
        "index_encounter_types",
        "adult_age_min",
        "lookback_days",
        "measurement_lookback_days",
        "medication_lookback_days",
        "followup_days",
    }
    _reject_unknown_keys(raw, allowed, context="study")
    encounter_types = tuple(
        str(value).strip().upper()
        for value in _required_list(raw, "index_encounter_types")
    )
    if not encounter_types or any(not value for value in encounter_types):
        raise GLP1ConfigError("study.index_encounter_types must not be empty.")
    return StudyConfig(
        study_start=_optional_date(raw, "study_start"),
        study_end=_optional_date(raw, "study_end"),
        index_encounter_types=encounter_types,
        adult_age_min=_positive_int(raw, "adult_age_min"),
        lookback_days=_nonnegative_int(raw, "lookback_days"),
        measurement_lookback_days=_nonnegative_int(
            raw, "measurement_lookback_days"
        ),
        medication_lookback_days=_nonnegative_int(raw, "medication_lookback_days"),
        followup_days=_nonnegative_int(raw, "followup_days"),
    )


def _load_hypercapnia(raw: dict[str, Any]) -> HypercapniaConfig:
    allowed = {
        "index_window_hours",
        "pco2_gt_mm_hg",
        "pco2_sensitivity_thresholds_mm_hg",
        "pco2_plausible_min_mm_hg",
        "pco2_plausible_max_mm_hg",
        "ph_max",
        "ph_plausible_min",
        "ph_plausible_max",
        "hco3_plausible_min_mmol_l",
        "hco3_plausible_max_mmol_l",
        "po2_plausible_min_mm_hg",
        "po2_plausible_max_mm_hg",
        "sao2_plausible_min_percent",
        "sao2_plausible_max_percent",
        "acute_acidemia_ph_lt",
        "repeat_window_days",
        "pair_tolerance_minutes",
        "allow_date_only_pairing",
        "primary_requires_arterial_specimen",
        "include_vbg_secondary_cohort",
    }
    _reject_unknown_keys(raw, allowed, context="hypercapnia")
    sensitivity = tuple(
        sorted(
            {
                _positive_float_value(value, "pco2_sensitivity_thresholds_mm_hg")
                for value in _required_list(
                    raw, "pco2_sensitivity_thresholds_mm_hg"
                )
            }
        )
    )
    repeat_window = tuple(
        _nonnegative_int_value(value, "repeat_window_days")
        for value in _required_list(raw, "repeat_window_days")
    )
    if len(repeat_window) != 2 or repeat_window[0] > repeat_window[1]:
        raise GLP1ConfigError(
            "hypercapnia.repeat_window_days must be [minimum, maximum]."
        )
    pco2_plausible_min = _positive_float(raw, "pco2_plausible_min_mm_hg")
    pco2_plausible_max = _positive_float(raw, "pco2_plausible_max_mm_hg")
    ph_plausible_min = _positive_float(raw, "ph_plausible_min")
    ph_plausible_max = _positive_float(raw, "ph_plausible_max")
    hco3_plausible_min = _positive_float(raw, "hco3_plausible_min_mmol_l")
    hco3_plausible_max = _positive_float(raw, "hco3_plausible_max_mmol_l")
    po2_plausible_min = _positive_float(raw, "po2_plausible_min_mm_hg")
    po2_plausible_max = _positive_float(raw, "po2_plausible_max_mm_hg")
    sao2_plausible_min = _positive_float(raw, "sao2_plausible_min_percent")
    sao2_plausible_max = _positive_float(raw, "sao2_plausible_max_percent")
    if pco2_plausible_min >= pco2_plausible_max:
        raise GLP1ConfigError("PCO2 plausible minimum must be below maximum.")
    if ph_plausible_min >= ph_plausible_max:
        raise GLP1ConfigError("pH plausible minimum must be below maximum.")
    for label, minimum, maximum in (
        ("HCO3", hco3_plausible_min, hco3_plausible_max),
        ("PO2", po2_plausible_min, po2_plausible_max),
        ("SaO2", sao2_plausible_min, sao2_plausible_max),
    ):
        if minimum >= maximum:
            raise GLP1ConfigError(
                f"{label} plausible minimum must be below maximum."
            )
    return HypercapniaConfig(
        index_window_hours=_positive_int(raw, "index_window_hours"),
        pco2_gt_mm_hg=_positive_float(raw, "pco2_gt_mm_hg"),
        pco2_sensitivity_thresholds_mm_hg=sensitivity,
        pco2_plausible_min_mm_hg=pco2_plausible_min,
        pco2_plausible_max_mm_hg=pco2_plausible_max,
        ph_max=_positive_float(raw, "ph_max"),
        ph_plausible_min=ph_plausible_min,
        ph_plausible_max=ph_plausible_max,
        hco3_plausible_min_mmol_l=hco3_plausible_min,
        hco3_plausible_max_mmol_l=hco3_plausible_max,
        po2_plausible_min_mm_hg=po2_plausible_min,
        po2_plausible_max_mm_hg=po2_plausible_max,
        sao2_plausible_min_percent=sao2_plausible_min,
        sao2_plausible_max_percent=sao2_plausible_max,
        acute_acidemia_ph_lt=_positive_float(raw, "acute_acidemia_ph_lt"),
        repeat_window_days=(repeat_window[0], repeat_window[1]),
        pair_tolerance_minutes=_nonnegative_int(raw, "pair_tolerance_minutes"),
        allow_date_only_pairing=_required_bool(raw, "allow_date_only_pairing"),
        primary_requires_arterial_specimen=_required_bool(
            raw, "primary_requires_arterial_specimen"
        ),
        include_vbg_secondary_cohort=_required_bool(
            raw, "include_vbg_secondary_cohort"
        ),
    )


def _load_obesity(raw: dict[str, Any]) -> ObesityConfig:
    allowed = {
        "bmi_pre_index_days",
        "same_encounter_fallback",
        "thresholds",
        "bmi_min_kg_m2",
        "bmi_max_kg_m2",
        "weight_min_kg",
        "weight_max_kg",
        "height_min_m",
        "height_max_m",
    }
    _reject_unknown_keys(raw, allowed, context="obesity")
    thresholds = tuple(
        sorted(
            {
                _positive_float_value(value, "obesity.thresholds")
                for value in _required_list(raw, "thresholds")
            }
        )
    )
    if not thresholds:
        raise GLP1ConfigError("obesity.thresholds must not be empty.")
    bmi_min = _positive_float(raw, "bmi_min_kg_m2")
    bmi_max = _positive_float(raw, "bmi_max_kg_m2")
    weight_min = _positive_float(raw, "weight_min_kg")
    weight_max = _positive_float(raw, "weight_max_kg")
    height_min = _positive_float(raw, "height_min_m")
    height_max = _positive_float(raw, "height_max_m")
    if bmi_min >= bmi_max:
        raise GLP1ConfigError("BMI plausible minimum must be below maximum.")
    if weight_min >= weight_max:
        raise GLP1ConfigError("Weight plausible minimum must be below maximum.")
    if height_min >= height_max:
        raise GLP1ConfigError("Height plausible minimum must be below maximum.")
    return ObesityConfig(
        bmi_pre_index_days=_nonnegative_int(raw, "bmi_pre_index_days"),
        same_encounter_fallback=_required_bool(raw, "same_encounter_fallback"),
        thresholds=thresholds,
        bmi_min_kg_m2=bmi_min,
        bmi_max_kg_m2=bmi_max,
        weight_min_kg=weight_min,
        weight_max_kg=weight_max,
        height_min_m=height_min,
        height_max_m=height_max,
    )


def _load_output(raw: dict[str, Any]) -> OutputConfig:
    allowed = {"database_name", "write_parquet", "write_html_qa"}
    _reject_unknown_keys(raw, allowed, context="output")
    database_name = _required_text(raw, "database_name")
    if Path(database_name).name != database_name or not database_name.endswith(
        ".duckdb"
    ):
        raise GLP1ConfigError(
            "output.database_name must be a .duckdb filename without directories."
        )
    return OutputConfig(
        database_name=database_name,
        write_parquet=_required_bool(raw, "write_parquet"),
        write_html_qa=_required_bool(raw, "write_html_qa"),
    )


def _load_exclusions(raw: dict[str, Any]) -> ExclusionConfig:
    allowed = {"cleaned_view_excludes"}
    _reject_unknown_keys(raw, allowed, context="exclusions")
    known_flags = {
        "cardiac_arrest_context",
        "major_trauma_context",
        "procedure_sedation_context",
        "postoperative_context",
        "implausible_value",
        "probable_venous_specimen",
    }
    configured = tuple(
        str(value).strip() for value in _required_list(raw, "cleaned_view_excludes")
    )
    if len(configured) != len(set(configured)):
        raise GLP1ConfigError(
            "exclusions.cleaned_view_excludes may not contain duplicates."
        )
    unknown = sorted(set(configured) - known_flags)
    if unknown:
        raise GLP1ConfigError(
            "Unknown cleaned-view exclusion flag(s): " + ", ".join(unknown) + "."
        )
    return ExclusionConfig(cleaned_view_excludes=configured)


def _load_runtime(raw: Any) -> RuntimeConfig:
    if not isinstance(raw, dict):
        raise GLP1ConfigError("runtime must be a YAML mapping.")
    allowed = {"duckdb_memory_limit_mib", "duckdb_threads"}
    _reject_unknown_keys(raw, allowed, context="runtime")
    return RuntimeConfig(
        duckdb_memory_limit_mib=(
            _positive_int(raw, "duckdb_memory_limit_mib")
            if "duckdb_memory_limit_mib" in raw
            else 4096
        ),
        duckdb_threads=(
            _positive_int(raw, "duckdb_threads")
            if "duckdb_threads" in raw
            else 1
        ),
    )


def _required_mapping(raw: dict[str, Any], key: str) -> dict[str, Any]:
    value = raw.get(key)
    if not isinstance(value, dict):
        raise GLP1ConfigError(f"{key} must be a YAML mapping.")
    return value


def _required_list(raw: dict[str, Any], key: str) -> list[Any]:
    value = raw.get(key)
    if not isinstance(value, list):
        raise GLP1ConfigError(f"{key} must be a YAML list.")
    return value


def _required_text(raw: dict[str, Any], key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise GLP1ConfigError(f"{key} must be a non-empty string.")
    return value.strip()


def _required_bool(raw: dict[str, Any], key: str) -> bool:
    value = raw.get(key)
    if not isinstance(value, bool):
        raise GLP1ConfigError(f"{key} must be true or false.")
    return value


def _required_date(raw: dict[str, Any], key: str) -> date:
    value = _optional_date(raw, key)
    if value is None:
        raise GLP1ConfigError(f"{key} must be an ISO date.")
    return value


def _optional_date(raw: dict[str, Any], key: str) -> date | None:
    value = raw.get(key)
    if value is None:
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise GLP1ConfigError(f"{key} must be an ISO date or null.") from exc


def _positive_int(raw: dict[str, Any], key: str) -> int:
    value = _nonnegative_int(raw, key)
    if value == 0:
        raise GLP1ConfigError(f"{key} must be greater than zero.")
    return value


def _nonnegative_int(raw: dict[str, Any], key: str) -> int:
    if key not in raw:
        raise GLP1ConfigError(f"Missing required value: {key}.")
    return _nonnegative_int_value(raw[key], key)


def _nonnegative_int_value(value: Any, key: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise GLP1ConfigError(f"{key} must be a nonnegative integer.")
    return value


def _positive_float(raw: dict[str, Any], key: str) -> float:
    if key not in raw:
        raise GLP1ConfigError(f"Missing required value: {key}.")
    return _positive_float_value(raw[key], key)


def _positive_float_value(value: Any, key: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise GLP1ConfigError(f"{key} must be numeric.")
    numeric = float(value)
    if numeric <= 0:
        raise GLP1ConfigError(f"{key} must be greater than zero.")
    return numeric


def _reject_unknown_keys(
    raw: dict[str, Any], allowed: set[str], *, context: str
) -> None:
    unknown = sorted(set(raw) - allowed)
    if unknown:
        raise GLP1ConfigError(
            f"Unknown {context} configuration key(s): {', '.join(unknown)}."
        )

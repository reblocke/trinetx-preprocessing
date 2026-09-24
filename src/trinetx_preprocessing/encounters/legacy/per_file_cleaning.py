"""Behavioral-parity port of the frozen Stata ``cleandata`` program."""

from __future__ import annotations

import hashlib
import json
import math
import warnings
from dataclasses import dataclass, field
from enum import StrEnum
from numbers import Real
from typing import Literal

import numpy as np
import pandas as pd

from trinetx_preprocessing.encounters.legacy.raw_schema import (
    EXPECTED_COLUMN_COUNT,
    RawSchema,
)
from trinetx_preprocessing.encounters.legacy.stata_compat import (
    RecodeRule,
    first_after,
    is_regular_missing,
    stata_concat,
    stata_date,
    stata_ge,
    stata_month_index_from_daily,
    stata_recode,
    stata_round,
    stata_row_max,
    stata_row_mean,
    stata_row_min,
    stata_ym,
)

FROZEN_SOURCE_SHA256 = (
    "2e45b83f499bd4d7ee319165d74ab5cb0a8f2f9214930ea22312e61df56f8c39"
)
IMPLEMENTED_SOURCE_LINES = (367, 638)
UNPORTED_SOURCE_LINES = (640, 3308)
COMPLETE_SOURCE_LINES = (367, 3305)
DEFERRED_IO_SOURCE_LINES = (3306, 3308)
EXPECTED_MANIFEST_SHA256 = (
    "1d8e6720be7faa289b3007a3e28515604d6faf5ae4ac59dd6c86679c2540f174"
)
EXPECTED_RAW_HEADER_SHA256 = (
    "5960e248da63d5464fbf1feaf0e20f6b2dd2b968775d5e94c36e9a401d569375"
)
EXPECTED_SCHEMA_CONTRACT_SHA256 = (
    "cf2131e021852637a78e61f49a3b196730b9555814df270e1a6643000c38c07c"
)

_SETTING_CODES = {
    "AMBULATORY": "AMB",
    "EMERGENCY": "EMER",
    "INPATIENT": "INPAT",
}
_RAW_SUFFIXES = frozenset({"BEFORE", "AFTER"})


class RfsFamily(StrEnum):
    """Exact reason-for-suspicion values used by the frozen call sites."""

    ABG = "ABG"
    OBESITY = "OBESITY"
    PREDISPOSITION = "PREDISPOSITION"
    RESPFAIL = "RESPFAIL"
    VBG = "VBG"
    VENTSUPPORT = "VENTSUPPORT"


class PerFileCleaningError(ValueError):
    """Raised when a per-file input cannot be interpreted unambiguously."""


class PerFileCleaningIncompleteError(RuntimeError):
    """Retained for compatibility with the earlier fail-closed checkpoint."""


@dataclass(frozen=True, slots=True)
class PerFileContext:
    """One exact frozen ``cleandata`` call site."""

    setting: str
    setting_code: str
    raw_suffix: str
    family: RfsFamily = RfsFamily.ABG

    @classmethod
    def create(
        cls,
        *,
        setting: str,
        raw_suffix: str,
        family: RfsFamily = RfsFamily.ABG,
    ) -> PerFileContext:
        if setting not in _SETTING_CODES:
            expected = ", ".join(_SETTING_CODES)
            raise PerFileCleaningError(f"setting must be exactly one of: {expected}")
        if raw_suffix not in _RAW_SUFFIXES:
            expected = ", ".join(sorted(_RAW_SUFFIXES))
            raise PerFileCleaningError(f"raw_suffix must be exactly one of: {expected}")
        if not isinstance(family, RfsFamily):
            raise PerFileCleaningError("family must be an RfsFamily")
        return cls(
            setting=setting,
            setting_code=_SETTING_CODES[setting],
            raw_suffix=raw_suffix,
            family=family,
        )

    @property
    def reason_for_suspicion(self) -> str:
        return self.family.value


# Backward-compatible name for the already published ABG-only API.
AbgFileContext = PerFileContext


@dataclass(slots=True)
class CleaningMetadata:
    """Stata metadata established by the translated commands."""

    variable_labels: dict[str, str] = field(default_factory=dict)
    value_label_definitions: dict[str, dict[int, str]] = field(default_factory=dict)
    variable_value_labels: dict[str, str] = field(default_factory=dict)
    display_formats: dict[str, str] = field(default_factory=dict)
    storage_types: dict[
        str, Literal["byte", "int", "long", "float", "double", "string"]
    ] = field(default_factory=dict)
    string_widths: dict[str, int] = field(default_factory=dict)
    sort_variables: tuple[str, ...] = ()
    characteristics: tuple[tuple[str, str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class PartialPerFileCleaningResult:
    """A partial result that cannot be mistaken for a certified final dataset."""

    frame: pd.DataFrame
    metadata: CleaningMetadata
    context: PerFileContext
    source_sha256: str = FROZEN_SOURCE_SHA256
    implemented_source_lines: tuple[int, int] = IMPLEMENTED_SOURCE_LINES
    unported_source_lines: tuple[int, int] = UNPORTED_SOURCE_LINES
    complete: bool = False


@dataclass(frozen=True, slots=True)
class CompletePerFileCleaningResult:
    """Complete in-memory ABG transformation through frozen source line 3305."""

    frame: pd.DataFrame
    metadata: CleaningMetadata
    context: PerFileContext
    source_sha256: str = FROZEN_SOURCE_SHA256
    implemented_source_lines: tuple[int, int] = COMPLETE_SOURCE_LINES
    deferred_io_source_lines: tuple[int, int] = DEFERRED_IO_SOURCE_LINES
    complete: bool = True


@dataclass(slots=True)
class _CleaningState:
    frame: pd.DataFrame
    metadata: CleaningMetadata = field(default_factory=CleaningMetadata)

    def _require(self, name: str) -> pd.Series:
        if name not in self.frame.columns:
            raise PerFileCleaningError(f"required Stata variable is absent: {name}")
        return self.frame[name]

    def generate_float(self, name: str, values: object) -> None:
        if name in self.frame.columns:
            raise PerFileCleaningError(
                f"generated Stata variable already exists: {name}"
            )
        try:
            series = pd.Series(values, index=self.frame.index, dtype=np.float32)
        except (TypeError, ValueError) as exc:
            raise PerFileCleaningError(
                f"could not generate Stata float variable: {name}"
            ) from exc
        with warnings.catch_warnings():
            # Command-order fidelity deliberately appends one Stata variable
            # at a time; pandas otherwise emits a nonfunctional fragmentation
            # warning for this small certified fixture.
            warnings.simplefilter("ignore", pd.errors.PerformanceWarning)
            self.frame[name] = series
        self.metadata.display_formats[name] = "%9.0g"

    def generate_string(self, name: str, values: object) -> None:
        if name in self.frame.columns:
            raise PerFileCleaningError(
                f"generated Stata variable already exists: {name}"
            )
        series = pd.Series(values, index=self.frame.index, dtype=object)
        if not series.map(lambda value: isinstance(value, str)).all():
            raise PerFileCleaningError(
                f"could not generate Stata string variable: {name}"
            )
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", pd.errors.PerformanceWarning)
            self.frame[name] = series
        width = max(
            1,
            max((len(value.encode("utf-8")) for value in series), default=0),
        )
        self.metadata.display_formats[name] = f"%{max(9, width)}s"

    def drop(self, *names: str) -> None:
        for name in names:
            self._require(name)
        self.frame.drop(columns=list(names), inplace=True)
        for name in names:
            self.metadata.variable_labels.pop(name, None)
            self.metadata.variable_value_labels.pop(name, None)
            self.metadata.display_formats.pop(name, None)
            self.metadata.storage_types.pop(name, None)
            self.metadata.string_widths.pop(name, None)

    def rename(self, old: str, new: str) -> None:
        self._require(old)
        if new in self.frame.columns:
            raise PerFileCleaningError(f"renamed Stata variable already exists: {new}")
        self.frame.rename(columns={old: new}, inplace=True)
        for mapping in (
            self.metadata.variable_labels,
            self.metadata.variable_value_labels,
            self.metadata.display_formats,
            self.metadata.storage_types,
            self.metadata.string_widths,
        ):
            if old in mapping:
                mapping[new] = mapping.pop(old)

    def recode_to_missing(
        self,
        name: str,
        *,
        at_or_below: float,
        at_or_above: float,
    ) -> None:
        series = self._require(name)
        observed = series.notna()
        mask = observed & ((series <= at_or_below) | (series >= at_or_above))
        self.frame.loc[mask, name] = math.nan

    def label(self, name: str, label: str) -> None:
        self._require(name)
        self.metadata.variable_labels[name] = label[:80]

    def define_value_label(self, name: str, values: dict[int, str]) -> None:
        if name in self.metadata.value_label_definitions:
            raise PerFileCleaningError(f"Stata value label already exists: {name}")
        self.metadata.value_label_definitions[name] = dict(values)

    def bind_value_label(self, variable: str, value_label: str) -> None:
        self._require(variable)
        if value_label not in self.metadata.value_label_definitions:
            raise PerFileCleaningError(f"undefined Stata value label: {value_label}")
        self.metadata.variable_value_labels[variable] = value_label
        width = max(
            9,
            *(
                len(label)
                for label in self.metadata.value_label_definitions[value_label].values()
            ),
        )
        self.metadata.display_formats[variable] = f"%{width}.0g"

    def format(self, name: str, display_format: str) -> None:
        self._require(name)
        self.metadata.display_formats[name] = display_format


def _validate_schema(schema: RawSchema) -> None:
    if schema.manifest_sha256 != EXPECTED_MANIFEST_SHA256:
        raise PerFileCleaningError("raw schema has the wrong manifest identity")
    if schema.raw_header_sha256 != EXPECTED_RAW_HEADER_SHA256:
        raise PerFileCleaningError("raw schema has the wrong header identity")
    if len(schema.columns) != EXPECTED_COLUMN_COUNT:
        raise PerFileCleaningError("raw schema must contain exactly 534 columns")
    if [column.position for column in schema.columns] != list(
        range(1, EXPECTED_COLUMN_COUNT + 1)
    ):
        raise PerFileCleaningError("raw schema positions are not exact and contiguous")
    raw_names = [column.raw_name for column in schema.columns]
    stata_names = [column.stata_name for column in schema.columns]
    if len(set(raw_names)) != EXPECTED_COLUMN_COUNT:
        raise PerFileCleaningError("raw schema contains duplicate raw names")
    if len(set(stata_names)) != EXPECTED_COLUMN_COUNT:
        raise PerFileCleaningError("raw schema contains duplicate Stata names")
    if any(
        column.expected_import_class not in {"numeric", "string"}
        for column in schema.columns
    ):
        raise PerFileCleaningError("raw schema contains an unsupported import class")
    if schema.source_tolerated_absent != ("date_i50",):
        raise PerFileCleaningError("raw schema optional-column contract changed")
    payload = {
        "columns": [
            {
                "expected_import_class": column.expected_import_class,
                "fixture_encoding": column.fixture_encoding,
                "position": column.position,
                "raw_name": column.raw_name,
                "source_status": column.source_status,
                "stata_name": column.stata_name,
            }
            for column in schema.columns
        ],
        "source_tolerated_absent": list(schema.source_tolerated_absent),
    }
    contract_sha256 = hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    if contract_sha256 != EXPECTED_SCHEMA_CONTRACT_SHA256:
        raise PerFileCleaningError("raw schema column contract changed")


def _normalize_string_value(value: object, *, column: str, row: int) -> str:
    if value is None or value is pd.NA:
        return ""
    if isinstance(value, Real) and not isinstance(value, (bool, np.bool_)):
        if math.isnan(float(value)):
            return ""
    if not isinstance(value, str):
        raise PerFileCleaningError(
            f"string column {column} has a non-string value at row {row}"
        )
    return value


def _normalize_numeric_value(value: object, *, column: str, row: int) -> float:
    if value is None or value is pd.NA:
        return math.nan
    if isinstance(value, str):
        if value.strip() == "":
            return math.nan
        try:
            result = float(value)
        except ValueError as exc:
            raise PerFileCleaningError(
                f"numeric column {column} has a nonnumeric value at row {row}"
            ) from exc
    elif isinstance(value, Real) and not isinstance(value, (bool, np.bool_)):
        result = float(value)
        if math.isnan(result):
            return math.nan
    else:
        raise PerFileCleaningError(
            f"numeric column {column} has a nonnumeric value at row {row}"
        )
    if not math.isfinite(result):
        raise PerFileCleaningError(
            f"numeric column {column} has a nonfinite value at row {row}"
        )
    return result


def _is_tostring_date_variable(name: str) -> bool:
    return (
        name.startswith("date")
        or name.startswith("first_date")
        or name.startswith("last_date")
    )


def _is_finite_numeric_text(value: str) -> bool:
    try:
        numeric = float(value)
    except ValueError:
        return False
    return math.isfinite(numeric)


def _normalize_input(
    raw_frame: pd.DataFrame,
    schema: RawSchema,
) -> tuple[
    pd.DataFrame,
    dict[str, Literal["byte", "int", "long", "float", "double"]],
]:
    _validate_schema(schema)
    if raw_frame.columns.duplicated().any():
        raise PerFileCleaningError("raw frame contains duplicate column names")
    expected = [column.raw_name for column in schema.columns]
    observed = list(raw_frame.columns)
    if observed != expected:
        raise PerFileCleaningError(
            "raw frame columns and order do not match the tracked 534-column schema"
        )

    normalized: dict[str, pd.Series] = {}
    numeric_storage: dict[str, Literal["byte", "int", "long", "float", "double"]] = {}
    for column in schema.columns:
        source = raw_frame[column.raw_name]
        if column.expected_import_class == "string":
            values: list[str] = []
            has_nonempty = False
            all_nonempty_finite = True
            for row_number, value in enumerate(source, start=1):
                normalized_value = _normalize_string_value(
                    value,
                    column=column.raw_name,
                    row=row_number,
                )
                values.append(normalized_value)
                if normalized_value.strip():
                    has_nonempty = True
                    all_nonempty_finite &= _is_finite_numeric_text(normalized_value)
            if not has_nonempty and _is_tostring_date_variable(column.stata_name):
                # An all-missing delimited field imports as numeric missing in
                # Stata.  The frozen source-wide ``tostring`` loop then turns
                # each regular missing value into the literal string ".".
                values = ["."] * len(values)
            elif not has_nonempty or all_nonempty_finite:
                raise PerFileCleaningError(
                    f"string column {column.raw_name} would be inferred as numeric by Stata import"
                )
            normalized[column.stata_name] = pd.Series(values, dtype=object)
        else:
            values = [
                _normalize_numeric_value(
                    value,
                    column=column.raw_name,
                    row=row_number,
                )
                for row_number, value in enumerate(source, start=1)
            ]
            # ``set type float`` supplies the default for noninteger fields,
            # while ``import delimited`` still selects exact integer storage
            # and promotes values outside Stata's long range to double.
            storage = _numeric_storage_for_values(values)
            normalized[column.stata_name] = _normalized_numeric_series(
                values, storage=storage
            )
            numeric_storage[column.stata_name] = storage
    return (
        pd.DataFrame(
            normalized, columns=[column.stata_name for column in schema.columns]
        ),
        numeric_storage,
    )


def _initialize_import_formats(
    state: _CleaningState,
    schema: RawSchema,
    numeric_storage: dict[str, Literal["byte", "int", "long", "float", "double"]],
) -> None:
    """Record the formats assigned by Stata's strict delimited import.

    Imported integer fields receive their inferred integer type's display
    format.  Generated values are handled separately by ``generate_float`` and
    retain ``%9.0g`` even if the final ``compress`` narrows their storage.
    """

    for column in schema.columns:
        series = state._require(column.stata_name)
        if column.raw_name != column.stata_name:
            state.metadata.variable_labels[column.stata_name] = column.raw_name
        if column.expected_import_class == "string":
            width = max(
                1,
                max((len(value.encode("utf-8")) for value in series), default=0),
            )
            state.metadata.display_formats[column.stata_name] = f"%{max(9, width)}s"
            continue
        storage = numeric_storage[column.stata_name]
        state.metadata.display_formats[column.stata_name] = {
            "byte": "%8.0g",
            "int": "%8.0g",
            "long": "%12.0g",
            "float": "%9.0g",
            "double": "%10.0g",
        }[storage]


def _float_expression(value: object) -> float:
    return math.nan if is_regular_missing(value) else float(value)  # type: ignore[arg-type]


def _subtract(left: object, right: object) -> float:
    if is_regular_missing(left) or is_regular_missing(right):
        return math.nan
    return float(left) - float(right)  # type: ignore[arg-type]


def _choose_if_missing(primary: object, fallback: object) -> float:
    return _float_expression(fallback if is_regular_missing(primary) else primary)


def _relative_date(event_text: object, encounter_day: object) -> float:
    event_day = stata_date(event_text, "YMD")
    return _subtract(event_day, encounter_day)


def _rounded_choice(primary: object, fallback: object, unit: float) -> float:
    return stata_round(
        fallback if is_regular_missing(primary) else primary,
        unit,
    )


def _calculated_bmi(weight: object, height: object) -> float:
    if is_regular_missing(weight) or is_regular_missing(height):
        return math.nan
    numeric_height = float(height)  # type: ignore[arg-type]
    if numeric_height == 0:
        return math.nan
    value = (float(weight) * 0.453592) / ((numeric_height * 0.0254) ** 2)  # type: ignore[arg-type]
    return stata_round(value, 0.1)


def _replace_numeric(state: _CleaningState, name: str, values: object) -> None:
    dtype = state._require(name).dtype
    if dtype not in (np.dtype("float32"), np.dtype("float64")):
        raise PerFileCleaningError(f"could not replace Stata numeric variable: {name}")
    try:
        state.frame[name] = pd.Series(values, index=state.frame.index, dtype=dtype)
    except (TypeError, ValueError) as exc:
        raise PerFileCleaningError(
            f"could not replace Stata numeric variable: {name}"
        ) from exc


def _recode_in_place(
    state: _CleaningState,
    name: str,
    rules: tuple[RecodeRule, ...],
) -> None:
    float_rules = tuple(
        RecodeRule(
            None if rule.lower is None else float(np.float32(rule.lower)),
            None if rule.upper is None else float(np.float32(rule.upper)),
            rule.replacement,
            match_missing=rule.match_missing,
        )
        for rule in rules
    )
    _replace_numeric(
        state,
        name,
        [stata_recode(value, float_rules) for value in state._require(name)],
    )


def _generate_relative_date(
    state: _CleaningState,
    *,
    target: str,
    source: str,
    label: str | None = None,
    drop_source: bool = True,
) -> None:
    state.generate_float(
        target,
        [
            _relative_date(event, encounter)
            for event, encounter in zip(
                state._require(source),
                state._require("encounter_date"),
                strict=True,
            )
        ],
    )
    if label is not None:
        state.label(target, label)
    if drop_source:
        state.drop(source)


def _clean_measurement(
    state: _CleaningState,
    *,
    source: str,
    target: str,
    variable_label: str,
    date_source: str,
    date_target: str,
    date_label: str,
    lower_missing: float | None = None,
    upper_missing: float | None = None,
) -> None:
    if lower_missing is not None or upper_missing is not None:
        rules = tuple(
            rule
            for rule in (
                RecodeRule.interval(None, lower_missing, math.nan)
                if lower_missing is not None
                else None,
                RecodeRule.interval(upper_missing, None, math.nan)
                if upper_missing is not None
                else None,
            )
            if rule is not None
        )
        _recode_in_place(state, source, rules)
    state.rename(source, target)
    state.label(target, variable_label)
    _generate_relative_date(
        state,
        target=date_target,
        source=date_source,
        label=date_label,
    )


def _generate_first_after(
    state: _CleaningState,
    target: str,
    sources: tuple[str, ...],
    *,
    label: str | None = None,
) -> None:
    values = zip(*(state._require(source) for source in sources), strict=True)
    state.generate_float(target, [first_after(tuple(row)) for row in values])
    if label is not None:
        state.label(target, label)


def _generate_row_stat(
    state: _CleaningState,
    target: str,
    sources: tuple[str, ...],
    *,
    statistic: Literal["min", "max", "mean"],
    label: str | None = None,
) -> None:
    function = {
        "min": stata_row_min,
        "max": stata_row_max,
        "mean": stata_row_mean,
    }[statistic]
    values = zip(*(state._require(source) for source in sources), strict=True)
    state.generate_float(target, [function(tuple(row)) for row in values])
    if label is not None:
        state.label(target, label)


def _define_and_bind_binary_label(
    state: _CleaningState,
    *,
    variable: str,
    name: str,
    zero: str,
    one: str,
) -> None:
    state.define_value_label(name, {0: zero, 1: one})
    state.bind_value_label(variable, name)


def _generate_any_indicator(
    state: _CleaningState,
    target: str,
    sources: tuple[str, ...],
) -> None:
    values = zip(*(state._require(source) for source in sources), strict=True)
    state.generate_float(
        target,
        [1 if any(value == 1 for value in row) else 0 for row in values],
    )


def _numeric_storage_for_values(
    values: list[float],
) -> Literal["byte", "int", "long", "float", "double"]:
    """Select Stata's numeric import/compress storage for observed values."""

    observed = [value for value in values if not math.isnan(value)]
    lower = min(observed, default=0)
    upper = max(observed, default=0)
    if lower < -2_147_483_647 or upper > 2_147_483_620:
        return "double"
    if all(value.is_integer() for value in observed):
        if -127 <= lower and upper <= 100:
            return "byte"
        if -32_767 <= lower and upper <= 32_740:
            return "int"
        return "long"
    return "float"


def _normalized_numeric_series(
    values: list[float],
    *,
    storage: Literal["byte", "int", "long", "float", "double"],
) -> pd.Series:
    """Use a Python container that preserves the inferred Stata values."""

    dtype = np.float32 if storage in {"byte", "int", "float"} else np.float64
    return pd.Series(values, dtype=dtype)


def _compressed_numeric_storage(
    series: pd.Series,
) -> Literal["byte", "int", "long", "float", "double"]:
    observed = [float(value) for value in series if not is_regular_missing(value)]
    return _numeric_storage_for_values(observed)


def _finalize_compression_metadata(state: _CleaningState) -> None:
    metadata = state.metadata
    metadata.storage_types.clear()
    metadata.string_widths.clear()

    for name in state.frame.columns:
        series = state.frame[name]
        if series.dtype == object:
            if not series.map(lambda value: isinstance(value, str)).all():
                raise PerFileCleaningError(
                    f"string variable contains a non-string value: {name}"
                )
            width = max(
                1,
                max((len(value.encode("utf-8")) for value in series), default=0),
            )
            metadata.storage_types[name] = "string"
            metadata.string_widths[name] = width
            metadata.display_formats[name] = f"%{max(9, width)}s"
            continue

        storage = _compressed_numeric_storage(series)
        metadata.storage_types[name] = storage
        metadata.display_formats.setdefault(name, "%9.0g")


def _apply_preamble_and_demographics(
    state: _CleaningState,
    context: PerFileContext,
) -> None:
    frame = state.frame
    state.generate_string(
        "pat_enc_hash",
        [
            stata_concat((patient_id, encounter_id), punct="-")
            for patient_id, encounter_id in zip(
                frame["patient_id"],
                frame["encounter_id"],
                strict=True,
            )
        ],
    )
    state.generate_float(f"{context.family.value}_rfs", np.ones(len(frame)))
    state.generate_float(f"{context.setting_code}_enc", np.ones(len(frame)))

    state.label("encounter_id", "Encounter ID")
    state.generate_float(
        "encounter_date",
        [stata_date(value, "YMD") for value in frame["qualify_date"]],
    )
    state.format("encounter_date", "%td")
    state.label("encounter_date", "Date of encounter")
    state.drop("qualify_date")

    state.label("age_at_encounter", "Age (years)")
    state.generate_float(
        "age_by_ten",
        [
            math.nan if is_regular_missing(value) else float(value) / 10
            for value in frame["age_at_encounter"]
        ],
    )
    state.label("age_by_ten", "Age per 10 years")
    age_rules = (
        RecodeRule.missing(0),
        RecodeRule.interval(None, 30, 1),
        RecodeRule.interval(30, 40, 2),
        RecodeRule.interval(40, 50, 3),
        RecodeRule.interval(50, 60, 4),
        RecodeRule.interval(60, 70, 5),
        RecodeRule.interval(70, 80, 6),
        RecodeRule.interval(80, None, 7),
    )
    state.generate_float(
        "age_decade",
        [
            stata_recode(value, age_rules, generated=True)
            for value in frame["age_at_encounter"]
        ],
    )
    state.define_value_label(
        "decade_lab",
        {
            0: "Missing Age",
            1: "<30y",
            2: "30s",
            3: "40s",
            4: "50s",
            5: "60s",
            6: "70s",
            7: "80+",
        },
    )
    state.bind_value_label("age_decade", "decade_lab")
    state.label("age_decade", "Age (decade)")

    state.label("location", "Location")
    state.define_value_label(
        "loc_lab",
        {0: "South", 1: "Northeast", 2: "Midwest", 3: "West"},
    )
    state.bind_value_label("location", "loc_lab")
    state.label("race", "Race")
    state.define_value_label(
        "race_lab",
        {
            0: "White",
            1: "Black or African American",
            2: "Unknown",
            3: "Asian",
            4: "American Indian or Alaska Native",
            5: "Native Hawaiian / Pacific Islander",
        },
    )
    state.bind_value_label("race", "race_lab")
    state.label("ethnicity", "Ethnicity")
    state.define_value_label(
        "ethnicity_lab",
        {0: "Not Hispanic or Latino", 1: "Hispanic or Latino", 2: "Unknown"},
    )
    state.bind_value_label("ethnicity", "ethnicity_lab")
    state.label("sex", "Male Gender?")
    state.define_value_label(
        "sex_lab",
        {0: "Female", 1: "Male", 2: "Unknown or Other"},
    )
    state.bind_value_label("sex", "sex_lab")

    state.generate_float(
        "death_date",
        [
            _subtract(stata_date(death_year_month, "YM"), encounter_date)
            for death_year_month, encounter_date in zip(
                frame["death_year_month"],
                frame["encounter_date"],
                strict=True,
            )
        ],
    )
    state.label(
        "death_date",
        "Day of Death (Relative to Encounter-Year-Month)",
    )
    state.drop("death_year_month")
    state.generate_float(
        "died",
        [0 if is_regular_missing(value) else 1 for value in frame["death_date"]],
    )
    state.label("died", "Patient Died?")

    state.generate_float(
        "encounter_date_ym",
        [stata_month_index_from_daily(value) for value in frame["encounter_date"]],
    )
    state.generate_float(
        "death_date_ym",
        [
            stata_month_index_from_daily(
                math.nan
                if is_regular_missing(death_date) or is_regular_missing(encounter_date)
                else float(death_date) + float(encounter_date)
            )
            for death_date, encounter_date in zip(
                frame["death_date"],
                frame["encounter_date"],
                strict=True,
            )
        ],
    )
    june_2023 = stata_ym(2023, 6)
    state.generate_float(
        "months_death_or_cens",
        [
            _subtract(
                june_2023 if is_regular_missing(death_ym) else death_ym,
                encounter_ym,
            )
            for death_ym, encounter_ym in zip(
                frame["death_date_ym"],
                frame["encounter_date_ym"],
                strict=True,
            )
        ],
    )
    state.label(
        "months_death_or_cens",
        "Time from encounter to death or censoring (months)",
    )
    state.drop("encounter_date_ym", "death_date_ym")


def _apply_vital_signs(state: _CleaningState) -> None:
    frame = state.frame

    state.recode_to_missing("value_weight", at_or_below=50, at_or_above=500)
    state.generate_float("curr_weight", frame["value_weight"])
    state.label("curr_weight", "Current Weight (lbs)")
    state.drop("value_weight")
    state.generate_float(
        "curr_weight_date",
        [
            _relative_date(event, encounter)
            for event, encounter in zip(
                frame["date_weight"],
                frame["encounter_date"],
                strict=True,
            )
        ],
    )
    state.label("curr_weight_date", "Day of Current Weight (Encounter-Day)")
    state.drop("date_weight")

    state.recode_to_missing("value_prev_weight", at_or_below=50, at_or_above=500)
    state.label("value_prev_weight", "Prior Weight (lbs)")
    state.generate_float(
        "prev_weight_date",
        [
            _relative_date(event, encounter)
            for event, encounter in zip(
                frame["date_prev_weight"],
                frame["encounter_date"],
                strict=True,
            )
        ],
    )
    state.label(
        "prev_weight_date",
        "Day of Prev Weight (Ref'd to Encounter-Day)",
    )
    state.drop("date_prev_weight")

    state.recode_to_missing("value_height", at_or_below=50, at_or_above=90)
    state.rename("value_height", "curr_height")
    state.label("curr_height", "Current Height (inches)")
    state.generate_float(
        "curr_height_date",
        [
            _relative_date(event, encounter)
            for event, encounter in zip(
                frame["date_height"],
                frame["encounter_date"],
                strict=True,
            )
        ],
    )
    state.label("curr_height_date", "Day of Current Height (Encounter-Day)")
    state.drop("date_height")

    state.recode_to_missing("value_prev_height", at_or_below=50, at_or_above=90)
    state.label("value_prev_height", "Prior Height (lbs)")
    state.generate_float(
        "prev_height_date",
        [
            _relative_date(event, encounter)
            for event, encounter in zip(
                frame["date_prev_height"],
                frame["encounter_date"],
                strict=True,
            )
        ],
    )
    state.label(
        "prev_height_date",
        "Day of Prev Height (Ref'd to Encounter-Day)",
    )
    state.drop("date_prev_height")

    state.recode_to_missing("value_bmi", at_or_below=10, at_or_above=50.1)
    state.rename("value_bmi", "curr_bmi")
    state.label("curr_bmi", "Current BMI kg/m2")
    state.generate_float(
        "curr_bmi_date",
        [
            _relative_date(event, encounter)
            for event, encounter in zip(
                frame["date_bmi"],
                frame["encounter_date"],
                strict=True,
            )
        ],
    )
    state.label("curr_bmi_date", "Day of Current BMI (Encounter-Day)")
    state.drop("date_bmi")

    state.recode_to_missing("value_prev_bmi", at_or_below=10, at_or_above=50.1)
    state.label("value_prev_bmi", "Prior BMI kg/m2")
    state.generate_float(
        "prev_bmi_date",
        [
            _relative_date(event, encounter)
            for event, encounter in zip(
                frame["date_prev_bmi"],
                frame["encounter_date"],
                strict=True,
            )
        ],
    )
    state.label(
        "prev_bmi_date",
        "Day of Prev BMI (Ref'd to Encounter-Day)",
    )
    state.drop("date_prev_bmi")

    state.generate_float(
        "height",
        [
            _rounded_choice(current, previous, 1)
            for current, previous in zip(
                frame["curr_height"],
                frame["value_prev_height"],
                strict=True,
            )
        ],
    )
    state.label(
        "height",
        "Height (inches; current if availble, last if not)",
    )
    state.generate_float(
        "height_date",
        [
            _choose_if_missing(current_height, previous_date)
            if is_regular_missing(current_height)
            else _float_expression(current_date)
            for current_height, previous_date, current_date in zip(
                frame["curr_height"],
                frame["prev_height_date"],
                frame["curr_height_date"],
                strict=True,
            )
        ],
    )
    # The frozen source relabels curr_height_date and never labels height_date.
    state.label("curr_height_date", "Day of Height (Encounter-Day)")

    state.generate_float(
        "weight",
        [
            _rounded_choice(current, previous, 1)
            for current, previous in zip(
                frame["curr_weight"],
                frame["value_prev_weight"],
                strict=True,
            )
        ],
    )
    state.label(
        "weight",
        "Weight (lbs; current if availble, last if not)",
    )
    state.generate_float(
        "weight_date",
        [
            _choose_if_missing(current_weight, previous_date)
            if is_regular_missing(current_weight)
            else _float_expression(current_date)
            for current_weight, previous_date, current_date in zip(
                frame["curr_weight"],
                frame["prev_weight_date"],
                frame["curr_weight_date"],
                strict=True,
            )
        ],
    )
    state.label("weight_date", "Day of Weight (Encounter-Day)")

    state.generate_float(
        "calc_bmi",
        [
            _calculated_bmi(weight, height)
            for weight, height in zip(
                frame["weight"],
                frame["height"],
                strict=True,
            )
        ],
    )
    state.generate_float(
        "calc_bmi_date",
        [
            math.nan
            if is_regular_missing(calc_bmi)
            else stata_row_min((height_date, weight_date))
            for calc_bmi, height_date, weight_date in zip(
                frame["calc_bmi"],
                frame["height_date"],
                frame["weight_date"],
                strict=True,
            )
        ],
    )
    state.generate_float(
        "working_bmi",
        [
            _rounded_choice(current, previous, 0.1)
            for current, previous in zip(
                frame["curr_bmi"],
                frame["value_prev_bmi"],
                strict=True,
            )
        ],
    )
    state.generate_float(
        "working_bmi_date",
        [
            _choose_if_missing(current_bmi, previous_date)
            if is_regular_missing(current_bmi)
            else _float_expression(current_date)
            for current_bmi, previous_date, current_date in zip(
                frame["curr_bmi"],
                frame["prev_bmi_date"],
                frame["curr_bmi_date"],
                strict=True,
            )
        ],
    )
    state.generate_float(
        "bmi",
        [
            stata_round(
                calc_bmi if is_regular_missing(working_bmi) else working_bmi,
                0.1,
            )
            for working_bmi, calc_bmi in zip(
                frame["working_bmi"],
                frame["calc_bmi"],
                strict=True,
            )
        ],
    )
    state.label(
        "bmi",
        "BMI kg/m2; current if availble, last if not, calc'd from height "
        "weight if neither available)",
    )
    state.generate_float(
        "bmi_date",
        [
            _choose_if_missing(working_date, calculated_date)
            for working_date, calculated_date in zip(
                frame["working_bmi_date"],
                frame["calc_bmi_date"],
                strict=True,
            )
        ],
    )
    state.generate_float(
        "bmi_int",
        [stata_round(value, 1) for value in frame["bmi"]],
    )
    state.label("bmi_int", "BMI kg/m2")
    state.generate_float(
        "bmi_by_five",
        [
            math.nan if is_regular_missing(value) else float(value) / 5
            for value in frame["bmi"]
        ],
    )
    state.label("bmi_by_five", "BMI per 5 kg/m2")

    state.recode_to_missing("value_rr", at_or_below=2, at_or_above=75)
    state.generate_float("rr", frame["value_rr"])
    state.drop("value_rr")
    state.label("rr", "Respiratory Rate")
    state.generate_float(
        "rr_date",
        [
            _relative_date(event, encounter)
            for event, encounter in zip(
                frame["date_rr"],
                frame["encounter_date"],
                strict=True,
            )
        ],
    )
    state.label("rr_date", "Day of RR (Encounter-Day)")
    state.drop("date_rr")

    state.recode_to_missing("value_new_temp", at_or_below=40, at_or_above=110)
    state.generate_float("temp_new", frame["value_new_temp"])
    state.drop("value_new_temp")
    state.label("temp_new", "Temperature (F)")
    state.generate_float(
        "new_temp_date",
        [
            _relative_date(event, encounter)
            for event, encounter in zip(
                frame["date_new_temp"],
                frame["encounter_date"],
                strict=True,
            )
        ],
    )
    state.label("new_temp_date", "Day of New Temp (Encounter-Day)")
    state.drop("date_new_temp")

    state.recode_to_missing("value_sysbp", at_or_below=30, at_or_above=350)
    state.generate_float("sbp", frame["value_sysbp"])
    state.drop("value_sysbp")
    state.label("sbp", "Systolic BP")
    state.generate_float(
        "sbp_date",
        [
            _relative_date(event, encounter)
            for event, encounter in zip(
                frame["date_sysbp"],
                frame["encounter_date"],
                strict=True,
            )
        ],
    )
    state.label("sbp_date", "Day of Systolic BP (Encounter-Day)")
    state.drop("date_sysbp")

    state.recode_to_missing("value_diabp", at_or_below=20, at_or_above=250)
    state.generate_float("dbp", frame["value_diabp"])
    state.drop("value_diabp")
    state.label("dbp", "Diastolic BP")
    state.generate_float(
        "dbp_date",
        [
            _relative_date(event, encounter)
            for event, encounter in zip(
                frame["date_diabp"],
                frame["encounter_date"],
                strict=True,
            )
        ],
    )
    state.label("dbp_date", "Day of Diastolic BP (Encounter-Day)")
    state.drop("date_diabp")

    state.recode_to_missing("value_spo2", at_or_below=50, at_or_above=100)
    state.rename("value_spo2", "spo2")
    state.label("spo2", "O2 Saturation")
    state.generate_float(
        "spo2_date",
        [
            _relative_date(event, encounter)
            for event, encounter in zip(
                frame["date_spo2"],
                frame["encounter_date"],
                strict=True,
            )
        ],
    )
    state.label("spo2_date", "Day of SpO2 reading (Encounter-Day)")
    state.drop("date_spo2")

    state.recode_to_missing("value_hr", at_or_below=15, at_or_above=300)
    state.rename("value_hr", "hr")
    state.label("hr", "Heart Rate")
    state.generate_float(
        "hr_date",
        [
            _relative_date(event, encounter)
            for event, encounter in zip(
                frame["date_hr"],
                frame["encounter_date"],
                strict=True,
            )
        ],
    )
    state.label("hr_date", "Day of Heart Rate reading (Encounter-Day)")
    state.drop("date_hr")


def _apply_labs_and_acid_base(state: _CleaningState) -> None:
    """Apply frozen source lines 640-1304 in command order."""

    early_measurements = (
        (
            "value_27441",
            "abg_ph",
            "pH (ABG)",
            "date_27441",
            "abg_ph_date",
            "Day of ABG pH (Encounter-Day)",
            6.5,
            7.8,
        ),
        (
            "value_27466",
            "vbg_ph",
            "pH (VBG)",
            "date_27466",
            "vbg_ph_date",
            "Day of VBG pH (Encounter-Day)",
            6.4,
            7.7,
        ),
        (
            "value_19604_20263",
            "abg_hco3",
            "HCO3 (ABG)",
            "date_19604_20263",
            "abg_hco3_date",
            "Day of ABG HCO3 (Encounter-Day)",
            0.0,
            60.0,
        ),
        (
            "value_146274",
            "vbg_hco3",
            "HCO3 (VBG)",
            "date_146274",
            "vbg_hco3_date",
            "Day of VBG HCO3 (Encounter-Day)",
            0.0,
            60.0,
        ),
        (
            "value_29512",
            "sodium",
            "Serum Sodium",
            "date_29512",
            "sodium_date",
            "Day of Serum Sodium(Encounter-Day)",
            80.0,
            190.0,
        ),
        (
            "value_potassium",
            "serum_k",
            "Serum Potassium",
            "date_potassium",
            "serum_k_date",
            "Day of Serum Potassium (Encounter-Day)",
            1.0,
            12.0,
        ),
        (
            "value_7187",
            "hgb",
            "Serum Hemoglobin",
            "date_7187",
            "hgb_date",
            "Day of Hgb (Encounter-Day)",
            3.0,
            25.0,
        ),
        (
            "value_264648",
            "wbc",
            "White Blood Cell count",
            "date_264648",
            "wbc_date",
            "Day of WBC (Encounter-Day)",
            0.01,
            500.0,
        ),
        (
            "value_265157",
            "plt",
            "Platelet Count",
            "date_265157",
            "plt_date",
            "Day of Plt (Encounter-Day)",
            0.01,
            2000.0,
        ),
        (
            "value_serum_bicarb",
            "serum_hco3",
            "Serum Bicarbonate (measured)",
            "date_serum_bicarb",
            "serum_hco3_date",
            "Day of Serum HCO3- (Encounter-Day)",
            0.9,
            65.0,
        ),
    )
    for (
        source,
        target,
        variable_label,
        date_source,
        date_target,
        date_label,
        lower,
        upper,
    ) in early_measurements:
        _clean_measurement(
            state,
            source=source,
            target=target,
            variable_label=variable_label,
            date_source=date_source,
            date_target=date_target,
            date_label=date_label,
            lower_missing=lower,
            upper_missing=upper,
        )
        if target == "abg_hco3":
            state.generate_float(
                "abg_hco3_int",
                [stata_round(value, 1) for value in state._require("abg_hco3")],
            )
            state.label("abg_hco3_int", "HCO3 (ABG, nearest integer)")

    _generate_row_stat(
        state,
        "any_bicarb",
        ("abg_hco3", "vbg_hco3", "serum_hco3"),
        statistic="mean",
        label="Any bicarbonate; averaged if multiple (ABG, VBG, Chem)",
    )
    state.generate_float(
        "int_bicarb",
        [stata_round(value, 1) for value in state._require("any_bicarb")],
    )
    state.label("int_bicarb", "Serum Bicarbonate (integer)")
    hco3_rules = tuple(
        RecodeRule(
            None if rule.lower is None else float(np.float32(rule.lower)),
            None if rule.upper is None else float(np.float32(rule.upper)),
            rule.replacement,
        )
        for rule in (
            RecodeRule.interval(None, 23.99, 0),
            RecodeRule.interval(24, 26.99, 1),
            RecodeRule.interval(27, 29.99, 2),
            RecodeRule.interval(30, None, 3),
        )
    )
    state.generate_float(
        "hco3_cat",
        [
            stata_recode(value, hco3_rules, generated=True)
            for value in state._require("serum_hco3")
        ],
    )
    state.label("hco3_cat", "HCO3- (BMP) Category")
    state.define_value_label(
        "hco3_cat_lab",
        {0: "<24", 1: "24-26", 2: "27-29", 3: "30+"},
    )
    state.bind_value_label("hco3_cat", "hco3_cat_lab")

    later_routine_measurements = (
        (
            "value_serum_chloride",
            "serum_cl",
            "Serum Chloride",
            "date_serum_chloride",
            "serum_cl_date",
            "Day of Serum Chloride (Encounter-Day)",
            65.0,
            150.0,
        ),
        (
            "value_21600",
            "serum_cr",
            "Serum Creatinine",
            "date_21600",
            "serum_cr_date",
            "Day of serum Creatinine (21600) (Encounter-Day)",
            0.1,
            20.0,
        ),
        (
            "value_serum_lactate",
            "serum_lac",
            "Serum Lactate",
            "date_serum_lactate",
            "serum_lac_date",
            "Day of serum lactate (Encounter-Day)",
            0.1,
            50.0,
        ),
        (
            "value_vbg_co2",
            "vbg_co2",
            "VBG PCO2",
            "date_vbg_co2",
            "vbg_co2_date",
            "Day of VBG CO2 (Encounter-Day)",
            2.0,
            250.0,
        ),
        (
            "value_pco2_unspec_blood",
            "pco2_nos",
            "PCO2 not specified source",
            "date_pco2_unspec_blood",
            "pco2_nos_date",
            "Day of CO2 not specified source (Encounter-Day)",
            2.0,
            250.0,
        ),
        (
            "value_highest_vbg_co2",
            "highest_vbg_co2",
            "Highest VBG PCO2",
            "date_highest_vbg_co2",
            "highest_vbg_co2_date",
            "Day of Highest VBG CO2 (Encounter-Day)",
            2.0,
            250.0,
        ),
        (
            "value_highest_pco2_unspec_blood",
            "highest_pco2_nos",
            "Highest PCO2 not specified source",
            "date_highest_pco2_unspec_blood",
            "highest_pco2_nos_date",
            "Day of Highest CO2 not specified source (Encounter-Day)",
            2.0,
            250.0,
        ),
    )
    for (
        source,
        target,
        variable_label,
        date_source,
        date_target,
        date_label,
        lower,
        upper,
    ) in later_routine_measurements:
        _clean_measurement(
            state,
            source=source,
            target=target,
            variable_label=variable_label,
            date_source=date_source,
            date_target=date_target,
            date_label=date_label,
            lower_missing=lower,
            upper_missing=upper,
        )

    paco2_sources = ("value_115576", "value_20198", "value_327718")
    for source in paco2_sources:
        _recode_in_place(
            state,
            source,
            (
                RecodeRule.interval(None, 2, math.nan),
                RecodeRule.interval(250, None, math.nan),
            ),
        )
    _generate_row_stat(
        state,
        "paco2",
        paco2_sources,
        statistic="mean",
        label="Arterial PCO2",
    )
    paco2_date_specs = (
        ("date_20198", "paco2_date_1", "Day of PaCO2 (20198) (Encounter-Day)"),
        ("date_115576", "paco2_date_2", "Day of PaCO2 (115576) (Encounter-Day)"),
        ("date_327718", "paco2_date_3", "Day of PaCO2 (327718) (Encounter-Day)"),
    )
    for date_source, date_target, date_label in paco2_date_specs:
        _generate_relative_date(
            state,
            target=date_target,
            source=date_source,
            label=date_label,
        )
    _generate_first_after(
        state,
        "paco2_date",
        ("paco2_date_1", "paco2_date_2", "paco2_date_3"),
        label="Date closest to encoutner start of PaCO2",
    )
    state.generate_float(
        "paco2_int",
        [stata_round(value, 1) for value in state._require("paco2")],
    )
    state.label("paco2_int", "PaCO2")
    state.drop(*paco2_sources)

    highest_sources = (
        "value_highest_115576",
        "value_highest_20198",
        "value_highest_327718",
    )
    for source in highest_sources:
        _recode_in_place(
            state,
            source,
            (
                RecodeRule.interval(None, 2, math.nan),
                RecodeRule.interval(250, None, math.nan),
            ),
        )
    _generate_row_stat(
        state,
        "highest_paco2",
        highest_sources,
        statistic="max",
        label="Highest Arterial PCO2",
    )
    highest_date_specs = (
        (
            "date_highest_20198",
            "paco2_date_highest_1",
            "Day of Highest PaCO2 (20198) (Encounter-Day)",
        ),
        (
            "date_highest_115576",
            "paco2_date_highest_2",
            "Day of Highest PaCO2 (115576) (Encounter-Day)",
        ),
        (
            "date_highest_327718",
            "paco2_date_highest_3",
            "Day of Highest PaCO2 (327718) (Encounter-Day)",
        ),
    )
    for date_source, date_target, date_label in highest_date_specs:
        _generate_relative_date(
            state,
            target=date_target,
            source=date_source,
            label=date_label,
        )
    _generate_first_after(
        state,
        "paco2_date_highest",
        (
            "paco2_date_highest_1",
            "paco2_date_highest_2",
            "paco2_date_highest_3",
        ),
    )

    gas_measurements = (
        (
            "value_192583",
            "temp_cor_oxygen",
            "O2 (temp corrected)",
            "date_192583",
            "temp_cor_oxygen_date",
            "Day of Temp-corrected PaO2 (Encounter-Day)",
            30.0,
            110.0,
        ),
        (
            "value_394866",
            "vbg_ph_temp_cor",
            "VBG pH (temp corrected)",
            "date_394866",
            "temp_cor_vbg_ph_date",
            "Day of Temp-corrected VBG pH (Encounter-Day)",
            6.4,
            7.7,
        ),
        (
            "value_27052",
            "vbg_po2",
            "VBG PO2",
            "date_27052",
            "vbg_po2_date",
            "Day of VBG PO2 (Encounter-Day)",
            10.0,
            300.0,
        ),
        (
            "value_lactate_venous_blood",
            "vbg_lactate",
            "Lactate (VBG)",
            "date_lactate_venous_blood",
            "vbg_lactate_date",
            "Day of VBG Lactate (Encounter-Day)",
            0.1,
            50.0,
        ),
        (
            "value_483917",
            "vbg_hco3_calc",
            "VBG HCO3 by Calc",
            "date_483917",
            "vbg_hco3_calc_date",
            "Day of VBG HCO3 calc (Encounter-Day)",
            2.0,
            60.0,
        ),
        (
            "value_27037",
            "abg_po2",
            "PO2 (ABG)",
            "date_27037",
            "abg_po2_date",
            "Day of PaO2 (Encounter-Day)",
            10.0,
            500.0,
        ),
        (
            "value_192559",
            "abg_po2_temp_cor",
            "PO2 (ABG, temp corr)",
            "date_192559",
            "abg_po2_temp_cor_date",
            "Day of Temp-Corrected PaO2 (Encounter-Day)",
            10.0,
            500.0,
        ),
        (
            "value_332544",
            "abg_ph_temp_cor",
            "pH (ABG, temp corr)",
            "date_332544",
            "abg_ph_temp_cor_date",
            "Day of Temp-Corrected ABG pH (Encounter-Day)",
            6.4,
            7.7,
        ),
        (
            "value_25189",
            "abg_lactate",
            "Lactate (ABG)",
            "date_25189",
            "abg_lactate_date",
            "Day of ABG Lactate (Encounter-Day)",
            0.1,
            50.0,
        ),
        (
            "value_115584",
            "ph_blood",
            "pH (blood)",
            "date_115584",
            "ph_blood_date",
            "Day of pH Blood (Encounter-Day)",
            6.4,
            7.7,
        ),
        (
            "value_115568",
            "po2_blood",
            "PO2 (blood)",
            "date_115568",
            "po2_blood_date",
            "Day of pO2 Blood (Encounter-Day)",
            10.0,
            500.0,
        ),
        (
            "value_759878",
            "vbg_temp",
            "Temp (VBG)",
            "date_759878",
            "vbg_temp_date",
            "Day of VBG Temp (Encounter-Day)",
            70.0,
            110.0,
        ),
        (
            "value_608356",
            "abg_temp",
            "Temp (ABG)",
            "date_608356",
            "abg_temp_date",
            "Day of ABG Temp (Encounter-Day)",
            70.0,
            110.0,
        ),
        (
            "value_27110",
            "vbg_o2sat",
            "VBG O2 Saturation",
            "date_27110",
            "vbg_o2sat_date",
            "Day of VBG O2 Saturation (Encounter-Day)",
            10.0,
            100.0,
        ),
        (
            "value_27086",
            "abg_o2sat",
            "ABG O2 Saturation (SaO2)",
            "date_27086",
            "abg_o2sat_date",
            "Day of ABG O2 Saturation (Encounter-Day)",
            10.0,
            100.0,
        ),
        (
            "value_205641",
            "sao2_blood",
            "SaO2 (blood)",
            "date_205641",
            "sao2_blood_date",
            "Day of SaO2 blood (Encounter-Day)",
            10.0,
            100.0,
        ),
    )
    for (
        source,
        target,
        variable_label,
        date_source,
        date_target,
        date_label,
        lower,
        upper,
    ) in gas_measurements:
        _clean_measurement(
            state,
            source=source,
            target=target,
            variable_label=variable_label,
            date_source=date_source,
            date_target=date_target,
            date_label=date_label,
            lower_missing=lower,
            upper_missing=upper,
        )

    abg_predictor = [
        serum if is_regular_missing(abg) else abg
        for abg, serum in zip(
            state._require("abg_hco3"),
            state._require("serum_hco3"),
            strict=True,
        )
    ]
    _replace_numeric(
        state,
        "abg_ph",
        [
            (
                6.1 + math.log10(float(hco3) / (0.03 * float(co2)))
                if is_regular_missing(ph)
                and not is_regular_missing(hco3)
                and not is_regular_missing(co2)
                else ph
            )
            for ph, hco3, co2 in zip(
                state._require("abg_ph"),
                abg_predictor,
                state._require("paco2"),
                strict=True,
            )
        ],
    )
    vbg_predictor = [
        serum if is_regular_missing(vbg) else vbg
        for vbg, serum in zip(
            state._require("vbg_hco3"),
            state._require("serum_hco3"),
            strict=True,
        )
    ]
    _replace_numeric(
        state,
        "vbg_ph",
        [
            (
                6.1 + math.log10(float(hco3) / (0.03 * float(co2)))
                if is_regular_missing(ph)
                and not is_regular_missing(hco3)
                and not is_regular_missing(co2)
                else ph
            )
            for ph, hco3, co2 in zip(
                state._require("vbg_ph"),
                vbg_predictor,
                state._require("vbg_co2"),
                strict=True,
            )
        ],
    )

    def threshold_flag(
        *,
        target: str,
        source: str,
        threshold: float,
        variable_label: str,
        value_label: str,
        zero: str,
        one: str,
    ) -> None:
        state.generate_float(
            target,
            [
                (
                    math.nan
                    if is_regular_missing(value)
                    else int(float(value) >= threshold)
                )
                for value in state._require(source)
            ],
        )
        state.label(target, variable_label)
        _define_and_bind_binary_label(
            state,
            variable=target,
            name=value_label,
            zero=zero,
            one=one,
        )

    threshold_flag(
        target="paco2_flag",
        source="paco2",
        threshold=45,
        variable_label="PaCO2 >= 45 mmHg w/n 24h of admission?",
        value_label="paco2_flag_lab",
        zero="All PaCO2 < 45 mmHg",
        one="PaCO2 >= 45 mmHg",
    )
    threshold_flag(
        target="highest_paco2_flag",
        source="highest_paco2",
        threshold=45,
        variable_label="PaCO2 >= 45 mmHg (any)?",
        value_label="highest_paco2_flag_lab",
        zero="All PaCO2 < 45 mmHg",
        one="PaCO2 >= 45 mmHg",
    )
    threshold_flag(
        target="paco2_52_flag",
        source="paco2",
        threshold=52,
        variable_label="PaCO2 >= 52 mmHg w/n 24h of admission?",
        value_label="paco2_52_flag_lab",
        zero="All PaCO2 < 52 mmHg",
        one="PaCO2 >= 52 mmHg",
    )
    threshold_flag(
        target="vbg_co2_flag",
        source="vbg_co2",
        threshold=50,
        variable_label="VBG CO2 >= 50 mmHg w/n 24h of admission?",
        value_label="vbg_co2_flag_lab",
        zero="All VBG CO2 < 50 mmHg",
        one="VBG CO2 >= 50 mmHg",
    )
    threshold_flag(
        target="highest_vbg_co2_flag",
        source="highest_vbg_co2",
        threshold=50,
        variable_label="VBG CO2 >= 50 mmHg (any))?",
        value_label="highest_vbg_co2_flag_lab",
        zero="All VBG CO2 < 50 mmHg",
        one="VBG CO2 >= 50 mmHg",
    )

    state.generate_float(
        "miss_paco2_flag",
        [
            0 if is_regular_missing(value) else value
            for value in state._require("paco2_flag")
        ],
    )
    state.label(
        "miss_paco2_flag",
        "PaCO2 >= 45 mmHg w/n 24h of admission? (missing = no)",
    )
    state.generate_float(
        "miss_vbg_co2_flag",
        [
            0 if is_regular_missing(value) else value
            for value in state._require("vbg_co2_flag")
        ],
    )
    state.label(
        "miss_vbg_co2_flag",
        "VBG CO2 >= 50 mmHg w/n 24h of admission? (missing=no)",
    )
    state.generate_float(
        "miss_vbg_or_abg_co2_flag",
        [
            int(bool(abg) or bool(vbg))
            for abg, vbg in zip(
                state._require("miss_paco2_flag"),
                state._require("miss_vbg_co2_flag"),
                strict=True,
            )
        ],
    )
    state.label(
        "miss_vbg_or_abg_co2_flag",
        "Either PaCO2 >= 45 mmHg or VBG CO2 >= 50 mmHg w/n 24h of admission? (missing=no)",
    )
    threshold_flag(
        target="hco3_flag",
        source="serum_hco3",
        threshold=27,
        variable_label="HCO3- (BMP) >= 27 mEq/L w/n 24h of admission?",
        value_label="hco3_flag_lab",
        zero="All HCO3- (BMP) < 27 mEq/L",
        one="HCO3- (BMP) >= 27 mEq/L",
    )
    for source, target in (
        ("paco2_flag", "not_paco2_flag"),
        ("hco3_flag", "not_hco3_flag"),
    ):
        state.generate_float(
            target,
            [
                (
                    math.nan
                    if is_regular_missing(value)
                    else 0
                    if value == 1
                    else 1
                    if value == 0
                    else value
                )
                for value in state._require(source)
            ],
        )
        state.label(
            target,
            f"RECODE of {source} ({state.metadata.variable_labels[source]})",
        )

    k_rules = tuple(
        RecodeRule(
            None if rule.lower is None else float(np.float32(rule.lower)),
            None if rule.upper is None else float(np.float32(rule.upper)),
            rule.replacement,
        )
        for rule in (
            RecodeRule.interval(None, 3.49, 0),
            RecodeRule.interval(3.5, 4.34, 1),
            RecodeRule.interval(4.35, 5.19, 2),
            RecodeRule.interval(5.2, None, 3),
        )
    )
    state.generate_float(
        "k_cat",
        [
            stata_recode(value, k_rules, generated=True)
            for value in state._require("serum_k")
        ],
    )
    state.label("k_cat", "K+ (BMP) Category")
    state.define_value_label(
        "k_cat_lab",
        {0: "<3.5", 1: "3.5-4.35", 2: "4.35-5.2", 3: "5.2+"},
    )
    state.bind_value_label("k_cat", "k_cat_lab")

    chemistry_specs = (
        (
            "value_bnp",
            "bnp",
            "B-Natriuretic Peptide",
            "date_bnp",
            "bnp_date",
            0.01,
            500000,
        ),
        (
            "value_phos",
            "serum_phos",
            "Phosphate",
            "date_phos",
            "serum_phos_date",
            0.1,
            30,
        ),
        ("value_ca", "serum_ca", "Total Calcium", "date_ca", "serum_ca_date", 0.1, 30),
        (
            "value_albumin",
            "serum_albumin",
            "Serum Albumin",
            "date_albumin",
            "serum_albumin_date",
            0.1,
            6,
        ),
        (
            "value_tprot",
            "serum_tprot",
            "Serum Total Protein",
            "date_tprot",
            "serum_tprot_date",
            0.1,
            12,
        ),
    )
    for (
        source,
        target,
        label,
        date_source,
        date_target,
        lower,
        upper,
    ) in chemistry_specs:
        _recode_in_place(
            state,
            source,
            (
                RecodeRule.interval(None, lower, math.nan),
                RecodeRule.interval(upper, None, math.nan),
            ),
        )
        state.rename(source, target)
        state.label(target, label)
        state.rename(date_source, date_target)

    state.generate_float(
        "acidemia",
        [
            (
                math.nan
                if is_regular_missing(abg) and is_regular_missing(vbg)
                else 1
                if (
                    (not is_regular_missing(abg) and float(abg) <= 7.35)
                    or (
                        is_regular_missing(abg)
                        and not is_regular_missing(vbg)
                        and float(vbg) <= 7.32
                    )
                )
                else 0
            )
            for abg, vbg in zip(
                state._require("abg_ph"),
                state._require("vbg_ph"),
                strict=True,
            )
        ],
    )
    state.label("acidemia", "Acidemia by ABG or VBG?")
    state.define_value_label(
        "acidemia_lab",
        {
            0: "ABG pH > 7.35 or VBG pH > 7.32",
            1: "ABG pH < 7.35 (or missing & VBG pH < 7.32)",
        },
    )
    state.bind_value_label("acidemia", "acidemia_lab")

    for target, hco3_name, ph_name, label in (
        ("abg_sbe", "abg_hco3", "abg_ph", "Standard Base Excess (ABG)"),
        ("vbg_sbe", "vbg_hco3", "vbg_ph", "Standard Base Excess (VBG)"),
    ):
        state.generate_float(
            target,
            [
                (
                    math.nan
                    if is_regular_missing(hco3) or is_regular_missing(ph)
                    else float(hco3) - 24.8 + (16.2 * (float(ph) - 7.4))
                )
                for hco3, ph in zip(
                    state._require(hco3_name),
                    state._require(ph_name),
                    strict=True,
                )
            ],
        )
        state.label(target, label)

    state.generate_float(
        "cw_simple_acute_resp_acid",
        [
            (
                math.nan
                if is_regular_missing(sbe)
                else 1
                if -2 <= float(sbe) <= 2 and acidemia == 1
                else 0
                if float(sbe) < -2 or float(sbe) > 2
                else math.nan
            )
            for sbe, acidemia in zip(
                state._require("abg_sbe"),
                state._require("acidemia"),
                strict=True,
            )
        ],
    )
    state.label(
        "cw_simple_acute_resp_acid",
        "Consistent with simple acute respiratory acidosis?",
    )
    _define_and_bind_binary_label(
        state,
        variable="cw_simple_acute_resp_acid",
        name="cwsra_lab",
        zero="no",
        one="yes",
    )

    state.generate_float(
        "paco2_52_comp_flag",
        [
            (
                math.nan
                if is_regular_missing(paco2) or is_regular_missing(acidemia)
                else 1
                if float(paco2) >= 52 and acidemia == 0
                else 0
            )
            for paco2, acidemia in zip(
                state._require("paco2"),
                state._require("acidemia"),
                strict=True,
            )
        ],
    )
    state.label(
        "paco2_52_comp_flag",
        "PaCO2 >= 52 mmHg w/n 24h of admission?",
    )
    _define_and_bind_binary_label(
        state,
        variable="paco2_52_comp_flag",
        name="paco2_52_comp_flag_lab",
        zero="All PaCO2 < 52 mmHg & pH > 7.35",
        one="PaCO2 >= 52 mmHg & pH > 7.35",
    )


def _apply_medications(state: _CleaningState) -> None:
    """Apply frozen inpatient and outpatient medication transformations."""

    inpatient_specs = (
        (
            "ip_med_1",
            "po_steroid",
            "PO Corticosteroid (Inpatient)",
            "roid_lab",
            "No PO Steroid Rx'd",
            "PO Steroid Rx'd",
            "date_ip_med_1",
            "po_steroid_date",
            "Day of PO Steroid, inpatient (Encounter-Day)",
        ),
        (
            "ip_med_2",
            "narcan",
            "Narcan or other antidote (Inpatient)",
            "antidote_lab",
            "No antidote Rx'd",
            "Antidote (e.g. narcan) rx'd",
            "date_ip_med_2",
            "narcan_date",
            "Day of Narcan, inpatient (Encounter-Day)",
        ),
        (
            "ip_med_3",
            "inpt_inh",
            "Inhaled Treatments Rx'd (Inpatient)",
            "inpt_inh_lab",
            "No inhalers given inpatient",
            "Inhalers given inpt",
            "date_ip_med_3",
            "inpt_inh_date",
            "Day of Inhaler, inpatient (Encounter-Day)",
        ),
        (
            "ip_med_4",
            "vasodilators",
            "Vasodilators (Inpatient)",
            "vaso_lab",
            "No Vasodilators Given",
            "Vasodilators Given",
            "date_ip_med_4",
            "vasodilators_date",
            "Day of Vasodilators, inpatient (Encounter-Day)",
        ),
        (
            "ip_med_5",
            "ip_diuretics",
            "Diuretics (inpatient)",
            "ip_diur_lab",
            "Not on inpatient diuretics",
            "On inpatient diuretic(s)",
            "date_ip_med_5",
            "ip_diuretics_date",
            "Day of Diuretics, inpatient (Encounter-Day)",
        ),
        (
            "ip_med_6",
            "ip_abx",
            "Antibiotics (Inpatient)",
            "ip_abx_lab",
            "No inpatient antibiotics",
            "Given inpatient antibiotics",
            "date_ip_med_6",
            "ip_abx_date",
            "Day of Antibiotics, inpatient (Encounter-Day)",
        ),
        (
            "ip_med_7",
            "paralytic",
            "Neuromuscular Blockade",
            "ip_nmb_lab",
            "No inpatient paralytic",
            "Given inpatient paralytic",
            "date_ip_med_7",
            "paralytic_date",
            "Day of Neuromuscular Blockade, inpatient (Encounter-Day)",
        ),
    )
    for (
        source,
        target,
        label,
        value_label,
        zero,
        one,
        date_source,
        date_target,
        date_label,
    ) in inpatient_specs:
        state.rename(source, target)
        state.label(target, label)
        _define_and_bind_binary_label(
            state,
            variable=target,
            name=value_label,
            zero=zero,
            one=one,
        )
        _generate_relative_date(
            state,
            target=date_target,
            source=date_source,
            label=date_label,
        )

    for variable in (
        "inpt_inh",
        "ip_abx",
        "ip_diuretics",
        "narcan",
        "paralytic",
        "po_steroid",
        "vasodilators",
    ):
        state.generate_float(
            f"{variable}_0",
            [
                int(value == 1 and date in {-1, 0})
                for value, date in zip(
                    state._require(variable),
                    state._require(f"{variable}_date"),
                    strict=True,
                )
            ],
        )

    outpatient_specs = (
        (
            "op_med_1",
            "op_diuretics",
            "Diuretics (outpatient)",
            "op_diur_lab",
            "Not on outpatient diuretics",
            "On outpatient diuretic(s)",
            "first_date_op_med_1",
            "op_diuretics_first_date",
            "1st Day of Diuretics, outpatient (Encounter-Day)",
            "last_date_op_med_1",
            "op_diuretics_last_date",
            "Last Day of Diuretics, outpatient (Encounter-Day)",
            "op_diuretics_365d",
            "Diuretics",
            "op_diur_365d_lab",
            "Not on outpatient diuretics w/n 1yr",
            "On outpatient diuretic(s) w/n 1yr",
        ),
        (
            "op_med_2",
            "op_opiate",
            "Opiate (outpatient)",
            "op_opiate_lab",
            "No outpatient opiate Rx",
            "Received outpatient opiate Rx",
            "first_date_op_med_2",
            "op_opiate_first_date",
            "First Day of Opiate, outpatient (Encounter-Day)",
            "last_date_op_med_2",
            "op_opiate_last_date",
            "Last Day of Opiate, outpatient (Encounter-Day)",
            "op_opiate_365d",
            "Opiate",
            "op_opiate_lab_365d",
            "No outpatient opiate Rx w/n 1yr",
            "Received outpatient opiate Rx w/n 1yr",
        ),
        (
            "op_med_3",
            "op_mat",
            "Medication Assisted Treatment",
            "op_mat_lab",
            "No MAT med rx",
            "MAT rx'd",
            "first_date_op_med_3",
            "op_mat_first_date",
            "First Day of Medication Assisted Therapy for OUD, outpatient (Encounter-Day)",
            "last_date_op_med_3",
            "op_mat_last_date",
            "Last Day of Medication Assisted Therapy for OUD, outpatient (Encounter-Day)",
            "op_mat_365d",
            "Medication Assisted Treatment",
            "op_mat_lab_365d",
            "No MAT med rx w/n 365d",
            "MAT rx'd w/n 365d",
        ),
        (
            "op_med_4",
            "op_nrt",
            "Nicotine Cessation",
            "op_nrt_lab",
            "No nicotine cess med rx",
            "Nicotine cessation med rx'd",
            "first_date_op_med_4",
            "op_nrt_first_date",
            "First Day of Nicotine Dependence Treatment, outpatient (Encounter-Day)",
            "last_date_op_med_4",
            "op_nrt_last_date",
            "Last Day of Nicotine Dependence Treatment, outpatient (Encounter-Day)",
            "op_nrt_365d",
            "Nicotine Cessation",
            "op_nrt_lab_365d",
            "No nicotine cess med rx w/n 1yr",
            "Nicotine cessation med rx'd w/n 1yr",
        ),
        (
            "op_med_5",
            "copd_med",
            "COPD Meds",
            "copd_med_lab",
            "No outpatient COPD meds",
            "Outpatient COPD Meds",
            "first_date_op_med_5",
            "copd_med_first_date",
            "First Day of COPD Med, outpatient (Encounter-Day)",
            "last_date_op_med_5",
            "copd_med_last_date",
            "Last Day of COPD Med, outpatient (Encounter-Day)",
            "copd_med_365d",
            "Outpatient COPD Meds w/n 1 yr",
            "copd_med_lab_365d",
            "No outpatient COPD meds w/n 1yr",
            "Outpatient COPD Meds w/n 1yr",
        ),
        (
            "op_med_6",
            "muscle_relax",
            "Muscle Relaxants",
            "musc_rel_lab",
            "No Muscle Relaxant Rx",
            "Muscle Relaxant Rx",
            "first_date_op_med_6",
            "muscle_relax_first_date",
            "First Day of Muscle Relaxant, outpatient (Encounter-Day)",
            "last_date_op_med_6",
            "muscle_relax_last_date",
            "Last Day of Muscle Relaxant, outpatient (Encounter-Day)",
            "muscle_relax_365d",
            "OP Muscle Relaxants w/n 1yr",
            "musc_rel_lab_365d",
            "No Muscle Relaxant Rx w/n 1yr",
            "Muscle Relaxant Rx w/n 1 yr",
        ),
    )
    for (
        source,
        target,
        label,
        value_label,
        zero,
        one,
        first_source,
        first_target,
        first_label,
        last_source,
        last_target,
        last_label,
        within_target,
        within_label,
        within_value_label,
        within_zero,
        within_one,
    ) in outpatient_specs:
        state.rename(source, target)
        state.label(target, label)
        _define_and_bind_binary_label(
            state,
            variable=target,
            name=value_label,
            zero=zero,
            one=one,
        )
        _generate_relative_date(
            state,
            target=first_target,
            source=first_source,
            label=first_label,
        )
        _generate_relative_date(
            state,
            target=last_target,
            source=last_source,
            label=last_label,
        )
        state.generate_float(
            within_target,
            [
                int(stata_ge(last_date, -365) and medication == 1)
                for last_date, medication in zip(
                    state._require(last_target),
                    state._require(target),
                    strict=True,
                )
            ],
        )
        state.label(within_target, within_label)
        _define_and_bind_binary_label(
            state,
            variable=within_target,
            name=within_value_label,
            zero=within_zero,
            one=within_one,
        )


def _apply_procedures(state: _CleaningState) -> None:
    """Apply frozen procedure transformations through source line 2097."""

    state.rename("has_tte", "tte_proc")
    state.label("tte_proc", "TTE Procedure Performed")
    _define_and_bind_binary_label(
        state,
        variable="tte_proc",
        name="tte_lab",
        zero="No TTE",
        one="TTE Billed",
    )
    _generate_relative_date(
        state,
        target="tte_proc_first_date",
        source="first_date_tte",
        label="First Day of TTE Procedure(Encounter-Day)",
    )
    _generate_relative_date(
        state,
        target="tte_proc_last_date",
        source="last_date_tte",
        label="Last Day of TTE Procedure(Encounter-Day)",
    )

    state.generate_float("vent_proc", np.zeros(len(state.frame)))
    state.label("vent_proc", "Procedure code for NIV or IMV")
    state.generate_float("niv_proc", np.zeros(len(state.frame)))
    state.label("niv_proc", "Non-invasive Ventilation Procedure?")
    state.generate_float("imv_proc", np.zeros(len(state.frame)))
    state.label("imv_proc", "Invasive Mechanical Ventilation Procedure")
    _define_and_bind_binary_label(
        state,
        variable="vent_proc",
        name="vent_lab",
        zero="No NIV or IMV",
        one="Either NIV or IMV",
    )
    state.label("imv_proc", "Procedure code for IMV")
    _define_and_bind_binary_label(
        state,
        variable="imv_proc",
        name="imv_lab",
        zero="No IMV",
        one="Received IMV",
    )
    state.label("niv_proc", "Procedure code for NIV (not including nightly CPAP)")
    _define_and_bind_binary_label(
        state,
        variable="niv_proc",
        name="niv_lab",
        zero="No NIV",
        one="Received NIV (not including nightly CPAP)",
    )

    state.rename("has_94660", "cpap")
    state.label("cpap", "CPAP proc. code")
    _define_and_bind_binary_label(
        state,
        variable="cpap",
        name="cpap_lab",
        zero="No CPAP Proc Code",
        one="CPAP Proc Code",
    )
    _generate_relative_date(
        state,
        target="cpap_first_date",
        source="first_date_94660",
        label="First Day of CPAP (Encounter-Day)",
    )
    _generate_relative_date(
        state,
        target="cpap_last_date",
        source="last_date_94660",
        label="Last Day of CPAP (Encounter-Day)",
    )

    def composite_ventilation(
        *,
        target: str,
        codes: tuple[str, ...],
        first_target: str,
        first_label: str,
        last_target: str,
        last_label: str,
    ) -> None:
        _replace_numeric(
            state,
            target,
            [
                int(any(value == 1 for value in row))
                for row in zip(
                    *(state._require(f"has_{code}") for code in codes),
                    strict=True,
                )
            ],
        )
        first_dates: list[str] = []
        last_dates: list[str] = []
        for code in codes:
            first_date = f"_{code}_first_date"
            last_date = f"_{code}_last_date"
            _generate_relative_date(
                state,
                target=first_date,
                source=f"first_date_{code}",
            )
            first_dates.append(first_date)
        _generate_first_after(
            state,
            first_target,
            tuple(first_dates),
            label=first_label,
        )
        for code in codes:
            last_date = f"_{code}_last_date"
            _generate_relative_date(
                state,
                target=last_date,
                source=f"last_date_{code}",
            )
            last_dates.append(last_date)
        _generate_row_stat(
            state,
            last_target,
            tuple(last_dates),
            statistic="max",
            label=last_label,
        )
        state.drop(*(f"has_{code}" for code in codes))
        state.drop(*first_dates)
        state.drop(*last_dates)

    composite_ventilation(
        target="niv_proc",
        codes=("5a09358", "5a09458", "5a09558", "5a09357", "5a09457", "5a09557"),
        first_target="niv_proc_first_date",
        first_label="First Date of NIV Procedure Code",
        last_target="niv_proc_last_date",
        last_label="Last date of NIV Procedure Code",
    )
    composite_ventilation(
        target="imv_proc",
        codes=("94002", "94003", "5a19054", "5a1935z", "5a1945z", "5a1955z"),
        first_target="imv_proc_first_date",
        first_label="First Date during the encounter IMV Procedure Code",
        last_target="imv_proc_last_date",
        last_label="Last Date of IMV Procedure Code",
    )
    state.drop("has_430191008", "first_date_430191008", "last_date_430191008")
    _replace_numeric(
        state,
        "vent_proc",
        [
            int(imv == 1 or niv == 1)
            for imv, niv in zip(
                state._require("imv_proc"),
                state._require("niv_proc"),
                strict=True,
            )
        ],
    )
    _generate_first_after(
        state,
        "vent_proc_first_date",
        ("imv_proc_first_date", "niv_proc_first_date"),
        label="Date closest to encoutner start of Vent (IMV or NIV) Procedure Code",
    )
    _generate_row_stat(
        state,
        "vent_proc_last_date",
        ("imv_proc_last_date", "niv_proc_last_date"),
        statistic="max",
        label="Last Date of Vent (IMV or NIV) Procedure Code",
    )

    procedure_specs = (
        (
            "has_94640",
            "aero",
            "Aerosolized Treatment",
            "aero_lab",
            "No Aersolized Tx",
            "Inh or Airway Therapy Given",
            "first_date_94640",
            "aero_first_date",
            "First Day of Aerosolized treatment (Encounter-Day)",
            "last_date_94640",
            "aero_last_date",
            "Last Day of Aerosolized treatment (Encounter-Day)",
        ),
        (
            "has_94664",
            "inh_teaching",
            "Inhaler Teaching",
            "inh_tch_lab",
            "No Inh Teaching",
            "Inh Teaching Provided",
            "first_date_94664",
            "inh_teaching_first_date",
            "First Day of Inhaler Teaching (Encounter-Day)",
            "last_date_94664",
            "inh_teaching_last_date",
            "Last Day of Inhaler Teaching (Encounter-Day)",
        ),
        (
            "has_71045",
            "cxr1v",
            "1 View CXR",
            "cxr1v_lab",
            "No 1-view CXR",
            "1+ CXR 1-view",
            "first_date_71045",
            "cxr1v_first_date",
            "First Day of 1-view CXR (Encounter-Day)",
            "last_date_71045",
            "cxr1v_last_date",
            "Last First Day of 1-view CXR (Encounter-Day)",
        ),
        (
            "has_71046",
            "cxr2v",
            "2 View CXR",
            "cxr2v_lab",
            "No 2-view CXR",
            "1+ CXR 2-view",
            "first_date_71046",
            "cxr2v_first_date",
            "First Day of 2-view CXR (Encounter-Day)",
            "last_date_71046",
            "cxr2v_last_date",
            "Last Day of 2-view CXR (Encounter-Day)",
        ),
        (
            "has_71250",
            "ctcnoncon",
            "CT Chest Non-Contrast",
            "ctcnoncon_lab",
            "No CT Chest Non-Con",
            "CT Chest Non-Con Obtained",
            "first_date_71250",
            "ctcnoncon_first_date",
            "First Day of CT Chest Non-Contrast (Encounter-Day)",
            "last_date_71250",
            "ctcnoncon_last_date",
            "Last Day of CT Chest Non-Contrast (Encounter-Day)",
        ),
        (
            "has_71260",
            "ctccon",
            "CT Chest w Contrast",
            "ctccon_lab",
            "No CT Chest w Con",
            "CT Chest w Con Obtained",
            "first_date_71260",
            "ctccon_first_date",
            "First Day of CT Chest w/ Contrast (Encounter-Day)",
            "last_date_71260",
            "ctccon_last_date",
            "Last Day of CT Chest w/ Contrast (Encounter-Day)",
        ),
        (
            "has_ct_abdm",
            "ctabdpelv",
            "CT of the Abdomen / Pelvis",
            "ctabdpelv_lab",
            "No CT Abd/Pelv",
            "CT Abd/Pelv",
            "first_date_ct_abdm",
            "ctabdpelv_first_date",
            "First Day of CT Abdomen/Pelvis (Encounter-Day)",
            "last_date_ct_abdm",
            "ctabdpelv_last_date",
            "Last Day of CT Abdomen/Pelvis (Encounter-Day)",
        ),
        (
            "has_61911006",
            "meas_venous_o2_proc",
            "Measurement of O2 in Venous Blood Procedure",
            "meas_venous_o2_proc_lab",
            "No Venous O2 Measurement Procedure",
            "Venous O2 Measurement Procedure",
            "first_date_61911006",
            "meas_venous_o2_proc_first_date",
            "First Day of Venous Gas Measurement Procecedure (Encounter-Day)",
            "last_date_61911006",
            "meas_venous_o2_proc_last_date",
            "Last Day of Venous Gas Measurement Procecedure (Encounter-Day)",
        ),
        (
            "has_91308007",
            "meas_arterial_gas_proc",
            "Measurement of Gasses in Arterial Blood Procedure",
            "meas_arterial_gas_proc_lab",
            "No Arterial Gas Measurement Procedure",
            "Arterial Gas Measurement Procedure",
            "first_date_91308007",
            "meas_art_gas_proc_first_date",
            "Day of Arterial Gas Measurement Procecedure (Encounter-Day)",
            "last_date_91308007",
            "meas_art_gas_proc_last_date",
            "Last Day of Arterial Gas Measurement Procecedure (Encounter-Day)",
        ),
        (
            "has_87040",
            "blood_cx_proc",
            "Blood Cultures (procedure)",
            "blood_cx_proc_lab",
            "No Blood Cultures",
            "Blood Cultures",
            "first_date_87040",
            "blood_cx_proc_first_date",
            "First Day of Blood Culture Collection Procecedure (Encounter-Day)",
            "last_date_87040",
            "blood_cx_proc_last_date",
            "Last Day of Blood Culture Collection Procecedure (Encounter-Day)",
        ),
        (
            "has_36600",
            "art_punct_proc",
            "Arterial Puncture (procedure)",
            "art_punct_proc_lab",
            "No Arterial Puncture",
            "Arterial Puncture",
            "first_date_36600",
            "art_punct_proc_first_date",
            "First Day of Arterial Puncture Procecedure (Encounter-Day)",
            "last_date_36600",
            "art_punct_proc_last_date",
            "Last Day of Arterial Puncture Procecedure (Encounter-Day)",
        ),
    )
    for (
        source,
        target,
        label,
        value_label,
        zero,
        one,
        first_source,
        first_target,
        first_label,
        last_source,
        last_target,
        last_label,
    ) in procedure_specs:
        state.rename(source, target)
        state.label(target, label)
        _define_and_bind_binary_label(
            state,
            variable=target,
            name=value_label,
            zero=zero,
            one=one,
        )
        _generate_relative_date(
            state,
            target=first_target,
            source=first_source,
            label=first_label,
        )
        _generate_relative_date(
            state,
            target=last_target,
            source=last_source,
            label=last_label,
        )

    state.rename("has_99291", "cc_time")
    state.label("cc_time", "Critical Care Services Billed")
    _define_and_bind_binary_label(
        state,
        variable="cc_time",
        name="cc_lab",
        zero="No Crit Care Services",
        one="Crit Care Services",
    )
    _generate_relative_date(
        state,
        target="cc_time_first_date",
        source="first_date_99291",
        label="First Day of Critical Care Time (Encounter-Day)",
    )
    _generate_relative_date(
        state,
        target="cc_time_last_date",
        source="last_date_99291",
        label="Last Day of Critical Care Time (Encounter-Day)",
    )

    for variable in (
        "aero",
        "blood_cx_proc",
        "cc_time",
        "cpap",
        "ctabdpelv",
        "ctccon",
        "ctcnoncon",
        "cxr1v",
        "cxr2v",
        "imv_proc",
        "inh_teaching",
        "niv_proc",
        "tte_proc",
        "vent_proc",
    ):
        state.generate_float(
            f"{variable}_0",
            [
                int(value == 1 and first_date in {-1, 0})
                for value, first_date in zip(
                    state._require(variable),
                    state._require(f"{variable}_first_date"),
                    strict=True,
                )
            ],
        )

    for variable in (
        "aero",
        "blood_cx_proc",
        "cpap",
        "ctabdpelv",
        "ctccon",
        "ctcnoncon",
        "cxr1v",
        "cxr2v",
        "imv_proc",
        "inh_teaching",
        "niv_proc",
        "tte_proc",
    ):
        state.generate_float(
            f"{variable}_dur",
            [
                _subtract(last_date, first_date)
                for last_date, first_date in zip(
                    state._require(f"{variable}_last_date"),
                    state._require(f"{variable}_first_date"),
                    strict=True,
                )
            ],
        )


def _generate_current_diagnosis_role(
    state: _CleaningState,
    *,
    code: str,
    source: str,
    suffix: str,
    label: str,
) -> None:
    target = f"{code}_{suffix}"
    state.generate_float(
        target,
        [
            (
                1
                if indicator == "S"
                else math.nan
                if has_code == 0
                else 0
                if indicator == "U"
                else math.nan
            )
            for indicator, has_code in zip(
                state._require(source),
                state._require(f"has_{code}"),
                strict=True,
            )
        ],
    )
    state.bind_value_label(target, "dx_lab")
    state.label(target, label)
    state.drop(source)


def _apply_current_diagnoses(state: _CleaningState) -> None:
    """Apply frozen encounter-diagnosis transformations."""

    hypercap_codes = ("j9612", "j9622", "j9602", "j9692", "e662")
    _generate_any_indicator(
        state,
        "hypercap_resp_failure",
        tuple(f"has_{code}" for code in hypercap_codes),
    )
    state.label("hypercap_resp_failure", "Hypercapnic Respiratory Failure Dx")
    _define_and_bind_binary_label(
        state,
        variable="hypercap_resp_failure",
        name="hcrf_lab",
        zero="No Hypercap Resp Failure",
        one="Hypercap Resp Failure",
    )
    state.define_value_label("dx_lab", {0: "No", 1: "Yes"})

    hypercap_labels = {
        "j9612": "ICD J96.12: Chronic respiratory failure with hypercapnia",
        "j9622": "ICD J96.22: Acute and Chronic respiratory failure with hypercapnia",
        "j9602": "ICD J96.02: Acute respiratory failure with hypercapnia",
        "j9692": "ICD J96.92: Respiratory failure, unspecified with hypercapnia",
    }
    for code in ("j9612", "j9622", "j9602", "j9692"):
        state.label(f"has_{code}", hypercap_labels[code])
        _generate_relative_date(
            state,
            target=f"{code}_date",
            source=f"date_{code}",
            label=f"Date of {hypercap_labels[code]}",
        )
        dotted = {
            "j9612": "J96.12",
            "j9622": "J96.22",
            "j9602": "J96.02",
            "j9692": "J96.92",
        }[code]
        _generate_current_diagnosis_role(
            state,
            code=code,
            source=f"pcpl_dx_ind_{code}",
            suffix="pcpl",
            label=f"ICD {dotted} is Principal Dx",
        )
        _generate_current_diagnosis_role(
            state,
            code=code,
            source=f"adm_dx_{code}",
            suffix="adm",
            label=f"ICD {dotted} is Admitting Dx",
        )
        _generate_current_diagnosis_role(
            state,
            code=code,
            source=f"visit_reason_{code}",
            suffix="vr",
            label=f"ICD {dotted} is Visit Reason",
        )

    _generate_relative_date(
        state,
        target="ohs_code_date",
        source="date_e662",
        label="Date of ICD E66.2: Morbid Obesity with Hypoventilation",
    )
    _generate_current_diagnosis_role(
        state,
        code="e662",
        source="pcpl_dx_ind_e662",
        suffix="pcpl",
        label="ICD E66.2 is Principal Dx",
    )
    _generate_current_diagnosis_role(
        state,
        code="e662",
        source="adm_dx_e662",
        suffix="adm",
        label="ICD E66.2 is Admitting Dx",
    )
    _generate_current_diagnosis_role(
        state,
        code="e662",
        source="visit_reason_e662",
        suffix="vr",
        label="ICD E66.2 is Visit Reason",
    )
    state.rename("has_e662", "ohs_code")
    state.label("ohs_code", "ICD for hypoventilation with obesity")
    _generate_first_after(
        state,
        "hypercap_resp_failure_date",
        ("ohs_code_date", "j9692_date", "j9602_date", "j9612_date", "j9622_date"),
        label="Date closest to encoutner start of ICD Code for Hypercapnic RF",
    )

    other_rf_codes = (
        "j9600",
        "j9601",
        "j961",
        "j9610",
        "j9611",
        "j962",
        "j9620",
        "j9621",
        "j9690",
        "j9691",
    )
    _generate_any_indicator(
        state,
        "other_resp_failure",
        tuple(f"has_{code}" for code in other_rf_codes),
    )
    other_rf_labels = {
        "j9600": "J96.00: Acute Respiratory Failure, unspecified whether hypoxia or hypercapnia",
        "j9601": "J96.01 Acute respiratory failure, with hypoxia",
        "j961": "J96.1: Chronic Respiratory Failure",
        "j9610": "J96.10: Chronic Respiratory Failure, unspecified whether hypoxia or hypercapnia",
        "j9611": "J96.11: Chronic Respiratory Failure with hypoxia",
        "j962": "J96.2: Acute and Chronic Respiratory Failure",
        "j9620": (
            "J96.20: Acute and Chronic Respiratory Failure, unspecified whether "
            "hypoxia or hypercapnia "
        ),
        "j9621": "J96.21: Acute and Chronic Respiratory Failure, with hypoxia",
        "j9690": (
            "J96.90: Respiratory Failure, unspecified whether with hypoxia or hypercapnia"
        ),
        "j9691": "J96.91: Respiratory Failure, unspecified with hypoxia",
    }
    for code in other_rf_codes:
        state.label(f"has_{code}", other_rf_labels[code])
    state.label("other_resp_failure", "Other Respiratory Failure Dx")
    _define_and_bind_binary_label(
        state,
        variable="other_resp_failure",
        name="rf_lab",
        zero="No Other Resp Failure",
        one="Resp Failure (Hypox. or Unspec.)",
    )
    for code in other_rf_codes:
        _generate_relative_date(
            state,
            target=f"{code}_date",
            source=f"date_{code}",
        )
    _generate_first_after(
        state,
        "other_resp_failure_date",
        tuple(f"{code}_date" for code in other_rf_codes),
        label="Date closest to encoutner start of ICD Code for Other RF",
    )

    simple_current = (
        (
            "has_a41",
            "sepsis_dx",
            "ICD Code for Sepsis",
            "sepsis_lab",
            "No Sepsis Dx Code",
            "Sepsis Dx Code",
            True,
            "date_a41",
            "sepsis_dx_date",
            "Day of Sepsis Dx Code (Encounter-Day)",
        ),
        (
            "has_r40",
            "stupor_dx",
            "ICD Code for Stupor or Coma",
            "stupor_lab",
            "No Stupor or Coma Dx Code (R40)",
            "Stupor or Coma Dx Code (R40)",
            True,
            "date_r40",
            "stupor_dx_date",
            "Day of Stupor Dx Code (Encounter-Day)",
        ),
        (
            "has_r41",
            "cog_signs_dx",
            "ICD Code for Alt Cog Function/Awareness Dx",
            "cog_lab",
            "No Alt Cog Func/Aware Dx (R41)",
            "Alt Cog Func/Aware Dx (R41)",
            True,
            "date_r41",
            "cog_signs_dx_date",
            "Day of Alt Cog Func/Aware Dx Code (Encounter-Day)",
        ),
        (
            "has_r53",
            "mal_fat_dx",
            "ICD Code for Malaise/Fatigue Dx",
            "mal_fat_lab",
            "No Malaise/Fatigue Dx (R53)",
            "Malaise/Fatigue Dx (R53)",
            True,
            "date_r53",
            "mal_fat_dx_date",
            "Day of Malaise/Fatigue Dx Code (Encounter-Day)",
        ),
        (
            "has_e8729",
            "resp_acid_dx",
            "Respiratory Acidosis (Diagnosis)",
            "resp_acid_dx_lab",
            "No Respiratory Acidosis (Diagnosis)",
            "Respiratory Acidosis (Diagnosis)",
            True,
            "date_e8729",
            "resp_acid_dx_date",
            "Day of Respiratory Acidosis (Diagnosis)",
        ),
        (
            "has_g4734",
            "sleep_hypovent_dx",
            "Idiopathic Sleep Hypoventilation",
            "sleep_hypovent_dx_lab",
            "No Idiopathic Sleep Hypoventilation",
            "Idiopathic Sleep Hypoventilation",
            True,
            "date_g4734",
            "sleep_hypovent_dx_date",
            "Day of Idiopathic Sleep Hypoventilation",
        ),
        (
            "has_g4735",
            "cchs_dx",
            "Congenital Central Sleep Hypoventilation",
            "cchs_dx_lab",
            "No Congenital Central Sleep Hypoventilation",
            "Congenital Central Sleep Hypoventilation",
            True,
            "date_g4735",
            "cchs_dx_date",
            "Day of Congenital Central Sleep Hypoventilation",
        ),
        (
            "has_g4736",
            "other_sleep_hypovent_dx",
            "Sleep Hypoventilation in Other Conditions",
            "other_sleep_hypovent_dx_lab",
            "No Sleep Hypoventilation in Other Conditions",
            "Sleep Hypoventilation in Other Conditions",
            True,
            "date_g4736",
            "other_sleep_hypovent_dx_date",
            "Day of Sleep Hypoventilation in Other Conditions",
        ),
        (
            "has_e8720",
            "acidosis_unspec",
            "Acidosis, Unspecified",
            "acidosis_unspec_lab",
            "No Acidosis, Unspecified",
            "Acidosis, Unspecified",
            True,
            "date_e8720",
            "acidosis_unspec_date",
            "Day of Acidosis, Unspecified",
        ),
        (
            "has_headache",
            "headache_dx",
            "Headache (diagnosis)",
            "headache_dx_lab",
            "No Headache (diagnosis)",
            "Headache (diagnosis)",
            True,
            "date_headache",
            "headache_dx_date",
            "Day of Headache (diagnosis)",
        ),
    )
    for (
        source,
        target,
        label,
        value_label,
        zero,
        one,
        bind,
        date_source,
        date_target,
        date_label,
    ) in simple_current:
        state.rename(source, target)
        state.label(target, label)
        state.define_value_label(value_label, {0: zero, 1: one})
        if bind:
            state.bind_value_label(target, value_label)
        _generate_relative_date(
            state,
            target=date_target,
            source=date_source,
            label=date_label,
        )

    def current_composite(
        *,
        target: str,
        codes: tuple[str, ...],
        variable_label: str,
        value_label: str,
        zero: str,
        one: str,
        date_target: str,
        date_label: str,
    ) -> None:
        _generate_any_indicator(
            state,
            target,
            tuple(f"has_{code}" for code in codes),
        )
        relative_dates: list[str] = []
        for code in codes:
            relative_date = f"{code}_date"
            _generate_relative_date(
                state,
                target=relative_date,
                source=f"date_{code}",
            )
            relative_dates.append(relative_date)
        state.label(target, variable_label)
        _define_and_bind_binary_label(
            state,
            variable=target,
            name=value_label,
            zero=zero,
            one=one,
        )
        _generate_first_after(
            state,
            date_target,
            tuple(relative_dates),
            label=date_label,
        )
        state.drop(*(f"has_{code}" for code in codes))
        state.drop(*relative_dates)

    current_composite(
        target="dysp_dx",
        codes=("r06", "r060", "r0600", "r0602", "r0603", "r0609"),
        variable_label="Dyspnea Dx Code",
        value_label="dys_lab",
        zero="No Dyspnea Dx",
        one="Dyspnea Dx Code",
        date_target="dysp_dx_date",
        date_label="Date closest to encoutner start of ICD Code Dyspnea",
    )
    current_composite(
        target="symp_obs",
        codes=("r061", "r062", "r0683"),
        variable_label="Symptom of Airway Obstruction (wheeze, snoring, stridor)",
        value_label="symp_obs_lab",
        zero="No obstructive symptom",
        one="Obstructive symptom dx code",
        date_target="symp_obs_date",
        date_label="Date closest to encoutner start of ICD Code Upper Airway Obstruction",
    )
    current_composite(
        target="abn_br_dx",
        codes=("r0681", "r063"),
        variable_label="Abn Breathing Pattern Dx",
        value_label="abn_br_dx_lab",
        zero="No abn breathing pattern dx",
        one="Abn breathing pattern dx",
        date_target="abn_br_dx_date",
        date_label="Date closest to encoutner start of ICD Code Abnormal Breathing Pattern",
    )

    resp_abnormality_codes = ("r065", "r066", "r067", "r068", "r0689", "r069")
    _generate_any_indicator(
        state,
        "resp_abnormality",
        tuple(f"has_{code}" for code in resp_abnormality_codes),
    )
    for code in resp_abnormality_codes:
        _generate_relative_date(
            state,
            target=f"{code}_date",
            source=f"date_{code}",
            drop_source=code != "r0689",
        )
    state.label("resp_abnormality", "Other Resp Abnormality Dx")
    _define_and_bind_binary_label(
        state,
        variable="resp_abnormality",
        name="resp_abnormality_lab",
        zero="No Other Resp Abnormality Dx",
        one="Other Resp Abnormality Dx",
    )
    _generate_first_after(
        state,
        "resp_abnormality_date",
        tuple(f"{code}_date" for code in resp_abnormality_codes),
        label="Date closest to encoutner start of ICD Code: Respiratory Abnormality",
    )
    state.drop(*(f"has_{code}" for code in ("r065", "r066", "r067", "r068", "r069")))
    state.drop(*(f"{code}_date" for code in ("r065", "r066", "r067", "r068", "r069")))

    state.rename("has_r0689", "other_abn_of_br")
    state.label("other_abn_of_br", "Other Abnormalities of Breathing Dx")
    _define_and_bind_binary_label(
        state,
        variable="other_abn_of_br",
        name="other_abn_of_br_lab",
        zero="No Other Abnormalities of Breathing Dx",
        one="Other Abnormalities of Breathing Dx",
    )
    _generate_relative_date(
        state,
        target="other_abn_of_br_date",
        source="date_r0689",
        label="Day of Other Abnormalities of Breathing Dx",
    )

    current_composite(
        target="fast_br",
        codes=("r064", "r0682"),
        variable_label="Tachypnea or Hypervent Dx Code",
        value_label="fast_br_lab",
        zero="Neither Tachyp vs Hypervent Dx Code",
        one="Either Tachyp or Hypervent Dx Code",
        date_target="fast_br_date",
        date_label="Date closest to encoutner start of ICD Code: Fast Breathing",
    )
    current_composite(
        target="pulm_edema_dx",
        codes=("j81", "r0601"),
        variable_label="Pulm Edema or Orthopnea Dx Code",
        value_label="pulm_edema_dx_lab",
        zero="Neither Pulm Edema or Orthop Dx Code",
        one="Either Pulm Edema or Orthop Dx Code",
        date_target="pulm_edema_dx_date",
        date_label="Date closest to encoutner start of ICD Code: Pulmonary Edema",
    )
    current_composite(
        target="pna_dx",
        codes=("j09", "j10", "j11", "j12", "j13", "j14", "j15", "j16", "j17", "j18"),
        variable_label="Pneumonia Dx",
        value_label="pna_dx_lab",
        zero="No Pneumonia Diagnosed",
        one="Pneumonia",
        date_target="pna_dx_date",
        date_label="Date closest to encoutner start of ICD Code: PNa",
    )

    # ``date_i50`` is absent, but Stata resolves it as the unique abbreviation
    # of ``date_i50_acute`` in this exact schema.
    state.drop("date_e84", "date_i50_acute")
    state.generate_float(
        "acute_chf",
        [int(value == 1) for value in state._require("has_i50_acute")],
    )
    state.label("acute_chf", "Acute CHF (I50*) Diagnosis")

    acute_old_codes = ("j440", "j441", "j21", "j46")
    _generate_any_indicator(
        state,
        "acute_old",
        tuple(f"has_{code}" for code in acute_old_codes),
    )
    acute_old_dates: list[str] = []
    for code in acute_old_codes:
        date_name = f"{code}_date"
        _generate_relative_date(
            state,
            target=date_name,
            source=f"date_{code}",
        )
        acute_old_dates.append(date_name)
    state.label("acute_old", "Exacerbation of Obstructive Lung Disease")
    _define_and_bind_binary_label(
        state,
        variable="acute_old",
        name="acute_old_lab",
        zero="No AE COPD or Asthma",
        one="AE of COPD or Asthma",
    )
    _generate_first_after(
        state,
        "acute_old_date",
        tuple(f"has_{code}" for code in acute_old_codes),
        label=(
            "Date closest to encoutner start of ICD Code: Acute Obstructive Lung "
            "Dz (COPD or Asthma)"
        ),
    )
    state.drop(*(f"has_{code}" for code in acute_old_codes))
    state.drop(*acute_old_dates)

    current_composite(
        target="resp_dep_compl",
        codes=("z79891", "e9352", "f1110", "t40", "f19982"),
        variable_label="Complication of Respiratory Depressant",
        value_label="resp_dep_compl_lab",
        zero="No Dx of Comp from Resp Depr",
        one=" Dx of Comp from Resp Depr",
        date_target="resp_dep_compl_date",
        date_label=(
            "Date closest to encoutner start of ICD Code: Complication of Respiratory Depressant"
        ),
    )

    state.rename("has_g61", "acute_nmd")
    state.label("acute_nmd", "Acute Neuromuscular Dz (e.g. GBS)")
    _define_and_bind_binary_label(
        state,
        variable="acute_nmd",
        name="acute_nmd_lab",
        zero="No Acute NMD",
        one="Acute NMD",
    )
    _generate_relative_date(
        state,
        target="acute_nmd_date",
        source="date_g61",
        label=(
            "Date closest to encoutner start of ICD Code: Acute Neuromuscular disease (G61*)"
        ),
    )


def _apply_prior_diagnoses_and_final_flags(state: _CleaningState) -> None:
    """Apply frozen prior-diagnosis and final phenotype transformations."""

    def simple_prior(
        *,
        source: str,
        target: str,
        variable_label: str,
        value_label: str,
        zero: str,
        one: str,
        code: str,
        first_label: str,
        last_label: str,
    ) -> None:
        state.rename(source, target)
        state.label(target, variable_label)
        _define_and_bind_binary_label(
            state,
            variable=target,
            name=value_label,
            zero=zero,
            one=one,
        )
        _generate_relative_date(
            state,
            target=f"{target}_first_date",
            source=f"first_date_{code}",
            label=first_label,
        )
        _generate_relative_date(
            state,
            target=f"{target}_last_date",
            source=f"last_date_{code}",
            label=last_label,
        )

    simple_prior(
        source="has_g473",
        target="osa",
        variable_label="OSA",
        value_label="osa_lab",
        zero="No OSA diagnosis",
        one="OSA diagnosed",
        code="g473",
        first_label="First Date of ICD Code: OSA (G47.3)",
        last_label="Date closest to encoutner start of ICD Code: OSA (G47.3)",
    )
    simple_prior(
        source="has_j45",
        target="asthma",
        variable_label="Asthma",
        value_label="asthma_lab",
        zero="No Asthma diagnosis",
        one="Asthma diagnosed",
        code="j45",
        first_label="First Date of ICD Code: Asthma (J45*)",
        last_label="Date closest to encoutner start of ICD Code: Asthma (J45*)",
    )

    state.rename("has_j43", "copd")
    _replace_numeric(
        state,
        "copd",
        [
            1 if j44 == 1 else j43
            for j43, j44 in zip(
                state._require("copd"),
                state._require("has_j44"),
                strict=True,
            )
        ],
    )
    state.drop("has_j44")
    state.label("copd", "COPD")
    _define_and_bind_binary_label(
        state,
        variable="copd",
        name="copd_lab",
        zero="No COPD diagnosis",
        one="COPD diagnosed",
    )
    for code in ("j43", "j44"):
        _generate_relative_date(
            state,
            target=f"{code}_first_date",
            source=f"first_date_{code}",
        )
        _generate_relative_date(
            state,
            target=f"{code}_last_date",
            source=f"last_date_{code}",
        )
    _generate_row_stat(
        state,
        "copd_first_date",
        ("j43_first_date", "j44_first_date"),
        statistic="min",
        label="First Date ICD Code: COPD (j43 or j44)",
    )
    _generate_row_stat(
        state,
        "copd_last_date",
        ("j43_last_date", "j44_last_date"),
        statistic="max",
        label="Date closest to encoutner start of ICD Code: COPD (j43 or j44)",
    )
    state.drop(
        "j43_first_date",
        "j44_first_date",
        "j43_last_date",
        "j44_last_date",
    )

    simple_prior(
        source="has_i50",
        target="chf",
        variable_label="CHF",
        value_label="chf_lab",
        zero="No CHF diagnosis",
        one="CHF diagnosed",
        code="i50",
        first_label="First Date ICD Code: CHF (I50*)",
        last_label="Date closest to encoutner start of ICD Code: CHF (I50*)",
    )
    simple_prior(
        source="has_i63",
        target="stroke",
        variable_label="Stroke",
        value_label="stroke_lab",
        zero="No stroke diagnosis",
        one="Prior stroke diagnosis",
        code="i63",
        first_label="First Date ICD Code: Stroke (I63)",
        last_label="Date closest to encoutner start of ICD Code: Stroke (I63)",
    )
    simple_prior(
        source="has_n18",
        target="ckd",
        variable_label="CKD",
        value_label="ckd_lab",
        zero="No CKD diagnosis",
        one="CKD diagnosed",
        code="n18",
        first_label="First Date of ICD Code: CKD (N18*)",
        last_label="Date closest to encoutner start of ICD Code: CKD (N18*)",
    )

    def composite_prior(
        *,
        target: str,
        codes: tuple[str, ...],
        variable_label: str,
        value_label: str,
        zero: str,
        one: str,
        first_label: str,
        last_label: str,
        first_statistic: Literal["min", "max"] = "min",
    ) -> None:
        _generate_any_indicator(
            state,
            target,
            tuple(f"has_{code}" for code in codes),
        )
        first_dates: list[str] = []
        last_dates: list[str] = []
        for code in codes:
            first_date = f"{code}_first_date"
            last_date = f"{code}_last_date"
            _generate_relative_date(
                state,
                target=first_date,
                source=f"first_date_{code}",
            )
            _generate_relative_date(
                state,
                target=last_date,
                source=f"last_date_{code}",
            )
            first_dates.append(first_date)
            last_dates.append(last_date)
        state.label(target, variable_label)
        _define_and_bind_binary_label(
            state,
            variable=target,
            name=value_label,
            zero=zero,
            one=one,
        )
        _generate_row_stat(
            state,
            f"{target}_first_date",
            tuple(first_dates),
            statistic=first_statistic,
            label=first_label,
        )
        _generate_row_stat(
            state,
            f"{target}_last_date",
            tuple(last_dates),
            statistic="max",
            label=last_label,
        )
        state.drop(*(f"has_{code}" for code in codes))
        state.drop(*first_dates)
        state.drop(*last_dates)

    composite_prior(
        target="ctd",
        codes=("m05", "m06", "m30", "m31", "m32", "m33", "m34", "m35", "m36"),
        variable_label="Connective Tissue Disease",
        value_label="ctd_lab",
        zero="No CTD diagnosis",
        one="CTD diagnosed",
        first_label="First Date of ICD Code: Connective Tissue Disease",
        last_label="Last Date of ICD Code: Connective Tissue Disease",
    )
    composite_prior(
        target="dem",
        codes=("f01", "f02", "f03", "f04", "f05", "f06", "f07", "f08", "f09"),
        variable_label="Dementia",
        value_label="dem_lab",
        zero="No Dementia diagnosis",
        one="Dementia diagnosed",
        first_label="Date of First ICD Code: Dementia F01-09",
        last_label="Date of Last ICD Code: Dementia F01-09",
    )
    composite_prior(
        target="dm",
        codes=("e08", "e09", "e10", "e11", "e12", "e13"),
        variable_label="Diabetes",
        value_label="dm_lab",
        zero="No Diabetes diagnosis",
        one="Diabetes diagnosed",
        first_label="First Date ICD Code: Diabetes E08-13",
        last_label="Last Date ICD Code: Diabetes E08-13",
    )

    simple_prior(
        source="has_i70",
        target="pvd",
        variable_label="Peripheral Vascular Disease",
        value_label="pvd_lab",
        zero="No PVD diagnosis",
        one="PVD diagnosed",
        code="i70",
        first_label="First Date of ICD Code: Peripheral Vascular Disease (I70)",
        last_label=(
            "Date closest to encoutner start of ICD Code: Peripheral Vascular Disease (I70)"
        ),
    )
    simple_prior(
        source="has_f11",
        target="oud",
        variable_label="Opiate Use Disorder",
        value_label="oud_lab",
        zero="No OUD diagnosis",
        one="OUD diagnosed",
        code="f11",
        first_label="First Date of ICD Code: Opiate Use Disorder (F11*)",
        last_label="Date closest to encoutner start of ICD Code: Opiate Use Disorder (F11*)",
    )
    simple_prior(
        source="has_f13",
        target="sedatives",
        variable_label="Sedative Use Disorder",
        value_label="sed_lab",
        zero="No Sed Use d/o diagnosis",
        one="Sed Use d/o diagnosed",
        code="f13",
        first_label="First Date of ICD Code: Sedative Use (F13*)",
        last_label="Date closest to encoutner start of ICD Code: Sedative Use (F13*)",
    )
    simple_prior(
        source="has_e84",
        target="cfdo",
        variable_label="Cystic Fibrosis",
        value_label="cfdo_lab",
        zero="No CF diagnosis",
        one="CF diagnosed",
        code="e84",
        first_label="First Date of ICD Code: CF Disorder (E84*)",
        last_label="Date closest to encoutner start of ICD Code: CF Disorder (E84*)",
    )
    simple_prior(
        source="has_i27",
        target="phtn",
        variable_label="Pulmonary Hypertension",
        value_label="phtn_lab",
        zero="No Pulm HTN diagnosis",
        one="Pulm HTN diagnosed",
        code="i27",
        first_label="First Date of ICD Code: Pulmonary HTN (I27*)",
        last_label="Date closest to encoutner start of ICD Code: Pulmonary HTN (I27*)",
    )
    simple_prior(
        source="has_d751",
        target="polycy",
        variable_label="Sec Polycythemia",
        value_label="polycy_lab",
        zero="No Polycythemia diagnosis",
        one="Polycythemia diagnosed",
        code="d751",
        first_label="First Date of ICD Code: Polycythemia (D75.1)",
        last_label="Date closest to encoutner start of ICD Code: Polycythemia (D75.1)",
    )
    composite_prior(
        target="nmd",
        codes=("g12", "g14", "g70", "g35", "g71", "g95", "g36", "g37"),
        variable_label="Neuromuscular Disease",
        value_label="nmd_lab",
        zero="No NMD diagnosis",
        one="NMD diagnosed",
        first_label=(
            "First Date of ICD Code: Neuromuscular disease (g12,14,35-37,70,71,95)"
        ),
        last_label=(
            "Last Date of ICD Code: Neuromuscular disease (g12,14,35-37,70,71,95)"
        ),
    )
    composite_prior(
        target="nic",
        codes=("f17", "f12", "f18"),
        variable_label="Nicotine dependence",
        value_label="nic_lab",
        zero="No Nicotine dep. diagnosis",
        one="Nicotine dep. diagnosed",
        first_label="First Date of ICD Code: Nicotine Dependence (F12,17,18)",
        last_label="Last Date of ICD Code: Nicotine Dependence (F12,17,18)",
        first_statistic="max",
    )

    state.generate_float(
        "ovs",
        [
            int(copd == 1 and osa == 1)
            for copd, osa in zip(
                state._require("copd"),
                state._require("osa"),
                strict=True,
            )
        ],
    )
    state.label("ovs", "COPD-OSA Overlap Syndrome")
    _define_and_bind_binary_label(
        state,
        variable="ovs",
        name="ovs_label",
        zero="No OVS",
        one="OVS (OSA + COPD)",
    )

    state.label("los", "Duration of Encounter")
    _recode_in_place(
        state,
        "los",
        (RecodeRule.interval(25.1, 25.9, math.nan),),
    )

    def eligible_ohs(
        bmi: object,
        copd: object,
        chf: object,
        asthma: object,
        oud: object,
        nmd: object,
    ) -> bool:
        return stata_ge(bmi, 30) and all(
            value != 1 for value in (copd, chf, asthma, oud, nmd)
        )

    state.generate_float(
        "ats_ohs_flag",
        [
            (
                1
                if ohs_code == 1
                else math.nan
                if paco2_flag != 1
                else int(eligible_ohs(bmi, copd, chf, asthma, oud, nmd))
            )
            for bmi, copd, chf, asthma, oud, nmd, paco2_flag, ohs_code in zip(
                state._require("bmi_int"),
                state._require("copd"),
                state._require("chf"),
                state._require("asthma"),
                state._require("oud"),
                state._require("nmd"),
                state._require("paco2_flag"),
                state._require("ohs_code"),
                strict=True,
            )
        ],
    )
    state.label("ats_ohs_flag", "ATS OHS (2019) Guideline Applies")

    state.generate_float(
        "pos_ohs_flag",
        [
            int(eligible_ohs(bmi, copd, chf, asthma, oud, nmd))
            for bmi, copd, chf, asthma, oud, nmd in zip(
                state._require("bmi_int"),
                state._require("copd"),
                state._require("chf"),
                state._require("asthma"),
                state._require("oud"),
                state._require("nmd"),
                strict=True,
            )
        ],
    )
    state.label("pos_ohs_flag", "Pos OHS [includes w and w/o CO2>45mmHg]")

    state.generate_float(
        "ats_copd_flag",
        [
            (
                math.nan
                if paco2_flag != 1
                else int(
                    copd == 1
                    and all(value != 1 for value in (osa, chf, asthma, oud, nmd))
                )
            )
            for copd, osa, chf, asthma, oud, nmd, paco2_flag in zip(
                state._require("copd"),
                state._require("osa"),
                state._require("chf"),
                state._require("asthma"),
                state._require("oud"),
                state._require("nmd"),
                state._require("paco2_flag"),
                strict=True,
            )
        ],
    )
    state.label("ats_copd_flag", "ATS COPD-NIV (2021?) Guideline Applies")

    state.generate_float(
        "guidelines",
        [
            (
                math.nan
                if paco2_flag != 1
                else 2
                if ats_copd == 1
                else 1
                if ats_ohs == 1
                else 0
            )
            for ats_ohs, ats_copd, paco2_flag in zip(
                state._require("ats_ohs_flag"),
                state._require("ats_copd_flag"),
                state._require("paco2_flag"),
                strict=True,
            )
        ],
    )
    state.label("guidelines", "Which Guidelines Apply?")
    state.define_value_label(
        "guideline_val",
        {0: "Hypercapnic, but none", 1: "OHS Guideline", 2: "COPD Guideline"},
    )
    state.bind_value_label("guidelines", "guideline_val")


def clean_abg_per_file_prefix(
    raw_frame: pd.DataFrame,
    *,
    schema: RawSchema,
    setting: str,
    raw_suffix: str,
) -> PartialPerFileCleaningResult:
    """Apply the exact, shared ABG prefix through frozen source line 638.

    The caller owns CSV I/O and must supply the already verified tracked raw
    schema.  The input frame is never mutated.
    """

    context = PerFileContext.create(setting=setting, raw_suffix=raw_suffix)
    normalized, numeric_storage = _normalize_input(raw_frame, schema)
    state = _CleaningState(normalized)
    _initialize_import_formats(state, schema, numeric_storage)
    _apply_preamble_and_demographics(state, context)
    _apply_vital_signs(state)
    return PartialPerFileCleaningResult(
        frame=state.frame,
        metadata=state.metadata,
        context=context,
    )


def clean_abg_per_file(
    raw_frame: pd.DataFrame,
    *,
    schema: RawSchema,
    setting: str,
    raw_suffix: str,
) -> CompletePerFileCleaningResult:
    """Apply the complete frozen ABG transformation before its save/clear I/O."""

    return clean_per_file(
        raw_frame,
        schema=schema,
        setting=setting,
        raw_suffix=raw_suffix,
        family=RfsFamily.ABG,
    )


def clean_per_file(
    raw_frame: pd.DataFrame,
    *,
    schema: RawSchema,
    setting: str,
    raw_suffix: str,
    family: RfsFamily,
) -> CompletePerFileCleaningResult:
    """Apply frozen ``cleandata`` through line 3305 for one exact call site."""

    context = PerFileContext.create(
        setting=setting,
        raw_suffix=raw_suffix,
        family=family,
    )
    normalized, numeric_storage = _normalize_input(raw_frame, schema)
    state = _CleaningState(normalized)
    _initialize_import_formats(state, schema, numeric_storage)
    _apply_preamble_and_demographics(state, context)
    _apply_vital_signs(state)
    _apply_labs_and_acid_base(state)
    _apply_medications(state)
    _apply_procedures(state)
    _apply_current_diagnoses(state)
    _apply_prior_diagnoses_and_final_flags(state)
    _finalize_compression_metadata(state)
    return CompletePerFileCleaningResult(
        frame=state.frame,
        metadata=state.metadata,
        context=context,
    )

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import date, timedelta
from numbers import Real
from typing import Literal

import numpy as np
import pandas as pd

_STATA_EPOCH = date(1960, 1, 1)
_YMD_PATTERN = re.compile(
    r"^(?P<year>\d{4})(?:[-/. ]?)(?P<month>\d{1,2})(?:[-/. ]?)(?P<day>\d{1,2})$"
)
_YM_PATTERN = re.compile(r"^(?P<year>\d{4})(?:[-/. ]?)(?P<month>\d{1,2})$")


def is_regular_missing(value: object) -> bool:
    """Return whether a scalar represents Stata's regular numeric missing value."""

    if value is None or value is pd.NA:
        return True
    if isinstance(value, Real):
        return math.isnan(float(value))
    return False


def stata_ge(left: object, right: object) -> bool:
    """Stata scalar ``>=`` semantics for real numbers and regular missing."""

    if is_regular_missing(left):
        return True
    if is_regular_missing(right):
        return False
    return float(left) >= float(right)  # type: ignore[arg-type]


def stata_lt(left: object, right: object) -> bool:
    """Stata scalar ``<`` semantics for real numbers and regular missing."""

    if is_regular_missing(right):
        return not is_regular_missing(left)
    if is_regular_missing(left):
        return False
    return float(left) < float(right)  # type: ignore[arg-type]


def stata_date(value: object, mask: Literal["YMD", "YM"]) -> float:
    """Parse the YMD and YM date forms exercised by the frozen oracle."""

    if not isinstance(value, str) or not value:
        return math.nan
    pattern = _YMD_PATTERN if mask == "YMD" else _YM_PATTERN
    match = pattern.fullmatch(value.strip())
    if match is None:
        return math.nan
    try:
        year = int(match.group("year"))
        month = int(match.group("month"))
        day = int(match.group("day")) if mask == "YMD" else 1
        parsed = date(year, month, day)
    except ValueError:
        return math.nan
    return float((parsed - _STATA_EPOCH).days)


def stata_ym(year: object, month: object) -> float:
    """Return Stata's monthly date index, where January 1960 is zero."""

    if is_regular_missing(year) or is_regular_missing(month):
        return math.nan
    parsed_year = int(float(year))  # type: ignore[arg-type]
    parsed_month = int(float(month))  # type: ignore[arg-type]
    if parsed_month < 1 or parsed_month > 12:
        return math.nan
    return float((parsed_year - 1960) * 12 + parsed_month - 1)


def stata_month_index_from_daily(stata_day: object) -> float:
    if is_regular_missing(stata_day):
        return math.nan
    parsed = _STATA_EPOCH + timedelta(days=int(float(stata_day)))  # type: ignore[arg-type]
    return stata_ym(parsed.year, parsed.month)


def stata_relative_day(
    event_text: object,
    encounter_text: object,
    *,
    event_mask: Literal["YMD", "YM"] = "YMD",
) -> float:
    event_day = stata_date(event_text, event_mask)
    encounter_day = stata_date(encounter_text, "YMD")
    if is_regular_missing(event_day) or is_regular_missing(encounter_day):
        return math.nan
    return event_day - encounter_day


def stata_round(value: object, unit: object) -> float:
    """Match Stata ``round(x, unit)`` including its half-unit direction."""

    if is_regular_missing(value) or is_regular_missing(unit):
        return math.nan
    numeric_value = float(value)  # type: ignore[arg-type]
    numeric_unit = float(unit)  # type: ignore[arg-type]
    if not math.isfinite(numeric_value) or not math.isfinite(numeric_unit):
        return math.nan
    if numeric_unit <= 0:
        raise ValueError("Stata rounding unit must be greater than zero")
    rounded = math.floor(numeric_value / numeric_unit + 0.5) * numeric_unit
    return 0.0 if rounded == 0 else rounded


def _nonmissing(values: list[object] | tuple[object, ...]) -> list[float]:
    return [float(value) for value in values if not is_regular_missing(value)]  # type: ignore[arg-type]


def stata_row_min(values: list[object] | tuple[object, ...]) -> float:
    observed = _nonmissing(values)
    return float(np.float32(min(observed))) if observed else math.nan


def stata_row_max(values: list[object] | tuple[object, ...]) -> float:
    observed = _nonmissing(values)
    return float(np.float32(max(observed))) if observed else math.nan


def stata_row_mean(values: list[object] | tuple[object, ...]) -> float:
    observed = _nonmissing(values)
    return float(np.float32(sum(observed) / len(observed))) if observed else math.nan


def first_after(values: list[object] | tuple[object, ...]) -> float:
    """Match the frozen oracle's ``first_after`` program."""

    observed = _nonmissing(values)
    nonnegative = [value for value in observed if value >= 0]
    if nonnegative:
        return min(nonnegative)
    negative = [value for value in observed if value < 0]
    return max(negative) if negative else math.nan


@dataclass(frozen=True, slots=True)
class RecodeRule:
    lower: float | None
    upper: float | None
    replacement: float
    match_missing: bool = False

    @classmethod
    def interval(
        cls,
        lower: float | None,
        upper: float | None,
        replacement: float,
    ) -> RecodeRule:
        if lower is not None and upper is not None and lower > upper:
            raise ValueError("recode interval lower bound exceeds upper bound")
        return cls(lower, upper, replacement)

    @classmethod
    def missing(cls, replacement: float) -> RecodeRule:
        return cls(None, None, replacement, match_missing=True)

    def matches(self, value: object) -> bool:
        if is_regular_missing(value):
            return self.match_missing
        if self.match_missing:
            return False
        numeric = float(value)  # type: ignore[arg-type]
        return (self.lower is None or numeric >= self.lower) and (
            self.upper is None or numeric <= self.upper
        )


def stata_recode(
    value: object,
    rules: tuple[RecodeRule, ...],
    *,
    generated: bool = False,
) -> float:
    """Apply inclusive rules in order, preserving unmatched values.

    ``recode ..., generate()`` creates a Stata float; ``generated=True``
    reproduces that storage rounding.
    """

    result = math.nan if is_regular_missing(value) else float(value)  # type: ignore[arg-type]
    for rule in rules:
        if rule.matches(value):
            result = rule.replacement
            break
    if generated and not is_regular_missing(result):
        return float(np.float32(result))
    return result


def stata_default_numeric_text(value: object) -> str:
    """Match Stata ``strofreal(x, "%9.0g")`` for certified integer IDs.

    The frozen preprocessing oracle uses default numeric conversion only while
    concatenating patient and encounter identifiers. Nonintegral values are
    rejected until an executable golden certifies that broader domain.
    """

    if is_regular_missing(value):
        return "."
    numeric = float(value)  # type: ignore[arg-type]
    if not math.isfinite(numeric):
        raise ValueError(
            "Stata numeric text requires a finite value or regular missing"
        )
    if not numeric.is_integer():
        raise ValueError(
            "Default Stata numeric text is certified only for integer identifiers"
        )
    integer = int(numeric)
    if abs(integer) < 10_000_000:
        return str(integer)

    precision = 2
    rendered = format(numeric, f".{precision}e")
    while len(rendered) > 9 and precision > 0:
        precision -= 1
        rendered = format(numeric, f".{precision}e")
    if len(rendered) > 9:
        raise ValueError(
            "Numeric identifier cannot be represented by Stata's %9.0g format"
        )
    return rendered


def stata_concat(
    values: list[object] | tuple[object, ...],
    *,
    punct: str = "",
) -> str:
    """Match the frozen ``egen concat`` domain used for identifier keys.

    Strings (and ``None`` as explicit string missing) remain strings. Real
    numbers use the certified integer-ID conversion above. ``pd.NA`` is
    rejected because it does not carry enough source-type information to
    distinguish Stata string missing from numeric missing.
    """

    pieces: list[str] = []
    for value in values:
        if isinstance(value, str):
            pieces.append(value)
        elif value is None:
            pieces.append("")
        elif value is pd.NA:
            raise ValueError("pd.NA is ambiguous in Stata concatenation")
        else:
            pieces.append(stata_default_numeric_text(value))
    return punct.join(pieces).strip(" ")

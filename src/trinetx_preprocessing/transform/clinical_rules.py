"""Typed clinical-code and numeric eligibility rules."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


def _normalize_text(value: object) -> str:
    if pd.isna(value):
        return ""
    return str(value).strip().upper()


@dataclass(frozen=True)
class CodeRule:
    """A named set of exact codes and literal code prefixes."""

    name: str
    exact_codes: tuple[str, ...] = ()
    prefixes: tuple[str, ...] = ()
    allowed_code_systems: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("Code rule name must not be empty.")
        if not self.exact_codes and not self.prefixes:
            raise ValueError(f"Code rule {self.name!r} must define codes or prefixes.")
        object.__setattr__(
            self,
            "exact_codes",
            tuple(_normalize_text(value) for value in self.exact_codes),
        )
        object.__setattr__(
            self,
            "prefixes",
            tuple(_normalize_text(value) for value in self.prefixes),
        )
        object.__setattr__(
            self,
            "allowed_code_systems",
            tuple(_normalize_text(value) for value in self.allowed_code_systems),
        )

    def matches(self, code: object, code_system: object | None = None) -> bool:
        """Return whether one code and optional system satisfy the rule."""

        normalized_code = _normalize_text(code)
        if not normalized_code:
            return False
        if self.allowed_code_systems and code_system is not None:
            if _normalize_text(code_system) not in self.allowed_code_systems:
                return False
        return normalized_code in self.exact_codes or normalized_code.startswith(
            self.prefixes
        )

    def mask(
        self,
        codes: pd.Series,
        *,
        code_systems: pd.Series | None = None,
    ) -> pd.Series:
        """Return a vectorized mask for a code series."""

        normalized = codes.astype("string").str.strip().str.upper()
        mask = normalized.isin(self.exact_codes)
        if self.prefixes:
            mask |= normalized.str.startswith(self.prefixes, na=False)
        if self.allowed_code_systems and code_systems is not None:
            systems = code_systems.astype("string").str.strip().str.upper()
            mask &= systems.isin(self.allowed_code_systems)
        return mask.fillna(False)


@dataclass(frozen=True)
class NumericCodeRule(CodeRule):
    """Code rule with units and an open or closed numeric interval."""

    min_value: float | None = None
    max_value: float | None = None
    min_inclusive: bool = False
    max_inclusive: bool = False
    canonical_unit: str | None = None
    unit_factors: tuple[tuple[str, float], ...] = ()


@dataclass(frozen=True)
class RuleAudit:
    """Aggregate, non-row-level diagnostics from one rule application."""

    considered: int
    accepted: int
    rejected_code_system: int
    rejected_unit: int
    rejected_non_numeric: int
    rejected_range: int


@dataclass(frozen=True)
class NumericRuleResult:
    """Rows accepted by a numeric rule plus aggregate diagnostics."""

    rows: pd.DataFrame
    audit: RuleAudit


def apply_numeric_code_rule(
    frame: pd.DataFrame,
    rule: NumericCodeRule,
    *,
    value_column: str,
    code_column: str = "code",
    code_system_column: str = "code_system",
    unit_column: str = "units_of_measure",
) -> NumericRuleResult:
    """Apply code, system, unit, conversion, and range checks in float64."""

    codes = frame[code_column].astype("string")
    code_mask = rule.mask(codes)
    considered_rows = frame.loc[code_mask].copy()
    considered = len(considered_rows)
    if considered_rows.empty:
        return NumericRuleResult(
            rows=considered_rows,
            audit=RuleAudit(0, 0, 0, 0, 0, 0),
        )

    valid_system = pd.Series(True, index=considered_rows.index)
    if rule.allowed_code_systems:
        if code_system_column not in considered_rows:
            valid_system &= False
        else:
            systems = (
                considered_rows[code_system_column]
                .astype("string")
                .str.strip()
                .str.upper()
            )
            valid_system &= systems.isin(rule.allowed_code_systems)

    converted = pd.to_numeric(considered_rows[value_column], errors="coerce").astype(
        "float64"
    )
    finite = pd.Series(np.isfinite(converted), index=converted.index)

    valid_unit = pd.Series(True, index=considered_rows.index)
    if rule.unit_factors:
        valid_unit &= False
        if unit_column in considered_rows:
            units = (
                considered_rows[unit_column].astype("string").str.strip().str.lower()
            )
            for raw_unit, factor in rule.unit_factors:
                unit_mask = (units == raw_unit.strip().lower()).fillna(False)
                converted.loc[unit_mask] *= factor
                valid_unit |= unit_mask

    in_range = pd.Series(True, index=considered_rows.index)
    if rule.min_value is not None:
        if rule.min_inclusive:
            in_range &= converted >= rule.min_value
        else:
            in_range &= converted > rule.min_value
    if rule.max_value is not None:
        if rule.max_inclusive:
            in_range &= converted <= rule.max_value
        else:
            in_range &= converted < rule.max_value

    accepted_mask = (valid_system & valid_unit & finite & in_range).fillna(False)
    accepted = considered_rows.loc[accepted_mask].copy()
    accepted[value_column] = converted.loc[accepted_mask]
    return NumericRuleResult(
        rows=accepted.reset_index(drop=True),
        audit=RuleAudit(
            considered=considered,
            accepted=len(accepted),
            rejected_code_system=int((~valid_system).sum()),
            rejected_unit=int((valid_system & ~valid_unit).sum()),
            rejected_non_numeric=int((valid_system & valid_unit & ~finite).sum()),
            rejected_range=int((valid_system & valid_unit & finite & ~in_range).sum()),
        ),
    )


def exact_code_rule(name: str, *codes: str) -> CodeRule:
    """Build a readable exact-code rule."""

    return CodeRule(name=name, exact_codes=tuple(codes))


def prefix_code_rule(name: str, *prefixes: str) -> CodeRule:
    """Build a readable literal-prefix rule."""

    return CodeRule(name=name, prefixes=tuple(prefixes))

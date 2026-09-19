"""Versioned measurement windows inherited from the accepted source derivation."""

from dataclasses import dataclass


@dataclass(frozen=True)
class FeatureConfig:
    lookback_days: int = 730
    measurement_lookback_days: int = 365
    medication_lookback_days: int = 730
    followup_days: int = 365

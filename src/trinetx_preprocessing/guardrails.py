"""Performance guardrails and row-count logging helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import pandas as pd


@dataclass(frozen=True)
class GuardrailConfig:
    """Configuration for performance guardrails."""

    max_join_multiplier: float = 1.0


def log_row_count(logger, label: str, rows: int) -> None:
    """Log a row-count boundary for diagnostics."""

    logger.info("Row count %s: %s", label, rows)


def check_join_multiplier(
    left_rows: int,
    merged_rows: int,
    max_multiplier: float,
    *,
    context: str,
) -> None:
    """Ensure joins do not exceed the configured row multiplier."""

    if max_multiplier <= 0:
        raise ValueError("Guardrail max_join_multiplier must be positive.")
    if left_rows == 0:
        if merged_rows > 0:
            raise ValueError(
                f"Join in {context} produced {merged_rows} rows from empty input."
            )
        return
    allowed = left_rows * max_multiplier
    if merged_rows > allowed:
        raise ValueError(
            f"Join in {context} produced {merged_rows} rows, exceeding {allowed:.2f}."
        )


def check_required_ids(
    df: pd.DataFrame,
    required: Sequence[str],
    *,
    context: str,
) -> None:
    """Ensure required identifier columns are present and non-null."""

    missing = [column for column in required if column not in df.columns]
    if missing:
        missing_list = ", ".join(missing)
        raise ValueError(f"{context} is missing required IDs: {missing_list}")

    if df.loc[:, required].isna().any().any():
        raise ValueError(f"{context} contains missing required IDs.")

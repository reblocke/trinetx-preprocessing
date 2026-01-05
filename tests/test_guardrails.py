from __future__ import annotations

import pandas as pd
import pytest

from trinetx_preprocessing.guardrails import (
    check_join_multiplier,
    check_required_ids,
)


def test_check_join_multiplier_allows_within_limit() -> None:
    check_join_multiplier(10, 12, 1.5, context="demo")


def test_check_join_multiplier_raises_on_explosion() -> None:
    with pytest.raises(ValueError, match="exceed"):
        check_join_multiplier(10, 25, 2.0, context="demo")


def test_check_required_ids_raises_on_missing_column() -> None:
    frame = pd.DataFrame({"patient_id": ["P1"]})
    with pytest.raises(ValueError, match="missing required IDs"):
        check_required_ids(frame, ["patient_id", "encounter_id"], context="test")


def test_check_required_ids_raises_on_nulls() -> None:
    frame = pd.DataFrame({"patient_id": ["P1", None], "encounter_id": ["E1", "E2"]})
    with pytest.raises(ValueError, match="missing required IDs"):
        check_required_ids(frame, ["patient_id", "encounter_id"], context="test")


def test_check_required_ids_passes() -> None:
    frame = pd.DataFrame({"patient_id": ["P1"], "encounter_id": ["E1"]})
    check_required_ids(frame, ["patient_id", "encounter_id"], context="test")

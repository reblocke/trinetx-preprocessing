from __future__ import annotations

from pathlib import Path

import pandas as pd

from trinetx_preprocessing.transform.encounter import (
    ALLOWED_ENCOUNTER_TYPES,
    ENCOUNTER_COLUMNS,
    filter_encounters_by_type,
    finalize_encounters,
    normalize_encounter_chunk,
)

FIXTURE_PATH = (
    Path(__file__).resolve().parent / "fixtures" / "encounter" / "encounter0001.csv"
)


def _load_fixture() -> pd.DataFrame:
    return pd.read_csv(FIXTURE_PATH, parse_dates=["start_date", "end_date"])


def test_normalize_encounter_chunk_filters_types() -> None:
    df = _load_fixture()

    normalized = normalize_encounter_chunk(df)

    assert list(normalized.columns) == ENCOUNTER_COLUMNS
    assert set(normalized["type"]) <= ALLOWED_ENCOUNTER_TYPES
    assert "derived_by_TriNetX" not in normalized.columns
    assert len(normalized) == 6


def test_finalize_ambulatory_encounters() -> None:
    normalized = normalize_encounter_chunk(_load_fixture())
    filtered = filter_encounters_by_type(normalized, "AMB")
    finalized = finalize_encounters(filtered)

    assert len(finalized) == 1
    row = finalized.iloc[0]
    assert row["encounter_id"] == "E1"
    assert row["start_date"] == pd.Timestamp("2022-01-01")
    assert row["end_date"] == pd.Timestamp("2022-01-03")
    assert row["LOS"] == 3


def test_finalize_emergency_encounters_fill_end_date() -> None:
    normalized = normalize_encounter_chunk(_load_fixture())
    filtered = filter_encounters_by_type(normalized, "EMER")
    finalized = finalize_encounters(filtered)

    assert len(finalized) == 1
    row = finalized.iloc[0]
    expected_end = pd.Timestamp("2022-12-31")
    expected_los = (expected_end - pd.Timestamp("2022-02-01")).days + 1
    assert row["end_date"] == expected_end
    assert row["LOS"] == expected_los


def test_finalize_inpatient_encounters_removes_negative_los() -> None:
    normalized = normalize_encounter_chunk(_load_fixture())
    filtered = filter_encounters_by_type(normalized, "IMP")
    finalized = finalize_encounters(filtered)

    assert list(finalized["encounter_id"]) == ["E5"]
    assert finalized.iloc[0]["LOS"] == 1

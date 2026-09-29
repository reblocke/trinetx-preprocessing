from __future__ import annotations

from pathlib import Path

import pandas as pd

from trinetx_preprocessing.transform.diagnosis import (
    normalize_diagnosis_chunk,
    split_diagnosis_by_code,
)

FIXTURE_PATH = (
    Path(__file__).resolve().parent / "fixtures" / "diagnosis" / "diagnosis0001.csv"
)


def _load_fixture() -> pd.DataFrame:
    return pd.read_csv(FIXTURE_PATH, parse_dates=["date"])


def test_j46_includes_corrected_j4542_code() -> None:
    frame = normalize_diagnosis_chunk(_load_fixture()).iloc[[0]].copy()
    frame["code"] = "J45.42"

    assert split_diagnosis_by_code(frame)["HAS_J46"]["code"].tolist() == ["J45.42"]


def test_split_diagnosis_preserves_duplicate_overlapping_rows() -> None:
    df = normalize_diagnosis_chunk(_load_fixture())
    duplicated = pd.concat([df, df.loc[[2]]], ignore_index=True)

    groups = split_diagnosis_by_code(duplicated)

    assert groups["HAS_G473"]["code"].tolist().count("G47.34") == 2
    assert groups["HAS_G4734"]["code"].tolist() == ["G47.34", "G47.34"]

from __future__ import annotations

from pathlib import Path

import pandas as pd

from trinetx_preprocessing.transform.medications import (
    normalize_medications_chunk,
    split_medications_by_code,
)

FIXTURE_PATH = (
    Path(__file__).resolve().parent / "fixtures" / "medications" / "medication0001.csv"
)


def _load_fixture() -> pd.DataFrame:
    return pd.read_csv(FIXTURE_PATH, parse_dates=["start_date"])


def test_split_medications_preserves_duplicate_overlapping_rows() -> None:
    df = normalize_medications_chunk(_load_fixture())
    duplicated = pd.concat([df, df.loc[[2]]], ignore_index=True)

    groups = split_medications_by_code(duplicated)

    assert groups["IPmed_list3"]["code"].tolist() == ["7213", "7213"]
    assert groups["OPmed_list5"]["code"].tolist() == ["7213", "7213"]

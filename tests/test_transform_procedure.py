from __future__ import annotations

from pathlib import Path

import pandas as pd

from trinetx_preprocessing.transform.procedure import (
    normalize_procedure_chunk,
    split_procedure_by_code,
)

FIXTURE_PATH = (
    Path(__file__).resolve().parent / "fixtures" / "procedure" / "procedure0001.csv"
)


def _load_fixture() -> pd.DataFrame:
    return pd.read_csv(FIXTURE_PATH, parse_dates=["date"])


def test_tte_excludes_legacy_typos_and_non_tte_modalities() -> None:
    template = normalize_procedure_chunk(_load_fixture()).iloc[[0]]
    codes = [
        "93303",
        "93304",
        "93306",
        "93307",
        "93308",
        "93356",
        "99304",
        "93312",
        "93350",
    ]
    frame = pd.concat([template] * len(codes), ignore_index=True)
    frame["code"] = codes

    assert split_procedure_by_code(frame)["HAS_TTE"]["code"].tolist() == codes[:6]


def test_split_procedure_preserves_duplicate_overlapping_rows() -> None:
    df = normalize_procedure_chunk(_load_fixture())
    duplicated = pd.concat([df, df.loc[[1]]], ignore_index=True)

    groups = split_procedure_by_code(duplicated)

    assert groups["HAS_TTE"]["code"].tolist() == ["93306", "93306"]

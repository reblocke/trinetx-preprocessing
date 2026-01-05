from __future__ import annotations

from pathlib import Path

import pandas as pd

from trinetx_preprocessing.transform.procedure import (
    PROCEDURE_COLUMNS,
    normalize_procedure_chunk,
    split_procedure_by_code,
)

FIXTURE_PATH = (
    Path(__file__).resolve().parent / "fixtures" / "procedure" / "procedure0001.csv"
)


def _load_fixture() -> pd.DataFrame:
    return pd.read_csv(FIXTURE_PATH, parse_dates=["date"])


def test_normalize_procedure_chunk_structure() -> None:
    df = _load_fixture()

    normalized = normalize_procedure_chunk(df)

    assert list(normalized.columns) == PROCEDURE_COLUMNS
    assert len(normalized) == 13
    assert "code_system" not in normalized.columns
    assert pd.isna(normalized.loc[12, "date"])


def test_split_procedure_by_code_groups() -> None:
    df = normalize_procedure_chunk(_load_fixture())

    groups = split_procedure_by_code(df)

    assert groups["HAS_94660"]["code"].tolist() == ["94660"]
    assert groups["HAS_TTE"]["code"].tolist() == ["93306"]
    assert groups["HAS_99291"]["code"].tolist() == ["99292"]
    assert groups["HAS_CT_ABDM"]["code"].tolist() == ["74150"]
    assert groups["HAS_61911006"]["code"].tolist() == ["61911006"]

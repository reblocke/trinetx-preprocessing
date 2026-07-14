from __future__ import annotations

from pathlib import Path

import pandas as pd

from trinetx_preprocessing.transform.labs import (
    NORMALIZED_LAB_COLUMNS,
    normalize_lab_results_chunk,
)

FIXTURE_PATH = (
    Path(__file__).resolve().parent / "fixtures" / "labs" / "lab_results0001.csv"
)


def _load_fixture() -> pd.DataFrame:
    return pd.read_csv(FIXTURE_PATH, parse_dates=["date"])


def test_normalize_lab_results_chunk_structure() -> None:
    df = _load_fixture()

    normalized = normalize_lab_results_chunk(df)

    assert list(normalized.columns) == NORMALIZED_LAB_COLUMNS
    assert len(normalized) == 3
    assert normalized.loc[0, "code_system"] == "LOINC"
    assert normalized.loc[0, "units_of_measure"] == "mmol/L"
    assert normalized["code"].tolist() == ["6298-4", "2019-8", "2823-3"]
    assert pd.isna(normalized.loc[1, "lab_result_num_val"])

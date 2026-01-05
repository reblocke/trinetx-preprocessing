from __future__ import annotations

import pandas as pd

from trinetx_preprocessing.regression import hash_csv, hash_table, normalize_table


def test_normalize_table_sorts_columns_and_rows() -> None:
    df = pd.DataFrame({"b": [2, 1], "a": [2, 1]})

    normalized = normalize_table(df)

    assert list(normalized.columns) == ["a", "b"]
    assert normalized.iloc[0].to_dict() == {"a": 1, "b": 1}
    assert normalized.iloc[1].to_dict() == {"a": 2, "b": 2}


def test_hash_table_is_deterministic_for_ordering() -> None:
    df_a = pd.DataFrame({"b": [2, 1], "a": [2, 1]})
    df_b = pd.DataFrame({"a": [1, 2], "b": [1, 2]})

    assert hash_table(df_a) == hash_table(df_b)


def test_hash_csv_matches_table(tmp_path) -> None:
    df = pd.DataFrame({"b": ["2", "1"], "a": ["2", "1"]})
    path = tmp_path / "sample.csv"
    df.to_csv(path, index=False)

    assert hash_csv(path) == hash_table(df)

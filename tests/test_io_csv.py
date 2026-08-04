from __future__ import annotations

import csv
from pathlib import Path

import pandas as pd
from pandas.testing import assert_frame_equal

from trinetx_preprocessing.io.csv import (
    LEGACY_READ_CSV_NA_TOKENS,
    coerce_legacy_na_tokens,
    iter_csv,
)


def _write_csv(path: Path, rows: list[list[str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["col1", "col2"])
        writer.writerows(rows)


def test_iter_csv_yields_chunks(tmp_path: Path) -> None:
    input_csv = tmp_path / "sample.csv"
    rows = [["1", "a"], ["2", "b"], ["3", "c"], ["4", "d"], ["5", "e"]]
    _write_csv(input_csv, rows)

    chunks = list(iter_csv(input_csv, chunksize=2))

    assert [len(chunk) for chunk in chunks] == [2, 2, 1]
    assert list(chunks[0].columns) == ["col1", "col2"]


def test_iter_csv_preserves_literal_na_like_source_tokens(tmp_path: Path) -> None:
    input_csv = tmp_path / "source.csv"
    _write_csv(
        input_csv,
        [
            ["NA", "N/A"],
            ["NULL", ""],
        ],
    )

    frame = next(
        iter_csv(
            input_csv,
            dtype="string",
            preserve_source_tokens=True,
        )
    )

    assert frame.loc[0].tolist() == ["NA", "N/A"]
    assert frame.loc[1, "col1"] == "NULL"
    assert pd.isna(frame.loc[1, "col2"])


def test_legacy_na_coercion_matches_default_read_csv_without_mutating_source(
    tmp_path: Path,
) -> None:
    expected_tokens = {
        "",
        "#N/A",
        "#N/A N/A",
        "#NA",
        "-1.#IND",
        "-1.#QNAN",
        "-NaN",
        "-nan",
        "1.#IND",
        "1.#QNAN",
        "<NA>",
        "N/A",
        "NA",
        "NULL",
        "NaN",
        "None",
        "n/a",
        "nan",
        "null",
    }
    assert LEGACY_READ_CSV_NA_TOKENS == expected_tokens
    input_csv = tmp_path / "legacy-na.csv"
    _write_csv(
        input_csv,
        [
            *[[token, "ordinary"] for token in sorted(expected_tokens)],
            [" NULL ", "Null"],
            ["NONE", "none"],
        ],
    )

    legacy = next(iter_csv(input_csv, dtype="string"))
    source = next(
        iter_csv(
            input_csv,
            dtype="string",
            preserve_source_tokens=True,
        )
    )
    source_before = source.copy(deep=True)

    transformed = coerce_legacy_na_tokens(source)

    assert_frame_equal(transformed, legacy)
    assert_frame_equal(source, source_before)
    assert source.iloc[-2:].values.tolist() == [
        [" NULL ", "Null"],
        ["NONE", "none"],
    ]

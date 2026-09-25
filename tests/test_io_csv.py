from __future__ import annotations

import csv
from pathlib import Path

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

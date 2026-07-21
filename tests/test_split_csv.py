from __future__ import annotations

import csv
from pathlib import Path

from trinetx_preprocessing.tools.split_csv import DEFAULT_SUFFIX_WIDTH, split_csv


def _write_csv(path: Path, rows: list[list[str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["col1", "col2"])
        writer.writerows(rows)


def test_split_csv_creates_chunks_with_headers(tmp_path: Path) -> None:
    input_csv = tmp_path / "encounter.csv"
    rows = [["1", "a"], ["2", "b"], ["3", "c"], ["4", "d"], ["5", "e"]]
    _write_csv(input_csv, rows)

    out_dir = tmp_path / "chunks"
    output_paths = split_csv(input_csv, out_dir, lines_per_chunk=2, prefix="encounter")

    expected_suffixes = [
        str(index).zfill(DEFAULT_SUFFIX_WIDTH) for index in range(1, 4)
    ]
    expected_names = [f"encounter{suffix}.csv" for suffix in expected_suffixes]
    assert [path.name for path in output_paths] == expected_names

    total_rows = 0
    for path in output_paths:
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.reader(handle)
            header = next(reader)
            assert header == ["col1", "col2"]
            chunk_rows = list(reader)
            assert len(chunk_rows) <= 2
            total_rows += len(chunk_rows)

    assert total_rows == len(rows)

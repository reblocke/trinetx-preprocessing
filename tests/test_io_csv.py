from __future__ import annotations

import csv
from pathlib import Path

from trinetx_preprocessing.io.csv import iter_csv


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

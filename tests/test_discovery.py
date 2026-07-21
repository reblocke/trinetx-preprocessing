from __future__ import annotations

from pathlib import Path

from trinetx_preprocessing.discovery import detect_chunked, discover_domain_files


def _touch_csv(path: Path) -> None:
    path.write_text("col1\n1\n")


def test_discover_domain_files_chunked_sorted(tmp_path: Path) -> None:
    for name in ["encounter0002.csv", "encounter0001.csv", "encounter0003.csv"]:
        _touch_csv(tmp_path / name)

    result = discover_domain_files(tmp_path, "encounter*.csv")

    assert [path.name for path in result] == [
        "encounter0001.csv",
        "encounter0002.csv",
        "encounter0003.csv",
    ]
    assert detect_chunked(result) is True


def test_discover_domain_files_unchunked(tmp_path: Path) -> None:
    file_path = tmp_path / "encounter.csv"
    _touch_csv(file_path)

    result = discover_domain_files(tmp_path, "encounter*.csv")

    assert result == [file_path]
    assert detect_chunked(result) is False


def test_discover_domain_files_prefers_chunked(tmp_path: Path) -> None:
    _touch_csv(tmp_path / "encounter.csv")
    _touch_csv(tmp_path / "encounter0001.csv")

    result = discover_domain_files(tmp_path, "encounter*.csv")

    assert [path.name for path in result] == ["encounter0001.csv"]

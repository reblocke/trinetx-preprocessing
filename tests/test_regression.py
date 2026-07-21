from __future__ import annotations

import json

import pandas as pd
import pytest

from trinetx_preprocessing.regression import (
    TableHashEntry,
    collect_directory_entries,
    collect_directory_hashes,
    compare_manifest_entries,
    hash_csv,
    hash_csv_with_metadata,
    hash_parquet,
    hash_parquet_with_metadata,
    hash_table,
    load_hash_manifest,
    load_hash_manifest_entries,
    normalize_table,
    write_hash_manifest,
)


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


def test_hash_csv_matches_table_across_small_chunks(tmp_path) -> None:
    df = pd.DataFrame(
        {
            "b": ["2", "1", "2", "contains,comma", 'contains"quote'],
            "a": ["z", "y", "x", "w", "v"],
        }
    )
    path = tmp_path / "sample.csv"
    df.to_csv(path, index=False)

    result = hash_csv_with_metadata(path, chunk_rows=2)

    assert result.hash == hash_table(df)
    assert result.row_count == 5
    assert result.columns == ("b", "a")
    assert not list(tmp_path.glob(".trinetx-hash-*"))


def test_hash_csv_rejects_invalid_chunk_rows(tmp_path) -> None:
    path = tmp_path / "sample.csv"
    pd.DataFrame({"a": ["1"]}).to_csv(path, index=False)

    with pytest.raises(ValueError, match="chunk_rows"):
        hash_csv(path, chunk_rows=0)


def test_hash_parquet_matches_table(tmp_path) -> None:
    df = pd.DataFrame({"b": ["2", "1"], "a": ["2", "1"]})
    path = tmp_path / "sample.parquet"
    df.to_parquet(path, index=False)

    assert hash_parquet(path) == hash_table(df)


def test_hash_parquet_matches_table_across_small_batches(tmp_path) -> None:
    df = pd.DataFrame(
        {
            "b": ["2", "1", "2", "contains,comma", 'contains"quote'],
            "a": ["z", "y", "x", "w", "v"],
        }
    )
    path = tmp_path / "sample.parquet"
    df.to_parquet(path, index=False, row_group_size=2)

    result = hash_parquet_with_metadata(path, chunk_rows=2)

    assert result.hash == hash_table(df)
    assert result.row_count == 5
    assert result.columns == ("b", "a")
    assert not list(tmp_path.glob(".trinetx-hash-*"))


def test_hash_parquet_rejects_invalid_chunk_rows(tmp_path) -> None:
    path = tmp_path / "sample.parquet"
    pd.DataFrame({"a": ["1"]}).to_parquet(path, index=False)

    with pytest.raises(ValueError, match="chunk_rows"):
        hash_parquet(path, chunk_rows=0)


def test_hash_csv_and_parquet_match_for_csv_visible_values(tmp_path) -> None:
    df = pd.DataFrame(
        {
            "float_value": [55.0, 60.5],
            "int_value": [1, 2],
            "blank_value": ["", None],
            "date_value": pd.to_datetime(["2022-01-01", "2022-01-02"]),
        }
    )
    csv_path = tmp_path / "sample.csv"
    parquet_path = tmp_path / "sample.parquet"
    df.to_csv(csv_path, index=False)
    df.to_parquet(parquet_path, index=False)

    assert hash_csv(csv_path) == hash_parquet(parquet_path)


def test_table_hash_entry_uses_chunked_parquet_metadata(tmp_path) -> None:
    work_dir = tmp_path / "work"
    output_dir = tmp_path / "output"
    work_dir.mkdir()
    output_dir.mkdir()
    path = work_dir / "sample.parquet"
    pd.DataFrame({"b": ["2", "1", "3"], "a": ["z", "y", "x"]}).to_parquet(
        path,
        index=False,
        row_group_size=1,
    )

    entries = collect_directory_entries(
        work_dir=work_dir,
        output_dir=output_dir,
        scope="work",
        csv_chunk_rows=1,
    )
    entry = entries["work_dir/sample.csv"]

    assert entry.row_count == 3
    assert entry.columns == ("b", "a")
    assert entry.physical_format == "parquet"
    assert not list(work_dir.glob(".trinetx-hash-*"))


def test_collect_directory_hashes_normalizes_parquet_work_keys(tmp_path) -> None:
    work_dir = tmp_path / "work"
    output_dir = tmp_path / "output"
    work_dir.mkdir()
    output_dir.mkdir()
    pd.DataFrame({"patient_id": ["P1"]}).to_parquet(
        work_dir / "RFS_ABG.parquet",
        index=False,
    )
    pd.DataFrame({"patient_id": ["P1"]}).to_csv(
        output_dir / "RFS_ABG_ENC_AMB_AFTER.csv",
        index=False,
    )

    hashes = collect_directory_hashes(work_dir=work_dir, output_dir=output_dir)

    assert sorted(hashes) == [
        "output_dir/RFS_ABG_ENC_AMB_AFTER.csv",
        "work_dir/RFS_ABG.csv",
    ]


def test_collect_directory_hashes_allows_identical_duplicate_logical_keys(
    tmp_path,
) -> None:
    work_dir = tmp_path / "work"
    output_dir = tmp_path / "output"
    work_dir.mkdir()
    output_dir.mkdir()
    df = pd.DataFrame({"value": [55.0]})
    df.to_csv(work_dir / "A.csv", index=False)
    df.to_parquet(work_dir / "A.parquet", index=False)

    hashes = collect_directory_hashes(work_dir=work_dir, output_dir=output_dir)

    assert sorted(hashes) == ["work_dir/A.csv"]


def test_collect_directory_hashes_rejects_conflicting_duplicate_logical_keys(
    tmp_path,
) -> None:
    work_dir = tmp_path / "work"
    output_dir = tmp_path / "output"
    work_dir.mkdir()
    output_dir.mkdir()
    pd.DataFrame({"value": [1.0]}).to_csv(work_dir / "A.csv", index=False)
    pd.DataFrame({"value": [2.0]}).to_parquet(work_dir / "A.parquet", index=False)

    with pytest.raises(ValueError, match="Conflicting duplicate logical output"):
        collect_directory_hashes(work_dir=work_dir, output_dir=output_dir)


def test_collect_directory_entries_supports_final_scope(tmp_path) -> None:
    work_dir = tmp_path / "work"
    output_dir = tmp_path / "output"
    work_dir.mkdir()
    output_dir.mkdir()
    output_path = output_dir / "RFS_ABG_ENC_AMB_AFTER.csv"
    pd.DataFrame({"patient_id": ["P1"]}).to_csv(output_path, index=False)

    entries = collect_directory_entries(
        work_dir=work_dir,
        output_dir=output_dir,
        scope="final",
        csv_chunk_rows=1,
    )

    assert sorted(entries) == ["output_dir/RFS_ABG_ENC_AMB_AFTER.csv"]
    entry = entries["output_dir/RFS_ABG_ENC_AMB_AFTER.csv"]
    assert entry.row_count == 1
    assert entry.columns == ("patient_id",)
    assert entry.physical_format == "csv"
    assert entry.source_size_bytes == output_path.stat().st_size
    assert entry.source_mtime_ns == output_path.stat().st_mtime_ns


def test_collect_directory_entries_ignores_noise_paths(tmp_path) -> None:
    work_dir = tmp_path / "work"
    output_dir = tmp_path / "output"
    work_dir.mkdir()
    output_dir.mkdir()
    pd.DataFrame({"patient_id": ["P1"]}).to_csv(
        output_dir / "RFS_ABG_ENC_AMB_AFTER.csv",
        index=False,
    )
    pd.DataFrame({"patient_id": ["SIDE"]}).to_csv(
        output_dir / "._RFS_ABG_ENC_AMB_AFTER.csv",
        index=False,
    )
    scratch_dir = output_dir / ".trinetx-hash-leftover"
    scratch_dir.mkdir()
    pd.DataFrame({"patient_id": ["SCRATCH"]}).to_csv(
        scratch_dir / "chunk-000000.csv",
        index=False,
    )
    macos_dir = output_dir / "__MACOSX"
    macos_dir.mkdir()
    pd.DataFrame({"patient_id": ["ARCHIVE"]}).to_csv(
        macos_dir / "RFS_ABG_ENC_AMB_AFTER.csv",
        index=False,
    )

    entries = collect_directory_entries(
        work_dir=work_dir,
        output_dir=output_dir,
        scope="final",
        csv_chunk_rows=1,
    )

    assert sorted(entries) == ["output_dir/RFS_ABG_ENC_AMB_AFTER.csv"]
    assert entries["output_dir/RFS_ABG_ENC_AMB_AFTER.csv"].row_count == 1


def test_write_hash_manifest_writes_metadata_and_loads_hashes(tmp_path) -> None:
    out_dir = tmp_path / "manifest"
    entry = TableHashEntry(
        key="output_dir/a.csv",
        hash="abc",
        row_count=2,
        columns=("a", "b"),
        physical_format="csv",
        source_path="/tmp/a.csv",
    )

    manifest_path = write_hash_manifest(
        out_dir,
        {entry.key: entry},
        scope="final",
        output_dir=tmp_path / "output",
        generated_at="2026-06-08T00:00:00+00:00",
    )
    raw = json.loads(manifest_path.read_text())

    assert raw["schema_version"] == 2
    assert raw["generated_at"] == "2026-06-08T00:00:00+00:00"
    assert raw["hashes"] == {"output_dir/a.csv": "abc"}
    assert raw["scope"] == "final"
    assert raw["output_dir"] == str((tmp_path / "output").resolve())
    assert raw["tables"][0]["row_count"] == 2
    assert load_hash_manifest(out_dir) == {"output_dir/a.csv": "abc"}
    assert load_hash_manifest_entries(out_dir)["output_dir/a.csv"] == entry


def test_write_hash_manifest_rejects_invalid_scope(tmp_path) -> None:
    with pytest.raises(ValueError, match="Hash scope must be one of"):
        write_hash_manifest(
            tmp_path / "manifest",
            {"output_dir/a.csv": "abc"},
            scope="invalid",  # type: ignore[arg-type]
        )


def test_load_hash_manifest_entries_reads_v1_hashes(tmp_path) -> None:
    out_dir = tmp_path / "manifest"
    out_dir.mkdir()
    (out_dir / "hashes.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "hash_algorithm": "sha256",
                "hashes": {"output_dir/a.csv": "abc"},
            }
        )
    )

    entries = load_hash_manifest_entries(out_dir)

    assert entries["output_dir/a.csv"].hash == "abc"
    assert entries["output_dir/a.csv"].row_count is None


def test_compare_manifest_entries_reports_metadata_mismatches() -> None:
    baseline = {
        "output_dir/a.csv": TableHashEntry(
            key="output_dir/a.csv",
            hash="abc",
            row_count=2,
            columns=("a", "b"),
        )
    }
    current = {
        "output_dir/a.csv": TableHashEntry(
            key="output_dir/a.csv",
            hash="def",
            row_count=3,
            columns=("a", "c"),
        )
    }

    result = compare_manifest_entries(current, baseline)

    assert not result.ok
    assert result.hash_mismatched == {"output_dir/a.csv": ("abc", "def")}
    assert result.row_count_mismatched == {"output_dir/a.csv": (2, 3)}
    assert result.columns_mismatched == {"output_dir/a.csv": (("a", "b"), ("a", "c"))}


def test_compare_manifest_entries_reports_order_only_column_mismatches() -> None:
    baseline = {
        "output_dir/a.csv": TableHashEntry(
            key="output_dir/a.csv",
            hash="abc",
            row_count=2,
            columns=("a", "b"),
        )
    }
    current = {
        "output_dir/a.csv": TableHashEntry(
            key="output_dir/a.csv",
            hash="abc",
            row_count=2,
            columns=("b", "a"),
        )
    }

    result = compare_manifest_entries(current, baseline)

    assert not result.ok
    assert result.hash_mismatched == {}
    assert result.row_count_mismatched == {}
    assert result.columns_mismatched == {"output_dir/a.csv": (("a", "b"), ("b", "a"))}

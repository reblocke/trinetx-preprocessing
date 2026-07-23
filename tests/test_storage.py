from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from trinetx_preprocessing import storage
from trinetx_preprocessing.config import (
    ChunkingConfig,
    Config,
    DomainConfig,
    GuardrailConfig,
    RfsConfig,
    StorageConfig,
)
from trinetx_preprocessing.storage import (
    PartitionedKeyLookup,
    PartitionedParquetStore,
    WorkTableWriter,
    find_work_tables,
    iter_work_tables,
    logical_output_key,
    read_table,
    write_work_table,
)


def _config(
    tmp_path: Path,
    *,
    intermediate_format: str = "parquet",
    emit_legacy_csv_intermediates: bool = False,
) -> Config:
    return Config(
        data_dir=tmp_path / "data",
        work_dir=tmp_path / "work",
        output_dir=tmp_path / "output",
        domains={"encounter": DomainConfig(pattern="Encounter/encounter*.csv")},
        chunking=ChunkingConfig(),
        rfs=RfsConfig(),
        guardrails=GuardrailConfig(),
        storage=StorageConfig(
            intermediate_format=intermediate_format,
            emit_legacy_csv_intermediates=emit_legacy_csv_intermediates,
            parquet_row_group_size=10,
        ),
    )


def test_write_work_table_parquet_uses_logical_name(tmp_path: Path) -> None:
    config = _config(tmp_path)
    frame = pd.DataFrame({"patient_id": ["P1"], "encounter_id": ["E1"]})

    paths = write_work_table(config, "encounter_NEW_0001.csv", frame)

    assert paths == [tmp_path / "work" / "encounter_NEW_0001.parquet"]
    assert not (tmp_path / "work" / "encounter_NEW_0001.csv").exists()
    loaded = read_table(paths[0], dtype={"patient_id": "string"})
    assert loaded["patient_id"].dtype.name == "string"
    assert loaded.to_dict("records") == frame.to_dict("records")


def test_write_work_table_can_emit_legacy_csv_companion(tmp_path: Path) -> None:
    config = _config(tmp_path, emit_legacy_csv_intermediates=True)
    frame = pd.DataFrame({"patient_id": ["P1"], "encounter_id": ["E1"]})

    paths = write_work_table(config, "encounter_NEW_0001.csv", frame)

    assert paths == [
        tmp_path / "work" / "encounter_NEW_0001.parquet",
        tmp_path / "work" / "encounter_NEW_0001.csv",
    ]


def test_work_table_writer_appends_parquet_chunks(tmp_path: Path) -> None:
    config = _config(tmp_path)

    with WorkTableWriter(config, "events.csv") as writer:
        writer.write(pd.DataFrame({"patient_id": ["P1"], "encounter_id": ["E1"]}))
        writer.write(pd.DataFrame({"patient_id": ["P2"], "encounter_id": ["E2"]}))
        paths = list(writer.written_paths)

    loaded = read_table(paths[0])

    assert paths == [tmp_path / "work" / "events.parquet"]
    assert loaded.to_dict("records") == [
        {"patient_id": "P1", "encounter_id": "E1"},
        {"patient_id": "P2", "encounter_id": "E2"},
    ]


def test_work_table_writer_can_disable_compatibility_output(tmp_path: Path) -> None:
    config = _config(tmp_path)

    with WorkTableWriter(config, "events.csv", enabled=False) as writer:
        writer.write(pd.DataFrame({"patient_id": ["P1"], "encounter_id": ["E1"]}))

    assert writer.written_paths == []
    assert not (tmp_path / "work").exists()


def test_find_work_tables_prefers_configured_format(tmp_path: Path) -> None:
    config = _config(tmp_path, emit_legacy_csv_intermediates=True)
    write_work_table(
        config,
        "RFS_ABG.csv",
        pd.DataFrame(
            {"patient_id": ["P1"], "encounter_id": ["E1"], "date": ["2022-01-01"]}
        ),
    )

    paths = find_work_tables(config, "RFS_*.csv")

    assert paths == [tmp_path / "work" / "RFS_ABG.parquet"]


def test_iter_work_tables_streams_parquet_batches(tmp_path: Path) -> None:
    path = tmp_path / "events.parquet"
    pd.DataFrame(
        {
            "patient_id": ["P1", "P2", "P3", "P4", "P5"],
            "encounter_id": ["E1", "E2", "E3", "E4", "E5"],
        }
    ).to_parquet(path, index=False, row_group_size=2)

    chunks = list(
        iter_work_tables(
            [path],
            chunksize=2,
            usecols=["patient_id"],
            dtype={"patient_id": "string"},
        )
    )

    assert [len(chunk) for chunk in chunks] == [2, 2, 1]
    assert [list(chunk.columns) for chunk in chunks] == [["patient_id"]] * 3
    assert all(chunk["patient_id"].dtype.name == "string" for chunk in chunks)
    assert pd.concat(chunks, ignore_index=True).to_dict("records") == [
        {"patient_id": "P1"},
        {"patient_id": "P2"},
        {"patient_id": "P3"},
        {"patient_id": "P4"},
        {"patient_id": "P5"},
    ]


def test_iter_work_tables_rejects_invalid_parquet_chunksize(tmp_path: Path) -> None:
    path = tmp_path / "events.parquet"
    pd.DataFrame({"patient_id": ["P1"]}).to_parquet(path, index=False)

    try:
        list(iter_work_tables([path], chunksize=0))
    except ValueError as exc:
        assert "chunksize" in str(exc)
    else:
        raise AssertionError("Expected invalid Parquet chunksize to raise ValueError")


def test_logical_output_key_normalizes_parquet_work_suffix(tmp_path: Path) -> None:
    work_dir = tmp_path / "work"
    output_dir = tmp_path / "output"
    path = work_dir / "RFS_ABG.parquet"

    assert logical_output_key(path, work_dir, output_dir) == "work_dir/RFS_ABG.csv"


def test_partitioned_parquet_store_round_trips_and_cleans(tmp_path: Path) -> None:
    frame = pd.DataFrame(
        {
            "patient_id": ["P1", "P2", "P1"],
            "encounter_id": ["E1", "E2", "E3"],
            "value": [1, 2, 3],
        }
    )

    with PartitionedParquetStore(
        tmp_path,
        prefix=".trinetx-test-partitions-",
        key_columns=["patient_id"],
        bucket_count=4,
        row_group_size=2,
    ) as store:
        store.add_frame(frame.iloc[:2])
        store.add_frame(frame.iloc[2:])
        observed = pd.concat(
            [partition for _, partition in store.iter_frames()],
            ignore_index=True,
        )
        populated = store.populated_buckets()

    assert observed.sort_values("encounter_id").reset_index(drop=True).equals(frame)
    assert populated
    assert not list(tmp_path.glob(".trinetx-test-partitions-*"))


def test_partitioned_parquet_store_rejects_writes_after_read(tmp_path: Path) -> None:
    frame = pd.DataFrame({"patient_id": ["P1"], "value": [1]})

    with PartitionedParquetStore(
        tmp_path,
        prefix=".trinetx-test-partitions-",
        key_columns=["patient_id"],
        bucket_count=2,
    ) as store:
        store.add_frame(frame)
        list(store.iter_frames())
        with pytest.raises(RuntimeError, match="sealed"):
            store.add_frame(frame)


def test_partitioned_parquet_store_releases_each_writer_while_sealing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = PartitionedParquetStore(
        tmp_path,
        prefix=".trinetx-test-partitions-",
        key_columns=["patient_id"],
        bucket_count=4,
    )
    closed: list[int] = []

    class _Writer:
        def __init__(self, bucket: int) -> None:
            self.bucket = bucket

        def close(self) -> None:
            assert self.bucket not in store._writers
            closed.append(self.bucket)

    store._writers = {bucket: _Writer(bucket) for bucket in range(4)}
    arrow_releases: list[None] = []
    monkeypatch.setattr(storage, "_ARROW_RELEASE_INTERVAL", 2)
    monkeypatch.setattr(
        storage,
        "release_unused_arrow_memory",
        lambda: arrow_releases.append(None),
    )

    store.seal()

    assert sorted(closed) == [0, 1, 2, 3]
    assert arrow_releases == [None, None, None]
    assert store._writers == {}
    assert store._sealed is True


def test_partitioned_parquet_store_releases_unused_memory_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    releases: list[None] = []
    monkeypatch.setattr(
        storage,
        "release_unused_tabular_memory",
        lambda: releases.append(None),
    )
    store = PartitionedParquetStore(
        tmp_path,
        prefix=".trinetx-test-partitions-",
        key_columns=["patient_id"],
        bucket_count=2,
    )

    store.seal()
    store.seal()

    assert releases == [None]


def test_partitioned_key_lookup_queries_and_deduplicates_membership(
    tmp_path: Path,
) -> None:
    with PartitionedKeyLookup(
        tmp_path,
        prefix=".trinetx-test-lookup-",
        key_column="lookup_key",
        stored_columns=["lookup_key", "encounter_id"],
        bucket_count=4,
    ) as lookup:
        lookup.add_frame(
            pd.DataFrame(
                {
                    "lookup_key": ["value:E1", "value:E1", "value:E2"],
                    "encounter_id": ["E1", "E1", "E2"],
                }
            )
        )

        matches = lookup.frame_for_keys(
            pd.Series(["value:E2", "value:E3"], dtype="string")
        )
        assert matches["encounter_id"].tolist() == ["E2"]
        assert lookup.unique_count() == 2

    assert not list(tmp_path.glob(".trinetx-test-lookup-*"))


def test_partitioned_key_lookup_rejects_cross_chunk_duplicate_unique_key(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="Duplicate lookup key"):
        with PartitionedKeyLookup(
            tmp_path,
            prefix=".trinetx-test-lookup-",
            key_column="lookup_key",
            stored_columns=["lookup_key", "value"],
            bucket_count=4,
            require_unique=True,
        ) as lookup:
            lookup.add_frame(pd.DataFrame({"lookup_key": ["P1"], "value": [1]}))
            lookup.add_frame(pd.DataFrame({"lookup_key": ["P1"], "value": [2]}))
            lookup.finalize()

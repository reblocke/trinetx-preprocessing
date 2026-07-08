from __future__ import annotations

from pathlib import Path

import pandas as pd

from trinetx_preprocessing.config import (
    ChunkingConfig,
    Config,
    DomainConfig,
    GuardrailConfig,
    RfsConfig,
    StorageConfig,
)
from trinetx_preprocessing.storage import (
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

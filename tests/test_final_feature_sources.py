from __future__ import annotations

import json
import traceback
from pathlib import Path

import pandas as pd
import pytest

import trinetx_preprocessing.pipeline.final_feature_sources as final_feature_sources
import trinetx_preprocessing.storage as storage
from trinetx_preprocessing.config import (
    ChunkingConfig,
    Config,
    DomainConfig,
    GuardrailConfig,
    RfsConfig,
    StorageConfig,
)
from trinetx_preprocessing.pipeline.final_feature_sources import (
    FINAL_FEATURE_INDEX_MAX_CHUNK_ROWS,
    LAB_SOURCE_NAME,
    SOURCE_COLUMNS,
    FinalFeatureBucket,
    FinalFeatureSourceStore,
)
from trinetx_preprocessing.storage import stable_bucket_ids, write_work_table
from trinetx_preprocessing.transform.diagnosis import DIAGNOSIS_COLUMNS
from trinetx_preprocessing.transform.labs import LAB_COLUMNS
from trinetx_preprocessing.transform.vitals import VITALS_COLUMNS


def _config(tmp_path: Path) -> Config:
    return Config(
        data_dir=tmp_path / "data",
        work_dir=tmp_path / "work",
        output_dir=tmp_path / "output",
        domains={"patient": DomainConfig(pattern="Patient/patient*.csv")},
        chunking=ChunkingConfig(enabled=True, lines_per_chunk=1),
        rfs=RfsConfig(enabled=True),
        guardrails=GuardrailConfig(),
        storage=StorageConfig(
            intermediate_format="parquet",
            emit_legacy_csv_intermediates=False,
            analysis_bucket_count=4,
        ),
    )


def test_final_feature_sources_scan_once_and_serve_patient_bucket(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _config(tmp_path)
    config.work_dir.mkdir()
    write_work_table(
        config,
        "value_BMI.csv",
        pd.DataFrame(
            [["P1", "E1", "39156-5", "2022-01-01", 42.0]],
            columns=VITALS_COLUMNS,
        ),
    )
    write_work_table(
        config,
        "lab_results_NEW_0001.csv",
        pd.DataFrame(
            [["P1", "E1", "2019-8", "2022-01-01", 55.0]],
            columns=LAB_COLUMNS,
        ),
    )
    write_work_table(
        config,
        "HAS_J9600.csv",
        pd.DataFrame(
            [["P1", "E1", "J96.00", "P", "U", "U", "2022-01-01"]],
            columns=DIAGNOSIS_COLUMNS,
        ),
    )

    bucket = int(
        stable_bucket_ids(
            pd.DataFrame({"patient_id": ["P1"]}),
            bucket_count=config.storage.analysis_bucket_count,
        ).iloc[0]
    )
    observed_lock_transfers: list[tuple[int, ...]] = []
    monkeypatch.setattr(
        final_feature_sources,
        "duplicate_lock_file_descriptors_for_spawn",
        lambda descriptors: observed_lock_transfers.append(descriptors) or (),
    )
    with FinalFeatureSourceStore(
        config,
        chunksize=1,
        lock_file_descriptors=(101, 102),
    ) as store:
        source_bucket = store.bucket(bucket)
        bmi = source_bucket.frame("value_BMI.csv", VITALS_COLUMNS)
        labs = source_bucket.frame(LAB_SOURCE_NAME, LAB_COLUMNS)
        diagnosis = source_bucket.frame("HAS_J9600.csv", DIAGNOSIS_COLUMNS)

        assert store.files_scanned == 3
        assert store.rows_indexed == 3
        assert store.peak_worker_rss_mb > 0
        assert set(store.worker_metrics) == {"vitals", "labs", "diagnosis"}
        assert store.worker_metrics["vitals"]["rows_indexed"] == 1
        assert store.worker_metrics["vitals"]["peak_rss_mb"] > 0
        assert bmi["value"].tolist() == [42.0]
        assert labs["lab_result_num_val"].tolist() == [55.0]
        assert diagnosis["principal_diagnosis_indicator"].tolist() == ["P"]

    assert observed_lock_transfers == [(101, 102)] * 3
    assert not list(config.work_dir.glob(".trinetx-final-feature-sources-*"))


def test_final_feature_source_store_caps_index_chunks(tmp_path: Path) -> None:
    config = _config(tmp_path)

    assert (
        FinalFeatureSourceStore(config, chunksize=250_000).chunksize
        == FINAL_FEATURE_INDEX_MAX_CHUNK_ROWS
    )
    assert (
        FinalFeatureSourceStore(config, chunksize=None).chunksize
        == FINAL_FEATURE_INDEX_MAX_CHUNK_ROWS
    )
    assert FinalFeatureSourceStore(config, chunksize=10_000).chunksize == 10_000


def test_final_feature_source_worker_failure_cleans_scratch(tmp_path: Path) -> None:
    config = _config(tmp_path)
    config.work_dir.mkdir()
    write_work_table(
        config,
        "analysis_vital_features.csv",
        pd.DataFrame({"source_name": ["value_BMI.csv"], "value": [42.0]}),
    )

    with pytest.raises(RuntimeError, match="Final vitals feature index failed"):
        with FinalFeatureSourceStore(config, chunksize=1):
            pass

    assert not list(config.work_dir.glob(".trinetx-final-feature-sources-*"))


def test_domain_partition_reader_retries_oserror_once_without_threads(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    partition_root = tmp_path / "labs"
    partition_root.mkdir()
    partition_path = partition_root / "bucket-003.parquet"
    partition_path.touch()
    expected = pd.DataFrame({"patient_id": ["P1"]})
    calls: list[tuple[Path, list[str] | None, bool]] = []

    def read_partition(
        path: Path,
        *,
        columns: list[str] | None,
        use_threads: bool,
    ) -> pd.DataFrame:
        calls.append((path, columns, use_threads))
        if use_threads:
            raise OSError("transient synthetic read error")
        return expected

    monkeypatch.setattr(
        final_feature_sources,
        "_read_verified_parquet",
        read_partition,
    )

    reader = final_feature_sources._DomainPartitionReader("labs", partition_root)
    observed = reader.read_frame(3, columns=["patient_id"])

    assert observed is expected
    assert calls == [
        (partition_path, ["patient_id"], True),
        (partition_path, ["patient_id"], False),
    ]


def test_domain_partition_reader_persistent_oserror_has_partition_context_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    partition_root = tmp_path / "diagnosis"
    partition_root.mkdir()
    partition_path = partition_root / "bucket-002.parquet"
    partition_path.touch()
    attempts: list[bool] = []
    sensitive_sentinel = "synthetic-row-value-P1"

    def fail_read(
        path: Path,
        *,
        columns: list[str] | None,
        use_threads: bool,
    ) -> pd.DataFrame:
        del path, columns
        attempts.append(use_threads)
        raise OSError(sensitive_sentinel)

    monkeypatch.setattr(
        final_feature_sources,
        "_read_verified_parquet",
        fail_read,
    )
    reader = final_feature_sources._DomainPartitionReader(
        "diagnosis",
        partition_root,
    )

    with pytest.raises(OSError) as error:
        reader.read_frame(2, columns=["patient_id"])

    message = str(error.value)
    assert "domain=diagnosis" in message
    assert "bucket=2" in message
    assert f"path={partition_path}" in message
    assert sensitive_sentinel not in message
    assert error.value.__cause__ is None
    assert error.value.__suppress_context__ is True
    formatted_traceback = "".join(
        traceback.format_exception(
            type(error.value),
            error.value,
            error.value.__traceback__,
        )
    )
    assert sensitive_sentinel not in formatted_traceback
    assert attempts == [True, False]


def test_verified_parquet_read_enables_page_checksum_verification(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import pyarrow as pa
    import pyarrow.parquet as pq

    partition_path = tmp_path / "bucket-001.parquet"
    observed: dict[str, object] = {}

    class _ParquetFile:
        def __init__(self, path: Path, **kwargs: object) -> None:
            observed["path"] = path
            observed["constructor_kwargs"] = kwargs

        def __enter__(self) -> "_ParquetFile":
            return self

        def __exit__(self, *args: object) -> None:
            observed["closed"] = True

        def read(self, **kwargs: object) -> pa.Table:
            observed["read_kwargs"] = kwargs
            return pa.table({"patient_id": ["P1"]})

    monkeypatch.setattr(pq, "ParquetFile", _ParquetFile)

    result = final_feature_sources._read_verified_parquet(
        partition_path,
        columns=["patient_id"],
        use_threads=False,
    )

    assert result.to_dict("records") == [{"patient_id": "P1"}]
    assert observed == {
        "path": partition_path,
        "constructor_kwargs": {"page_checksum_verification": True},
        "read_kwargs": {"columns": ["patient_id"], "use_threads": False},
        "closed": True,
    }


def test_feature_worker_fsyncs_checksummed_bucket_before_complete_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import pyarrow.parquet as pq

    config = _config(tmp_path)
    root = tmp_path / "feature-scratch"
    root.mkdir()
    metadata_path = root / "vitals.json"
    input_path = tmp_path / "value_BMI.parquet"
    definition = final_feature_sources._SourceDefinition(
        domain="vitals",
        name="value_BMI.csv",
        paths=(input_path,),
        columns=tuple(VITALS_COLUMNS),
        date_column="date",
        numeric_column="value",
    )
    source_frame = pd.DataFrame(
        [["P1", "E1", "39156-5", "2022-01-01", 42.0]],
        columns=VITALS_COLUMNS,
    )
    monkeypatch.setattr(
        final_feature_sources,
        "iter_work_tables",
        lambda *args, **kwargs: iter([source_frame]),
    )
    events: list[tuple[str, object]] = []

    class _ParquetWriter:
        def __init__(
            self,
            path: Path,
            schema: object,
            **kwargs: object,
        ) -> None:
            del schema
            self.path = Path(path)
            self.path.touch()
            events.append(("writer", kwargs))

        def write_table(self, table: object, *, row_group_size: int) -> None:
            del table, row_group_size

        def close(self) -> None:
            events.append(("close", self.path))

    monkeypatch.setattr(pq, "ParquetWriter", _ParquetWriter)
    monkeypatch.setattr(
        storage,
        "fsync_file_strict",
        lambda path: events.append(("file_fsync", path)),
    )
    monkeypatch.setattr(
        storage,
        "fsync_directory_strict",
        lambda path: events.append(("directory_fsync", path)),
    )

    def record_metadata(path: Path, text: str) -> None:
        assert path == metadata_path
        events.append(("metadata", json.loads(text)["status"]))

    monkeypatch.setattr(final_feature_sources, "write_text_atomic", record_metadata)

    final_feature_sources._build_feature_domain_worker_body(
        config,
        chunksize=1,
        domain="vitals",
        definitions=(definition,),
        row_order_start=0,
        root=root,
        metadata_path=metadata_path,
    )

    assert events[0][0] == "writer"
    assert events[0][1]["write_page_checksum"] is True
    assert [event for event, _ in events[1:]] == [
        "close",
        "file_fsync",
        "directory_fsync",
        "metadata",
    ]
    assert events[-1] == ("metadata", "complete")


def test_final_feature_bucket_materializes_sources_in_observed_order() -> None:
    frame = pd.DataFrame(
        [
            ["value_BMI.csv", "P1", "E2", "39156-5", "2022-01-02", 41.0],
            ["value_BMI.csv", "P1", "E1", "39156-5", "2022-01-01", 40.0],
            ["HAS_J9600.csv", "P1", "E3", "J96.00", "2022-01-03", None],
        ],
        columns=SOURCE_COLUMNS[:6],
    )
    for column in SOURCE_COLUMNS[6:9]:
        frame[column] = pd.NA
    frame["_source_row_order"] = [2, 1, 3]

    bucket = FinalFeatureBucket(frame.loc[:, SOURCE_COLUMNS])
    bmi = bucket.frame("value_BMI.csv", VITALS_COLUMNS)

    assert bmi["encounter_id"].tolist() == ["E1", "E2"]
    assert bmi["value"].tolist() == [40.0, 41.0]
    assert bucket.has_source("HAS_J9600.csv")

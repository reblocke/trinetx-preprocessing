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
from trinetx_preprocessing.pipeline.final_feature_sources import (
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
    with FinalFeatureSourceStore(config, chunksize=1) as store:
        source_bucket = store.bucket(bucket)
        bmi = source_bucket.frame("value_BMI.csv", VITALS_COLUMNS)
        labs = source_bucket.frame(LAB_SOURCE_NAME, LAB_COLUMNS)
        diagnosis = source_bucket.frame("HAS_J9600.csv", DIAGNOSIS_COLUMNS)

        assert store.files_scanned == 3
        assert store.rows_indexed == 3
        assert bmi["value"].tolist() == [42.0]
        assert labs["lab_result_num_val"].tolist() == [55.0]
        assert diagnosis["principal_diagnosis_indicator"].tolist() == ["P"]

    assert not list(config.work_dir.glob(".trinetx-final-feature-sources-*"))


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

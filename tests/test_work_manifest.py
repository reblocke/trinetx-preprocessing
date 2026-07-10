from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pandas as pd
import pytest

from trinetx_preprocessing.config import (
    ChunkingConfig,
    Config,
    DomainConfig,
    GuardrailConfig,
    RfsConfig,
    StorageConfig,
)
from trinetx_preprocessing.work_manifest import (
    StaleWorkError,
    initialize_work_manifest,
    mark_stage_complete,
    mark_stage_started,
    require_current_work,
)


def _config(tmp_path: Path) -> Config:
    data_dir = tmp_path / "data"
    work_dir = tmp_path / "work"
    output_dir = tmp_path / "output"
    (data_dir / "Encounter").mkdir(parents=True)
    work_dir.mkdir()
    output_dir.mkdir()
    (data_dir / "Encounter" / "encounter0001.csv").write_text(
        "encounter_id,patient_id,start_date,end_date,type\n"
    )
    return Config(
        data_dir=data_dir,
        work_dir=work_dir,
        output_dir=output_dir,
        domains={"encounter": DomainConfig(pattern="Encounter/encounter*.csv")},
        chunking=ChunkingConfig(),
        rfs=RfsConfig(enabled=True),
        guardrails=GuardrailConfig(),
        storage=StorageConfig(intermediate_format="parquet"),
    )


def test_work_manifest_records_and_requires_completed_stages(tmp_path: Path) -> None:
    config = _config(tmp_path)
    path = initialize_work_manifest(config)
    output = config.work_dir / "encounter_NEW_0001.parquet"
    pd.DataFrame({"encounter_id": ["E1"]}).to_parquet(output, index=False)

    mark_stage_complete(config, "encounter", [output])
    manifest = require_current_work(config, required_stages=["encounter"])

    assert path.exists()
    assert manifest["intermediate_schema_version"] == 5
    assert manifest["runtime_versions"]["python"]
    assert manifest["stages"]["encounter"]["status"] == "complete"
    assert manifest["stages"]["encounter"]["outputs"][0]["size_bytes"] > 0
    assert manifest["stages"]["encounter"]["outputs"][0]["row_count"] == 1


def test_work_manifest_fails_when_rules_change(tmp_path: Path) -> None:
    config = _config(tmp_path)
    initialize_work_manifest(config)
    changed = replace(
        config,
        rfs=replace(config.rfs, abg_min_pco2_mmhg=50.0),
    )

    with pytest.raises(StaleWorkError, match="config_hash"):
        require_current_work(changed, required_stages=[])


def test_work_manifest_rejects_unmanaged_work(tmp_path: Path) -> None:
    config = _config(tmp_path)
    (config.work_dir / "old.csv").write_text("value\n1\n")

    with pytest.raises(StaleWorkError, match="unmanaged artifacts"):
        initialize_work_manifest(config)


def test_work_manifest_rejects_changed_completed_artifact(tmp_path: Path) -> None:
    config = _config(tmp_path)
    initialize_work_manifest(config)
    output = config.work_dir / "encounter_NEW_0001.parquet"
    pd.DataFrame({"encounter_id": ["E1"]}).to_parquet(output, index=False)
    mark_stage_complete(config, "encounter", [output])
    output.write_bytes(b"changed")

    with pytest.raises(StaleWorkError, match="artifact changed"):
        require_current_work(config, required_stages=["encounter"])


def test_work_manifest_running_stage_is_not_reusable(tmp_path: Path) -> None:
    config = _config(tmp_path)
    initialize_work_manifest(config)
    mark_stage_started(config, "encounter")

    with pytest.raises(StaleWorkError, match="missing completed stages"):
        require_current_work(config, required_stages=["encounter"])

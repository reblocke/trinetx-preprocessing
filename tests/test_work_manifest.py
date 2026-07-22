from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pandas as pd
import pytest

import trinetx_preprocessing.work_manifest as work_manifest_module
from trinetx_preprocessing.config import (
    ChunkingConfig,
    Config,
    DataScreenConfig,
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
    assert manifest["schema_version"] == 5
    assert manifest["intermediate_schema_version"] == 7
    assert len(manifest["git_code_state_sha256"]) == 64
    assert manifest["combined_element_catalog_sha256"] is None
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


def test_work_manifest_fails_when_behavior_code_changes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _config(tmp_path)
    monkeypatch.setattr(
        work_manifest_module,
        "current_git_code_state_sha256",
        lambda: "a" * 64,
    )
    initialize_work_manifest(config)
    monkeypatch.setattr(
        work_manifest_module,
        "current_git_code_state_sha256",
        lambda: "b" * 64,
    )

    with pytest.raises(StaleWorkError, match="git_code_state_sha256"):
        require_current_work(config, required_stages=[])


def test_work_manifest_fails_when_combined_catalog_changes(tmp_path: Path) -> None:
    config = _config(tmp_path)
    manifest_path = initialize_work_manifest(config)
    manifest = json.loads(manifest_path.read_text())
    manifest["combined_element_catalog_sha256"] = "a" * 64
    manifest_path.write_text(json.dumps(manifest))

    with pytest.raises(StaleWorkError, match="combined_element_catalog_sha256"):
        require_current_work(config, required_stages=[])


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


def test_work_manifest_fingerprints_legacy_data_screen_inputs(tmp_path: Path) -> None:
    config = replace(
        _config(tmp_path),
        data_screen=DataScreenConfig(source="legacy_files"),
    )
    data_checks_dir = config.work_dir / "data_checks"
    data_checks_dir.mkdir()
    amb_path = data_checks_dir / "amb_enc_screen.csv"
    inp_path = data_checks_dir / "inp_enc_screen.csv"
    amb_path.write_text("encounter_id\nE1\n")
    inp_path.write_text("encounter_id\nE2\n")

    manifest_path = initialize_work_manifest(config)
    manifest = require_current_work(config, required_stages=[])
    data_screen_inputs = [
        item for item in manifest["inputs"] if item["domain"] == "data_screen"
    ]

    assert manifest_path.exists()
    assert [Path(item["path"]).name for item in data_screen_inputs] == [
        "amb_enc_screen.csv",
        "inp_enc_screen.csv",
    ]
    assert all(item["header"] == "encounter_id" for item in data_screen_inputs)

    amb_path.write_text("encounter_id\nE1\nE3\n")
    with pytest.raises(StaleWorkError, match="inputs"):
        require_current_work(config, required_stages=[])


def test_work_manifest_requires_both_legacy_data_screen_inputs(tmp_path: Path) -> None:
    config = replace(
        _config(tmp_path),
        data_screen=DataScreenConfig(source="legacy_files"),
    )
    data_checks_dir = config.work_dir / "data_checks"
    data_checks_dir.mkdir()
    (data_checks_dir / "amb_enc_screen.csv").write_text("encounter_id\nE1\n")

    with pytest.raises(StaleWorkError, match="inp_enc_screen.csv"):
        initialize_work_manifest(config)

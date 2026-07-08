from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from trinetx_preprocessing.config import (
    ChunkingConfig,
    Config,
    DomainConfig,
    GuardrailConfig,
    RfsConfig,
    StorageConfig,
)
from trinetx_preprocessing.profiling import (
    StageTimer,
    current_git_code_dirty,
    current_git_code_state_sha256,
    write_provenance,
)


def test_stage_timer_records_elapsed() -> None:
    times = iter([1.0, 2.25])

    def time_fn() -> float:
        return next(times)

    timings: dict[str, float] = {}
    with StageTimer("demo", timings=timings, time_fn=time_fn):
        pass

    assert timings["demo"] == pytest.approx(1.25)


def test_write_provenance_records_config_code_and_outputs(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text("data_dir: data\n")
    work_dir = tmp_path / "work"
    output_dir = tmp_path / "output"
    profile_dir = tmp_path / "profile"
    work_dir.mkdir()
    output_dir.mkdir()
    work_path = work_dir / "intermediate.parquet"
    work_path.write_text("not a real parquet for provenance inventory\n")
    output_path = output_dir / "result.csv"
    output_path.write_text("patient_id\nP1\n")
    output_parquet = output_dir / "internal.parquet"
    output_parquet.write_text("not a real parquet for provenance inventory\n")
    config = Config(
        data_dir=tmp_path / "data",
        work_dir=work_dir,
        output_dir=output_dir,
        domains={"encounter": DomainConfig(pattern="Encounter/encounter*.csv")},
        chunking=ChunkingConfig(),
        rfs=RfsConfig(),
        guardrails=GuardrailConfig(),
        storage=StorageConfig(),
    )

    provenance_path = write_provenance(
        profile_dir,
        config=config,
        output_paths=[work_path, output_path, output_parquet],
        stage_timings={"run": 1.2345},
        started_at=datetime(2026, 6, 8, tzinfo=timezone.utc),
        ended_at=datetime(2026, 6, 8, 0, 0, 2, tzinfo=timezone.utc),
        config_path=config_path,
        strict=True,
    )
    payload = json.loads(provenance_path.read_text())

    assert payload["schema_version"] == 2
    assert payload["config_path"] == str(config_path.resolve())
    assert (
        payload["config_sha256"] == hashlib.sha256(config_path.read_bytes()).hexdigest()
    )
    assert payload["package_version"] == "0.1.0"
    assert payload["python_version"]
    assert isinstance(payload["git_dirty"], bool)
    assert payload["git_code_dirty"] == current_git_code_dirty()
    assert payload["git_code_state_sha256"] == current_git_code_state_sha256()
    assert payload["strict"] is True
    assert payload["stage_timings_seconds"] == {"run": 1.234}
    assert payload["generated_file_count"] == 3
    assert payload["output_file_count"] == 1
    assert payload["output_files"] == [
        {
            "path": str(output_path.resolve()),
            "exists": True,
            "size_bytes": output_path.stat().st_size,
            "mtime_ns": output_path.stat().st_mtime_ns,
        }
    ]

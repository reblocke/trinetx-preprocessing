from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from trinetx_preprocessing.config import ConfigError, load_config, validate_config


def _write_config(path: Path) -> None:
    content = textwrap.dedent(
        """
        data_dir: data
        work_dir: work
        output_dir: output
        domains:
          encounter:
            pattern: "Encounter/encounter*.csv"
        """
    ).strip()
    path.write_text(f"{content}\n")


def _write_encounter_csv(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "encounter_id,patient_id,start_date,end_date,type,"
        "start_date_derived_by_TriNetX,end_date_derived_by_TriNetX,"
        "derived_by_TriNetX,source_id\n"
    )


def test_load_and_validate_config(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    work_dir = tmp_path / "work"
    output_dir = tmp_path / "output"
    work_dir.mkdir()
    output_dir.mkdir()
    _write_encounter_csv(data_dir / "Encounter" / "encounter0001.csv")

    config_path = tmp_path / "config.yaml"
    _write_config(config_path)

    config = load_config(config_path)
    assert config.data_dir == data_dir.resolve()
    validate_config(config)


def test_validate_config_missing_files(tmp_path: Path) -> None:
    (tmp_path / "data").mkdir()
    (tmp_path / "work").mkdir()
    (tmp_path / "output").mkdir()
    config_path = tmp_path / "config.yaml"
    _write_config(config_path)

    config = load_config(config_path)
    with pytest.raises(ConfigError, match="No files found"):
        validate_config(config)

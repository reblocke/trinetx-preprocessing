from __future__ import annotations

import shutil
from pathlib import Path

import pandas as pd
import pytest

from trinetx_preprocessing.config import load_config, validate_config
from trinetx_preprocessing.pipeline.vitals_stage import run_vitals_stage
from trinetx_preprocessing.transform.vitals import VITALS_COLUMNS

FIXTURE_PATH = (
    Path(__file__).resolve().parent / "fixtures" / "vitals" / "vital_signs0001.csv"
)


def _write_config(path: Path, data_dir: Path, work_dir: Path, output_dir: Path) -> None:
    content = (
        f'data_dir: "{data_dir}"\n'
        f'work_dir: "{work_dir}"\n'
        f'output_dir: "{output_dir}"\n'
        "domains:\n"
        "  vitals:\n"
        '    pattern: "Vital Signs/vital_signs*.csv"\n'
    )
    path.write_text(content)


def test_run_vitals_stage_outputs(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    work_dir = tmp_path / "work"
    output_dir = tmp_path / "output"
    data_dir.mkdir()
    work_dir.mkdir()
    output_dir.mkdir()

    vitals_dir = data_dir / "Vital Signs"
    vitals_dir.mkdir()
    shutil.copy(FIXTURE_PATH, vitals_dir / "vital_signs0001.csv")

    config_path = tmp_path / "config.yaml"
    _write_config(config_path, data_dir, work_dir, output_dir)
    config = load_config(config_path)
    validate_config(config)

    outputs = run_vitals_stage(config)

    normalized_path = work_dir / "vital_signs_NEW_0001.csv"
    assert normalized_path in outputs

    normalized = pd.read_csv(normalized_path, parse_dates=["date"])
    assert list(normalized.columns) == VITALS_COLUMNS
    assert len(normalized) == 18

    temp = pd.read_csv(work_dir / "value_759878.csv")
    assert temp["value"].iloc[0] == pytest.approx(40.0, rel=1e-3)

    new_temp = pd.read_csv(work_dir / "value_New_Temp.csv")
    assert new_temp["value"].iloc[0] == pytest.approx(98.6, rel=1e-3)

    weight = pd.read_csv(work_dir / "value_Weight.csv")
    assert weight["value"].tolist() == [180.0]

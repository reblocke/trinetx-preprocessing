from __future__ import annotations

import shutil
from pathlib import Path

import pandas as pd

from trinetx_preprocessing.config import load_config, validate_config
from trinetx_preprocessing.pipeline.labs_stage import run_labs_stage
from trinetx_preprocessing.transform.labs import LAB_COLUMNS

FIXTURE_PATH = (
    Path(__file__).resolve().parent / "fixtures" / "labs" / "lab_results0001.csv"
)


def _write_config(path: Path, data_dir: Path, work_dir: Path, output_dir: Path) -> None:
    content = (
        f'data_dir: "{data_dir}"\n'
        f'work_dir: "{work_dir}"\n'
        f'output_dir: "{output_dir}"\n'
        "domains:\n"
        "  labs:\n"
        '    pattern: "Lab Results/lab_results*.csv"\n'
    )
    path.write_text(content)


def test_run_labs_stage_outputs(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    work_dir = tmp_path / "work"
    output_dir = tmp_path / "output"
    data_dir.mkdir()
    work_dir.mkdir()
    output_dir.mkdir()

    labs_dir = data_dir / "Lab Results"
    labs_dir.mkdir()
    shutil.copy(FIXTURE_PATH, labs_dir / "lab_results0001.csv")

    config_path = tmp_path / "config.yaml"
    _write_config(config_path, data_dir, work_dir, output_dir)
    config = load_config(config_path)
    validate_config(config)

    outputs = run_labs_stage(config)

    expected_output = work_dir / "lab_results_NEW_0001.csv"
    assert outputs == [expected_output]

    normalized = pd.read_csv(expected_output, parse_dates=["date"])
    assert list(normalized.columns) == LAB_COLUMNS
    assert len(normalized) == 3

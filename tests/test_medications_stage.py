from __future__ import annotations

import shutil
from pathlib import Path

import pandas as pd

from trinetx_preprocessing.config import load_config, validate_config
from trinetx_preprocessing.pipeline.medications_stage import run_medications_stage
from trinetx_preprocessing.transform.medications import MEDICATION_COLUMNS

FIXTURE_PATH = (
    Path(__file__).resolve().parent / "fixtures" / "medications" / "medication0001.csv"
)


def _write_config(path: Path, data_dir: Path, work_dir: Path, output_dir: Path) -> None:
    content = (
        f'data_dir: "{data_dir}"\n'
        f'work_dir: "{work_dir}"\n'
        f'output_dir: "{output_dir}"\n'
        "domains:\n"
        "  meds:\n"
        '    pattern: "Medications/medication*.csv"\n'
    )
    path.write_text(content)


def test_run_medications_stage_outputs(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    work_dir = tmp_path / "work"
    output_dir = tmp_path / "output"
    data_dir.mkdir()
    work_dir.mkdir()
    output_dir.mkdir()

    meds_dir = data_dir / "Medications"
    meds_dir.mkdir()
    shutil.copy(FIXTURE_PATH, meds_dir / "medication0001.csv")

    config_path = tmp_path / "config.yaml"
    _write_config(config_path, data_dir, work_dir, output_dir)
    config = load_config(config_path)
    validate_config(config)

    outputs = run_medications_stage(config)

    normalized_path = work_dir / "medication_NEW_0001.csv"
    assert normalized_path in outputs

    normalized = pd.read_csv(normalized_path, parse_dates=["start_date"])
    assert list(normalized.columns) == MEDICATION_COLUMNS
    assert len(normalized) == 12

    ipmed_list1 = pd.read_csv(
        work_dir / "IPmed_list1.csv",
        dtype={"code": "string"},
    )
    assert ipmed_list1["code"].tolist() == ["6902"]

    opmed_list5 = pd.read_csv(
        work_dir / "OPmed_list5.csv",
        dtype={"code": "string"},
    )
    assert opmed_list5["code"].tolist() == ["7213"]

    opmed_list6 = pd.read_csv(
        work_dir / "OPmed_list6.csv",
        dtype={"code": "string"},
    )
    assert opmed_list6["code"].tolist() == ["21949"]

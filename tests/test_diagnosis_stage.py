from __future__ import annotations

import shutil
from pathlib import Path

import pandas as pd

from trinetx_preprocessing.config import load_config, validate_config
from trinetx_preprocessing.pipeline.diagnosis_stage import run_diagnosis_stage
from trinetx_preprocessing.transform.diagnosis import DIAGNOSIS_COLUMNS

FIXTURE_PATH = (
    Path(__file__).resolve().parent / "fixtures" / "diagnosis" / "diagnosis0001.csv"
)


def _write_config(path: Path, data_dir: Path, work_dir: Path, output_dir: Path) -> None:
    content = (
        f'data_dir: "{data_dir}"\n'
        f'work_dir: "{work_dir}"\n'
        f'output_dir: "{output_dir}"\n'
        "domains:\n"
        "  diagnosis:\n"
        '    pattern: "Diagnosis/diagnosis*.csv"\n'
    )
    path.write_text(content)


def test_run_diagnosis_stage_outputs(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    work_dir = tmp_path / "work"
    output_dir = tmp_path / "output"
    data_dir.mkdir()
    work_dir.mkdir()
    output_dir.mkdir()

    diag_dir = data_dir / "Diagnosis"
    diag_dir.mkdir()
    shutil.copy(FIXTURE_PATH, diag_dir / "diagnosis0001.csv")

    config_path = tmp_path / "config.yaml"
    _write_config(config_path, data_dir, work_dir, output_dir)
    config = load_config(config_path)
    validate_config(config)

    outputs = run_diagnosis_stage(config)

    normalized_path = work_dir / "diagnosis_NEW_0001.csv"
    assert normalized_path in outputs

    normalized = pd.read_csv(normalized_path, parse_dates=["date"])
    assert list(normalized.columns) == DIAGNOSIS_COLUMNS
    assert normalized.loc[0, "principal_diagnosis_indicator"] == "U"

    assert (work_dir / "HAS_J9612.csv").exists()
    assert (work_dir / "HAS_G473.csv").exists()
    assert (work_dir / "HAS_G4734.csv").exists()
    assert (work_dir / "HAS_I50_acute.csv").exists()
    assert (work_dir / "HAS_headache.csv").exists()

    j9612 = pd.read_csv(work_dir / "HAS_J9612.csv")
    assert j9612["code"].tolist() == ["J96.12"]

    g473 = pd.read_csv(work_dir / "HAS_G473.csv")
    assert set(g473["code"].tolist()) == {"G47.30", "G47.34"}

    g4734 = pd.read_csv(work_dir / "HAS_G4734.csv")
    assert g4734["code"].tolist() == ["G47.34"]

    headache = pd.read_csv(work_dir / "HAS_headache.csv")
    assert headache.empty

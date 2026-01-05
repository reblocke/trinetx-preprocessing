from __future__ import annotations

import shutil
from pathlib import Path

import pandas as pd

from trinetx_preprocessing.config import load_config, validate_config
from trinetx_preprocessing.pipeline.procedure_stage import run_procedure_stage
from trinetx_preprocessing.transform.procedure import PROCEDURE_COLUMNS

FIXTURE_PATH = (
    Path(__file__).resolve().parent / "fixtures" / "procedure" / "procedure0001.csv"
)


def _write_config(path: Path, data_dir: Path, work_dir: Path, output_dir: Path) -> None:
    content = (
        f'data_dir: "{data_dir}"\n'
        f'work_dir: "{work_dir}"\n'
        f'output_dir: "{output_dir}"\n'
        "domains:\n"
        "  procedure:\n"
        '    pattern: "Procedure/procedure*.csv"\n'
    )
    path.write_text(content)


def test_run_procedure_stage_outputs(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    work_dir = tmp_path / "work"
    output_dir = tmp_path / "output"
    data_dir.mkdir()
    work_dir.mkdir()
    output_dir.mkdir()

    proc_dir = data_dir / "Procedure"
    proc_dir.mkdir()
    shutil.copy(FIXTURE_PATH, proc_dir / "procedure0001.csv")

    config_path = tmp_path / "config.yaml"
    _write_config(config_path, data_dir, work_dir, output_dir)
    config = load_config(config_path)
    validate_config(config)

    outputs = run_procedure_stage(config)

    normalized_path = work_dir / "procedure_NEW_0001.csv"
    assert normalized_path in outputs

    normalized = pd.read_csv(normalized_path, parse_dates=["date"])
    assert list(normalized.columns) == PROCEDURE_COLUMNS
    assert len(normalized) == 13

    has_94660 = pd.read_csv(
        work_dir / "HAS_94660.csv",
        dtype={"code": "string"},
    )
    assert has_94660["code"].tolist() == ["94660"]

    has_tte = pd.read_csv(
        work_dir / "HAS_TTE.csv",
        dtype={"code": "string"},
    )
    assert has_tte["code"].tolist() == ["93306"]

    has_ct_abdm = pd.read_csv(
        work_dir / "HAS_CT_ABDM.csv",
        dtype={"code": "string"},
    )
    assert has_ct_abdm["code"].tolist() == ["74150"]

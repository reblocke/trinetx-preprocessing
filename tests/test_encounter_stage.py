from __future__ import annotations

import shutil
from pathlib import Path

import pandas as pd

from trinetx_preprocessing.config import load_config, validate_config
from trinetx_preprocessing.pipeline.encounter_stage import run_encounter_stage

FIXTURE_PATH = (
    Path(__file__).resolve().parent / "fixtures" / "encounter" / "encounter0001.csv"
)


def _write_config(path: Path, data_dir: Path, work_dir: Path, output_dir: Path) -> None:
    content = (
        f'data_dir: "{data_dir}"\n'
        f'work_dir: "{work_dir}"\n'
        f'output_dir: "{output_dir}"\n'
        "domains:\n"
        "  encounter:\n"
        '    pattern: "Encounter/encounter*.csv"\n'
    )
    path.write_text(content)


def test_run_encounter_stage_outputs(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    work_dir = tmp_path / "work"
    output_dir = tmp_path / "output"
    data_dir.mkdir()
    work_dir.mkdir()
    output_dir.mkdir()

    encounter_dir = data_dir / "Encounter"
    encounter_dir.mkdir()
    shutil.copy(FIXTURE_PATH, encounter_dir / "encounter0001.csv")

    config_path = tmp_path / "config.yaml"
    _write_config(config_path, data_dir, work_dir, output_dir)
    config = load_config(config_path)
    validate_config(config)

    outputs = run_encounter_stage(config)

    expected_outputs = {
        work_dir / "encounter_NEW_0001.csv",
        work_dir / "AMB_encounters.csv",
        work_dir / "EMER_encounters.csv",
        work_dir / "INPAT_encounters.csv",
    }
    assert set(outputs) == expected_outputs

    amb = pd.read_csv(
        work_dir / "AMB_encounters.csv",
        parse_dates=["start_date", "end_date"],
    )
    assert list(amb["encounter_id"]) == ["E1"]
    assert amb.iloc[0]["LOS"] == 3

    emer = pd.read_csv(
        work_dir / "EMER_encounters.csv",
        parse_dates=["start_date", "end_date"],
    )
    assert emer.iloc[0]["end_date"] == pd.Timestamp("2022-12-31")

    inpat = pd.read_csv(
        work_dir / "INPAT_encounters.csv",
        parse_dates=["start_date", "end_date"],
    )
    assert list(inpat["encounter_id"]) == ["E5"]

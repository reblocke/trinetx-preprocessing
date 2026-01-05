from __future__ import annotations

import shutil
from pathlib import Path

import pandas as pd

from trinetx_preprocessing.config import load_config, validate_config
from trinetx_preprocessing.pipeline.rfs_stage import run_rfs_stage
from trinetx_preprocessing.transform.rfs import RFS_OUTPUT_COLUMNS

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "rfs"


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


def _write_placeholder_encounter(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "encounter_id,patient_id,start_date,end_date,type,"
        "start_date_derived_by_TriNetX,end_date_derived_by_TriNetX,"
        "derived_by_TriNetX,source_id\n"
    )


def test_run_rfs_stage_outputs(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    work_dir = tmp_path / "work"
    output_dir = tmp_path / "output"
    data_dir.mkdir()
    work_dir.mkdir()
    output_dir.mkdir()

    _write_placeholder_encounter(data_dir / "Encounter" / "encounter0001.csv")

    for filename in (
        "encounter_NEW_0001.csv",
        "lab_results_NEW_0001.csv",
        "diagnosis_NEW_0001.csv",
        "procedure_NEW_0001.csv",
        "vital_signs_NEW_0001.csv",
    ):
        shutil.copy(FIXTURE_DIR / filename, work_dir / filename)

    config_path = tmp_path / "config.yaml"
    _write_config(config_path, data_dir, work_dir, output_dir)
    config = load_config(config_path)
    validate_config(config)

    outputs = run_rfs_stage(config)

    output_path = work_dir / "rfs_encounter_flags.csv"
    assert output_path in outputs

    flags = pd.read_csv(output_path)
    assert list(flags.columns) == RFS_OUTPUT_COLUMNS
    indexed = flags.set_index("encounter_id")
    assert indexed.loc["E1", "rfs_abg"]
    assert indexed.loc["E2", "rfs_vbg"]
    assert indexed.loc["E3", "rfs_respfail"]
    assert indexed.loc["E4", "rfs_obesity"]
    assert indexed.loc["E5", "rfs_ventsupport"]
    assert indexed.loc["E6", "rfs_predisposition"]

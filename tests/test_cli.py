from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
FIXTURE_PATH = ROOT / "tests" / "fixtures" / "encounter" / "encounter0001.csv"
LAB_FIXTURE_PATH = ROOT / "tests" / "fixtures" / "labs" / "lab_results0001.csv"


def _build_env() -> dict[str, str]:
    env = os.environ.copy()
    pythonpath_entries = [str(SRC)]
    existing = env.get("PYTHONPATH")
    if existing:
        pythonpath_entries.append(existing)
    env["PYTHONPATH"] = os.pathsep.join(pythonpath_entries)
    return env


def _write_config(path: Path) -> None:
    content = (
        "data_dir: data\n"
        "work_dir: work\n"
        "output_dir: output\n"
        "domains:\n"
        "  encounter:\n"
        '    pattern: "Encounter/encounter*.csv"\n'
    )
    path.write_text(content)


def _write_encounter_config(
    path: Path,
    data_dir: Path,
    work_dir: Path,
    output_dir: Path,
) -> None:
    content = (
        f'data_dir: "{data_dir}"\n'
        f'work_dir: "{work_dir}"\n'
        f'output_dir: "{output_dir}"\n'
        "domains:\n"
        "  encounter:\n"
        '    pattern: "Encounter/encounter*.csv"\n'
    )
    path.write_text(content)


def _write_encounter_csv(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "encounter_id,patient_id,start_date,end_date,type,"
        "start_date_derived_by_TriNetX,end_date_derived_by_TriNetX,"
        "derived_by_TriNetX,source_id\n"
    )


def _write_labs_config(
    path: Path,
    data_dir: Path,
    work_dir: Path,
    output_dir: Path,
) -> None:
    content = (
        f'data_dir: "{data_dir}"\n'
        f'work_dir: "{work_dir}"\n'
        f'output_dir: "{output_dir}"\n'
        "domains:\n"
        "  labs:\n"
        '    pattern: "Lab Results/lab_results*.csv"\n'
    )
    path.write_text(content)


def test_validate_config_cli(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    work_dir = tmp_path / "work"
    output_dir = tmp_path / "output"
    work_dir.mkdir()
    output_dir.mkdir()
    _write_encounter_csv(data_dir / "Encounter" / "encounter0001.csv")

    config_path = tmp_path / "config.yaml"
    _write_config(config_path)

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "trinetx_preprocessing",
            "validate-config",
            "--config",
            str(config_path),
        ],
        cwd=ROOT,
        env=_build_env(),
        capture_output=True,
        text=True,
        check=False,
    )

    output = (result.stdout or "") + (result.stderr or "")
    assert result.returncode == 0, output


def test_run_encounter_cli(tmp_path: Path) -> None:
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
    _write_encounter_config(config_path, data_dir, work_dir, output_dir)

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "trinetx_preprocessing",
            "run-encounter",
            "--config",
            str(config_path),
        ],
        cwd=ROOT,
        env=_build_env(),
        capture_output=True,
        text=True,
        check=False,
    )

    output = (result.stdout or "") + (result.stderr or "")
    assert result.returncode == 0, output
    assert (work_dir / "AMB_encounters.csv").exists()
    assert (work_dir / "EMER_encounters.csv").exists()
    assert (work_dir / "INPAT_encounters.csv").exists()


def test_run_labs_cli(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    work_dir = tmp_path / "work"
    output_dir = tmp_path / "output"
    data_dir.mkdir()
    work_dir.mkdir()
    output_dir.mkdir()

    labs_dir = data_dir / "Lab Results"
    labs_dir.mkdir()
    shutil.copy(LAB_FIXTURE_PATH, labs_dir / "lab_results0001.csv")

    config_path = tmp_path / "config.yaml"
    _write_labs_config(config_path, data_dir, work_dir, output_dir)

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "trinetx_preprocessing",
            "run-labs",
            "--config",
            str(config_path),
        ],
        cwd=ROOT,
        env=_build_env(),
        capture_output=True,
        text=True,
        check=False,
    )

    output = (result.stdout or "") + (result.stderr or "")
    assert result.returncode == 0, output
    assert (work_dir / "lab_results_NEW_0001.csv").exists()

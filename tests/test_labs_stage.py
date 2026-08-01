from __future__ import annotations

import json
import shutil
from pathlib import Path

import pandas as pd

from trinetx_preprocessing.combined_preprocessing.elements import (
    SOURCE_TABLE_BY_DOMAIN,
)
from trinetx_preprocessing.config import load_config, validate_config
from trinetx_preprocessing.pipeline.labs_stage import run_labs_stage
from trinetx_preprocessing.storage import resolve_work_table
from trinetx_preprocessing.transform.labs import NORMALIZED_LAB_COLUMNS

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
        '    pattern: "Lab Results/lab_result*.csv"\n'
        "storage:\n"
        "  emit_normalized_domain_tables: true\n"
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
    assert expected_output in outputs
    assert work_dir / "analysis_lab_features.csv" in outputs
    assert work_dir / "analysis_lab_availability.csv" in outputs
    assert work_dir / "analysis_rfs_labs.csv" in outputs

    normalized = pd.read_csv(expected_output, parse_dates=["date"])
    assert list(normalized.columns) == NORMALIZED_LAB_COLUMNS
    assert len(normalized) == 3

    feature_index = pd.read_csv(work_dir / "analysis_lab_features.csv")
    assert feature_index["source_name"].tolist() == [
        "value_potassium",
        "value_potassium",
    ]
    availability = pd.read_csv(work_dir / "analysis_lab_availability.csv")
    assert availability["encounter_id"].tolist() == ["E1", "E2", "E3"]

    audit = json.loads((work_dir / "rfs_rule_audit.json").read_text())
    assert audit["ruleset"] == "corrected_v1"
    assert audit["categories"]["ABG"]["considered"] == 1
    assert audit["categories"]["ABG"]["rejected_unit"] == 1
    assert "patient_id" not in json.dumps(audit)


def test_combined_labs_preserve_raw_na_token_and_transform_it_as_missing(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data"
    work_dir = tmp_path / "work"
    output_dir = tmp_path / "output"
    labs_dir = data_dir / "Lab Results"
    labs_dir.mkdir(parents=True)
    work_dir.mkdir()
    output_dir.mkdir()
    source_path = labs_dir / "lab_results0001.csv"
    source = pd.read_csv(FIXTURE_PATH, dtype="string", keep_default_na=False)
    source.loc[source["code"].eq("2019-8"), "date"] = "NULL"
    source.to_csv(source_path, index=False)

    config_path = tmp_path / "config.yaml"
    _write_config(config_path, data_dir, work_dir, output_dir)
    concept_sets_dir = Path(__file__).resolve().parents[1] / "config/concept_sets"
    with config_path.open("a") as handle:
        handle.write(
            f'combined:\n  enabled: true\n  concept_sets_dir: "{concept_sets_dir}"\n'
        )
    config = load_config(config_path)
    validate_config(config)

    run_labs_stage(config)

    normalized = pd.read_csv(
        work_dir / "lab_results_NEW_0001.csv",
        dtype={"code": "string"},
    )
    assert normalized.loc[normalized["code"].eq("2019-8"), "date"].isna().all()
    captured_path = resolve_work_table(
        config,
        f"combined_{SOURCE_TABLE_BY_DOMAIN['labs']}.csv",
    )
    captured = pd.read_csv(
        captured_path,
        dtype="string",
        keep_default_na=False,
    )
    captured_row = captured.loc[captured["code"].eq("2019-8")].iloc[0]
    assert captured_row["date"] == "NULL"
    assert captured_row["event_datetime"] == ""

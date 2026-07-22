from __future__ import annotations

import shutil
from pathlib import Path

import pandas as pd

from trinetx_preprocessing.combined_preprocessing.elements import (
    SOURCE_TABLE_BY_DOMAIN,
)
from trinetx_preprocessing.config import load_config, validate_config
from trinetx_preprocessing.pipeline.medications_stage import run_medications_stage
from trinetx_preprocessing.storage import resolve_work_table
from trinetx_preprocessing.transform.medications import NORMALIZED_MEDICATION_COLUMNS

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
        "storage:\n"
        "  emit_normalized_domain_tables: true\n"
        "  emit_legacy_group_tables: true\n"
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
    assert list(normalized.columns) == NORMALIZED_MEDICATION_COLUMNS
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


def test_combined_stage_captures_ingredient_without_legacy_features(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data"
    work_dir = tmp_path / "work"
    output_dir = tmp_path / "output"
    meds_dir = data_dir / "Medications"
    meds_dir.mkdir(parents=True)
    work_dir.mkdir()
    output_dir.mkdir()
    shutil.copy(FIXTURE_PATH, meds_dir / "medication0001.csv")
    (meds_dir / "medication_ingredient.csv").write_text(
        "patient_id,code_system,code,start_date,medication_text\n"
        "P-INGREDIENT,RXNORM,29046,2022-01-01,lisinopril\n"
    )

    config_path = tmp_path / "config.yaml"
    _write_config(config_path, data_dir, work_dir, output_dir)
    concept_sets_dir = Path(__file__).resolve().parents[1] / "config/concept_sets"
    with config_path.open("a") as handle:
        handle.write(
            f'combined:\n  enabled: true\n  concept_sets_dir: "{concept_sets_dir}"\n'
        )
    config = load_config(config_path)
    validate_config(config)

    run_medications_stage(config)

    normalized = pd.read_csv(work_dir / "medication_NEW_0001.csv")
    assert "P-INGREDIENT" not in set(normalized["patient_id"].astype(str))
    source_path = resolve_work_table(
        config,
        f"combined_{SOURCE_TABLE_BY_DOMAIN['medications']}.csv",
    )
    source = pd.read_csv(source_path, dtype="string")
    ingredient = source.loc[source["patient_id"].eq("P-INGREDIENT")]
    assert ingredient["code"].tolist() == ["29046"]
    assert ingredient["encounter_id"].isna().all()

from __future__ import annotations

import shutil
from pathlib import Path

import pandas as pd
import pytest

from trinetx_preprocessing.config import load_config, validate_config
from trinetx_preprocessing.pipeline.rfs_stage import (
    _build_rfs_flags_from_membership,
    _RfsEncounterStore,
    _RfsMembershipStore,
    run_rfs_stage,
)
from trinetx_preprocessing.storage import read_table, write_work_table
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


def test_run_rfs_stage_outputs_with_parquet_intermediates(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    work_dir = tmp_path / "work"
    output_dir = tmp_path / "output"
    data_dir.mkdir()
    work_dir.mkdir()
    output_dir.mkdir()

    _write_placeholder_encounter(data_dir / "Encounter" / "encounter0001.csv")
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        f'data_dir: "{data_dir}"\n'
        f'work_dir: "{work_dir}"\n'
        f'output_dir: "{output_dir}"\n'
        "domains:\n"
        "  encounter:\n"
        '    pattern: "Encounter/encounter*.csv"\n'
        "storage:\n"
        '  intermediate_format: "parquet"\n'
        "  emit_legacy_csv_intermediates: false\n"
        "  parquet_row_group_size: 1\n"
    )
    config = load_config(config_path)
    validate_config(config)

    for filename in (
        "encounter_NEW_0001.csv",
        "lab_results_NEW_0001.csv",
        "diagnosis_NEW_0001.csv",
        "procedure_NEW_0001.csv",
        "vital_signs_NEW_0001.csv",
    ):
        write_work_table(config, filename, pd.read_csv(FIXTURE_DIR / filename))

    outputs = run_rfs_stage(config)

    output_path = work_dir / "rfs_encounter_flags.parquet"
    assert output_path in outputs
    assert work_dir / "RFS_ABG.parquet" in outputs

    flags = read_table(output_path)
    indexed = flags.set_index("encounter_id")
    assert indexed.loc["E1", "rfs_abg"]
    assert indexed.loc["E2", "rfs_vbg"]


def test_rfs_membership_store_builds_flags(
    tmp_path: Path,
) -> None:
    with _RfsMembershipStore(tmp_path, bucket_count=2) as store:
        store.add_events("ABG", ["E1", "E1", None])
        store.add_events("RESPFAIL", ["E2"])
        encounters = pd.DataFrame(
            {
                "patient_id": ["P1", "P2", "P2"],
                "encounter_id": ["E1", "E2", "E2"],
            }
        )

        flags = _build_rfs_flags_from_membership(encounters, store)

        indexed = flags.set_index("encounter_id")
        assert indexed.loc["E1", "rfs_abg"]
        assert not indexed.loc["E1", "rfs_respfail"]
        assert indexed.loc["E2", "rfs_respfail"]


def test_rfs_encounter_store_preserves_first_seen_encounter_row(
    tmp_path: Path,
) -> None:
    with _RfsEncounterStore(tmp_path, bucket_count=1) as store:
        store.add_frame(
            pd.DataFrame(
                {
                    "patient_id": ["P1", "P2"],
                    "encounter_id": ["E1", "E2"],
                }
            )
        )
        store.add_frame(
            pd.DataFrame(
                {
                    "patient_id": ["P3", "P4"],
                    "encounter_id": ["E1", "E3"],
                }
            )
        )
        frames = [frame for _, frame in store.iter_unique_frames()]

    combined = pd.concat(frames, ignore_index=True)
    assert combined.to_dict("records") == [
        {"patient_id": "P1", "encounter_id": "E1"},
        {"patient_id": "P2", "encounter_id": "E2"},
        {"patient_id": "P4", "encounter_id": "E3"},
    ]
    assert store.seen_count == 3


def test_run_rfs_stage_removes_bucketed_scratch_directories(tmp_path: Path) -> None:
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

    run_rfs_stage(config)

    assert not list(work_dir.glob(".trinetx-rfs-membership-*"))
    assert not list(work_dir.glob(".trinetx-rfs-encounters-*"))


def test_rfs_membership_store_cleanup_raises_on_delete_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_remove_tree(path, *, context):
        raise PermissionError(f"denied: {context}")

    monkeypatch.setattr(
        "trinetx_preprocessing.pipeline.rfs_stage.remove_tree_strict",
        fail_remove_tree,
    )

    with pytest.raises(PermissionError, match="RFS membership scratch"):
        with _RfsMembershipStore(tmp_path):
            pass


def test_rfs_encounter_store_cleanup_raises_on_delete_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_remove_tree(path, *, context):
        raise PermissionError(f"denied: {context}")

    monkeypatch.setattr(
        "trinetx_preprocessing.pipeline.rfs_stage.remove_tree_strict",
        fail_remove_tree,
    )

    with pytest.raises(PermissionError, match="RFS encounter scratch"):
        with _RfsEncounterStore(tmp_path, bucket_count=1):
            pass


def test_run_rfs_stage_preserves_duplicate_events_and_first_encounter(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data"
    work_dir = tmp_path / "work"
    output_dir = tmp_path / "output"
    data_dir.mkdir()
    work_dir.mkdir()
    output_dir.mkdir()

    _write_placeholder_encounter(data_dir / "Encounter" / "encounter0001.csv")
    pd.DataFrame(
        {
            "patient_id": ["P1", "P2", "P3"],
            "encounter_id": ["E1", "E1", "E2"],
            "start_date": ["2022-01-01", "2022-01-01", "2022-01-02"],
            "end_date": ["2022-01-01", "2022-01-01", "2022-01-02"],
            "type": ["AMB", "AMB", "AMB"],
        }
    ).to_csv(work_dir / "encounter_NEW_0001.csv", index=False)
    pd.DataFrame(
        {
            "patient_id": ["P1", "P1", "P3"],
            "encounter_id": ["E1", "E1", "E2"],
            "code": ["2019-8", "2026-3", "11557-6"],
            "date": ["2022-01-01", "2022-01-01", "2022-01-02"],
            "lab_result_num_val": [50, 60, 45],
        }
    ).to_csv(work_dir / "lab_results_NEW_0001.csv", index=False)
    for filename, columns in {
        "diagnosis_NEW_0001.csv": [
            "patient_id",
            "encounter_id",
            "code",
            "principal_diagnosis_indicator",
            "admitting_diagnosis",
            "reason_for_visit",
            "date",
        ],
        "procedure_NEW_0001.csv": ["patient_id", "encounter_id", "code", "date"],
        "vital_signs_NEW_0001.csv": [
            "patient_id",
            "encounter_id",
            "code",
            "date",
            "value",
        ],
    }.items():
        pd.DataFrame(columns=columns).to_csv(work_dir / filename, index=False)

    config_path = tmp_path / "config.yaml"
    _write_config(config_path, data_dir, work_dir, output_dir)
    config = load_config(config_path)
    validate_config(config)

    run_rfs_stage(config)

    abg = pd.read_csv(work_dir / "RFS_ABG.csv")
    flags = pd.read_csv(work_dir / "rfs_encounter_flags.csv")

    assert len(abg) == 2
    assert flags.loc[flags["encounter_id"] == "E1", "patient_id"].item() == "P1"
    indexed = flags.set_index("encounter_id")
    assert indexed.loc["E1", "rfs_abg"]
    assert indexed.loc["E2", "rfs_vbg"]

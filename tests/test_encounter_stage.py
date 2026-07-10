from __future__ import annotations

import shutil
from pathlib import Path

import pandas as pd
import pytest

from trinetx_preprocessing.config import load_config, validate_config
from trinetx_preprocessing.pipeline.encounter_stage import (
    _EncounterReducerStore,
    run_encounter_stage,
)

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


def test_encounter_reducer_store_preserves_earliest_encounter(
    tmp_path: Path,
) -> None:
    later = pd.DataFrame(
        {
            "patient_id": ["P_later", "P_same_day"],
            "encounter_id": ["E1", "E2"],
            "start_date": [pd.Timestamp("2022-02-01"), pd.Timestamp("2022-03-01")],
            "end_date": [pd.Timestamp("2022-02-02"), pd.Timestamp("2022-03-02")],
            "type": ["AMB", "AMB"],
        }
    )
    earlier = pd.DataFrame(
        {
            "patient_id": ["P_earlier", "P_tie"],
            "encounter_id": ["E1", "E2"],
            "start_date": [pd.Timestamp("2022-01-01"), pd.Timestamp("2022-03-01")],
            "end_date": [pd.Timestamp("2022-01-03"), pd.Timestamp("2022-03-05")],
            "type": ["AMB", "AMB"],
        }
    )

    with _EncounterReducerStore(tmp_path) as reducer:
        reducer.update(later)
        reducer.update(earlier)
        frame = reducer.frame("AMB")

    indexed = frame.set_index("encounter_id")
    assert indexed.loc["E1", "patient_id"] == "P_earlier"
    assert indexed.loc["E1", "start_date"] == pd.Timestamp("2022-01-01")
    assert indexed.loc["E2", "patient_id"] == "P_same_day"
    assert not list(tmp_path.glob(".trinetx-encounter-reducer-*"))


def test_encounter_reducer_same_chunk_ties_keep_first_observed_row(
    tmp_path: Path,
) -> None:
    encounters = pd.DataFrame(
        {
            "patient_id": ["P_first", "P_second", "P_other"],
            "encounter_id": ["E1", "E1", "E2"],
            "start_date": [
                pd.Timestamp("2022-03-01"),
                pd.Timestamp("2022-03-01"),
                pd.Timestamp("2022-01-01"),
            ],
            "end_date": [
                pd.Timestamp("2022-03-02"),
                pd.Timestamp("2022-03-05"),
                pd.Timestamp("2022-01-03"),
            ],
            "type": ["AMB", "AMB", "AMB"],
        }
    )

    with _EncounterReducerStore(tmp_path) as reducer:
        reducer.update(encounters)
        frame = reducer.frame("AMB")
        assert reducer.next_row_order == len(encounters)

    indexed = frame.set_index("encounter_id")
    assert indexed.loc["E1", "patient_id"] == "P_first"
    assert indexed.loc["E1", "end_date"] == pd.Timestamp("2022-03-02")


def test_encounter_reducer_store_preserves_missing_string_values(
    tmp_path: Path,
) -> None:
    missing_values = pd.DataFrame(
        {
            "patient_id": pd.Series([pd.NA], dtype="string"),
            "encounter_id": pd.Series([pd.NA], dtype="string"),
            "start_date": [pd.Timestamp("2022-01-01")],
            "end_date": [pd.Timestamp("2022-01-03")],
            "type": pd.Series(["AMB"], dtype="string"),
        }
    )

    with _EncounterReducerStore(tmp_path) as reducer:
        reducer.update(missing_values)
        frame = reducer.frame("AMB")

    assert pd.isna(frame.loc[0, "patient_id"])
    assert pd.isna(frame.loc[0, "encounter_id"])
    assert frame.loc[0, "start_date"] == pd.Timestamp("2022-01-01")


def test_encounter_reducer_streams_unique_rows_across_batches(tmp_path: Path) -> None:
    encounters = pd.DataFrame(
        {
            "patient_id": ["P_later", "P_earlier", "P_second"],
            "encounter_id": ["E1", "E1", "E2"],
            "start_date": [
                pd.Timestamp("2022-03-01"),
                pd.Timestamp("2022-01-01"),
                pd.Timestamp("2022-02-01"),
            ],
            "end_date": [
                pd.Timestamp("2022-03-02"),
                pd.Timestamp("2022-01-04"),
                pd.Timestamp("2022-01-31"),
            ],
            "type": ["AMB", "AMB", "AMB"],
        }
    )

    with _EncounterReducerStore(tmp_path) as reducer:
        reducer.update(encounters)
        frames = list(reducer.iter_finalized_frames("AMB", batch_size=1))

    streamed = pd.concat(frames, ignore_index=True)
    assert list(streamed["encounter_id"]) == ["E1"]
    assert streamed.loc[0, "patient_id"] == "P_earlier"
    assert streamed.loc[0, "LOS"] == 4


def test_encounter_reducer_resolves_cross_setting_ids_globally(
    tmp_path: Path,
) -> None:
    encounters = pd.DataFrame(
        {
            "patient_id": ["P_later", "P_earlier", "P_other_type"],
            "encounter_id": ["E1", "E1", "E1"],
            "start_date": [
                pd.Timestamp("2022-02-01"),
                pd.Timestamp("2022-01-01"),
                pd.Timestamp("2022-03-01"),
            ],
            "end_date": [
                pd.Timestamp("2022-01-02"),
                pd.Timestamp("2022-02-03"),
                pd.Timestamp("2022-03-04"),
            ],
            "type": ["AMB", "AMB", "EMER"],
        }
    )

    with _EncounterReducerStore(tmp_path) as reducer:
        reducer.update(encounters)
        amb = reducer.frame("AMB")
        emer = reducer.frame("EMER")

    assert list(amb["patient_id"]) == ["P_earlier"]
    assert emer.empty


def test_encounter_reducer_reports_cross_setting_conflicts(tmp_path: Path) -> None:
    encounters = pd.DataFrame(
        {
            "patient_id": ["P1", "P1", "P1", "P2", "P2"],
            "encounter_id": ["E1", "E1", "E1", "E2", "E2"],
            "start_date": pd.to_datetime(
                [
                    "2022-01-01",
                    "2022-01-02",
                    "2022-01-03",
                    "2022-01-03",
                    "2022-01-04",
                ]
            ),
            "end_date": pd.to_datetime(
                [
                    "2022-01-02",
                    "2022-01-03",
                    "2022-01-04",
                    "2022-01-04",
                    "2022-01-05",
                ]
            ),
            "type": ["AMB", "EMER", "IMP", "AMB", "AMB"],
        }
    )

    with _EncounterReducerStore(tmp_path) as reducer:
        reducer.update(encounters)
        summary = reducer.conflict_summary()

    assert summary == {
        "schema_version": 1,
        "encounter_conflict_count": 1,
        "type_combinations": {"AMB+EMER+IMP": 1},
    }


def test_run_encounter_stage_removes_reducer_scratch_database(tmp_path: Path) -> None:
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

    run_encounter_stage(config)

    assert not list(work_dir.glob(".trinetx-encounter-reducer-*"))


def test_encounter_reducer_cleanup_raises_on_delete_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_remove_tree(path, *, context):
        raise PermissionError(f"denied: {context}")

    monkeypatch.setattr(
        "trinetx_preprocessing.storage.remove_tree_strict",
        fail_remove_tree,
    )

    with pytest.raises(PermissionError, match="Encounter reducer scratch"):
        with _EncounterReducerStore(tmp_path):
            pass

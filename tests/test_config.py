from __future__ import annotations

import json
import textwrap
from pathlib import Path

import pytest

from trinetx_preprocessing.config import (
    ConfigError,
    inspect_domain_paths,
    load_config,
    validate_config,
)


def _write_config(path: Path) -> None:
    content = textwrap.dedent(
        """
        data_dir: data
        work_dir: work
        output_dir: output
        domains:
          encounter:
            pattern: "Encounter/encounter*.csv"
        """
    ).strip()
    path.write_text(f"{content}\n")


def _write_encounter_csv(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "encounter_id,patient_id,start_date,end_date,type,"
        "start_date_derived_by_TriNetX,end_date_derived_by_TriNetX,"
        "derived_by_TriNetX,source_id\n"
    )


def test_load_and_validate_config(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    work_dir = tmp_path / "work"
    output_dir = tmp_path / "output"
    work_dir.mkdir()
    output_dir.mkdir()
    _write_encounter_csv(data_dir / "Encounter" / "encounter0001.csv")

    config_path = tmp_path / "config.yaml"
    _write_config(config_path)

    config = load_config(config_path)
    assert config.data_dir == data_dir.resolve()
    assert config.storage.intermediate_format == "csv"
    assert config.storage.emit_normalized_domain_tables is False
    validate_config(config)


def test_load_config_storage_options(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    work_dir = tmp_path / "work"
    output_dir = tmp_path / "output"
    work_dir.mkdir()
    output_dir.mkdir()
    _write_encounter_csv(data_dir / "Encounter" / "encounter0001.csv")

    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        textwrap.dedent(
            """
            data_dir: data
            work_dir: work
            output_dir: output
            storage:
              intermediate_format: parquet
              emit_legacy_csv_intermediates: false
              emit_normalized_domain_tables: true
              parquet_row_group_size: 1000
              analysis_bucket_count: 64
              emit_legacy_group_tables: true
            combined:
              enabled: true
              database_name: combined.duckdb
              schema_version: "1.0"
              concept_sets_dir: config/concept_sets
              duckdb_memory_limit_mib: 2048
            rfs:
              enabled: true
              ruleset: corrected_v1
              abg_min_pco2_mmhg: 47
              vbg_min_pco2_mmhg: 48
            cohort:
              event_selection: earliest_per_setting
            data_screen:
              mode: diagnosis_or_lab
              source: derived
            domains:
              encounter:
                pattern: "Encounter/encounter*.csv"
            """
        ).strip()
        + "\n"
    )

    config = load_config(config_path)
    assert config.storage.intermediate_format == "parquet"
    assert config.storage.emit_legacy_csv_intermediates is False
    assert config.storage.emit_normalized_domain_tables is True
    assert config.storage.parquet_row_group_size == 1000
    assert config.storage.analysis_bucket_count == 64
    assert config.storage.emit_legacy_group_tables is True
    assert config.combined.enabled is True
    assert config.combined.database_name == "combined.duckdb"
    assert config.combined.schema_version == "1.0"
    assert config.combined.duckdb_memory_limit_mib == 2048
    assert (
        config.combined.concept_sets_dir
        == (tmp_path / "config" / "concept_sets").resolve()
    )
    assert config.rfs.abg_min_pco2_mmhg == 47
    assert config.rfs.vbg_min_pco2_mmhg == 48
    assert config.cohort.event_selection == "earliest_per_setting"
    assert config.data_screen.mode == "diagnosis_or_lab"
    validate_config(config)


@pytest.mark.parametrize("value", [0, -1, 1.5, True, "3072"])
def test_combined_duckdb_memory_limit_requires_positive_integer(
    tmp_path: Path,
    value: object,
) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        textwrap.dedent(
            f"""
            data_dir: data
            work_dir: work
            output_dir: output
            combined:
              duckdb_memory_limit_mib: {json.dumps(value)}
            domains:
              encounter:
                pattern: "Encounter/encounter*.csv"
            """
        ).strip()
        + "\n"
    )

    with pytest.raises(ConfigError, match="duckdb_memory_limit_mib"):
        load_config(config_path)


def test_load_config_domain_patterns_list(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    work_dir = tmp_path / "work"
    output_dir = tmp_path / "output"
    meds_dir = data_dir / "Medications"
    meds_dir.mkdir(parents=True)
    work_dir.mkdir()
    output_dir.mkdir()
    (meds_dir / "medication_ingredient.csv").write_text("patient_id\n")
    (meds_dir / "medication_NEW_0001.csv").write_text("patient_id\n")
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        textwrap.dedent(
            """
            data_dir: data
            work_dir: work
            output_dir: output
            domains:
              meds:
                patterns:
                  - "Medications/medication[0-9]*.csv"
                  - "Medications/medication_ingredient*.csv"
            """
        ).strip()
        + "\n"
    )

    config = load_config(config_path)
    inspections = inspect_domain_paths(config)

    assert config.domains["meds"].pattern_list == (
        "Medications/medication[0-9]*.csv",
        "Medications/medication_ingredient*.csv",
    )
    assert inspections[0].matched_count == 1
    assert inspections[0].first_path == (meds_dir / "medication_ingredient.csv")


def test_validate_config_missing_files(tmp_path: Path) -> None:
    (tmp_path / "data").mkdir()
    (tmp_path / "work").mkdir()
    (tmp_path / "output").mkdir()
    config_path = tmp_path / "config.yaml"
    _write_config(config_path)

    config = load_config(config_path)
    with pytest.raises(ConfigError, match="No files found"):
        validate_config(config)


def test_inspect_domain_paths_reports_all_domains_without_raising(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data"
    work_dir = tmp_path / "work"
    output_dir = tmp_path / "output"
    work_dir.mkdir()
    output_dir.mkdir()
    _write_encounter_csv(data_dir / "Encounter" / "encounter0001.csv")
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        textwrap.dedent(
            """
            data_dir: data
            work_dir: work
            output_dir: output
            domains:
              encounter:
                pattern: "Encounter/encounter*.csv"
              labs:
                pattern: "Lab Results/lab_result*.csv"
            """
        ).strip()
        + "\n"
    )

    config = load_config(config_path)
    inspections = inspect_domain_paths(config)

    assert [(item.name, item.matched_count) for item in inspections] == [
        ("encounter", 1),
        ("labs", 0),
    ]
    assert inspections[0].search_dir == data_dir.resolve() / "Encounter"
    assert inspections[0].search_dir_exists is True
    assert inspections[1].search_dir == data_dir.resolve() / "Lab Results"
    assert inspections[1].search_dir_exists is False


def test_inspect_domain_paths_reports_present_empty_search_dir(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data"
    work_dir = tmp_path / "work"
    output_dir = tmp_path / "output"
    work_dir.mkdir()
    output_dir.mkdir()
    (data_dir / "Lab Results").mkdir(parents=True)
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        textwrap.dedent(
            """
            data_dir: data
            work_dir: work
            output_dir: output
            domains:
              labs:
                pattern: "Lab Results/lab_result*.csv"
            """
        ).strip()
        + "\n"
    )

    config = load_config(config_path)
    inspections = inspect_domain_paths(config)

    assert len(inspections) == 1
    assert inspections[0].matched_count == 0
    assert inspections[0].search_dir == data_dir.resolve() / "Lab Results"
    assert inspections[0].search_dir_exists is True


def test_vitals_pattern_matches_historical_and_restored_spellings(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data"
    work_dir = tmp_path / "work"
    output_dir = tmp_path / "output"
    vitals_dir = data_dir / "Vital Signs"
    vitals_dir.mkdir(parents=True)
    work_dir.mkdir()
    output_dir.mkdir()
    (vitals_dir / "vital_signs0001.csv").write_text("patient_id\n")
    (vitals_dir / "vitals_signs.csv").write_text("patient_id\n")
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        textwrap.dedent(
            """
            data_dir: data
            work_dir: work
            output_dir: output
            domains:
              vitals:
                pattern: "Vital Signs/vital*_signs*.csv"
            """
        ).strip()
        + "\n"
    )

    config = load_config(config_path)
    inspections = inspect_domain_paths(config)

    assert len(inspections) == 1
    assert inspections[0].name == "vitals"
    assert inspections[0].matched_count == 2
    assert {path.name for path in inspections[0].paths} == {
        "vital_signs0001.csv",
        "vitals_signs.csv",
    }


def test_inspect_domain_paths_can_cap_matches(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    work_dir = tmp_path / "work"
    output_dir = tmp_path / "output"
    work_dir.mkdir()
    output_dir.mkdir()
    _write_encounter_csv(data_dir / "Encounter" / "encounter0001.csv")
    _write_encounter_csv(data_dir / "Encounter" / "encounter0002.csv")
    config_path = tmp_path / "config.yaml"
    _write_config(config_path)

    config = load_config(config_path)
    inspections = inspect_domain_paths(config, max_matches=1)

    assert len(inspections) == 1
    assert inspections[0].matched_count == 1
    assert inspections[0].truncated is True


def test_inspect_domain_paths_caps_space_containing_domain_dirs(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data"
    work_dir = tmp_path / "work"
    output_dir = tmp_path / "output"
    work_dir.mkdir()
    output_dir.mkdir()
    labs_dir = data_dir / "Lab Results"
    labs_dir.mkdir(parents=True)
    (labs_dir / "lab_result0001.csv").write_text("patient_id\n")
    (labs_dir / "lab_result0002.csv").write_text("patient_id\n")
    (labs_dir / "._lab_result0003.csv").write_text("ignored\n")
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        textwrap.dedent(
            """
            data_dir: data
            work_dir: work
            output_dir: output
            domains:
              labs:
                pattern: "Lab Results/lab_result*.csv"
            """
        ).strip()
        + "\n"
    )

    config = load_config(config_path)
    inspections = inspect_domain_paths(config, max_matches=1)

    assert len(inspections) == 1
    assert inspections[0].matched_count == 1
    assert inspections[0].truncated is True
    assert inspections[0].first_path is not None
    assert inspections[0].first_path.name.startswith("lab_result")


def test_inspect_domain_paths_can_filter_domains(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    work_dir = tmp_path / "work"
    output_dir = tmp_path / "output"
    work_dir.mkdir()
    output_dir.mkdir()
    _write_encounter_csv(data_dir / "Encounter" / "encounter0001.csv")
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        textwrap.dedent(
            """
            data_dir: data
            work_dir: work
            output_dir: output
            domains:
              encounter:
                pattern: "Encounter/encounter*.csv"
              labs:
                pattern: "Lab Results/lab_result*.csv"
            """
        ).strip()
        + "\n"
    )

    config = load_config(config_path)
    inspections = inspect_domain_paths(config, domain_names={"labs"})

    assert [item.name for item in inspections] == ["labs"]


def test_load_config_rejects_unknown_storage_format(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        textwrap.dedent(
            """
            data_dir: data
            work_dir: work
            output_dir: output
            storage:
              intermediate_format: sqlite
            domains:
              encounter:
                pattern: "Encounter/encounter*.csv"
            """
        ).strip()
        + "\n"
    )

    with pytest.raises(ConfigError, match="intermediate_format"):
        load_config(config_path)

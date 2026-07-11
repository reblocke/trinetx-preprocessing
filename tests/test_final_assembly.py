from __future__ import annotations

import json
import logging
import warnings
from contextlib import ExitStack
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from trinetx_preprocessing.config import (
    ChunkingConfig,
    Config,
    DomainConfig,
    GuardrailConfig,
    RfsConfig,
    StorageConfig,
)
from trinetx_preprocessing.pipeline import final_assembly
from trinetx_preprocessing.storage import iter_work_tables, write_work_table


def _config(
    tmp_path: Path,
    *,
    intermediate_format: str = "csv",
) -> Config:
    return Config(
        data_dir=tmp_path / "data",
        work_dir=tmp_path / "work",
        output_dir=tmp_path / "output",
        domains={"patient": DomainConfig(pattern="Patient/patient*.csv")},
        chunking=ChunkingConfig(enabled=True, lines_per_chunk=1),
        rfs=RfsConfig(),
        guardrails=GuardrailConfig(),
        storage=StorageConfig(
            intermediate_format=intermediate_format,
            emit_legacy_csv_intermediates=False,
            parquet_row_group_size=1,
        ),
    )


def test_final_output_columns_match_legacy_schema_fixture() -> None:
    fixture_path = Path(__file__).parent / "fixtures" / "final_output_columns.json"
    expected = json.loads(fixture_path.read_text())

    assert final_assembly.FINAL_OUTPUT_COLUMNS == expected
    assert len(final_assembly.FINAL_OUTPUT_COLUMNS) == 534
    assert final_assembly.FINAL_OUTPUT_COLUMNS.index(
        "death_year_month"
    ) < final_assembly.FINAL_OUTPUT_COLUMNS.index("location")


def test_recode_base_columns_maps_canonical_ethnicity() -> None:
    frame = pd.DataFrame(
        {
            "patient_id": ["P1", "P2", "P3", "P4", "P5"],
            "encounter_id": ["E1", "E2", "E3", "E4", "E5"],
            "ethnicity": [
                "Not Hispanic or Latino",
                "Hispanic or Latino",
                "Unknown",
                "Non-Hispanic",
                "Hispanic",
            ],
            "patient_regional_location": [
                "South",
                "Northeast",
                "Midwest",
                "West",
                "US",
            ],
            "sex": ["F", "M", "Unknown", "F", "M"],
            "race": ["White", "Asian", "Unknown", "Black", "Other"],
            "death_year_month": ["", "", "", "", ""],
        }
    )

    recoded = final_assembly._recode_legacy_base_columns(frame)

    assert recoded["ethnicity"].tolist() == [0, 1, 2, "Non-Hispanic", "Hispanic"]
    assert recoded["location"].tolist() == [0, 1, 2, 3, "US"]


def test_final_assembly_enriches_legacy_feature_families(tmp_path: Path) -> None:
    config = _config(tmp_path)
    event_candidates = pd.DataFrame(
        [
            {
                "patient_id": "P1",
                "encounter_id": "E1",
                "qualify_date": pd.Timestamp("2022-06-01"),
                "RFS": "ABG",
                "sex": "M",
                "race": "White",
                "ethnicity": "Not Hispanic or Latino",
                "patient_regional_location": "Midwest",
                "birth_year": 1980,
                "death_year_month": "",
            }
        ],
        columns=final_assembly.FINAL_EVENT_CANDIDATE_COLUMNS,
    )
    encounters = pd.DataFrame(
        [
            {
                "encounter_id": "E1",
                "start_date": "2022-06-01",
                "end_date": "2022-06-03",
                "LOS": 3,
            }
        ]
    )

    write_work_table(
        config,
        "value_BMI.csv",
        pd.DataFrame(
            [
                {
                    "patient_id": "P1",
                    "encounter_id": "E1",
                    "code": "39156-5",
                    "date": "2022-06-01",
                    "value": 45.0,
                }
            ]
        ),
    )
    write_work_table(
        config,
        "lab_results_NEW_0001.csv",
        pd.DataFrame(
            [
                {
                    "patient_id": "P1",
                    "encounter_id": "E1",
                    "code": "2019-8",
                    "date": "2022-05-31",
                    "lab_result_num_val": 5.0,
                },
                {
                    "patient_id": "P1",
                    "encounter_id": "E1",
                    "code": "2019-8",
                    "date": "2022-06-01",
                    "lab_result_num_val": 55.0,
                },
                {
                    "patient_id": "P1",
                    "encounter_id": "E1",
                    "code": "30241-4",
                    "date": "2022-06-02",
                    "lab_result_num_val": 90.08,
                },
                {
                    "patient_id": "P1",
                    "encounter_id": "E1",
                    "code": "2823-3",
                    "date": "2022-06-01",
                    "lab_result_num_val": 1.8,
                },
                {
                    "patient_id": "P1",
                    "encounter_id": "E1",
                    "code": "2744-1",
                    "date": "2022-06-01",
                    "lab_result_num_val": 7.4123456789,
                },
                {
                    "patient_id": "P1",
                    "encounter_id": "E1",
                    "code": "26515-7",
                    "date": "2022-06-01",
                    "lab_result_num_val": 123.456789,
                },
                {
                    "patient_id": "P1",
                    "encounter_id": "E1",
                    "code": "6690-2",
                    "date": "2022-06-01",
                    "lab_result_num_val": 28.24,
                },
                {
                    "patient_id": "P1",
                    "encounter_id": "E1",
                    "code": "30934-4",
                    "date": "2022-06-01",
                    "lab_result_num_val": 1234.567,
                },
            ]
        ),
    )
    write_work_table(
        config,
        "HAS_J9600.csv",
        pd.DataFrame(
            [
                {
                    "patient_id": "P1",
                    "encounter_id": "E1",
                    "code": "J96.00",
                    "principal_diagnosis_indicator": "Y",
                    "admitting_diagnosis": "N",
                    "reason_for_visit": "N",
                    "date": "2022-06-01",
                }
            ]
        ),
    )
    write_work_table(
        config,
        "HAS_94660.csv",
        pd.DataFrame(
            [
                {
                    "patient_id": "P1",
                    "encounter_id": "E1",
                    "code": "94660",
                    "date": "2022-06-01",
                }
            ]
        ),
    )
    write_work_table(
        config,
        "IPmed_list5.csv",
        pd.DataFrame(
            [
                {
                    "patient_id": "P1",
                    "encounter_id": "E1",
                    "code": "4603",
                    "start_date": "2022-06-01",
                }
            ]
        ),
    )

    result = final_assembly.build_final_dataset_from_candidates(
        event_candidates,
        encounters,
        config=config,
        rfs_category="ABG",
        setting="AMB",
        guardrails=config.guardrails,
        strict=False,
        logger=logging.getLogger(__name__),
    )

    assert list(result.columns) == final_assembly.FINAL_OUTPUT_COLUMNS
    row = result.iloc[0].to_dict()
    assert row["sex"] == 1
    assert row["race"] == 0
    assert row["ethnicity"] == 0
    assert row["location"] == 2
    assert row["LOS"] == 3
    assert row["date_BMI"] == "2022-06-01"
    assert row["value_BMI"] == 45.0
    assert row["date_20198"] == "2022-06-01"
    assert row["value_20198"] == 55.0
    assert row["date_highest_20198"] == "2022-06-01"
    assert row["value_highest_20198"] == 55.0
    assert row["date_Lactate_Venous_Blood"] == "2022-06-02"
    assert row["value_Lactate_Venous_Blood"] == pytest.approx(10.0)
    assert row["date_potassium"] == "2022-06-01"
    assert row["value_potassium"] == pytest.approx(float(np.float32(1.8)))
    assert row["date_27441"] == "2022-06-01"
    assert row["value_27441"] == pytest.approx(_legacy_lab_feature_value(7.4123456789))
    assert row["date_265157"] == "2022-06-01"
    assert row["value_265157"] == pytest.approx(_legacy_lab_feature_value(123.456789))
    assert row["date_264648"] == "2022-06-01"
    assert row["value_264648"] == pytest.approx(float(np.float32(28.24)))
    assert row["value_264648"] != pytest.approx(_legacy_lab_feature_value(28.24))
    assert row["date_bnp"] == "2022-06-01"
    assert row["value_bnp"] == pytest.approx(float(np.float32(1234.567)))
    assert row["value_bnp"] != pytest.approx(_legacy_lab_feature_value(1234.567))
    assert row["HAS_J9600"] == 1
    assert row["principal_diagnosis_indicator"] == "Y"
    assert row["date_J9600"] == "2022-06-01"
    assert row["HAS_94660"] == 1
    assert row["first_date_94660"] == "2022-06-01"
    assert row["last_date_94660"] == "2022-06-01"
    assert row["IP_Med_5"] == 1
    assert row["date_IP_Med_5"] == "2022-06-01"
    assert not list(config.work_dir.glob(".trinetx-final-labs-*"))


def _legacy_lab_feature_value(value: float) -> float:
    return float(np.float32(str(np.float16(value))))


def test_legacy_lab_half_dtype_masks_extreme_values_without_warning() -> None:
    rules = {rule.name: rule for rule in final_assembly.LAB_VALUE_RULES}

    with warnings.catch_warnings():
        warnings.simplefilter("error", RuntimeWarning)
        values = final_assembly._legacy_lab_feature_values(
            rules["value_27441"],
            pd.Series(["2744-1", "2744-1"], dtype="string"),
            pd.Series(["1e100", "7.4123456789"]),
        )

    assert pd.isna(values.iloc[0])
    assert values.iloc[1] == pytest.approx(float(np.float16(7.4123456789)))


def test_legacy_lab_float_rules_preserve_float_values() -> None:
    rules = {rule.name: rule for rule in final_assembly.LAB_VALUE_RULES}

    values = final_assembly._legacy_lab_feature_values(
        rules["value_264648"],
        pd.Series(["26464-8"], dtype="string"),
        pd.Series(["16.26"]),
    )
    bnp_values = final_assembly._legacy_lab_feature_values(
        rules["value_bnp"],
        pd.Series(["42637-9"], dtype="string"),
        pd.Series(["2681.0"]),
    )

    assert float(np.float32(str(values.iloc[0]))) == pytest.approx(
        float(np.float32("16.26"))
    )
    assert float(np.float32(str(bnp_values.iloc[0]))) == pytest.approx(
        float(np.float32("2681.0"))
    )
    assert float(np.float32(str(values.iloc[0]))) != pytest.approx(
        _legacy_lab_feature_value(16.26)
    )
    assert float(np.float32(str(bnp_values.iloc[0]))) != pytest.approx(
        _legacy_lab_feature_value(2681.0)
    )


def test_lactate_venous_blood_prefers_legacy_converted_code_on_ties(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    current = pd.DataFrame({"patient_id": ["P1"], "encounter_id": ["E1"]})
    write_work_table(
        config,
        "lab_results_NEW_0001.csv",
        pd.DataFrame(
            [
                {
                    "patient_id": "P1",
                    "encounter_id": "E1",
                    "code": "2519-7",
                    "date": "2022-01-01",
                    "lab_result_num_val": "0.9",
                },
                {
                    "patient_id": "P1",
                    "encounter_id": "E1",
                    "code": "30241-4",
                    "date": "2022-01-01",
                    "lab_result_num_val": "1.1",
                },
            ]
        ),
    )

    enriched = final_assembly._merge_lab_value_features(
        current,
        config=config,
        patient_ids={"P1"},
        encounter_ids={"E1"},
        chunksize=1,
    )

    assert enriched.loc[0, "value_Lactate_Venous_Blood"] == pytest.approx(
        float(np.float32(str(np.float16(1.1) / 9.008)))
    )


def test_previous_vitals_match_executed_notebook_selection_and_int32_output(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    event_candidates = pd.DataFrame(
        [
            {
                "patient_id": "P1",
                "encounter_id": "E_current_1",
                "qualify_date": pd.Timestamp("2022-06-10"),
                "RFS": "ABG",
                "sex": "M",
                "race": "White",
                "ethnicity": "Not Hispanic or Latino",
                "patient_regional_location": "Midwest",
                "birth_year": 1980,
                "death_year_month": "",
            },
            {
                "patient_id": "P2",
                "encounter_id": "E_current_2",
                "qualify_date": pd.Timestamp("2022-06-10"),
                "RFS": "ABG",
                "sex": "F",
                "race": "White",
                "ethnicity": "Not Hispanic or Latino",
                "patient_regional_location": "Midwest",
                "birth_year": 1980,
                "death_year_month": "",
            },
        ],
        columns=final_assembly.FINAL_EVENT_CANDIDATE_COLUMNS,
    )
    encounters = pd.DataFrame(
        [
            {
                "encounter_id": "E_current_1",
                "start_date": "2022-06-10",
                "end_date": "2022-06-11",
                "LOS": 1,
            },
            {
                "encounter_id": "E_current_2",
                "start_date": "2022-06-10",
                "end_date": "2022-06-11",
                "LOS": 1,
            },
        ]
    )

    write_work_table(
        config,
        "value_Weight.csv",
        pd.DataFrame(
            [
                {
                    "patient_id": "P1",
                    "encounter_id": "E_current_1",
                    "code": "29463-7",
                    "date": "2022-06-01",
                    "value": 220.9,
                },
                {
                    "patient_id": "P1",
                    "encounter_id": "E_future_1",
                    "code": "29463-7",
                    "date": "2022-06-20",
                    "value": 999.9,
                },
                {
                    "patient_id": "P1",
                    "encounter_id": "E_equal_1",
                    "code": "29463-7",
                    "date": "2022-06-10",
                    "value": 888.9,
                },
                {
                    "patient_id": "P1",
                    "encounter_id": "E_prev_9",
                    "code": "29463-7",
                    "date": "2022-05-20",
                    "value": 159.9,
                },
                {
                    "patient_id": "P1",
                    "encounter_id": "E_prev_1",
                    "code": "29463-7",
                    "date": "2022-04-01",
                    "value": 140.9,
                },
                {
                    "patient_id": "P1",
                    "encounter_id": "E_prev_1",
                    "code": "29463-7",
                    "date": "2022-05-01",
                    "value": 150.9,
                },
                {
                    "patient_id": "P2",
                    "encounter_id": "E_current_2",
                    "code": "29463-7",
                    "date": "2022-06-20",
                    "value": 170.9,
                },
            ]
        ),
    )
    write_work_table(
        config,
        "value_Height.csv",
        pd.DataFrame(
            [
                {
                    "patient_id": "P1",
                    "encounter_id": "E_current_1",
                    "code": "8302-2",
                    "date": "2022-06-02",
                    "value": 70.9,
                },
                {
                    "patient_id": "P1",
                    "encounter_id": "E_height_prev",
                    "code": "8302-2",
                    "date": "2022-05-15",
                    "value": 69.9,
                },
            ]
        ),
    )
    write_work_table(
        config,
        "value_BMI.csv",
        pd.DataFrame(
            [
                {
                    "patient_id": "P1",
                    "encounter_id": "E_current_1",
                    "code": "39156-5",
                    "date": "2022-06-03",
                    "value": 27.9,
                }
            ]
        ),
    )

    result = final_assembly.build_final_dataset_from_candidates(
        event_candidates,
        encounters,
        config=config,
        rfs_category="ABG",
        setting="AMB",
        guardrails=config.guardrails,
        strict=False,
        logger=logging.getLogger(__name__),
    )

    p1, p2 = result.sort_values("patient_id").to_dict("records")
    assert p1["value_Prev_Weight"] == 159
    assert p1["date_Prev_Weight"] == "2022-05-20"
    assert p1["value_Prev_Height"] == 69
    assert p1["date_Prev_Height"] == "2022-05-15"
    assert p1["value_Prev_BMI"] == 0
    assert pd.isna(p1["date_Prev_BMI"])
    assert p2["value_Prev_Weight"] == 0
    assert pd.isna(p2["date_Prev_Weight"])
    assert not list(config.work_dir.glob(".trinetx-final-prev-vitals-*"))


def test_prior_diagnosis_last_date_uses_latest_patient_row(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    current = pd.DataFrame(
        {
            "patient_id": ["P1", "P2", "P3"],
            "encounter_id": ["E1", "E2", "E3"],
            "qualify_date": pd.to_datetime(["2022-06-01", "2022-06-01", "2022-06-01"]),
        }
    )
    base = {
        "code": "G473",
        "principal_diagnosis_indicator": "Unknown",
        "admitting_diagnosis": "Unknown",
        "reason_for_visit": "Unknown",
    }
    write_work_table(
        config,
        "HAS_G473.csv",
        pd.DataFrame(
            [
                {
                    **base,
                    "patient_id": "P1",
                    "encounter_id": "P1_old",
                    "date": "2022-01-01",
                },
                {
                    **base,
                    "patient_id": "P1",
                    "encounter_id": "P1_future",
                    "date": "2022-12-01",
                },
                {
                    **base,
                    "patient_id": "P2",
                    "encounter_id": "P2_old",
                    "date": "2022-01-01",
                },
                {
                    **base,
                    "patient_id": "P2",
                    "encounter_id": "P2_latest",
                    "date": "2022-05-15",
                },
                {
                    **base,
                    "patient_id": "P3",
                    "encounter_id": "P3_future",
                    "date": "2022-12-01",
                },
            ]
        ),
    )

    enriched = final_assembly._merge_prior_diagnosis_features(
        current,
        config=config,
        patient_ids={"P1", "P2", "P3"},
        encounter_ids={"E1", "E2", "E3"},
        chunksize=1,
    )

    p1, p2, p3 = enriched.sort_values("patient_id").to_dict("records")
    assert p1["HAS_G473"] == 1
    assert p1["first_date_G473"] == pd.Timestamp("2022-01-01")
    assert p1["last_date_G473"] == pd.Timestamp("2022-01-01")
    assert p2["HAS_G473"] == 1
    assert p2["first_date_G473"] == pd.Timestamp("2022-01-01")
    assert p2["last_date_G473"] == pd.Timestamp("2022-05-15")
    assert p3["HAS_G473"] == 0
    assert pd.isna(p3["first_date_G473"])
    assert pd.isna(p3["last_date_G473"])


def test_encounter_first_last_features_use_latest_current_date(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    current = pd.DataFrame({"patient_id": ["P1"], "encounter_id": ["E1"]})
    write_work_table(
        config,
        "HAS_94660.csv",
        pd.DataFrame(
            [
                {
                    "patient_id": "P1",
                    "encounter_id": "E1",
                    "code": "94660",
                    "date": "2022-01-01",
                },
                {
                    "patient_id": "P1",
                    "encounter_id": "E1",
                    "code": "94660",
                    "date": "2022-05-15",
                },
            ]
        ),
    )

    enriched = final_assembly._merge_encounter_first_last_features(
        current,
        config=config,
        groups=final_assembly.PROCEDURE_CODE_GROUPS,
        source_columns=final_assembly.PROCEDURE_COLUMNS,
        patient_ids={"P1"},
        encounter_ids={"E1"},
        chunksize=1,
    )

    row = enriched.iloc[0]
    assert row["HAS_94660"] == 1
    assert row["first_date_94660"] == pd.Timestamp("2022-01-01")
    assert row["last_date_94660"] == pd.Timestamp("2022-05-15")


def _write_patient_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(path, index=False)


def test_load_demographics_streams_chunks_and_preserves_output(tmp_path: Path) -> None:
    first = tmp_path / "patient_1.csv"
    second = tmp_path / "patient_2.csv"
    base = {
        "sex": "F",
        "race": "White",
        "ethnicity": "Not Hispanic",
        "patient_regional_location": "US",
        "month_year_death": "",
    }
    _write_patient_csv(
        first,
        [
            {
                **base,
                "patient_id": "P1",
                "year_of_birth": 1980,
                "month_year_death": 202001,
            }
        ],
    )
    _write_patient_csv(
        second,
        [{**base, "patient_id": "P2", "year_of_birth": 1975}],
    )

    demographics = final_assembly._load_demographics(
        [first, second],
        logging.getLogger(__name__),
        chunksize=1,
    )

    assert list(demographics.columns) == final_assembly.DEMOGRAPHIC_OUTPUT_COLUMNS
    assert demographics.to_dict("records") == [
        {
            "patient_id": "P1",
            "sex": "F",
            "race": "White",
            "ethnicity": "Not Hispanic",
            "patient_regional_location": "US",
            "birth_year": 1980,
            "death_year_month": "2020-01",
        },
        {
            "patient_id": "P2",
            "sex": "F",
            "race": "White",
            "ethnicity": "Not Hispanic",
            "patient_regional_location": "US",
            "birth_year": 1975,
            "death_year_month": "",
        },
    ]


def test_load_demographics_detects_duplicate_patient_ids_across_chunks(
    tmp_path: Path,
) -> None:
    first = tmp_path / "patient_1.csv"
    second = tmp_path / "patient_2.csv"
    base = {
        "sex": "F",
        "race": "White",
        "ethnicity": "Not Hispanic",
        "patient_regional_location": "US",
        "month_year_death": "",
    }
    _write_patient_csv(first, [{**base, "patient_id": "P1", "year_of_birth": 1980}])
    _write_patient_csv(second, [{**base, "patient_id": "P1", "year_of_birth": 1975}])

    with pytest.raises(ValueError, match="duplicate patient_id"):
        final_assembly._load_demographics(
            [first, second],
            logging.getLogger(__name__),
            chunksize=1,
        )


def test_load_demographics_lookup_filters_and_cleans_up(tmp_path: Path) -> None:
    path = tmp_path / "patient.csv"
    work_dir = tmp_path / "work"
    base = {
        "sex": "F",
        "race": "White",
        "ethnicity": "Not Hispanic",
        "patient_regional_location": "US",
        "month_year_death": "",
    }
    _write_patient_csv(
        path,
        [
            {**base, "patient_id": "P1", "year_of_birth": 1980},
            {**base, "patient_id": "P2", "year_of_birth": 1975},
        ],
    )

    with ExitStack() as stack:
        lookup = final_assembly._load_demographics_lookup(
            [path],
            work_dir=work_dir,
            stack=stack,
            logger=logging.getLogger(__name__),
            chunksize=1,
        )
        frame = lookup.frame_for_patient_ids(pd.Series(["P2", "P3"], dtype="string"))

    assert frame["patient_id"].tolist() == ["P2"]
    assert frame["birth_year"].tolist() == [1975]
    assert not list(work_dir.glob(".trinetx-demographics-*"))


def test_load_demographics_lookup_detects_duplicate_patient_ids_across_chunks(
    tmp_path: Path,
) -> None:
    path = tmp_path / "patient.csv"
    work_dir = tmp_path / "work"
    base = {
        "sex": "F",
        "race": "White",
        "ethnicity": "Not Hispanic",
        "patient_regional_location": "US",
        "month_year_death": "",
    }
    _write_patient_csv(
        path,
        [
            {**base, "patient_id": "P1", "year_of_birth": 1980},
            {**base, "patient_id": "P1", "year_of_birth": 1975},
        ],
    )

    with pytest.raises(ValueError, match="duplicate patient_id"):
        with ExitStack() as stack:
            final_assembly._load_demographics_lookup(
                [path],
                work_dir=work_dir,
                stack=stack,
                logger=logging.getLogger(__name__),
                chunksize=1,
            )

    assert not list(work_dir.glob(".trinetx-demographics-*"))


def test_build_final_dataset_matches_demographics_lookup(
    tmp_path: Path,
) -> None:
    events = pd.DataFrame(
        {
            "patient_id": ["P1", "P2"],
            "encounter_id": ["E1", "E2"],
            "date": ["2022-01-02", "2022-01-03"],
        }
    )
    demographics = pd.DataFrame(
        {
            "patient_id": ["P1", "P2"],
            "sex": ["F", "M"],
            "race": ["White", "Black"],
            "ethnicity": ["Not Hispanic", "Not Hispanic"],
            "patient_regional_location": ["US", "US"],
            "birth_year": [1980, 1970],
            "death_year_month": ["", ""],
        }
    )
    encounters = pd.DataFrame(
        {
            "encounter_id": ["E1", "E2"],
            "start_date": ["2022-01-01", "2022-01-01"],
            "end_date": ["2022-01-05", "2022-01-05"],
            "LOS": [5, 5],
        }
    )

    expected = final_assembly.build_final_dataset(
        events,
        demographics,
        encounters,
        rfs_category="ABG",
        setting="AMB",
        guardrails=GuardrailConfig(),
        strict=True,
        logger=logging.getLogger(__name__),
    )
    with final_assembly._DemographicsLookup(tmp_path) as lookup:
        lookup.add_frame(demographics)
        actual = final_assembly.build_final_dataset(
            events,
            lookup,
            encounters,
            rfs_category="ABG",
            setting="AMB",
            guardrails=GuardrailConfig(),
            strict=True,
            logger=logging.getLogger(__name__),
        )

    assert actual.to_dict("records") == expected.to_dict("records")
    assert not list(tmp_path.glob(".trinetx-demographics-*"))


def test_build_final_event_candidates_drops_missing_demographics() -> None:
    events = pd.DataFrame(
        {
            "patient_id": ["P1", "P2"],
            "encounter_id": ["E1", "E2"],
            "date": ["2022-01-02", "2022-01-03"],
        }
    )
    demographics = pd.DataFrame(
        {
            "patient_id": ["P1", "P2"],
            "sex": [pd.NA, "M"],
            "race": ["White", "Black"],
            "ethnicity": ["Not Hispanic", "Not Hispanic"],
            "patient_regional_location": ["US", "US"],
            "birth_year": [1980, 1970],
            "death_year_month": ["", ""],
        }
    )

    candidates = final_assembly.build_final_event_candidates(
        events,
        demographics,
        rfs_category="ABG",
        context="ABG/test",
        guardrails=GuardrailConfig(),
        strict=True,
        logger=logging.getLogger(__name__),
    )

    assert candidates["patient_id"].tolist() == ["P2"]


def test_final_event_selection_is_independent_per_setting() -> None:
    events = pd.DataFrame(
        {
            "patient_id": ["P1", "P1"],
            "encounter_id": ["E_AMB", "E_EMER"],
            "date": ["2022-01-02", "2022-02-02"],
        }
    )
    demographics = pd.DataFrame(
        {
            "patient_id": ["P1"],
            "sex": ["F"],
            "race": ["White"],
            "ethnicity": ["Not Hispanic"],
            "patient_regional_location": ["US"],
            "birth_year": [1980],
            "death_year_month": [""],
        }
    )
    emergency_encounters = pd.DataFrame(
        {
            "patient_id": ["P1"],
            "encounter_id": ["E_EMER"],
            "start_date": ["2022-02-01"],
            "end_date": ["2022-02-03"],
            "type": ["EMER"],
            "LOS": [3],
        }
    )

    result = final_assembly.build_final_dataset(
        events,
        demographics,
        emergency_encounters,
        rfs_category="ABG",
        setting="EMER",
        guardrails=GuardrailConfig(),
        strict=True,
        logger=logging.getLogger(__name__),
    )

    assert result[["patient_id", "encounter_id"]].to_dict("records") == [
        {"patient_id": "P1", "encounter_id": "E_EMER"}
    ]


def test_streamed_setting_cohort_reduces_earliest_patient_across_partitions() -> (
    None
):
    rows = pd.DataFrame(
        {
            "patient_id": ["P1", "P1", "P2"],
            "encounter_id": ["E_LATE", "E_EARLY", "E_OTHER"],
            "qualify_date": ["2022-03-01", "2022-01-01", "2022-02-01"],
            "_data_screen_eligible": [False, True, True],
        }
    )

    selected = final_assembly.reduce_setting_cohort_rows(rows)

    assert selected[["patient_id", "encounter_id"]].to_dict("records") == [
        {"patient_id": "P1", "encounter_id": "E_EARLY"},
        {"patient_id": "P2", "encounter_id": "E_OTHER"},
    ]
    assert selected["_data_screen_eligible"].tolist() == [True, True]


def test_current_diagnosis_reduction_uses_earliest_date_and_indicator_priority() -> (
    None
):
    rows = pd.DataFrame(
        {
            "patient_id": ["P1", "P1", "P1"],
            "encounter_id": ["E1", "E1", "E1"],
            "code": ["J96.00"] * 3,
            "principal_diagnosis_indicator": ["U", "S", "P"],
            "admitting_diagnosis": ["U", "N", "Y"],
            "reason_for_visit": ["U", "F", "T"],
            "date": ["2022-01-03", "2022-01-01", "2022-01-02"],
        }
    )

    selected = final_assembly._select_current_diagnosis(rows).iloc[0]

    assert selected["date"] == pd.Timestamp("2022-01-01")
    assert selected["principal_diagnosis_indicator"] == "P"
    assert selected["admitting_diagnosis"] == "Y"
    assert selected["reason_for_visit"] == "T"


def test_inpatient_medication_uses_earliest_date_per_encounter() -> None:
    rows = pd.DataFrame(
        {
            "patient_id": ["P1", "P1", "P2"],
            "encounter_id": ["E1", "E1", "E2"],
            "code": ["4603", "4603", "4603"],
            "start_date": pd.to_datetime(["2022-03-01", "2022-01-01", "2022-02-01"]),
        }
    )

    selected = final_assembly._select_ip_medication(rows, med_index="5")

    assert selected.sort_values("encounter_id").to_dict("records") == [
        {
            "encounter_id": "E1",
            "IP_Med_5": 1,
            "date_IP_Med_5": pd.Timestamp("2022-01-01"),
        },
        {
            "encounter_id": "E2",
            "IP_Med_5": 1,
            "date_IP_Med_5": pd.Timestamp("2022-02-01"),
        },
    ]


def test_outpatient_medication_last_date_validated_independently(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    current = pd.DataFrame(
        {
            "patient_id": ["P1", "P2"],
            "encounter_id": ["E1", "E2"],
            "qualify_date": pd.to_datetime(["2022-06-01", "2022-06-01"]),
        }
    )
    write_work_table(
        config,
        "OPmed_list1.csv",
        pd.DataFrame(
            [
                {
                    "patient_id": "P1",
                    "encounter_id": "E0",
                    "code": "1808",
                    "start_date": "2022-01-01",
                },
                {
                    "patient_id": "P1",
                    "encounter_id": "E2",
                    "code": "1808",
                    "start_date": "2022-12-01",
                },
                {
                    "patient_id": "P2",
                    "encounter_id": "E3",
                    "code": "1808",
                    "start_date": "2022-12-01",
                },
            ]
        ),
    )

    enriched = final_assembly._merge_medication_features(
        current,
        config=config,
        patient_ids={"P1", "P2"},
        encounter_ids={"E1", "E2"},
        chunksize=1,
    )

    p1, p2 = enriched.sort_values("patient_id").to_dict("records")
    assert p1["OP_Med_1"] == 1
    assert p1["first_date_OP_Med_1"] == pd.Timestamp("2022-01-01")
    assert p1["last_date_OP_Med_1"] == pd.Timestamp("2022-01-01")
    assert p2["OP_Med_1"] == 0
    assert pd.isna(p2["first_date_OP_Med_1"])
    assert pd.isna(p2["last_date_OP_Med_1"])


def test_build_final_dataset_matches_encounter_lookup(
    tmp_path: Path,
) -> None:
    events = pd.DataFrame(
        {
            "patient_id": ["P1", "P2"],
            "encounter_id": ["E1", "E2"],
            "date": ["2022-01-02", "2022-01-03"],
        }
    )
    demographics = pd.DataFrame(
        {
            "patient_id": ["P1", "P2"],
            "sex": ["F", "M"],
            "race": ["White", "Black"],
            "ethnicity": ["Not Hispanic", "Not Hispanic"],
            "patient_regional_location": ["US", "US"],
            "birth_year": [1980, 1970],
            "death_year_month": ["", ""],
        }
    )
    encounters = pd.DataFrame(
        {
            "encounter_id": ["E1", "E2"],
            "start_date": ["2022-01-01", "2022-01-01"],
            "end_date": ["2022-01-05", "2022-01-05"],
            "LOS": [5, 5],
        }
    )

    expected = final_assembly.build_final_dataset(
        events,
        demographics,
        encounters,
        rfs_category="ABG",
        setting="AMB",
        guardrails=GuardrailConfig(),
        strict=True,
        logger=logging.getLogger(__name__),
    )
    with final_assembly._EncounterLookup(tmp_path) as lookup:
        lookup.add_frame(encounters)
        actual = final_assembly.build_final_dataset(
            events,
            demographics,
            lookup,
            rfs_category="ABG",
            setting="AMB",
            guardrails=GuardrailConfig(),
            strict=True,
            logger=logging.getLogger(__name__),
        )

    assert actual.to_dict("records") == expected.to_dict("records")
    assert not list(tmp_path.glob(".trinetx-final-encounters-*"))


def test_load_data_check_encounter_ids_streams_chunks(tmp_path: Path) -> None:
    path = tmp_path / "data_checks.csv"
    pd.DataFrame({"encounter_id": ["E1", None, "E2", "E1"]}).to_csv(
        path,
        index=False,
    )

    allowed = final_assembly._load_data_check_encounter_ids(
        path,
        logger=logging.getLogger(__name__),
        chunksize=2,
    )

    assert allowed == {"E1", "E2"}


def test_load_data_check_encounter_lookup_filters_and_cleans_up(
    tmp_path: Path,
) -> None:
    work_dir = tmp_path / "work"
    path = tmp_path / "data_checks.csv"
    pd.DataFrame({"encounter_id": ["E1", None, "E2", "E1"]}).to_csv(
        path,
        index=False,
    )

    with ExitStack() as stack:
        lookup = final_assembly._load_data_check_encounter_lookup(
            path,
            work_dir=work_dir,
            stack=stack,
            logger=logging.getLogger(__name__),
            chunksize=2,
        )
        assert lookup is not None
        assert lookup.count() == 2
        filtered = lookup.filter_frame(
            pd.DataFrame({"encounter_id": ["E3", "E1", "E2"]})
        )
        assert filtered["encounter_id"].tolist() == ["E1", "E2"]

    assert not list(work_dir.glob(".trinetx-data-check-ids-*"))


def test_data_screen_eligibility_is_precomputed_before_patient_bucketing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    work_dir = tmp_path / "work"
    frame = pd.DataFrame(
        {
            "patient_id": ["P1", "P2", "P3"],
            "encounter_id": ["E1", "E2", "E3"],
        }
    )

    with final_assembly._EncounterIdLookup(work_dir) as lookup:
        lookup.add_values(pd.Series(["E1", "E3"], dtype="string"))
        calls: list[int] = []
        original_filter = lookup.filter_frame

        def spy_filter(candidate: pd.DataFrame) -> pd.DataFrame:
            calls.append(len(candidate))
            return original_filter(candidate)

        monkeypatch.setattr(lookup, "filter_frame", spy_filter)
        marked = final_assembly._mark_data_screen_eligibility(frame, lookup)

    assert calls == [3]
    assert marked[final_assembly.FINAL_DATA_SCREEN_ELIGIBLE_COLUMN].tolist() == [
        True,
        False,
        True,
    ]

    after = final_assembly._apply_precomputed_data_screen(
        frame,
        marked[final_assembly.FINAL_DATA_SCREEN_ELIGIBLE_COLUMN],
        context="ABG/AMB",
        logger=logging.getLogger(__name__),
    )
    assert after["encounter_id"].tolist() == ["E1", "E3"]


def test_precomputed_data_screen_rejects_row_count_drift() -> None:
    with pytest.raises(ValueError, match="eligibility length"):
        final_assembly._apply_precomputed_data_screen(
            pd.DataFrame({"encounter_id": ["E1", "E2"]}),
            pd.Series([True]),
            context="ABG/AMB",
            logger=logging.getLogger(__name__),
        )


def test_run_final_assembly_removes_data_check_lookup_scratch(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    patient_dir = config.data_dir / "Patient"
    patient_dir.mkdir(parents=True)
    _write_patient_csv(
        patient_dir / "patient.csv",
        [
            {
                "patient_id": "P1",
                "sex": "F",
                "race": "White",
                "ethnicity": "Not Hispanic",
                "year_of_birth": 1980,
                "patient_regional_location": "US",
                "month_year_death": "",
            }
        ],
    )

    for filename in final_assembly.SETTING_ENCOUNTER_FILES.values():
        write_work_table(
            config,
            filename,
            pd.DataFrame(columns=final_assembly.ENCOUNTER_COLUMNS),
        )
    for category in final_assembly.RFS_CATEGORIES:
        write_work_table(
            config,
            f"RFS_{category}.csv",
            pd.DataFrame(columns=final_assembly.RFS_EVENT_COLUMNS),
        )

    data_checks_dir = config.work_dir / "data_checks"
    data_checks_dir.mkdir(parents=True)
    pd.DataFrame({"encounter_id": ["E1"]}).to_csv(
        data_checks_dir / "amb_enc_screen.csv",
        index=False,
    )
    pd.DataFrame({"encounter_id": ["E2"]}).to_csv(
        data_checks_dir / "inp_enc_screen.csv",
        index=False,
    )

    final_assembly.run_final_assembly(config)

    assert not list(config.work_dir.glob(".trinetx-data-check-ids-*"))
    assert not list(config.work_dir.glob(".trinetx-demographics-*"))
    assert not list(config.work_dir.glob(".trinetx-final-encounters-*"))


def test_apply_data_checks_loads_allowed_ids_in_chunks(tmp_path: Path) -> None:
    df = pd.DataFrame(
        {
            "patient_id": ["P1", "P2", "P3"],
            "encounter_id": ["E1", "E2", "E3"],
            "qualify_date": ["2022-01-01", "2022-01-02", "2022-01-03"],
            "RFS": ["ABG", "ABG", "ABG"],
            "encounter_type": ["AMB", "AMB", "AMB"],
            "age_at_encounter": [50, 60, 70],
            "sex": ["F", "M", "F"],
            "race": ["White", "Black", "Asian"],
            "ethnicity": ["Not Hispanic", "Not Hispanic", "Hispanic"],
            "patient_regional_location": ["US", "US", "US"],
            "death_year_month": ["", "", ""],
            "LOS": [1, 2, 3],
        }
    )
    path = tmp_path / "data_checks.csv"
    pd.DataFrame({"encounter_id": ["E3", "E1"]}).to_csv(path, index=False)

    result = final_assembly.apply_data_checks(
        df,
        path,
        chunksize=1,
        context="ABG/AMB",
    )

    assert result["encounter_id"].tolist() == ["E1", "E3"]


def test_apply_data_checks_reuses_preloaded_allowed_ids(
    tmp_path: Path,
    monkeypatch,
) -> None:
    df = pd.DataFrame(
        {
            "patient_id": ["P1", "P2"],
            "encounter_id": ["E1", "E2"],
            "qualify_date": ["2022-01-01", "2022-01-02"],
            "RFS": ["ABG", "ABG"],
            "encounter_type": ["AMB", "AMB"],
            "age_at_encounter": [50, 60],
            "sex": ["F", "M"],
            "race": ["White", "Black"],
            "ethnicity": ["Not Hispanic", "Not Hispanic"],
            "patient_regional_location": ["US", "US"],
            "death_year_month": ["", ""],
            "LOS": [1, 2],
        }
    )

    def fail_read_csv(*args, **kwargs):
        raise AssertionError("data checks should already be loaded")

    monkeypatch.setattr(final_assembly.pd, "read_csv", fail_read_csv)

    result = final_assembly.apply_data_checks(
        df,
        tmp_path / "data_checks.csv",
        allowed_encounter_ids={"E2"},
        context="ABG/AMB",
    )

    assert result["encounter_id"].tolist() == ["E2"]


def test_load_encounter_streams_work_table_chunks(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config = _config(tmp_path, intermediate_format="csv")
    write_work_table(
        config,
        "AMB_encounters.csv",
        pd.DataFrame(
            {
                "encounter_id": ["E1", "E2"],
                "start_date": ["2022-01-01", "2022-01-02"],
                "end_date": ["2022-01-02", "2022-01-03"],
                "LOS": [1, 1],
                "unused": ["drop", "drop"],
            }
        ),
    )
    observed_chunksizes: list[int | None] = []

    def spy_iter_work_tables(*args, **kwargs):
        observed_chunksizes.append(kwargs.get("chunksize"))
        yield from iter_work_tables(*args, **kwargs)

    monkeypatch.setattr(final_assembly, "iter_work_tables", spy_iter_work_tables)

    encounters = final_assembly._load_encounter(
        config,
        "AMB",
        logging.getLogger(__name__),
        chunksize=config.chunking.lines_per_chunk,
    )

    assert observed_chunksizes == [1]
    assert list(encounters.columns) == final_assembly.ENCOUNTER_COLUMNS
    assert encounters.to_dict("records") == [
        {
            "encounter_id": "E1",
            "start_date": "2022-01-01",
            "end_date": "2022-01-02",
            "LOS": 1,
        },
        {
            "encounter_id": "E2",
            "start_date": "2022-01-02",
            "end_date": "2022-01-03",
            "LOS": 1,
        },
    ]


def test_load_encounter_lookup_filters_and_cleans_up(tmp_path: Path) -> None:
    config = _config(tmp_path, intermediate_format="csv")
    write_work_table(
        config,
        "AMB_encounters.csv",
        pd.DataFrame(
            {
                "encounter_id": ["E1", "E2"],
                "start_date": ["2022-01-01", "2022-01-02"],
                "end_date": ["2022-01-02", "2022-01-03"],
                "LOS": [1, 2],
                "unused": ["drop", "drop"],
            }
        ),
    )

    with ExitStack() as stack:
        lookup = final_assembly._load_encounter_lookup(
            config,
            "AMB",
            logging.getLogger(__name__),
            stack=stack,
            chunksize=1,
        )
        frame = lookup.frame_for_encounter_ids(pd.Series(["E2", "E3"], dtype="string"))

    assert frame["encounter_id"].tolist() == ["E2"]
    assert frame["LOS"].tolist() == [2]
    assert not list(config.work_dir.glob(".trinetx-final-encounters-*"))


def test_load_encounter_lookup_detects_duplicate_encounter_ids(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path, intermediate_format="csv")
    write_work_table(
        config,
        "AMB_encounters.csv",
        pd.DataFrame(
            {
                "encounter_id": ["E1", "E1"],
                "start_date": ["2022-01-01", "2022-01-02"],
                "end_date": ["2022-01-02", "2022-01-03"],
                "LOS": [1, 2],
            }
        ),
    )

    with pytest.raises(ValueError, match="duplicate encounter_id"):
        with ExitStack() as stack:
            final_assembly._load_encounter_lookup(
                config,
                "AMB",
                logging.getLogger(__name__),
                stack=stack,
                chunksize=1,
            )

    assert not list(config.work_dir.glob(".trinetx-final-encounters-*"))


def test_final_event_candidate_store_reduces_by_encounter_only(
    tmp_path: Path,
) -> None:
    candidates = pd.DataFrame(
        {
            "patient_id": ["P1", "P1", "P2", "P2"],
            "encounter_id": ["E1", "E2", "E3", "E3"],
            "qualify_date": [
                "2022-01-05",
                "2022-01-04",
                "2022-01-07",
                "2022-01-03",
            ],
            "RFS": ["ABG", "ABG", "ABG", "ABG"],
            "sex": ["F", "F", "M", "M"],
            "race": ["White", "White", "Black", "Black"],
            "ethnicity": [
                "Not Hispanic",
                "Not Hispanic",
                "Not Hispanic",
                "Not Hispanic",
            ],
            "patient_regional_location": ["US", "US", "US", "US"],
            "birth_year": [1980, 1980, 1970, 1970],
            "death_year_month": ["", "", "", ""],
        }
    )

    with final_assembly._FinalEventCandidateStore(tmp_path) as store:
        store.add_frame(candidates.iloc[:2])
        store.add_frame(candidates.iloc[2:])
        reduced = store.reduce()

    assert reduced.sort_values(["patient_id", "encounter_id"])[
        ["patient_id", "encounter_id", "qualify_date"]
    ].to_dict("records") == [
        {
            "patient_id": "P1",
            "encounter_id": "E1",
            "qualify_date": pd.Timestamp("2022-01-05"),
        },
        {
            "patient_id": "P1",
            "encounter_id": "E2",
            "qualify_date": pd.Timestamp("2022-01-04"),
        },
        {
            "patient_id": "P2",
            "encounter_id": "E3",
            "qualify_date": pd.Timestamp("2022-01-03"),
        },
    ]
    assert not list(tmp_path.glob(".trinetx-final-events-*"))


def test_load_final_event_candidates_cleans_category_scratch_before_return(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path, intermediate_format="parquet")
    write_work_table(
        config,
        "RFS_ABG.csv",
        pd.DataFrame(
            {
                "patient_id": ["P1", "P1", "P2"],
                "encounter_id": ["E1", "E2", "E3"],
                "date": ["2022-01-05", "2022-01-04", "2022-01-03"],
                "unused": ["drop", "drop", "drop"],
            }
        ),
    )
    demographics = pd.DataFrame(
        {
            "patient_id": ["P1", "P2"],
            "sex": ["F", "M"],
            "race": ["White", "Black"],
            "ethnicity": ["Not Hispanic", "Not Hispanic"],
            "patient_regional_location": ["US", "US"],
            "birth_year": [1980, 1970],
            "death_year_month": ["", ""],
        },
        columns=final_assembly.DEMOGRAPHIC_OUTPUT_COLUMNS,
    )

    with final_assembly._DemographicsLookup(config.work_dir) as lookup:
        lookup.add_frame(demographics)
        candidates = final_assembly._load_final_event_candidates(
            config,
            "ABG",
            lookup,
            logging.getLogger(__name__),
            chunksize=config.chunking.lines_per_chunk,
            guardrails=GuardrailConfig(),
            strict=True,
        )
        assert not list(config.work_dir.glob(".trinetx-final-events-*"))
        assert not list(config.work_dir.glob(".trinetx-final-patients-*"))

    assert candidates.sort_values(["patient_id", "encounter_id"])[
        ["patient_id", "encounter_id", "qualify_date"]
    ].to_dict("records") == [
        {
            "patient_id": "P1",
            "encounter_id": "E1",
            "qualify_date": pd.Timestamp("2022-01-05"),
        },
        {
            "patient_id": "P1",
            "encounter_id": "E2",
            "qualify_date": pd.Timestamp("2022-01-04"),
        },
        {
            "patient_id": "P2",
            "encounter_id": "E3",
            "qualify_date": pd.Timestamp("2022-01-03"),
        },
    ]


def test_final_event_candidate_store_cleanup_raises_on_delete_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_remove_tree(path, *, context):
        raise PermissionError(f"denied: {context}")

    monkeypatch.setattr(
        "trinetx_preprocessing.storage.remove_tree_strict",
        fail_remove_tree,
    )

    with pytest.raises(PermissionError, match="Final event candidate scratch"):
        with final_assembly._FinalEventCandidateStore(tmp_path):
            pass


def test_final_encounter_lookup_cleanup_raises_on_delete_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_remove_tree(path, *, context):
        raise PermissionError(f"denied: {context}")

    monkeypatch.setattr(
        "trinetx_preprocessing.storage.remove_tree_strict",
        fail_remove_tree,
    )

    with pytest.raises(PermissionError, match="Final encounter lookup scratch"):
        with final_assembly._EncounterLookup(tmp_path):
            pass


def test_final_lab_candidate_store_cleanup_raises_on_delete_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_remove_tree(path, *, context):
        raise PermissionError(f"denied: {context}")

    monkeypatch.setattr(
        "trinetx_preprocessing.storage.remove_tree_strict",
        fail_remove_tree,
    )

    with pytest.raises(PermissionError, match="Final lab feature scratch"):
        with final_assembly._FinalLabCandidateStore(tmp_path):
            pass


def test_final_previous_vital_candidate_store_cleanup_raises_on_delete_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_remove_tree(path, *, context):
        raise PermissionError(f"denied: {context}")

    monkeypatch.setattr(
        "trinetx_preprocessing.storage.remove_tree_strict",
        fail_remove_tree,
    )

    with pytest.raises(PermissionError, match="Final previous vital scratch"):
        with final_assembly._FinalPreviousVitalCandidateStore(tmp_path):
            pass


def test_load_rfs_event_streams_parquet_work_table_chunks(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config = _config(tmp_path, intermediate_format="parquet")
    write_work_table(
        config,
        "RFS_ABG.csv",
        pd.DataFrame(
            {
                "patient_id": ["P1", "P2"],
                "encounter_id": ["E1", "E2"],
                "date": ["2022-01-01", "2022-01-02"],
                "unused": ["drop", "drop"],
            }
        ),
    )
    observed_chunksizes: list[int | None] = []

    def spy_iter_work_tables(*args, **kwargs):
        observed_chunksizes.append(kwargs.get("chunksize"))
        yield from iter_work_tables(*args, **kwargs)

    monkeypatch.setattr(final_assembly, "iter_work_tables", spy_iter_work_tables)

    events = final_assembly._load_rfs_event(
        config,
        "ABG",
        logging.getLogger(__name__),
        chunksize=config.chunking.lines_per_chunk,
    )

    assert observed_chunksizes == [1]
    assert list(events.columns) == final_assembly.RFS_EVENT_COLUMNS
    assert events.to_dict("records") == [
        {"patient_id": "P1", "encounter_id": "E1", "date": "2022-01-01"},
        {"patient_id": "P2", "encounter_id": "E2", "date": "2022-01-02"},
    ]


def test_run_final_assembly_reuses_rfs_and_setting_inputs(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config = _config(tmp_path)
    encounter_calls: list[tuple[str, int | None]] = []
    rfs_calls: list[tuple[str, int | None, bool]] = []
    data_check_calls: list[int | None] = []
    demographics_calls: list[int | None] = []

    monkeypatch.setattr(
        final_assembly,
        "collect_domain_paths",
        lambda config: {"patient": [tmp_path / "patient.csv"]},
    )
    monkeypatch.setattr(
        final_assembly,
        "_load_demographics_lookup",
        lambda paths,
        *,
        work_dir,
        stack,
        logger,
        chunksize=None: demographics_calls.append(chunksize)
        or pd.DataFrame(columns=final_assembly.DEMOGRAPHIC_OUTPUT_COLUMNS),
    )

    def fake_load_encounter_lookup(config, setting, logger, *, stack, chunksize=None):
        encounter_calls.append((setting, chunksize))
        return pd.DataFrame(columns=final_assembly.ENCOUNTER_COLUMNS)

    def fake_iter_final_event_candidate_frames(
        config,
        category,
        demographics,
        logger,
        *,
        chunksize,
        guardrails,
        strict,
    ):
        rfs_calls.append((category, chunksize, strict))
        yield pd.DataFrame(columns=final_assembly.FINAL_EVENT_CANDIDATE_COLUMNS)

    def fake_load_data_check_encounter_lookup(
        data_checks_path,
        *,
        work_dir,
        stack,
        logger,
        chunksize=None,
    ):
        data_check_calls.append(chunksize)
        return None

    def fake_build_final_dataset_from_candidates(
        event_candidates,
        encounters,
        *,
        config=None,
        rfs_category,
        setting,
        guardrails,
        strict,
        logger,
        enrich_features=True,
        finalize_output=True,
    ):
        return pd.DataFrame(
            [
                {
                    "patient_id": f"P_{rfs_category}_{setting}",
                    "encounter_id": f"E_{rfs_category}_{setting}",
                    "qualify_date": "2022-01-01",
                    "RFS": rfs_category,
                    "encounter_type": setting,
                    "age_at_encounter": 50,
                    "sex": "F",
                    "race": "White",
                    "ethnicity": "Not Hispanic",
                    "patient_regional_location": "US",
                    "death_year_month": "",
                    "LOS": 1,
                }
            ]
        )

    monkeypatch.setattr(
        final_assembly,
        "_load_encounter_lookup",
        fake_load_encounter_lookup,
    )
    monkeypatch.setattr(
        final_assembly,
        "_iter_final_event_candidate_frames",
        fake_iter_final_event_candidate_frames,
    )
    monkeypatch.setattr(
        final_assembly,
        "_load_data_check_encounter_lookup",
        fake_load_data_check_encounter_lookup,
    )
    monkeypatch.setattr(
        final_assembly,
        "_load_derived_data_screen_lookup",
        lambda config,
        *,
        work_dir,
        stack,
        logger,
        chunksize,
        strict: data_check_calls.append(chunksize) or None,
    )
    monkeypatch.setattr(
        final_assembly,
        "build_final_dataset_from_candidates",
        fake_build_final_dataset_from_candidates,
    )

    outputs = final_assembly.run_final_assembly(config)

    assert encounter_calls == [
        (setting, config.chunking.lines_per_chunk)
        for setting in final_assembly.SETTINGS
    ]
    assert rfs_calls == [
        (category, config.chunking.lines_per_chunk, False)
        for category in final_assembly.RFS_CATEGORIES
    ]
    assert demographics_calls == [config.chunking.lines_per_chunk]
    assert data_check_calls == [config.chunking.lines_per_chunk]

    expected_outputs = [
        config.output_dir
        / final_assembly.SETTING_OUTPUT_DIRS[setting]
        / f"RFS_{category}_ENC_{setting}_{suffix}.csv"
        for setting in final_assembly.SETTINGS
        for category in final_assembly.RFS_CATEGORIES
        for suffix in ("BEFORE", "AFTER")
    ]
    assert outputs == expected_outputs
    assert all(path.exists() for path in expected_outputs)

"""Hand-counted aggregate categories for a candidate canonical source."""

import duckdb
import pandas as pd
import pytest

from trinetx_preprocessing.combined_preprocessing import (
    cohort_source_population_audit as population_audit,
)


def _source() -> duckdb.DuckDBPyConnection:
    connection = duckdb.connect()
    connection.execute(
        "CREATE TABLE source_encounter(patient_id VARCHAR, encounter_id VARCHAR, "
        "start_date VARCHAR, start_timestamp_precision VARCHAR)"
    )
    connection.executemany(
        "INSERT INTO source_encounter VALUES (?,?,?,?)",
        [
            ("001", "A", "2024-01-01", "date_only"),
            ("001", "A", "2024-01-02", "date_only"),
            ("002", "other", "2024-02-01", "date_only"),
            ("004", "D", "2024-04-01T10:00:00Z", "timestamp"),
            ("nullkey", None, "2024-04-02", "date_only"),
            ("extra", "X", "2024-05-01", "date_only"),
        ],
    )
    return connection


def test_historical_key_coverage_and_source_precision_are_separate_counts():
    historical = pd.DataFrame(
        {
            "patient_id": ["001", "002", "003", "004", "nullkey"],
            "encounter_id": ["A", "B", "C", "D", "wanted"],
        }
    )
    with _source() as connection:
        result = population_audit.audit_candidate_population(connection, historical)
        assert result.historical_patients == 5
        assert result.exact_index_present == 2
        assert result.patient_present_index_missing == 2
        assert result.patient_absent == 1
        assert result.complete_historical_key_coverage is False
        assert result.exact_index_keys_with_conflicting_starts == 1
        assert result.exact_index_source_rows == 3
        assert result.timestamp_start_rows == 1
        assert result.date_only_start_rows == 2
        assert result.other_precision_start_rows == 0
        assert (
            connection.execute("SELECT count(*) FROM source_encounter").fetchone()[0]
            == 6
        )


def test_missing_and_observed_starts_are_a_conflict_for_the_same_index_key():
    historical = pd.DataFrame({"patient_id": ["001"], "encounter_id": ["A"]})
    with duckdb.connect() as connection:
        connection.execute(
            "CREATE TABLE source_encounter(patient_id VARCHAR, encounter_id VARCHAR, "
            "start_date VARCHAR, start_timestamp_precision VARCHAR)"
        )
        connection.executemany(
            "INSERT INTO source_encounter VALUES (?,?,?,?)",
            [
                ("001", "A", None, None),
                ("001", "A", "2024-01-01", "date_only"),
            ],
        )
        result = population_audit.audit_candidate_population(connection, historical)
        assert result.exact_index_present == 1
        assert result.exact_index_source_rows == 2
        assert result.exact_index_keys_with_conflicting_starts == 1
        assert result.date_only_start_rows == 1
        assert result.other_precision_start_rows == 1


@pytest.mark.parametrize(
    "historical,error",
    [
        (
            pd.DataFrame({"patient_id": ["001", "001"], "encounter_id": ["A", "B"]}),
            "one nonnull index",
        ),
        (
            pd.DataFrame({"patient_id": ["001"], "encounter_id": [None]}),
            "one nonnull index",
        ),
        (
            pd.DataFrame({"patient_id": [1], "encounter_id": ["A"]}),
            "original strings",
        ),
        (
            pd.DataFrame({"patient_id": ["001"], "encounter_id": [" "]}),
            "one nonnull index",
        ),
    ],
)
def test_population_audit_rejects_invalid_historical_keys(historical, error):
    with _source() as connection:
        with pytest.raises(ValueError, match=error):
            population_audit.audit_candidate_population(connection, historical)

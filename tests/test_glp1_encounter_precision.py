"""The migration adapter preserves the reference encounter precision contract."""

import duckdb
import pytest

from trinetx_preprocessing.combined_preprocessing.glp1_adapter import (
    _SOURCE_HASH_COLUMNS,
    _create_encounter_source,
)


@pytest.mark.parametrize(
    "raw_end,canonical_precision,expected",
    [
        (None, None, "timestamp"),
        ("", None, "timestamp"),
        ("  ", None, "timestamp"),
        ("20240102", "date_only", "date_only"),
        ("2024-01-02", "date_only", "date_only"),
        ("2024-01-02 12:30:00", "timestamp", "timestamp"),
        ("invalid", "timestamp", "timestamp"),
    ],
)
def test_encounter_adapter_retains_reference_precision(
    raw_end, canonical_precision, expected
):
    with duckdb.connect() as con:
        con.execute("ATTACH ':memory:' AS preprocessed")
        fields = [
            f'"{name}" VARCHAR' for name in _SOURCE_HASH_COLUMNS["source_encounter"]
        ]
        fields += [
            "start_datetime TIMESTAMP",
            "end_datetime TIMESTAMP",
            "end_timestamp_precision VARCHAR",
            "source_file VARCHAR",
        ]
        con.execute(
            "CREATE TABLE preprocessed.source_encounter (" + ",".join(fields) + ")"
        )
        con.execute(
            "INSERT INTO preprocessed.source_encounter "
            "(patient_id,encounter_id,end_date,end_timestamp_precision,source_file) "
            "VALUES ('p','e',?,?,'synthetic.csv')",
            [raw_end, canonical_precision],
        )
        con.execute("CREATE TABLE gas_candidate_patient AS SELECT 'p' AS patient_id")
        con.execute(
            "CREATE TABLE gas_candidate_encounter AS SELECT 'e' AS encounter_id"
        )
        _create_encounter_source(con)
        assert con.execute(
            "SELECT end_date, encounter_end_precision FROM source_encounter"
        ).fetchall() == [(raw_end, expected)]
        # The canonical representation remains untouched, including absent precision.
        assert con.execute(
            "SELECT end_timestamp_precision FROM preprocessed.source_encounter"
        ).fetchone() == (canonical_precision,)

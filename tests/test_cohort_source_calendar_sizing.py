"""Full-source calendar sizing returns aggregate hints without inclusion."""

import duckdb

from trinetx_preprocessing.combined_preprocessing.cohort_source_calendar_sizing import (
    audit_calendar_source_sizing,
)


def _source(connection):
    connection.execute(
        "CREATE TABLE source_encounter(patient_id VARCHAR,encounter_id VARCHAR,"
        "start_date VARCHAR,start_timestamp_precision VARCHAR,type VARCHAR)"
    )
    connection.execute(
        "CREATE TABLE source_patient(patient_id VARCHAR,year_of_birth VARCHAR)"
    )
    connection.execute(
        "INSERT INTO source_encounter VALUES "
        "('p1','e1','20240101','date_only','emer'),"
        "('p1','e1','2024-01-01','date_only','EMER'),"
        "('p1','e2','2024-02-30','date_only','IMP'),"
        "('p2','e3','2024-03-01','date_only','OUT'),"
        "('p3','e4','2024-04-01','timestamp','IMP'),"
        "('', 'e5','2024-05-01','date_only','EMER'),"
        "('p4','e6',NULL,'date_only',NULL)"
    )
    connection.execute(
        "INSERT INTO source_patient VALUES "
        "('p1','1980'),('p2',NULL),('p3','2000'),('p4','20x0')"
    )


def test_calendar_source_sizing_keeps_duplicates_and_uncertain_values(tmp_path):
    path = tmp_path / "canonical.duckdb"
    with duckdb.connect(str(path)) as connection:
        _source(connection)
    with duckdb.connect(str(path), read_only=True) as connection:
        audit = audit_calendar_source_sizing(connection)
    assert (
        audit.source_encounter_rows,
        audit.invalid_encounter_key_rows,
        audit.date_only_rows,
        audit.parseable_date_only_rows,
        audit.in_scope_type_rows,
        audit.in_scope_type_with_parseable_date_rows,
        audit.missing_type_rows,
        audit.source_patient_rows,
        audit.invalid_birth_year_rows,
    ) == (7, 1, 6, 4, 5, 3, 1, 4, 2)
    assert 3 <= audit.approximate_distinct_encounter_keys <= 7
    assert 2 <= audit.approximate_in_scope_encounter_keys <= 5
    assert 2 <= audit.approximate_distinct_patient_ids <= 5


def test_calendar_source_sizing_empty_source():
    with duckdb.connect() as connection:
        connection.execute(
            "CREATE TABLE source_encounter(patient_id VARCHAR,encounter_id VARCHAR,"
            "start_date VARCHAR,start_timestamp_precision VARCHAR,type VARCHAR)"
        )
        connection.execute(
            "CREATE TABLE source_patient(patient_id VARCHAR,year_of_birth VARCHAR)"
        )
        audit = audit_calendar_source_sizing(connection)
        assert all(value == 0 for value in audit.__dict__.values())

"""Source-scope counts describe observed capture without implying negatives."""

import duckdb
import pytest

from trinetx_preprocessing.combined_preprocessing.cohort_source_scope_audit import (
    audit_candidate_source_scope,
)


def _source() -> duckdb.DuckDBPyConnection:
    connection = duckdb.connect()
    connection.execute("CREATE TABLE historical_patients(patient_id VARCHAR)")
    connection.execute("INSERT INTO historical_patients VALUES ('p1'),('p2'),('p3')")
    connection.execute("CREATE TABLE source_patient(patient_id VARCHAR)")
    connection.execute("INSERT INTO source_patient VALUES ('p1'),('p2'),('extra')")
    connection.execute(
        "CREATE TABLE patient_observability("
        "patient_id VARCHAR, logical_domain VARCHAR, event_count UBIGINT, "
        "first_event_datetime TIMESTAMP, last_event_datetime TIMESTAMP)"
    )
    connection.execute(
        "INSERT INTO patient_observability VALUES "
        "('p1','labs',2,'2024-01-01','2024-01-02'),"
        "('p2','labs',1,'2024-02-01','2024-02-01'),"
        "('p1','diagnosis',1,'2024-01-03','2024-01-03'),"
        "('p2','medications',3,'2024-01-04','2024-01-05'),"
        "('extra','labs',100,'2020-01-01','2025-01-01')"
    )
    connection.execute("CREATE TABLE source_file_inventory(domain VARCHAR)")
    connection.execute(
        "INSERT INTO source_file_inventory VALUES "
        "('labs'),('labs'),('diagnosis'),('meds'),('patient')"
    )
    return connection


def test_candidate_scope_uses_historical_patient_set_and_raw_inventory_alias():
    with _source() as connection:
        result = audit_candidate_source_scope(
            connection, historical_patient_relation="historical_patients"
        )
    assert result.historical_patients == 3
    assert result.source_patient_present == 2
    assert result.source_patient_missing == 1
    assert result.invalid_observability_rows == 0
    domains = {item.domain: item for item in result.domains}
    assert domains["labs"].patients_with_records == 2
    assert domains["labs"].patients_without_records == 1
    assert domains["labs"].observed_event_rows == 3
    assert domains["labs"].first_observed_event == "2024-01-01T00:00:00"
    assert domains["labs"].last_observed_event == "2024-02-01T00:00:00"
    assert domains["labs"].source_files == 2
    assert domains["medications"].patients_with_records == 1
    assert domains["medications"].observed_event_rows == 3
    assert domains["medications"].source_files == 1
    assert domains["vitals"].patients_with_records == 0
    assert domains["vitals"].patients_without_records == 3
    assert domains["vitals"].first_observed_event is None


def test_candidate_scope_rejects_bad_historical_grain_or_relation_name():
    with _source() as connection:
        with pytest.raises(ValueError, match="safe identifier"):
            audit_candidate_source_scope(
                connection,
                historical_patient_relation="historical_patients;DROP TABLE x",
            )
        connection.execute("INSERT INTO historical_patients VALUES ('p1')")
        with pytest.raises(ValueError, match="one nonblank row per patient"):
            audit_candidate_source_scope(
                connection, historical_patient_relation="historical_patients"
            )

"""Synthetic raw-vital projection across exact selected patient indexes."""

import duckdb
import pytest

from trinetx_preprocessing.combined_preprocessing.cohort_source_calendar_vitals import (
    iter_calendar_vital_candidates,
)

ELEMENT = "source.traditional.vital.value_bmi"


def _source() -> duckdb.DuckDBPyConnection:
    connection = duckdb.connect()
    connection.execute("CREATE TABLE selected(patient_id VARCHAR,encounter_id VARCHAR)")
    connection.execute(
        "INSERT INTO selected VALUES ('p','index'),('q','index'),('r','index')"
    )
    connection.execute(
        "CREATE TABLE element_catalog(element_id VARCHAR,domain VARCHAR)"
    )
    connection.execute("INSERT INTO element_catalog VALUES (?,'vital')", [ELEMENT])
    connection.execute(
        "CREATE TABLE source_vital_measurement("
        "patient_id VARCHAR,encounter_id VARCHAR,source_record_id VARCHAR,"
        "date VARCHAR,event_datetime TIMESTAMP,timestamp_precision VARCHAR,"
        "code_system_raw VARCHAR,code_system VARCHAR,code_raw VARCHAR,"
        "code VARCHAR,value VARCHAR,numeric_value DOUBLE,"
        "units_of_measure_raw VARCHAR,units_of_measure VARCHAR)"
    )
    connection.execute(
        "INSERT INTO source_vital_measurement VALUES "
        "('p','history','bmi-1','2024-01-01','2024-01-01','date_only',"
        "'LOINC','LOINC','39156-5','39156-5','32',32,'kg/m2','kg/m2'),"
        "('p','index','bmi-2','2024-02-01','2024-02-01','date_only',"
        "'LOINC','LOINC','39156-5','39156-5','31',31,'kg/m2','kg/m2'),"
        "('r','old','not-matched','2024-01-01','2024-01-01','date_only',"
        "'LOINC','LOINC','111','111','50',50,NULL,NULL),"
        "('other','index','other-bmi','2024-01-01','2024-01-01','date_only',"
        "'LOINC','LOINC','39156-5','39156-5','40',40,'kg/m2','kg/m2')"
    )
    connection.execute(
        "CREATE TABLE element_membership("
        "source_record_id VARCHAR,element_id VARCHAR,include BOOLEAN)"
    )
    connection.execute(
        "INSERT INTO element_membership VALUES "
        "('bmi-1',?,TRUE),('bmi-1',?,TRUE),('bmi-2',?,TRUE),"
        "('not-matched',?,FALSE),('other-bmi',?,TRUE)",
        [ELEMENT] * 5,
    )
    return connection


def test_vital_projection_preserves_history_index_day_and_absence():
    with _source() as connection:
        rows = list(
            iter_calendar_vital_candidates(
                connection, index_relation="selected", element_id=ELEMENT, fetch_size=1
            )
        )
    assert [(row.patient_id, row.index_encounter_id) for row in rows] == [
        ("p", "index"),
        ("p", "index"),
        ("q", "index"),
        ("r", "index"),
    ]
    source_ids = [
        row.candidate.source_record_id if row.candidate else None for row in rows
    ]
    assert source_ids == [
        "bmi-1",
        "bmi-2",
        None,
        None,
    ]
    assert rows[0].candidate.source_encounter_id == "history"
    assert rows[0].candidate.raw_date == "2024-01-01"
    assert rows[0].candidate.numeric_value == 32
    assert rows[0].candidate.units_of_measure_raw == "kg/m2"
    assert rows[1].candidate.raw_date == "2024-02-01"


def test_vital_projection_rejects_duplicate_source_key():
    with _source() as connection:
        connection.execute(
            "INSERT INTO source_vital_measurement "
            "SELECT * FROM source_vital_measurement WHERE source_record_id='bmi-1'"
        )
        with pytest.raises(ValueError, match="unique and nonblank"):
            list(
                iter_calendar_vital_candidates(
                    connection, index_relation="selected", element_id=ELEMENT
                )
            )


def test_vital_projection_rejects_missing_catalog_and_duplicate_index():
    with _source() as connection:
        with pytest.raises(ValueError, match="absent or ambiguous"):
            list(
                iter_calendar_vital_candidates(
                    connection, index_relation="selected", element_id="other"
                )
            )
        connection.execute("INSERT INTO selected VALUES ('p','another')")
        with pytest.raises(
            ValueError, match="one nonblank exact encounter per patient"
        ):
            list(
                iter_calendar_vital_candidates(
                    connection, index_relation="selected", element_id=ELEMENT
                )
            )

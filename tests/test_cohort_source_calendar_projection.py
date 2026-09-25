"""Synthetic exact-key and precision cases for the calendar source projection."""

from datetime import date

import duckdb
import pytest

from trinetx_preprocessing.combined_preprocessing import (
    cohort_source_calendar_projection as projection,
)


def _source() -> duckdb.DuckDBPyConnection:
    connection = duckdb.connect()
    connection.execute("CREATE TABLE element_catalog(element_id VARCHAR)")
    connection.execute(
        "INSERT INTO element_catalog VALUES "
        "('source.arterial_pco2'),('source.arterial_ph')"
    )
    connection.execute(
        "CREATE TABLE source_encounter("
        "patient_id VARCHAR,encounter_id VARCHAR,start_date VARCHAR,"
        "start_timestamp_precision VARCHAR)"
    )
    connection.execute(
        "INSERT INTO source_encounter VALUES "
        "('p','e','2024-01-01','date_only'),"
        "('p','e','2024-01-01','date_only'),"
        "('other','e','2024-02-01','date_only')"
    )
    connection.execute(
        "CREATE TABLE source_lab_measurement("
        "patient_id VARCHAR,encounter_id VARCHAR,source_record_id VARCHAR,"
        "date VARCHAR,timestamp_precision VARCHAR,numeric_value DOUBLE,"
        "units_of_measure VARCHAR,units_of_measure_raw VARCHAR,"
        "specimen VARCHAR,specimen_id VARCHAR,panel_id VARCHAR,"
        "code_system VARCHAR,code VARCHAR)"
    )
    connection.execute(
        "INSERT INTO source_lab_measurement VALUES "
        "('p','e','gas','2024-01-02','date_only',50,'mmhg','mmHg',"
        "'arterial','sample-1','panel-1','LOINC','2019-8'),"
        "('p','e','ph','2024-01-02','date_only',7.3,NULL,NULL,"
        "'arterial','sample-1','panel-1','LOINC','2744-1'),"
        "('p','e','uncataloged','2024-01-01','date_only',99,NULL,NULL,NULL,NULL,NULL,NULL,NULL),"
        "('other','e','other-gas','2024-01-01','date_only',90,NULL,NULL,NULL,NULL,NULL,NULL,NULL)"
    )
    connection.execute(
        "CREATE TABLE element_membership("
        "source_record_id VARCHAR,element_id VARCHAR,include BOOLEAN)"
    )
    connection.execute(
        "INSERT INTO element_membership VALUES "
        "('gas','source.arterial_pco2',TRUE),"
        "('gas','source.arterial_pco2',TRUE),"
        "('ph','source.arterial_ph',TRUE),"
        "('uncataloged','source.arterial_pco2',FALSE),"
        "('other-gas','source.arterial_pco2',TRUE)"
    )
    return connection


def test_exact_key_projection_preserves_raw_fields_without_duplicates():
    with _source() as connection:
        result = projection.project_calendar_encounter_evidence(
            connection, patient_id="p", encounter_id="e"
        )
    assert result.encounter_start_date == date(2024, 1, 1)
    assert result.encounter_source_rows == 2
    assert [row.source_record_id for row in result.gas_candidates] == ["gas", "ph"]
    gas = result.gas_candidates[0]
    assert (gas.element_id, gas.event_date, gas.numeric_value) == (
        "source.arterial_pco2",
        date(2024, 1, 2),
        50,
    )
    assert (gas.units_of_measure, gas.units_of_measure_raw) == ("mmhg", "mmHg")
    assert (gas.specimen_id, gas.panel_id) == ("sample-1", "panel-1")
    assert (gas.code_system, gas.code) == ("LOINC", "2019-8")


@pytest.mark.parametrize(
    ("sql", "message"),
    [
        (
            "INSERT INTO source_encounter VALUES ('p','e','2024-01-02','date_only')",
            "conflicting source start",
        ),
        (
            "INSERT INTO source_encounter VALUES ('p','e',NULL,'date_only')",
            "observed date-only",
        ),
        (
            "UPDATE source_lab_measurement SET date=NULL WHERE source_record_id='gas'",
            "observed date-only",
        ),
        (
            "UPDATE source_lab_measurement SET timestamp_precision='timestamp' "
            "WHERE source_record_id='gas'",
            "observed date-only",
        ),
        (
            "INSERT INTO element_membership VALUES ('gas','source.arterial_ph',TRUE)",
            "both arterial gas elements",
        ),
    ],
)
def test_projection_fails_on_ambiguous_or_unobserved_calendar_evidence(sql, message):
    with _source() as connection:
        connection.execute(sql)
        with pytest.raises(ValueError, match=message):
            projection.project_calendar_encounter_evidence(
                connection, patient_id="p", encounter_id="e"
            )


def test_projection_requires_original_exact_key():
    with _source() as connection:
        with pytest.raises(ValueError, match="absent"):
            projection.project_calendar_encounter_evidence(
                connection, patient_id="p", encounter_id="missing"
            )


def test_projection_rejects_missing_arterial_catalog_element():
    with _source() as connection:
        connection.execute(
            "DELETE FROM element_catalog WHERE element_id='source.arterial_ph'"
        )
        with pytest.raises(ValueError, match="required arterial gas catalog"):
            projection.project_calendar_encounter_evidence(
                connection, patient_id="p", encounter_id="e"
            )


def test_projection_accepts_observed_compact_dates_without_time_order():
    with _source() as connection:
        connection.execute(
            "UPDATE source_encounter SET start_date='20240101' WHERE patient_id='p'"
        )
        connection.execute(
            "UPDATE source_lab_measurement SET date='20240102' "
            "WHERE source_record_id IN ('gas','ph')"
        )
        result = projection.project_calendar_encounter_evidence(
            connection, patient_id="p", encounter_id="e"
        )
    assert result.encounter_start_date == date(2024, 1, 1)
    assert {row.event_date for row in result.gas_candidates} == {date(2024, 1, 2)}


def test_projection_rejects_invalid_compact_calendar_day():
    with _source() as connection:
        connection.execute(
            "UPDATE source_lab_measurement SET date='20240230' "
            "WHERE source_record_id='gas'"
        )
        with pytest.raises(ValueError, match="invalid observed calendar date"):
            projection.project_calendar_encounter_evidence(
                connection, patient_id="p", encounter_id="e"
            )

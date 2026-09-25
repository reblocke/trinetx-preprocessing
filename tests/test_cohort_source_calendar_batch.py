"""Bulk calendar projection preserves the exact-key single-encounter result."""

import duckdb
import pytest

from trinetx_preprocessing.combined_preprocessing import (
    cohort_source_calendar_projection,
)
from trinetx_preprocessing.combined_preprocessing.cohort_source_calendar_batch import (
    iter_calendar_population_evidence,
)

project_calendar_encounter_evidence = (
    cohort_source_calendar_projection.project_calendar_encounter_evidence
)


def _source(database: str = ":memory:") -> duckdb.DuckDBPyConnection:
    connection = duckdb.connect(database)
    connection.execute("CREATE TABLE element_catalog(element_id VARCHAR)")
    connection.execute(
        "INSERT INTO element_catalog VALUES "
        "('source.arterial_pco2'),('source.arterial_ph')"
    )
    connection.execute(
        "CREATE TABLE selected_index(patient_id VARCHAR,encounter_id VARCHAR)"
    )
    connection.execute("INSERT INTO selected_index VALUES ('p','e'),('q','f')")
    connection.execute(
        "CREATE TABLE source_encounter(patient_id VARCHAR,encounter_id VARCHAR,"
        "start_date VARCHAR,start_timestamp_precision VARCHAR)"
    )
    connection.execute(
        "INSERT INTO source_encounter VALUES "
        "('p','e','2024-01-01','date_only'),"
        "('p','e','2024-01-01','date_only'),"
        "('q','f','2024-02-01','date_only'),"
        "('other','e','2024-03-01','date_only')"
    )
    connection.execute(
        "CREATE TABLE source_lab_measurement("
        "patient_id VARCHAR,encounter_id VARCHAR,source_record_id VARCHAR,"
        "date VARCHAR,timestamp_precision VARCHAR,numeric_value DOUBLE,"
        "units_of_measure VARCHAR,units_of_measure_raw VARCHAR,"
        "specimen VARCHAR,specimen_id VARCHAR,panel_id VARCHAR)"
    )
    connection.execute(
        "INSERT INTO source_lab_measurement VALUES "
        "('p','e','gas','2024-01-02','date_only',50,'mmhg','mmHg',"
        "'arterial','sample','panel'),"
        "('p','e','ph','2024-01-02','date_only',7.3,NULL,NULL,"
        "'arterial','sample','panel'),"
        "('p','e','unmatched','2024-01-01','date_only',99,NULL,NULL,"
        "NULL,NULL,NULL),"
        "('other','e','other-gas','2024-03-01','date_only',90,NULL,NULL,"
        "NULL,NULL,NULL)"
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
        "('unmatched','source.arterial_pco2',FALSE),"
        "('other-gas','source.arterial_pco2',TRUE)"
    )
    return connection


def _temp_count(connection: duckdb.DuckDBPyConnection) -> int:
    return connection.execute(
        "SELECT count(*) FROM duckdb_tables() WHERE table_name LIKE 'calendar_%'"
    ).fetchone()[0]


def test_bulk_projection_matches_exact_key_and_keeps_empty_gas_encounter():
    with _source() as connection:
        single = project_calendar_encounter_evidence(
            connection, patient_id="p", encounter_id="e"
        )
        observed = list(
            iter_calendar_population_evidence(
                connection, index_relation="selected_index", fetch_size=1
            )
        )
        assert _temp_count(connection) == 0
    assert observed[0] == single
    assert (observed[1].patient_id, observed[1].encounter_id) == ("q", "f")
    assert observed[1].gas_candidates == ()


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (
            "INSERT INTO selected_index VALUES ('p','other')",
            "one nonblank exact encounter",
        ),
        (
            "UPDATE selected_index SET patient_id='' WHERE patient_id='p'",
            "one nonblank exact encounter",
        ),
        (
            "DELETE FROM source_encounter WHERE patient_id='q'",
            "absent, invalid or conflicting",
        ),
        (
            "INSERT INTO source_encounter VALUES ('p','e','2024-01-02','date_only')",
            "absent, invalid or conflicting",
        ),
        (
            "UPDATE source_lab_measurement SET date=NULL WHERE source_record_id='gas'",
            "observed date-only",
        ),
        (
            "INSERT INTO element_membership VALUES ('gas','source.arterial_ph',TRUE)",
            "ambiguous arterial elements",
        ),
    ],
)
def test_bulk_projection_fails_closed_and_cleans_temporary_tables(change, message):
    with _source() as connection:
        connection.execute(change)
        with pytest.raises(ValueError, match=message):
            list(
                iter_calendar_population_evidence(
                    connection, index_relation="selected_index", fetch_size=1
                )
            )
        assert _temp_count(connection) == 0


def test_closing_partial_iterator_removes_temporary_tables():
    with _source() as connection:
        stream = iter_calendar_population_evidence(
            connection, index_relation="selected_index", fetch_size=1
        )
        assert next(stream).patient_id == "p"
        assert _temp_count(connection) > 0
        stream.close()
        assert _temp_count(connection) == 0


def test_batch_projection_uses_only_temp_tables_on_read_only_source(tmp_path):
    database = tmp_path / "source.duckdb"
    with _source(str(database)):
        pass
    with duckdb.connect(str(database), read_only=True) as connection:
        observed = list(
            iter_calendar_population_evidence(
                connection, index_relation="selected_index", fetch_size=1
            )
        )
        assert [row.patient_id for row in observed] == ["p", "q"]
        assert _temp_count(connection) == 0


def test_batch_projection_normalizes_mixed_observed_date_forms():
    with _source() as connection:
        connection.execute(
            "UPDATE source_encounter SET start_date='20240101' "
            "WHERE patient_id='p' AND rowid=0"
        )
        connection.execute(
            "UPDATE source_lab_measurement SET date='20240102' "
            "WHERE source_record_id='gas'"
        )
        single = project_calendar_encounter_evidence(
            connection, patient_id="p", encounter_id="e"
        )
        observed = list(
            iter_calendar_population_evidence(
                connection, index_relation="selected_index", fetch_size=1
            )
        )
    assert observed[0] == single


def test_bulk_projection_rejects_unsafe_relation_and_numeric_keys():
    with _source() as connection:
        with pytest.raises(ValueError, match="simple SQL identifier"):
            list(
                iter_calendar_population_evidence(
                    connection, index_relation="x;DROP TABLE y"
                )
            )
        connection.execute(
            "CREATE TABLE numeric_keys(patient_id INTEGER,encounter_id VARCHAR)"
        )
        with pytest.raises(ValueError, match="VARCHAR"):
            list(
                iter_calendar_population_evidence(
                    connection, index_relation="numeric_keys"
                )
            )


def test_empty_index_avoids_source_scan_and_catalog_is_required():
    with _source() as connection:
        connection.execute("DELETE FROM selected_index")
        assert (
            list(
                iter_calendar_population_evidence(
                    connection, index_relation="selected_index"
                )
            )
            == []
        )
        assert _temp_count(connection) == 0
        connection.execute("INSERT INTO selected_index VALUES ('p','e')")
        connection.execute(
            "DELETE FROM element_catalog WHERE element_id='source.arterial_ph'"
        )
        with pytest.raises(ValueError, match="required arterial gas catalog"):
            list(
                iter_calendar_population_evidence(
                    connection, index_relation="selected_index"
                )
            )
        assert _temp_count(connection) == 0

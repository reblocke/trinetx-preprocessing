"""Calendar candidate fields preserve exact keys and source uncertainty."""

from datetime import date

import duckdb
import pytest

from trinetx_preprocessing.combined_preprocessing import (
    cohort_source_calendar_population as calendar_module,
)

build_calendar_candidate_fields = calendar_module.build_calendar_candidate_fields
stage_calendar_type_hint_keys = calendar_module.stage_calendar_type_hint_keys
build_calendar_type_hint_candidate_fields = (
    calendar_module.build_calendar_type_hint_candidate_fields
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
        "('p1','e1','20240101','date_only','EMER'),"
        "('p1','e1','2024-01-01','date_only','emer'),"
        "('p1','e2','2024-01-02','date_only','IMP'),"
        "('p1','e2','2024-01-03','date_only','IMP'),"
        "('p2','e3','2024-02-01','date_only',NULL),"
        "('p3','e4','2024-03-01','date_only','EMER'),"
        "('p3','e4','2024-03-01','date_only','IMP'),"
        "('', 'invalid','2024-04-01','date_only','EMER')"
    )
    connection.execute(
        "INSERT INTO source_patient VALUES ('p1','1980'),('p1','1980'),('p2',NULL)"
    )


def _intermediate_count(connection):
    return connection.execute(
        "SELECT count(*) FROM duckdb_tables() WHERE "
        "table_name LIKE '_calendar_raw_encounters_%' "
        "OR table_name LIKE '_calendar_raw_patients_%'"
    ).fetchone()[0]


def test_candidate_field_projection_keeps_duplicates_and_ambiguity_without_selection():
    with duckdb.connect() as connection:
        _source(connection)
        audit = build_calendar_candidate_fields(connection)
        rows = connection.execute(
            "SELECT patient_id,encounter_id,encounter_source_rows,"
            "encounter_start_date,encounter_start_precision,encounter_type,"
            "patient_source_rows,year_of_birth "
            "FROM calendar_candidate_fields ORDER BY patient_id,encounter_id"
        ).fetchall()
        conflicts = connection.execute(
            "SELECT patient_id,encounter_id,conflicting_start_dates,"
            "conflicting_types,conflicting_birth_years "
            "FROM calendar_candidate_fields ORDER BY patient_id,encounter_id"
        ).fetchall()
        assert _intermediate_count(connection) == 0
    assert audit.source_encounter_rows == 8
    assert audit.invalid_encounter_key_rows == 1
    assert audit.exact_encounter_keys == 4
    assert audit.duplicate_source_encounter_keys == 3
    assert (
        audit.unresolved_start_keys,
        audit.unresolved_type_keys,
        audit.unresolved_birth_year_keys,
    ) == (1, 2, 2)
    assert (
        audit.conflicting_start_keys,
        audit.conflicting_type_keys,
        audit.conflicting_birth_year_keys,
    ) == (1, 1, 0)
    assert rows == [
        ("p1", "e1", 2, date(2024, 1, 1), "date_only", "EMER", 2, 1980),
        ("p1", "e2", 2, None, None, "IMP", 2, 1980),
        ("p2", "e3", 1, date(2024, 2, 1), "date_only", None, 1, None),
        ("p3", "e4", 2, date(2024, 3, 1), "date_only", None, 0, None),
    ]
    assert conflicts == [
        ("p1", "e1", False, False, False),
        ("p1", "e2", True, False, False),
        ("p2", "e3", False, False, False),
        ("p3", "e4", False, True, False),
    ]


def test_conflicting_birth_year_keeps_all_patient_encounters_unknown():
    with duckdb.connect() as connection:
        _source(connection)
        connection.execute("INSERT INTO source_patient VALUES ('p1','1981')")
        audit = build_calendar_candidate_fields(connection)
        assert audit.conflicting_birth_year_keys == 2
        assert connection.execute(
            "SELECT encounter_id,year_of_birth,conflicting_birth_years "
            "FROM calendar_candidate_fields WHERE patient_id='p1' ORDER BY encounter_id"
        ).fetchall() == [("e1", None, True), ("e2", None, True)]


@pytest.mark.parametrize(
    "change",
    [
        "UPDATE source_encounter SET start_date=NULL WHERE encounter_id='e3'",
        "UPDATE source_encounter SET start_timestamp_precision='timestamp' "
        "WHERE encounter_id='e3'",
        "UPDATE source_encounter SET start_date='2024-02-01 12:00' "
        "WHERE encounter_id='e3'",
    ],
)
def test_unobserved_or_implied_start_never_becomes_a_calendar_date(change):
    with duckdb.connect() as connection:
        _source(connection)
        connection.execute(change)
        audit = build_calendar_candidate_fields(connection)
        assert audit.unresolved_start_keys == 2
        assert connection.execute(
            "SELECT encounter_start_date,encounter_start_precision,"
            "invalid_start_rows FROM calendar_candidate_fields "
            "WHERE patient_id='p2'"
        ).fetchone() == (None, None, 1)


def test_candidate_fields_on_read_only_source_and_empty_population(tmp_path):
    path = tmp_path / "source.duckdb"
    with duckdb.connect(str(path)) as connection:
        _source(connection)
    with duckdb.connect(str(path), read_only=True) as connection:
        assert build_calendar_candidate_fields(connection).exact_encounter_keys == 4
        assert _intermediate_count(connection) == 0
    with duckdb.connect() as connection:
        connection.execute(
            "CREATE TABLE source_encounter(patient_id VARCHAR,encounter_id VARCHAR,"
            "start_date VARCHAR,start_timestamp_precision VARCHAR,type VARCHAR)"
        )
        connection.execute(
            "CREATE TABLE source_patient(patient_id VARCHAR,year_of_birth VARCHAR)"
        )
        audit = build_calendar_candidate_fields(connection)
        assert audit.source_encounter_rows == audit.exact_encounter_keys == 0
        assert connection.execute(
            "SELECT count(*) FROM calendar_candidate_fields"
        ).fetchone() == (0,)


def test_candidate_fields_preserve_prior_output_on_source_failure():
    with duckdb.connect() as connection:
        _source(connection)
        build_calendar_candidate_fields(connection)
        connection.execute("DROP TABLE source_patient")
        with pytest.raises(duckdb.CatalogException):
            build_calendar_candidate_fields(connection)
        assert connection.execute(
            "SELECT count(*) FROM calendar_candidate_fields"
        ).fetchone() == (4,)
        assert _intermediate_count(connection) == 0


def test_candidate_fields_reject_unsafe_output_name():
    with duckdb.connect() as connection:
        _source(connection)
        with pytest.raises(ValueError, match="simple SQL identifier"):
            build_calendar_candidate_fields(
                connection, output_relation="x;DROP TABLE y"
            )
        with pytest.raises(ValueError, match="must differ from source tables"):
            build_calendar_candidate_fields(
                connection, output_relation="source_encounter"
            )


def test_type_hint_keys_retain_every_raw_row_for_selected_keys():
    with duckdb.connect() as connection:
        _source(connection)
        connection.execute(
            "INSERT INTO source_encounter VALUES "
            "('p1','e1','2024-01-01','date_only','OUT')"
        )
        hint = stage_calendar_type_hint_keys(connection)
        assert (hint.exact_candidate_keys, hint.valid_type_hint_source_rows) == (3, 6)
        assert connection.execute(
            "SELECT patient_id,encounter_id,type_hint_source_rows "
            "FROM calendar_type_hint_keys ORDER BY patient_id,encounter_id"
        ).fetchall() == [("p1", "e1", 2), ("p1", "e2", 2), ("p3", "e4", 2)]
        connection.execute("ALTER TABLE source_encounter RENAME TO original_encounter")
        connection.execute(
            "CREATE TEMP VIEW source_encounter AS "
            "SELECT e.* FROM original_encounter AS e "
            "SEMI JOIN calendar_type_hint_keys AS k "
            "ON e.patient_id=k.patient_id AND e.encounter_id=k.encounter_id"
        )
        fields = build_calendar_candidate_fields(connection)
        assert (fields.source_encounter_rows, fields.exact_encounter_keys) == (7, 3)
        assert fields.conflicting_type_keys == 2
        assert connection.execute(
            "SELECT encounter_source_rows,encounter_type,conflicting_types "
            "FROM calendar_candidate_fields WHERE patient_id='p1' "
            "AND encounter_id='e1'"
        ).fetchone() == (3, None, True)


def test_type_hint_keys_on_read_only_source_and_empty_input(tmp_path):
    path = tmp_path / "source.duckdb"
    with duckdb.connect(str(path)) as connection:
        _source(connection)
    with duckdb.connect(str(path), read_only=True) as connection:
        assert stage_calendar_type_hint_keys(connection).exact_candidate_keys == 3
    with duckdb.connect() as connection:
        connection.execute(
            "CREATE TABLE source_encounter(patient_id VARCHAR,encounter_id VARCHAR,"
            "start_date VARCHAR,start_timestamp_precision VARCHAR,type VARCHAR)"
        )
        assert stage_calendar_type_hint_keys(connection).exact_candidate_keys == 0
        assert connection.execute(
            "SELECT count(*) FROM calendar_type_hint_keys"
        ).fetchone() == (0,)


def test_type_hint_keys_preserve_prior_output_on_failure():
    with duckdb.connect() as connection:
        _source(connection)
        stage_calendar_type_hint_keys(connection)
        connection.execute("DROP TABLE source_encounter")
        with pytest.raises(duckdb.CatalogException):
            stage_calendar_type_hint_keys(connection)
        assert connection.execute(
            "SELECT count(*) FROM calendar_type_hint_keys"
        ).fetchone() == (3,)
        with pytest.raises(ValueError, match="simple SQL identifier"):
            stage_calendar_type_hint_keys(connection, output_relation="x;DROP TABLE y")


def test_type_hint_projection_retains_all_source_rows_and_cleans_scoped_stages():
    with duckdb.connect() as connection:
        _source(connection)
        connection.execute(
            "INSERT INTO source_encounter VALUES "
            "('p1','e1','2024-01-01','date_only','OUT')"
        )
        audit = build_calendar_type_hint_candidate_fields(connection)
        assert (
            audit.hinted.exact_candidate_keys,
            audit.hinted.valid_type_hint_source_rows,
        ) == (
            3,
            6,
        )
        assert (
            audit.projected.exact_encounter_keys,
            audit.projected.source_encounter_rows,
            audit.projected.conflicting_type_keys,
        ) == (3, 7, 2)
        assert connection.execute(
            "SELECT encounter_source_rows,encounter_type,conflicting_types "
            "FROM calendar_type_hint_candidate_fields WHERE patient_id='p1' "
            "AND encounter_id='e1'"
        ).fetchone() == (3, None, True)
        assert connection.execute(
            "SELECT count(*) FROM duckdb_tables() "
            "WHERE table_name LIKE '_calendar_hint_%'"
        ).fetchone() == (0,)
        assert connection.execute(
            "SELECT count(*) FROM duckdb_views() "
            "WHERE view_name LIKE '_calendar_hint_%'"
        ).fetchone() == (0,)


def test_type_hint_projection_read_only_empty_and_prior_output_preservation(tmp_path):
    path = tmp_path / "source.duckdb"
    with duckdb.connect(str(path)) as connection:
        _source(connection)
    with duckdb.connect(str(path), read_only=True) as connection:
        assert (
            build_calendar_type_hint_candidate_fields(
                connection
            ).projected.exact_encounter_keys
            == 3
        )
    with duckdb.connect() as connection:
        connection.execute(
            "CREATE TABLE source_encounter(patient_id VARCHAR,encounter_id VARCHAR,"
            "start_date VARCHAR,start_timestamp_precision VARCHAR,type VARCHAR)"
        )
        connection.execute(
            "CREATE TABLE source_patient(patient_id VARCHAR,year_of_birth VARCHAR)"
        )
        assert (
            build_calendar_type_hint_candidate_fields(
                connection
            ).projected.exact_encounter_keys
            == 0
        )
        connection.execute("DROP TABLE source_patient")
        with pytest.raises(duckdb.CatalogException):
            build_calendar_type_hint_candidate_fields(connection)
        assert connection.execute(
            "SELECT count(*) FROM calendar_type_hint_candidate_fields"
        ).fetchone() == (0,)
        assert connection.execute(
            "SELECT count(*) FROM duckdb_tables() "
            "WHERE table_name LIKE '_calendar_hint_%'"
        ).fetchone() == (0,)


def test_scoped_candidate_expected_count_failure_preserves_prior_output():
    with duckdb.connect() as connection:
        _source(connection)
        build_calendar_candidate_fields(connection)
        connection.execute(
            "CREATE TEMP VIEW one_key_source AS SELECT * FROM source_encounter "
            "WHERE patient_id='p1' AND encounter_id='e1'"
        )
        with pytest.raises(ValueError, match="scoped keys or source rows differ"):
            build_calendar_candidate_fields(
                connection,
                source_encounter_relation="one_key_source",
                expected_exact_keys=2,
            )
        assert connection.execute(
            "SELECT count(*) FROM calendar_candidate_fields"
        ).fetchone() == (4,)
        with pytest.raises(ValueError, match="nonnegative integers"):
            build_calendar_candidate_fields(connection, expected_exact_keys=True)

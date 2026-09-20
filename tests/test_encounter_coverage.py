import duckdb
import pytest

from trinetx_preprocessing.encounters.coverage import coverage_tables


@pytest.mark.parametrize("wrong_demographics", [False, True])
def test_coverage_corroborates_keys_and_preserves_unavailable(wrong_demographics):
    with duckdb.connect() as db:
        db.execute("""
            ATTACH ':memory:' AS preprocessed;
            CREATE TABLE legacy_base AS
            SELECT 'p-e' pat_enc_hash,'p' patient_id,'e' encounter_id,
                0 sex,0 race,0 ethnicity,0 AS "location",23376 encounter_date
            UNION ALL SELECT 'absent-z','absent','z',0,0,0,0,23376;
            CREATE TABLE preprocessed.source_patient AS
            SELECT 'p' patient_id,'F' sex,'White' race,
                'Not Hispanic or Latino' ethnicity,'South' patient_regional_location;
            CREATE TABLE preprocessed.source_encounter AS
            SELECT 'p' patient_id,'e' encounter_id,
                TIMESTAMP '2024-01-01' start_datetime,
                TIMESTAMP '2024-01-05' end_datetime;
            CREATE TABLE preprocessed.canonical_source_file_audit AS
                SELECT 'labs' logical_domain;
            CREATE TABLE preprocessed.patient_observability AS
                SELECT 'p' patient_id,'labs' logical_domain,2 event_count,
                TIMESTAMP '2022-01-01' first_event_datetime,
                TIMESTAMP '2024-01-05' last_event_datetime;
        """)
        if wrong_demographics:
            db.execute("UPDATE preprocessed.source_patient SET sex='M'")
        report = coverage_tables(db)
        assert report["pass"] != wrong_demographics
        assert report["rows"] == 2
        assert report["encounter_linked"] == 1
        assert (
            db.execute("""
            SELECT history_state FROM encounter_source_coverage
            WHERE index_event_id='absent-z' AND domain='labs'
        """).fetchone()[0]
            == "incomplete_capture"
        )
        assert (
            db.execute("""
            SELECT history_state FROM encounter_source_coverage
            WHERE index_event_id='p-e' AND domain='diagnosis'
        """).fetchone()[0]
            == "unavailable_domain"
        )
        assert (
            db.execute("""
            SELECT history_state FROM encounter_source_coverage
            WHERE index_event_id='p-e' AND domain='labs'
        """).fetchone()[0]
            == "observed_span"
        )

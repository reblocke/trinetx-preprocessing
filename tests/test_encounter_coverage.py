import duckdb
import pytest

from trinetx_preprocessing.encounters.coverage import coverage_tables


@pytest.mark.parametrize("wrong_demographics", [False, True])
@pytest.mark.parametrize("medication_export", ["medication", "medication_ingredient"])
def test_coverage_corroborates_keys_and_preserves_unavailable(
    wrong_demographics, medication_export
):
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
        db.execute(
            "INSERT INTO preprocessed.canonical_source_file_audit VALUES (?)",
            [medication_export],
        )
        db.execute("""
            INSERT INTO preprocessed.patient_observability
            SELECT 'p','medications',2,TIMESTAMP '2020-01-01',
                   TIMESTAMP '2024-01-05'
        """)
        if wrong_demographics:
            db.execute("UPDATE preprocessed.source_patient SET sex='M'")
        report = coverage_tables(
            db,
            policy="approved_incomplete_linkage",
            approved_exception="synthetic test approval",
        )
        assert report["pass"] != wrong_demographics
        assert report["rows"] == 2
        assert report["patient_total"] == 2
        assert report["encounter_total"] == 2
        assert report["contradictions_pass"] != wrong_demographics
        assert report["patient_unlinked"] == 1
        assert report["encounter_unlinked"] == 1
        assert not report["complete_patient_linkage"]
        assert not report["complete_encounter_linkage"]
        assert report["encounter_linked"] == 1
        assert report["audited_source_domains"]["medications"] == [medication_export]
        assert (
            db.execute("""
            SELECT history_state FROM encounter_source_coverage
            WHERE index_event_id='p-e' AND domain='medications'
        """).fetchone()[0]
            == "observed_span"
        )
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
        db.execute("DROP TABLE encounter_source_coverage")
        db.execute("DROP TABLE key_coverage")
        db.execute("DROP TABLE source_demographics")
        strict = coverage_tables(db)
        assert strict["pass"] is False
        assert strict["contradictions_pass"] != wrong_demographics
        if not wrong_demographics:
            db.execute("DELETE FROM legacy_base WHERE patient_id='absent'")
            db.execute("DROP TABLE encounter_source_coverage")
            db.execute("DROP TABLE key_coverage")
            db.execute("DROP TABLE source_demographics")
            complete = coverage_tables(db)
            assert complete["pass"] is True
            assert complete["complete_patient_linkage"] is True
            assert complete["complete_encounter_linkage"] is True


def test_unrecognized_audit_domain_cannot_hide_observed_records():
    # Contradictory source metadata must fail even with an empty legacy base.
    with duckdb.connect() as db:
        db.execute("""
            ATTACH ':memory:' AS preprocessed;
            CREATE TABLE legacy_base (pat_enc_hash VARCHAR,patient_id VARCHAR,
                encounter_id VARCHAR,sex INT,race INT,ethnicity INT,
                location INT,encounter_date INT);
            CREATE TABLE preprocessed.source_patient (patient_id VARCHAR,
                sex VARCHAR,race VARCHAR,ethnicity VARCHAR,
                patient_regional_location VARCHAR);
            CREATE TABLE preprocessed.source_encounter (patient_id VARCHAR,
                encounter_id VARCHAR,start_datetime TIMESTAMP,end_datetime TIMESTAMP);
            CREATE TABLE preprocessed.canonical_source_file_audit AS
                SELECT 'unrecognized_export' logical_domain;
            CREATE TABLE preprocessed.patient_observability AS
                SELECT 'synthetic' patient_id,'medications' logical_domain,
                1 event_count,TIMESTAMP '2020-01-01' first_event_datetime,
                TIMESTAMP '2020-01-01' last_event_datetime;
        """)
        with pytest.raises(ValueError, match="recognized audited domain"):
            coverage_tables(db)


def test_linked_patient_with_unlinked_encounter_needs_explicit_policy():
    with duckdb.connect() as db:
        db.execute("""
            ATTACH ':memory:' AS preprocessed;
            CREATE TABLE legacy_base AS
            SELECT 'p-e1' pat_enc_hash,'p' patient_id,'e1' encounter_id,
                0 sex,0 race,0 ethnicity,0 AS "location",23376 encounter_date
            UNION ALL SELECT 'p-e2','p','e2',0,0,0,0,23376;
            CREATE TABLE preprocessed.source_patient AS
            SELECT 'p' patient_id,'F' sex,'White' race,
                'Not Hispanic or Latino' ethnicity,'South' patient_regional_location;
            CREATE TABLE preprocessed.source_encounter AS
            SELECT 'p' patient_id,'e1' encounter_id,
                TIMESTAMP '2024-01-01' start_datetime,
                TIMESTAMP '2024-01-05' end_datetime;
            CREATE TABLE preprocessed.canonical_source_file_audit AS
                SELECT 'labs' logical_domain;
            CREATE TABLE preprocessed.patient_observability AS
                SELECT 'p' patient_id,'labs' logical_domain,2 event_count,
                TIMESTAMP '2022-01-01' first_event_datetime,
                TIMESTAMP '2024-01-05' last_event_datetime;
        """)
        report = coverage_tables(
            db,
            policy="approved_incomplete_linkage",
            approved_exception="synthetic approval",
        )
        assert report["pass"] is True
        assert report["patient_total"] == 1
        assert report["patient_linked"] == 1
        assert report["patient_linked_proportion"] == 1
        assert report["complete_patient_linkage"] is True
        assert report["encounter_total"] == 2
        assert report["encounter_linked"] == 1
        assert report["encounter_unlinked"] == 1
        assert not report["complete_encounter_linkage"]
        assert (
            db.execute(
                "SELECT DISTINCT history_state FROM encounter_source_coverage "
                "WHERE index_event_id='p-e2' AND domain='labs'"
            ).fetchone()[0]
            == "incomplete_capture"
        )
        for table in (
            "encounter_source_coverage",
            "key_coverage",
            "source_demographics",
        ):
            db.execute(f"DROP TABLE {table}")
        strict = coverage_tables(db)
        assert strict["pass"] is False
        assert strict["contradictions_pass"] is True


def test_zero_linkage_is_never_corroborated():
    with duckdb.connect() as db:
        db.execute("""
            ATTACH ':memory:' AS preprocessed;
            CREATE TABLE legacy_base AS
            SELECT 'p-e' pat_enc_hash,'p' patient_id,'e' encounter_id,
                0 sex,0 race,0 ethnicity,0 AS "location",23376 encounter_date;
            CREATE TABLE preprocessed.source_patient (
                patient_id VARCHAR, sex VARCHAR, race VARCHAR, ethnicity VARCHAR,
                patient_regional_location VARCHAR);
            CREATE TABLE preprocessed.source_encounter (
                patient_id VARCHAR, encounter_id VARCHAR,
                start_datetime TIMESTAMP, end_datetime TIMESTAMP);
            CREATE TABLE preprocessed.canonical_source_file_audit AS
                SELECT 'labs' logical_domain;
            CREATE TABLE preprocessed.patient_observability (
                patient_id VARCHAR,logical_domain VARCHAR,event_count BIGINT,
                first_event_datetime TIMESTAMP,last_event_datetime TIMESTAMP);
        """)
        report = coverage_tables(
            db,
            policy="approved_incomplete_linkage",
            approved_exception="synthetic approval",
        )
        assert report["pass"] is False
        assert report["contradictions_pass"] is False
        assert report["patient_linked"] == 0
        assert report["encounter_linked"] == 0
        assert report["patient_linked_proportion"] == 0

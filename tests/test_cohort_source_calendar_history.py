"""Raw diagnosis/lab history keeps source timing and absence distinct."""

import duckdb
import pytest

from trinetx_preprocessing.combined_preprocessing import (
    cohort_source_calendar_history as history,
)


def _source() -> duckdb.DuckDBPyConnection:
    db = duckdb.connect()
    db.execute("CREATE TABLE selected(patient_id VARCHAR,encounter_id VARCHAR)")
    db.execute("INSERT INTO selected VALUES ('p','index'),('q','index')")
    db.execute("CREATE TABLE element_catalog(element_id VARCHAR,domain VARCHAR)")
    db.execute(
        "INSERT INTO element_catalog VALUES ('dx-t2d','diagnosis'),('lab-a1c','lab')"
    )
    db.execute(
        "CREATE TABLE element_membership("
        "source_record_id VARCHAR,element_id VARCHAR,include BOOLEAN)"
    )
    db.execute(
        "INSERT INTO element_membership VALUES "
        "('dx-1','dx-t2d',TRUE),('dx-1','dx-t2d',TRUE),"
        "('dx-2','dx-t2d',FALSE),('a1c-1','lab-a1c',TRUE),"
        "('a1c-2','lab-a1c',TRUE),('other-a1c','lab-a1c',TRUE)"
    )
    db.execute(
        "CREATE TABLE source_diagnosis("
        "patient_id VARCHAR,encounter_id VARCHAR,source_record_id VARCHAR,"
        "source_file VARCHAR,date VARCHAR,event_datetime TIMESTAMP,"
        "timestamp_precision VARCHAR,code_system_raw VARCHAR,"
        "code_system VARCHAR,code_raw VARCHAR,code VARCHAR)"
    )
    db.execute(
        "INSERT INTO source_diagnosis VALUES "
        "('p','history','dx-1','Diagnosis/diagnosis.csv','20240101',"
        "'2024-01-01','date_only','ICD-10-CM','ICD-10-CM','E11.9','E11.9'),"
        "('p','index','dx-2','Diagnosis/diagnosis.csv','20240201',"
        "'2024-02-01','date_only','ICD-10-CM','ICD-10-CM','E11.9','E11.9')"
    )
    db.execute(
        "CREATE TABLE source_lab_measurement("
        "patient_id VARCHAR,encounter_id VARCHAR,source_record_id VARCHAR,"
        "source_file VARCHAR,date VARCHAR,event_datetime TIMESTAMP,"
        "timestamp_precision VARCHAR,code_system_raw VARCHAR,"
        "code_system VARCHAR,code_raw VARCHAR,code VARCHAR,"
        "lab_result_num_val VARCHAR,lab_result_text_val VARCHAR,"
        "numeric_value DOUBLE,units_of_measure_raw VARCHAR,"
        "units_of_measure VARCHAR)"
    )
    db.execute(
        "INSERT INTO source_lab_measurement VALUES "
        "('p','history','a1c-1','Labs/lab_results.csv','20240101',"
        "'2024-01-01','date_only','LOINC','LOINC','4548-4','4548-4',"
        "'6.6',NULL,6.6,'%','%'),"
        "('p','index','a1c-2','Labs/lab_results.csv','20240201',"
        "'2024-02-01','date_only','LOINC','LOINC','4548-4','4548-4',"
        "'7.0',NULL,7.0,'%','%'),"
        "('other','history','other-a1c','Labs/lab_results.csv','20240101',"
        "'2024-01-01','date_only','LOINC','LOINC','4548-4','4548-4',"
        "'8.0',NULL,8.0,'%','%')"
    )
    return db


@pytest.mark.parametrize(
    ("element", "domain", "source_ids"),
    [
        ("dx-t2d", "diagnosis", ["dx-1", None]),
        ("lab-a1c", "lab", ["a1c-1", "a1c-2", None]),
    ],
)
def test_history_preserves_cross_encounter_rows_and_absence(
    element, domain, source_ids
):
    with _source() as db:
        rows = list(
            history.iter_calendar_history_candidates(
                db,
                index_relation="selected",
                element_id=element,
                domain=domain,
                fetch_size=1,
            )
        )
    assert [
        row.candidate.source_record_id if row.candidate else None for row in rows
    ] == source_ids
    assert rows[0].index_encounter_id == "index"
    assert rows[0].candidate.source_encounter_id == "history"
    assert rows[0].candidate.raw_date == "20240101"
    assert rows[0].candidate.timestamp_precision == "date_only"
    assert rows[-1].patient_id == "q"
    assert rows[-1].candidate is None
    if domain == "lab":
        assert rows[0].candidate.raw_numeric_value == "6.6"
        assert rows[0].candidate.numeric_value == 6.6
        assert rows[1].candidate.raw_date == "20240201"
    else:
        assert rows[0].candidate.source_file == "Diagnosis/diagnosis.csv"
        assert rows[0].candidate.numeric_value is None


def test_history_rejects_bad_domain_catalog_and_index_keys():
    with _source() as db:
        with pytest.raises(ValueError, match="domain must be"):
            list(
                history.iter_calendar_history_candidates(
                    db,
                    index_relation="selected",
                    element_id="dx-t2d",
                    domain="procedure",
                )
            )
        with pytest.raises(ValueError, match="absent or ambiguous"):
            list(
                history.iter_calendar_history_candidates(
                    db, index_relation="selected", element_id="dx-t2d", domain="lab"
                )
            )
        db.execute("INSERT INTO selected VALUES ('p','another')")
        with pytest.raises(ValueError, match="one nonblank exact encounter"):
            list(
                history.iter_calendar_history_candidates(
                    db,
                    index_relation="selected",
                    element_id="dx-t2d",
                    domain="diagnosis",
                )
            )


def test_history_rejects_duplicate_matched_source_record():
    with _source() as db:
        db.execute(
            "INSERT INTO source_lab_measurement SELECT * FROM source_lab_measurement "
            "WHERE source_record_id='a1c-1'"
        )
        with pytest.raises(ValueError, match="unique and nonblank"):
            list(
                history.iter_calendar_history_candidates(
                    db, index_relation="selected", element_id="lab-a1c", domain="lab"
                )
            )

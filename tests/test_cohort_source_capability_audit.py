"""Aggregate-only temporal and medication source capability checks."""

from dataclasses import asdict

import duckdb
import pytest

from trinetx_preprocessing.combined_preprocessing import cohort_source_capability_audit


def _source() -> duckdb.DuckDBPyConnection:
    connection = duckdb.connect()
    connection.execute("CREATE TABLE element_catalog(element_id VARCHAR)")
    connection.execute(
        "INSERT INTO element_catalog VALUES "
        "('source.arterial_pco2'),('source.arterial_ph')"
    )
    connection.execute(
        "CREATE TABLE source_encounter("
        "start_timestamp_precision VARCHAR,start_datetime TIMESTAMP)"
    )
    connection.execute(
        "INSERT INTO source_encounter VALUES "
        "('date_only','2024-01-01'),"
        "('timestamp','2024-01-02 10:15:00'),"
        "('timestamp',NULL),(NULL,NULL)"
    )
    connection.execute(
        "CREATE TABLE source_lab_measurement("
        "source_record_id VARCHAR,timestamp_precision VARCHAR,event_datetime TIMESTAMP,"
        "patient_id VARCHAR,encounter_id VARCHAR,date VARCHAR,numeric_value DOUBLE,"
        "units_of_measure VARCHAR,specimen_id VARCHAR,panel_id VARCHAR)"
    )
    connection.execute(
        "INSERT INTO source_lab_measurement VALUES "
        "('gas-1','date_only','2024-01-01','p','e','2024-01-01',50,"
        "'mmhg','sample-1','panel-1'),"
        "('ph-1','date_only','2024-01-01','p','e','2024-01-01',7.3,"
        "NULL,'sample-1','panel-1'),"
        "('other-1','timestamp','2024-01-02 10:17:00','p','e',"
        "'2024-01-02 10:17:00',7.4,NULL,NULL,NULL),"
        "('gas-2','timestamp','2024-01-02 10:18:00','p','e',"
        "'2024-01-02 10:18:00',NULL,NULL,NULL,NULL)"
    )
    connection.execute(
        "CREATE TABLE element_membership("
        "source_record_id VARCHAR,element_id VARCHAR,include BOOLEAN)"
    )
    connection.execute(
        "INSERT INTO element_membership VALUES "
        "('gas-1','source.arterial_pco2',TRUE),"
        "('gas-1','source.arterial_pco2',TRUE),"
        "('gas-2','source.arterial_pco2',TRUE),"
        "('ph-1','source.arterial_ph',TRUE),"
        "('other-1','source.arterial_ph',FALSE)"
    )
    connection.execute(
        "CREATE TABLE source_medication("
        "start_timestamp_precision VARCHAR,start_datetime TIMESTAMP,"
        "end_date VARCHAR,order_status VARCHAR,status VARCHAR)"
    )
    connection.execute(
        "INSERT INTO source_medication VALUES "
        "('date_only','2024-01-01',NULL,NULL,NULL),"
        "('timestamp','2024-01-02 11:00:00','2024-01-03','ended','inactive'),"
        "('timestamp',NULL,'',NULL,'')"
    )
    connection.execute(
        "CREATE TABLE source_file_inventory(domain VARCHAR,header VARCHAR)"
    )
    connection.execute(
        "INSERT INTO source_file_inventory VALUES "
        "('encounter','patient_id,encounter_id,start_date,end_date'),"
        "('labs','patient_id,date,code'),"
        "('meds','patient_id,start_date'),"
        "('meds','patient_id,start_date,end_date,order_status,status')"
    )
    return connection


def test_capability_audit_distinguishes_timed_parsed_date_only_and_raw_field_capture():
    with _source() as connection:
        result = cohort_source_capability_audit.audit_candidate_source_capabilities(
            connection
        )
        assert connection.execute(
            "SELECT count(*) FROM source_medication"
        ).fetchone() == (3,)
    assert result.encounter_starts.source_rows == 4
    assert result.encounter_starts.date_only_rows == 1
    assert result.encounter_starts.timestamp_labeled_rows == 2
    assert result.encounter_starts.parsed_timestamp_rows == 1
    assert result.encounter_starts.unparsed_timestamp_rows == 1
    assert result.encounter_starts.other_precision_rows == 1
    assert result.lab_events.date_only_rows == 2
    assert result.lab_events.parsed_timestamp_rows == 2
    assert result.arterial_pco2_candidates.source_rows == 2
    assert result.arterial_pco2_candidates.date_only_rows == 1
    assert result.arterial_pco2_candidates.parsed_timestamp_rows == 1
    assert result.arterial_ph_candidates.source_rows == 1
    assert result.arterial_ph_candidates.date_only_rows == 1
    assert result.arterial_evidence.pco2_rows_with_numeric_value == 1
    assert result.arterial_evidence.pco2_rows_with_mmhg_unit == 1
    assert result.arterial_evidence.pco2_rows_with_specimen_id == 1
    assert result.arterial_evidence.ph_rows_with_numeric_value == 1
    assert result.arterial_evidence.same_day_specimen_groups_with_both_elements == 1
    assert result.arterial_evidence.same_day_panel_groups_with_both_elements == 1
    assert result.medication_starts.parsed_timestamp_rows == 1
    assert result.medication_starts.unparsed_timestamp_rows == 1
    assert result.medication_fields.source_rows == 3
    assert result.medication_fields.rows_with_end_date == 1
    assert result.medication_fields.rows_with_order_status == 1
    assert result.medication_fields.rows_with_status == 1
    headers = {item.domain: item for item in result.raw_headers}
    assert headers["encounter"].source_files == 1
    assert headers["encounter"].files_with_start_date == 1
    assert headers["labs"].files_with_date == 1
    assert headers["meds"].source_files == 2
    assert headers["meds"].files_with_start_date == 2
    assert headers["meds"].files_with_end_date == 1
    assert headers["meds"].files_with_order_status == 1
    assert headers["meds"].files_with_status == 1
    assert "patient_id" not in str(asdict(result))
    assert "2024-01-02" not in str(asdict(result))


def test_empty_candidate_has_zero_capability_without_imputing_capture():
    with _source() as connection:
        for table in (
            "source_encounter",
            "source_lab_measurement",
            "source_medication",
            "source_file_inventory",
            "element_membership",
        ):
            connection.execute(f"DELETE FROM {table}")
        result = cohort_source_capability_audit.audit_candidate_source_capabilities(
            connection
        )
    assert result.encounter_starts.source_rows == 0
    assert result.lab_events.parsed_timestamp_rows == 0
    assert result.arterial_pco2_candidates.source_rows == 0
    assert result.arterial_ph_candidates.source_rows == 0
    assert result.arterial_evidence.same_day_specimen_groups_with_both_elements == 0
    assert result.medication_fields.rows_with_end_date == 0
    assert {item.source_files for item in result.raw_headers} == {0}


def test_arterial_linkage_inventory_requires_same_day_without_asserting_pairing():
    with _source() as connection:
        connection.execute(
            "UPDATE source_lab_measurement SET date='2024-01-02' "
            "WHERE source_record_id='ph-1'"
        )
        result = cohort_source_capability_audit.audit_candidate_source_capabilities(
            connection
        )
    assert result.arterial_evidence.same_day_specimen_groups_with_both_elements == 0
    assert result.arterial_evidence.same_day_panel_groups_with_both_elements == 0
    assert result.arterial_evidence.ph_rows_with_specimen_id == 1


def test_missing_arterial_catalog_element_is_not_a_zero_candidate_result():
    with _source() as connection:
        connection.execute(
            "DELETE FROM element_catalog WHERE element_id='source.arterial_ph'"
        )
        with pytest.raises(ValueError, match="required arterial gas catalog elements"):
            cohort_source_capability_audit.audit_candidate_source_capabilities(
                connection
            )

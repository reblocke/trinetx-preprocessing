"""Fixed-category gas source audit never returns source labels or keys."""

from dataclasses import asdict

import duckdb
import pytest

from trinetx_preprocessing.combined_preprocessing import (
    cohort_source_gas_policy_audit,
)

audit_candidate_gas_policy = cohort_source_gas_policy_audit.audit_candidate_gas_policy


def _source() -> duckdb.DuckDBPyConnection:
    connection = duckdb.connect()
    connection.execute("CREATE TABLE element_catalog(element_id VARCHAR)")
    connection.execute(
        "INSERT INTO element_catalog VALUES "
        "('source.arterial_pco2'),('source.arterial_ph')"
    )
    connection.execute(
        "CREATE TABLE source_lab_measurement("
        "source_record_id VARCHAR,patient_id VARCHAR,encounter_id VARCHAR,"
        "date VARCHAR,timestamp_precision VARCHAR,numeric_value DOUBLE,"
        "specimen VARCHAR,units_of_measure VARCHAR,"
        "specimen_id VARCHAR,panel_id VARCHAR)"
    )
    connection.execute(
        "INSERT INTO source_lab_measurement VALUES "
        "('gas-1','private-p','e','2024-01-01','date_only',50,"
        "'ARTERIAL','mmHg','sample-1','panel-1'),"
        "('gas-2','private-p','e','2024-01-01','date_only',210,"
        "'other','kPa','sample-1','panel-1'),"
        "('ph-1','private-p','e','2024-01-01','date_only',7.3,"
        "'arterial',NULL,'sample-1','panel-1'),"
        "('ph-2','private-p','e','2024-01-01','date_only',14,"
        "NULL,'other','sample-1','panel-1'),"
        "('ph-3','private-p','e','2024-01-02','date_only',7.4,"
        "'arterial',NULL,'sample-1','panel-1'),"
        "('gas-bad','private-p','e','2024-01-01',NULL,NULL,"
        "NULL,NULL,NULL,NULL),"
        "('uncataloged','private-p','e','2024-01-01','date_only',99,"
        "'arterial','mmhg',NULL,NULL)"
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
        "('gas-bad','source.arterial_pco2',TRUE),"
        "('ph-1','source.arterial_ph',TRUE),"
        "('ph-2','source.arterial_ph',TRUE),"
        "('ph-3','source.arterial_ph',TRUE),"
        "('uncataloged','source.arterial_pco2',FALSE)"
    )
    return connection


def test_fixed_categories_and_ambiguous_same_day_link_groups():
    with _source() as connection:
        result = audit_candidate_gas_policy(connection)
    assert result.pco2.candidate_rows == 3
    assert result.pco2.missing_or_invalid_date == 1
    assert result.pco2.finite_numeric_rows == 2
    assert result.pco2.pco2_over_200_rows == 1
    assert result.pco2.arterial_specimen_rows == 1
    assert result.pco2.other_specimen_rows == 1
    assert result.pco2.missing_specimen_rows == 1
    assert result.pco2.mmhg_unit_rows == 1
    assert result.pco2.kpa_unit_rows == 1
    assert result.pco2.missing_unit_rows == 1
    assert result.ph.candidate_rows == 3
    assert result.ph.ph_at_or_above_14_rows == 1
    assert result.ph.missing_unit_rows == 2
    assert result.linkage.same_day_specimen_groups_with_both == 1
    assert result.linkage.same_day_specimen_groups_with_multiple_on_either_side == 1
    assert result.linkage.same_day_panel_groups_with_both == 1
    assert result.linkage.same_day_panel_groups_with_multiple_on_either_side == 1
    serialized = str(asdict(result))
    assert "private-p" not in serialized
    assert "sample-1" not in serialized
    assert "2024-01-01" not in serialized


def test_link_group_requires_same_date_and_source_keys():
    with _source() as connection:
        connection.execute(
            "UPDATE source_lab_measurement SET date='2024-01-03' "
            "WHERE source_record_id IN ('ph-1','ph-2')"
        )
        result = audit_candidate_gas_policy(connection)
    assert result.linkage.same_day_specimen_groups_with_both == 0
    assert result.linkage.same_day_panel_groups_with_both == 0

    with _source() as connection:
        connection.execute(
            "UPDATE source_lab_measurement SET patient_id=NULL "
            "WHERE source_record_id IN ('gas-1','gas-2','ph-1','ph-2')"
        )
        result = audit_candidate_gas_policy(connection)
    assert result.linkage.same_day_specimen_groups_with_both == 0
    assert result.linkage.same_day_panel_groups_with_both == 0


def test_empty_source_and_missing_catalog_are_distinct():
    with _source() as connection:
        connection.execute("DELETE FROM source_lab_measurement")
        result = audit_candidate_gas_policy(connection)
        assert result.pco2.candidate_rows == 0
        assert result.ph.candidate_rows == 0
        assert result.linkage.same_day_specimen_groups_with_both == 0
        connection.execute(
            "DELETE FROM element_catalog WHERE element_id='source.arterial_ph'"
        )
        with pytest.raises(ValueError, match="required arterial gas catalog"):
            audit_candidate_gas_policy(connection)

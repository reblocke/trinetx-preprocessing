"""Aggregate source facts for review of calendar-date arterial gas policy.

This inventory exposes only fixed-category counts. It does not choose valid
specimen labels, unit conversions, plausibility limits, or sample linkage.
The caller must use a validated cohort-source connection and keep the private
result under the study's restricted-data controls.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

import duckdb

_GAS_ELEMENTS = frozenset({"source.arterial_pco2", "source.arterial_ph"})


@dataclass(frozen=True)
class GasCandidateProfile:
    element_id: str
    candidate_rows: int
    missing_patient_or_encounter_key: int
    missing_source_record_key: int
    missing_or_invalid_date: int
    finite_numeric_rows: int
    nonpositive_numeric_rows: int
    raw_pco2_value_over_200_rows: int
    ph_at_or_above_14_rows: int
    arterial_specimen_rows: int
    missing_specimen_rows: int
    other_specimen_rows: int
    mmhg_unit_rows: int
    mmhg_spaced_unit_rows: int
    mmhg_ucum_unit_rows: int
    kpa_unit_rows: int
    ph_literal_unit_rows: int
    unitless_literal_unit_rows: int
    missing_unit_rows: int
    other_unit_rows: int
    specimen_id_rows: int
    panel_id_rows: int


@dataclass(frozen=True)
class GasLinkageProfile:
    records_matching_both_elements: int
    same_day_specimen_groups_with_both: int
    same_day_specimen_groups_with_multiple_on_either_side: int
    same_day_panel_groups_with_both: int
    same_day_panel_groups_with_multiple_on_either_side: int


@dataclass(frozen=True)
class CandidateGasPolicyAudit:
    pco2: GasCandidateProfile
    ph: GasCandidateProfile
    linkage: GasLinkageProfile


def _profile(
    connection: duckdb.DuckDBPyConnection, table: str, element_id: str
) -> GasCandidateProfile:
    raw_pco2_value_over_200 = (
        "count(*) FILTER(WHERE numeric_value IS NOT NULL "
        "AND isfinite(numeric_value) AND numeric_value>200)"
        if element_id == "source.arterial_pco2"
        else "0"
    )
    ph_at_or_above_14 = (
        "count(*) FILTER(WHERE numeric_value IS NOT NULL "
        "AND isfinite(numeric_value) AND numeric_value>=14)"
        if element_id == "source.arterial_ph"
        else "0"
    )
    counts = connection.execute(
        f"WITH matched AS (SELECT * FROM {table} WHERE "
        f"{'pco2' if element_id == 'source.arterial_pco2' else 'ph'}) "
        "SELECT count(*),"
        "count(*) FILTER(WHERE nullif(trim(patient_id),'') IS NULL "
        "OR nullif(trim(encounter_id),'') IS NULL),"
        "count(*) FILTER(WHERE nullif(trim(source_record_id),'') IS NULL),"
        "count(*) FILTER(WHERE date IS NULL OR "
        "timestamp_precision IS DISTINCT FROM 'date_only' "
        "OR coalesce(try_strptime(date,'%Y%m%d'),"
        "try_strptime(date,'%Y-%m-%d')) IS NULL),"
        "count(*) FILTER(WHERE numeric_value IS NOT NULL "
        "AND isfinite(numeric_value)),"
        "count(*) FILTER(WHERE numeric_value IS NOT NULL "
        "AND isfinite(numeric_value) AND numeric_value<=0),"
        f"{raw_pco2_value_over_200},"
        f"{ph_at_or_above_14},"
        "count(*) FILTER(WHERE lower(trim(specimen))='arterial'),"
        "count(*) FILTER(WHERE nullif(trim(specimen),'') IS NULL),"
        "count(*) FILTER(WHERE nullif(trim(specimen),'') IS NOT NULL "
        "AND lower(trim(specimen))!='arterial'),"
        "count(*) FILTER(WHERE lower(trim(units_of_measure))='mmhg'),"
        "count(*) FILTER(WHERE lower(trim(units_of_measure))='mm hg'),"
        "count(*) FILTER(WHERE lower(trim(units_of_measure))='mm[hg]'),"
        "count(*) FILTER(WHERE lower(trim(units_of_measure))='kpa'),"
        "count(*) FILTER(WHERE lower(trim(units_of_measure))='ph'),"
        "count(*) FILTER(WHERE lower(trim(units_of_measure))='unitless'),"
        "count(*) FILTER(WHERE nullif(trim(units_of_measure),'') IS NULL),"
        "count(*) FILTER(WHERE nullif(trim(units_of_measure),'') IS NOT NULL "
        "AND lower(trim(units_of_measure)) NOT IN ('mmhg','kpa')) ,"
        "count(*) FILTER(WHERE nullif(trim(specimen_id),'') IS NOT NULL),"
        "count(*) FILTER(WHERE nullif(trim(panel_id),'') IS NOT NULL) "
        "FROM matched",
    ).fetchone()
    result = GasCandidateProfile(element_id, *(int(value) for value in counts))
    if (
        result.arterial_specimen_rows
        + result.missing_specimen_rows
        + result.other_specimen_rows
        != result.candidate_rows
        or result.mmhg_unit_rows
        + result.kpa_unit_rows
        + result.missing_unit_rows
        + result.other_unit_rows
        != result.candidate_rows
    ):
        raise AssertionError("Arterial source category counts do not reconcile")
    return result


def _linkage(connection: duckdb.DuckDBPyConnection, table: str) -> GasLinkageProfile:
    matched = (
        "WITH matched AS (SELECT patient_id,encounter_id,date,"
        "timestamp_precision,source_record_id,specimen_id,panel_id,pco2,ph "
        f"FROM {table}) "
    )
    both = connection.execute(
        matched + "SELECT count(*) FROM matched WHERE pco2 AND ph"
    ).fetchone()[0]
    groups = []
    for key in ("specimen_id", "panel_id"):
        groups.append(
            connection.execute(
                matched
                + "SELECT count(*),count(*) FILTER(WHERE pco2_count>1 OR ph_count>1) "
                "FROM (SELECT count(DISTINCT source_record_id) FILTER(WHERE pco2) "
                "AS pco2_count,count(DISTINCT source_record_id) FILTER(WHERE ph) "
                "AS ph_count FROM matched WHERE (pco2 OR ph) "
                "AND nullif(trim(patient_id),'') IS NOT NULL "
                "AND nullif(trim(encounter_id),'') IS NOT NULL "
                "AND coalesce(try_strptime(date,'%Y%m%d'),"
                "try_strptime(date,'%Y-%m-%d')) IS NOT NULL "
                "AND timestamp_precision='date_only' "
                f"AND nullif(trim({key}),'') IS NOT NULL "
                f"GROUP BY patient_id,encounter_id,date,{key}) "
                "WHERE pco2_count>0 AND ph_count>0"
            ).fetchone()
        )
    return GasLinkageProfile(
        int(both),
        *(int(value) for pair in groups for value in pair),
    )


def audit_candidate_gas_policy(
    connection: duckdb.DuckDBPyConnection,
) -> CandidateGasPolicyAudit:
    """Count fixed gas evidence categories without accepting their clinical meaning."""
    available = {
        element_id
        for (element_id,) in connection.execute(
            "SELECT element_id FROM element_catalog "
            "WHERE element_id IN ('source.arterial_pco2','source.arterial_ph')"
        ).fetchall()
    }
    if available != _GAS_ELEMENTS:
        raise ValueError(
            "Candidate source lacks required arterial gas catalog elements"
        )
    suffix = uuid4().hex
    flags = f"gas_audit_flags_{suffix}"
    matched = f"gas_audit_matched_{suffix}"
    try:
        connection.execute(
            f"CREATE TEMP TABLE {flags} AS SELECT source_record_id,"
            "bool_or(element_id='source.arterial_pco2') AS pco2,"
            "bool_or(element_id='source.arterial_ph') AS ph "
            "FROM element_membership WHERE include IS TRUE "
            "AND element_id IN ('source.arterial_pco2','source.arterial_ph') "
            "GROUP BY source_record_id"
        )
        connection.execute(
            f"CREATE TEMP TABLE {matched} AS SELECT lab.patient_id,"
            "lab.encounter_id,lab.source_record_id,lab.date,"
            "lab.timestamp_precision,lab.numeric_value,lab.specimen,"
            "lab.units_of_measure,lab.specimen_id,lab.panel_id,"
            "flags.pco2,flags.ph FROM source_lab_measurement AS lab "
            f"JOIN {flags} AS flags ON lab.source_record_id=flags.source_record_id"
        )
        connection.execute(f"DROP TABLE {flags}")
        return CandidateGasPolicyAudit(
            pco2=_profile(connection, matched, "source.arterial_pco2"),
            ph=_profile(connection, matched, "source.arterial_ph"),
            linkage=_linkage(connection, matched),
        )
    finally:
        connection.execute(f"DROP TABLE IF EXISTS {matched}")
        connection.execute(f"DROP TABLE IF EXISTS {flags}")

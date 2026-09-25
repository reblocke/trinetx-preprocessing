"""Aggregate-only sizing of the full calendar encounter source.

Approximate distinct-key values guide a bounded source-interface design.
They are never eligibility counts or source acceptance evidence by themselves.
"""

from __future__ import annotations

from dataclasses import dataclass

import duckdb


@dataclass(frozen=True)
class CalendarSourceSizingAudit:
    source_encounter_rows: int
    invalid_encounter_key_rows: int
    date_only_rows: int
    parseable_date_only_rows: int
    in_scope_type_rows: int
    in_scope_type_with_parseable_date_rows: int
    missing_type_rows: int
    approximate_distinct_encounter_keys: int
    approximate_in_scope_encounter_keys: int
    source_patient_rows: int
    invalid_birth_year_rows: int
    approximate_distinct_patient_ids: int


def audit_calendar_source_sizing(
    connection: duckdb.DuckDBPyConnection,
) -> CalendarSourceSizingAudit:
    """Count raw source coverage without choosing eligible encounters.

    The caller opens a validated, read-only canonical source. These counts
    include every source encounter row, including duplicates and ineligible
    types. ``EMER`` and ``IMP`` here are fixed study-scope hints only. The
    approximate key estimates may differ from exact distinct counts and must
    never be used for a release denominator or reconciliation gate.
    """
    encounter = connection.execute(
        "WITH observed AS (SELECT patient_id,encounter_id,"
        "(patient_id IS NOT NULL AND encounter_id IS NOT NULL "
        "AND trim(patient_id)<>'' AND trim(encounter_id)<>'') AS valid_key,"
        "(start_timestamp_precision='date_only') AS date_only,"
        "(start_timestamp_precision='date_only' AND "
        "regexp_full_match(start_date,'([0-9]{8}|[0-9]{4}-[0-9]{2}-[0-9]{2})') "
        "AND coalesce(try_strptime(start_date,'%Y%m%d'),"
        "try_strptime(start_date,'%Y-%m-%d')) IS NOT NULL) AS parseable_day,"
        "(upper(trim(type)) IN ('EMER','IMP')) AS in_scope_type,"
        "(type IS NULL OR trim(type)='') AS missing_type "
        "FROM source_encounter) "
        "SELECT count(*),count(*) FILTER(WHERE NOT valid_key),"
        "count(*) FILTER(WHERE date_only),"
        "count(*) FILTER(WHERE parseable_day),"
        "count(*) FILTER(WHERE in_scope_type),"
        "count(*) FILTER(WHERE in_scope_type AND parseable_day),"
        "count(*) FILTER(WHERE missing_type),"
        "approx_count_distinct((patient_id,encounter_id)) "
        "FILTER(WHERE valid_key),"
        "approx_count_distinct((patient_id,encounter_id)) "
        "FILTER(WHERE valid_key AND in_scope_type) "
        "FROM observed"
    ).fetchone()
    patient = connection.execute(
        "SELECT count(*),count(*) FILTER(WHERE year_of_birth IS NULL "
        "OR NOT regexp_full_match(year_of_birth,'[0-9]{4}')) ,"
        "approx_count_distinct(patient_id) "
        "FILTER(WHERE patient_id IS NOT NULL AND trim(patient_id)<>'') "
        "FROM source_patient"
    ).fetchone()
    values = tuple(int(value or 0) for value in (*encounter, *patient))
    result = CalendarSourceSizingAudit(*values)
    if (
        result.invalid_encounter_key_rows > result.source_encounter_rows
        or result.date_only_rows > result.source_encounter_rows
        or result.parseable_date_only_rows > result.date_only_rows
        or result.in_scope_type_with_parseable_date_rows > result.in_scope_type_rows
        or result.invalid_birth_year_rows > result.source_patient_rows
    ):
        raise AssertionError("Calendar source sizing categories do not reconcile")
    return result

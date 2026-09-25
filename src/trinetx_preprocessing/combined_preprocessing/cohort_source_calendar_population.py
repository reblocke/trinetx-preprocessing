"""Candidate raw calendar encounter fields for downstream study selection.

This projection preserves one row per original encounter key and reports
source ambiguity. It does not apply age, encounter-type, gas, context or index
rules and cannot accept the source population for a clinical report.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from uuid import uuid4

import duckdb

_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")


@dataclass(frozen=True)
class CalendarCandidateFieldsAudit:
    source_encounter_rows: int
    invalid_encounter_key_rows: int
    exact_encounter_keys: int
    duplicate_source_encounter_keys: int
    unresolved_start_keys: int
    conflicting_start_keys: int
    unresolved_type_keys: int
    conflicting_type_keys: int
    unresolved_birth_year_keys: int
    conflicting_birth_year_keys: int


@dataclass(frozen=True)
class CalendarTypeHintKeysAudit:
    exact_candidate_keys: int
    valid_type_hint_source_rows: int


@dataclass(frozen=True)
class CalendarTypeHintProjectionAudit:
    hinted: CalendarTypeHintKeysAudit
    projected: CalendarCandidateFieldsAudit


def _quoted(value: str) -> str:
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise ValueError("Calendar candidate relation needs a simple SQL identifier")
    return f'"{value}"'


def stage_calendar_type_hint_keys(
    connection: duckdb.DuckDBPyConnection,
    *,
    output_relation: str = "calendar_type_hint_keys",
) -> CalendarTypeHintKeysAudit:
    """Stage exact keys with any EMER/IMP row, without declaring eligibility.

    The result is a narrow key relation; downstream staging must rejoin *all*
    raw records for each key, including out-of-scope or conflicting type rows.
    Invalid keys cannot enter the relation. This is a performance hint, not a
    clinical encounter-type rule or a patient/index selection.
    """
    output = _quoted(output_relation)
    if output_relation.casefold() in {"source_encounter", "source_patient"}:
        raise ValueError("Type-hint key output must differ from source tables")
    connection.execute("BEGIN TRANSACTION")
    try:
        connection.execute(
            f"CREATE OR REPLACE TEMP TABLE {output} AS "
            "SELECT patient_id,encounter_id,count(*) AS type_hint_source_rows "
            "FROM source_encounter WHERE patient_id IS NOT NULL "
            "AND encounter_id IS NOT NULL AND trim(patient_id)<>'' "
            "AND trim(encounter_id)<>'' "
            "AND upper(trim(type)) IN ('EMER','IMP') "
            "GROUP BY patient_id,encounter_id"
        )
        keys, rows = connection.execute(
            f"SELECT count(*),coalesce(sum(type_hint_source_rows),0) FROM {output}"
        ).fetchone()
        connection.execute("COMMIT")
    except BaseException:
        connection.execute("ROLLBACK")
        raise
    return CalendarTypeHintKeysAudit(int(keys), int(rows))


def build_calendar_candidate_fields(
    connection: duckdb.DuckDBPyConnection,
    *,
    output_relation: str = "calendar_candidate_fields",
    source_encounter_relation: str = "source_encounter",
    expected_exact_keys: int | None = None,
    minimum_source_rows: int | None = None,
) -> CalendarCandidateFieldsAudit:
    """Stage raw encounter/date/type/birth-year consensus without inclusion.

    Invalid source keys are counted but cannot enter the exact-key relation.
    A missing or conflicting raw start, type or birth year yields NULL for the
    corresponding consensus field, with counts retained for private QA. No
    missing field is interpreted as an observed clinical negative. The
    temporary output replaces an earlier temporary output only after QA. A
    caller-selected source relation must include every raw row for each key
    in its scope; it is not itself proof of an accepted source population.
    """
    output = _quoted(output_relation)
    source = _quoted(source_encounter_relation)
    if (
        expected_exact_keys is not None
        and (type(expected_exact_keys) is not int or expected_exact_keys < 0)
    ) or (
        minimum_source_rows is not None
        and (type(minimum_source_rows) is not int or minimum_source_rows < 0)
    ):
        raise ValueError(
            "Calendar candidate expected counts must be nonnegative integers"
        )
    if output_relation.casefold() in {
        "source_encounter",
        "source_patient",
        source_encounter_relation.casefold(),
    }:
        raise ValueError("Calendar candidate output must differ from source tables")
    suffix = uuid4().hex
    encounters = _quoted(f"_calendar_raw_encounters_{suffix}")
    patients = _quoted(f"_calendar_raw_patients_{suffix}")
    connection.execute("BEGIN TRANSACTION")
    try:
        source_rows, invalid_keys = connection.execute(
            "SELECT count(*),count(*) FILTER(WHERE patient_id IS NULL "
            "OR encounter_id IS NULL OR trim(patient_id)='' "
            f"OR trim(encounter_id)='') FROM {source}"
        ).fetchone()
        connection.execute(
            f"CREATE TEMP TABLE {encounters} AS WITH observed AS ("
            "SELECT patient_id,encounter_id,"
            "CASE WHEN start_timestamp_precision='date_only' "
            "AND regexp_full_match(start_date,"
            "'([0-9]{8}|[0-9]{4}-[0-9]{2}-[0-9]{2})') "
            "THEN coalesce(try_strptime(start_date,'%Y%m%d'),"
            "try_strptime(start_date,'%Y-%m-%d'))::DATE ELSE NULL END AS day,"
            "nullif(upper(trim(type)),'') AS encounter_type "
            f"FROM {source} WHERE patient_id IS NOT NULL "
            "AND encounter_id IS NOT NULL AND trim(patient_id)<>'' "
            "AND trim(encounter_id)<>'') "
            "SELECT patient_id,encounter_id,count(*) AS source_rows,"
            "count(*) FILTER(WHERE day IS NULL) AS invalid_start_rows,"
            "min(day) AS first_day,max(day) AS last_day,"
            "count(*) FILTER(WHERE encounter_type IS NULL) AS missing_type_rows,"
            "min(encounter_type) AS first_type,max(encounter_type) AS last_type "
            "FROM observed GROUP BY patient_id,encounter_id"
        )
        connection.execute(
            f"CREATE TEMP TABLE {patients} AS SELECT p.patient_id,"
            "count(*) AS source_rows,"
            "count(*) FILTER(WHERE p.year_of_birth IS NULL "
            "OR NOT regexp_full_match(p.year_of_birth,'[0-9]{4}')) "
            "AS invalid_birth_year_rows,"
            "min(p.year_of_birth) AS first_birth_year,"
            "max(p.year_of_birth) AS last_birth_year "
            "FROM source_patient AS p "
            f"SEMI JOIN (SELECT DISTINCT patient_id FROM {encounters}) AS e "
            "ON p.patient_id=e.patient_id GROUP BY p.patient_id"
        )
        connection.execute(
            f"CREATE OR REPLACE TEMP TABLE {output} AS SELECT "
            "e.patient_id,e.encounter_id,e.source_rows AS encounter_source_rows,"
            "e.invalid_start_rows,e.missing_type_rows,"
            "coalesce(p.source_rows,0) AS patient_source_rows,"
            "coalesce(p.invalid_birth_year_rows,0) AS invalid_birth_year_rows,"
            "coalesce(e.first_day<>e.last_day,FALSE) AS conflicting_start_dates,"
            "coalesce(e.first_type<>e.last_type,FALSE) AS conflicting_types,"
            "coalesce(p.first_birth_year<>p.last_birth_year,FALSE) "
            "AS conflicting_birth_years,"
            "CASE WHEN e.invalid_start_rows=0 AND e.first_day=e.last_day "
            "THEN e.first_day ELSE NULL END AS encounter_start_date,"
            "CASE WHEN e.invalid_start_rows=0 AND e.first_day=e.last_day "
            "THEN 'date_only' ELSE NULL END AS encounter_start_precision,"
            "CASE WHEN e.missing_type_rows=0 AND e.first_type=e.last_type "
            "THEN e.first_type ELSE NULL END AS encounter_type,"
            "CASE WHEN p.source_rows>0 AND p.invalid_birth_year_rows=0 "
            "AND p.first_birth_year=p.last_birth_year "
            "THEN try_cast(p.first_birth_year AS INTEGER) ELSE NULL END "
            "AS year_of_birth "
            f"FROM {encounters} AS e LEFT JOIN {patients} AS p "
            "ON e.patient_id=p.patient_id"
        )
        (
            keys,
            duplicates,
            unresolved_start,
            conflicting_start,
            unresolved_type,
            conflicting_type,
            unresolved_yob,
            conflicting_yob,
        ) = connection.execute(
            f"SELECT count(*),count(*) FILTER(WHERE encounter_source_rows>1),"
            "count(*) FILTER(WHERE encounter_start_date IS NULL),"
            "count(*) FILTER(WHERE conflicting_start_dates),"
            "count(*) FILTER(WHERE encounter_type IS NULL),"
            "count(*) FILTER(WHERE conflicting_types),"
            "count(*) FILTER(WHERE year_of_birth IS NULL),"
            f"count(*) FILTER(WHERE conflicting_birth_years) FROM {output}"
        ).fetchone()
        if (
            source_rows - invalid_keys
            != connection.execute(
                f"SELECT coalesce(sum(encounter_source_rows),0) FROM {output}"
            ).fetchone()[0]
        ):
            raise ValueError(
                "Calendar candidate source encounter rows do not reconcile"
            )
        if (
            expected_exact_keys is not None
            and keys != expected_exact_keys
            or minimum_source_rows is not None
            and source_rows < minimum_source_rows
        ):
            raise ValueError("Calendar candidate scoped keys or source rows differ")
        connection.execute(f"DROP TABLE {patients}")
        connection.execute(f"DROP TABLE {encounters}")
        connection.execute("COMMIT")
    except BaseException:
        connection.execute("ROLLBACK")
        raise
    return CalendarCandidateFieldsAudit(
        source_encounter_rows=int(source_rows),
        invalid_encounter_key_rows=int(invalid_keys),
        exact_encounter_keys=int(keys),
        duplicate_source_encounter_keys=int(duplicates),
        unresolved_start_keys=int(unresolved_start),
        conflicting_start_keys=int(conflicting_start),
        unresolved_type_keys=int(unresolved_type),
        conflicting_type_keys=int(conflicting_type),
        unresolved_birth_year_keys=int(unresolved_yob),
        conflicting_birth_year_keys=int(conflicting_yob),
    )


def build_calendar_type_hint_candidate_fields(
    connection: duckdb.DuckDBPyConnection,
    *,
    output_relation: str = "calendar_type_hint_candidate_fields",
) -> CalendarTypeHintProjectionAudit:
    """Project all raw rows at keys with any EMER/IMP type hint.

    This bounds the candidate projection without dropping out-of-scope or
    conflicting records at a hinted key. It neither defines eligible types
    nor resolves uncertain starts, age, context, gas or patient index.
    """
    _quoted(output_relation)
    if output_relation.casefold() in {"source_encounter", "source_patient"}:
        raise ValueError("Calendar candidate output must differ from source tables")
    suffix = uuid4().hex
    hinted_relation = _quoted(f"_calendar_hint_keys_{suffix}")
    scoped_relation = _quoted(f"_calendar_hint_source_{suffix}")
    hint_created = False
    view_created = False
    try:
        hinted = stage_calendar_type_hint_keys(
            connection, output_relation=f"_calendar_hint_keys_{suffix}"
        )
        hint_created = True
        connection.execute(
            f"CREATE TEMP VIEW {scoped_relation} AS SELECT e.* "
            "FROM source_encounter AS e "
            f"SEMI JOIN {hinted_relation} AS k "
            "ON e.patient_id=k.patient_id AND e.encounter_id=k.encounter_id"
        )
        view_created = True
        projected = build_calendar_candidate_fields(
            connection,
            output_relation=output_relation,
            source_encounter_relation=f"_calendar_hint_source_{suffix}",
            expected_exact_keys=hinted.exact_candidate_keys,
            minimum_source_rows=hinted.valid_type_hint_source_rows,
        )
        return CalendarTypeHintProjectionAudit(hinted=hinted, projected=projected)
    finally:
        if view_created:
            connection.execute(f"DROP VIEW {scoped_relation}")
        if hint_created:
            connection.execute(f"DROP TABLE {hinted_relation}")

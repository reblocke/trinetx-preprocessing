"""Read-only calendar evidence projection from a validated cohort source.

This is a source adapter candidate, not a source acceptance or a clinical gas
classifier. Call it only within ``open_accepted_cohort_source`` after the
population receipt has been reviewed. Raw values and units remain unmodified.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

import duckdb

_DAY = re.compile(r"(?:\d{8}|\d{4}-\d{2}-\d{2})\Z")
_GAS_ELEMENTS = ("source.arterial_pco2", "source.arterial_ph")


@dataclass(frozen=True)
class CalendarGasCandidate:
    element_id: str
    source_record_id: str
    event_date: date
    date_precision: str
    numeric_value: float | None
    units_of_measure: str | None
    units_of_measure_raw: str | None
    specimen: str | None
    specimen_id: str | None
    panel_id: str | None
    code_system: str | None
    code: str | None


@dataclass(frozen=True)
class CalendarEncounterEvidence:
    patient_id: str
    encounter_id: str
    encounter_start_date: date
    encounter_start_precision: str
    encounter_source_rows: int
    gas_candidates: tuple[CalendarGasCandidate, ...]


def _observed_day(raw: object, precision: object, *, label: str) -> date:
    if precision != "date_only" or not isinstance(raw, str) or not _DAY.fullmatch(raw):
        raise ValueError(f"{label} must have an observed date-only raw value")
    try:
        return (
            date(int(raw[:4]), int(raw[4:6]), int(raw[6:]))
            if len(raw) == 8
            else date.fromisoformat(raw)
        )
    except ValueError as exc:
        raise ValueError(f"{label} has an invalid observed calendar date") from exc


def project_calendar_encounter_evidence(
    connection: duckdb.DuckDBPyConnection,
    *,
    patient_id: str,
    encounter_id: str,
) -> CalendarEncounterEvidence:
    """Project exact-key encounter starts and catalog-matched arterial rows.

    Duplicate identical source starts are retained in the row count. Missing or
    conflicting starts and undated arterial candidates fail closed. Duplicate
    membership rows do not duplicate a clinical source record. The caller still
    must validate arterial specimen semantics, units, plausible values, panel
    linkage, and population scope before using a phenotype result.
    """
    if not isinstance(patient_id, str) or not patient_id.strip():
        raise ValueError("Original patient key must be nonblank")
    if not isinstance(encounter_id, str) or not encounter_id.strip():
        raise ValueError("Original encounter key must be nonblank")
    available = {
        element_id
        for (element_id,) in connection.execute(
            "SELECT element_id FROM element_catalog WHERE element_id IN (?,?)",
            list(_GAS_ELEMENTS),
        ).fetchall()
    }
    if available != set(_GAS_ELEMENTS):
        raise ValueError("Cohort source lacks required arterial gas catalog elements")
    starts = connection.execute(
        "SELECT start_date, start_timestamp_precision "
        "FROM source_encounter WHERE patient_id=? AND encounter_id=?",
        [patient_id, encounter_id],
    ).fetchall()
    if not starts:
        raise ValueError("Original patient/encounter key is absent from cohort source")
    parsed_starts = {
        _observed_day(raw, precision, label="Encounter start")
        for raw, precision in starts
    }
    if len(parsed_starts) != 1:
        raise ValueError("Original encounter has conflicting source start dates")
    start = next(iter(parsed_starts))
    rows = connection.execute(
        "SELECT lab.source_record_id,lab.date,lab.timestamp_precision,"
        "lab.numeric_value,lab.units_of_measure,lab.units_of_measure_raw,"
        "lab.specimen,lab.specimen_id,lab.panel_id,lab.code_system,lab.code,"
        "EXISTS(SELECT 1 FROM element_membership AS member "
        "WHERE member.source_record_id=lab.source_record_id "
        "AND member.element_id=? AND member.include IS TRUE) AS is_pco2,"
        "EXISTS(SELECT 1 FROM element_membership AS member "
        "WHERE member.source_record_id=lab.source_record_id "
        "AND member.element_id=? AND member.include IS TRUE) AS is_ph "
        "FROM source_lab_measurement AS lab "
        "WHERE lab.patient_id=? AND lab.encounter_id=? "
        "AND (is_pco2 OR is_ph) "
        "ORDER BY lab.source_record_id",
        [*_GAS_ELEMENTS, patient_id, encounter_id],
    ).fetchall()
    candidates: list[CalendarGasCandidate] = []
    seen: set[str] = set()
    for row in rows:
        (
            record_id,
            raw_date,
            precision,
            value,
            units,
            units_raw,
            specimen,
            specimen_id,
            panel_id,
            code_system,
            code,
            is_pco2,
            is_ph,
        ) = row
        if not isinstance(record_id, str) or not record_id.strip() or record_id in seen:
            raise ValueError("Arterial source-record keys must be unique and nonblank")
        seen.add(record_id)
        if is_pco2 and is_ph:
            raise ValueError("One lab source record matches both arterial gas elements")
        event_date = _observed_day(raw_date, precision, label="Arterial event")
        candidates.append(
            CalendarGasCandidate(
                element_id=_GAS_ELEMENTS[0] if is_pco2 else _GAS_ELEMENTS[1],
                source_record_id=record_id,
                event_date=event_date,
                date_precision="date_only",
                numeric_value=value,
                units_of_measure=units,
                units_of_measure_raw=units_raw,
                specimen=specimen,
                specimen_id=specimen_id,
                panel_id=panel_id,
                code_system=code_system,
                code=code,
            )
        )
    return CalendarEncounterEvidence(
        patient_id=patient_id,
        encounter_id=encounter_id,
        encounter_start_date=start,
        encounter_start_precision="date_only",
        encounter_source_rows=len(starts),
        gas_candidates=tuple(candidates),
    )

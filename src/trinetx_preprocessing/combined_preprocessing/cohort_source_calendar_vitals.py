"""Stream catalog-matched raw vital evidence for selected patient indexes.

Call only on a validated, accepted cohort-source connection. Catalog membership
identifies candidates; the study owns units, plausibility, timing and selection.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime

import duckdb

from .cohort_source_calendar_batch import _check_keys, _relation


@dataclass(frozen=True)
class CalendarVitalCandidate:
    source_record_id: str
    source_encounter_id: str | None
    raw_date: str | None
    event_datetime: datetime | None
    timestamp_precision: str | None
    code_system_raw: str | None
    code_system: str | None
    code_raw: str | None
    code: str | None
    raw_value: str | None
    numeric_value: float | None
    units_of_measure_raw: str | None
    units_of_measure: str | None


@dataclass(frozen=True)
class CalendarVitalProjection:
    patient_id: str
    index_encounter_id: str
    candidate: CalendarVitalCandidate | None


def iter_calendar_vital_candidates(
    connection: duckdb.DuckDBPyConnection,
    *,
    index_relation: str,
    element_id: str,
    fetch_size: int = 8192,
) -> Iterator[CalendarVitalProjection]:
    """Preserve every candidate and emit one empty marker for unmatched patients.

    The caller supplies one exact original encounter key per patient. Source
    records may belong to any encounter for that patient; the study must compare
    their observed dates with the selected index before making clinical claims.
    Duplicate membership rows cannot multiply source evidence. A duplicate
    source-record key in the matched vital table fails closed.
    """
    relation = _relation(index_relation)
    if not isinstance(element_id, str) or not element_id.strip():
        raise ValueError("Vital candidate element must be a nonblank catalog ID")
    if (
        isinstance(fetch_size, bool)
        or not isinstance(fetch_size, int)
        or fetch_size < 1
    ):
        raise ValueError("Vital candidate fetch size must be positive")
    _check_keys(connection, relation, one_per_patient=True)
    catalog = connection.execute(
        "SELECT count(*) FROM element_catalog WHERE element_id=? AND domain='vital'",
        [element_id],
    ).fetchone()[0]
    if catalog != 1:
        raise ValueError("Vital candidate element is absent or ambiguous in catalog")
    cursor = connection.execute(
        "WITH matched AS (SELECT v.* FROM source_vital_measurement AS v "
        "WHERE EXISTS (SELECT 1 FROM element_membership AS m "
        "WHERE m.source_record_id=v.source_record_id AND m.element_id=? "
        "AND m.include IS TRUE)) "
        "SELECT k.patient_id,k.encounter_id,v.source_record_id,v.encounter_id,"
        "v.date,v.event_datetime,v.timestamp_precision,v.code_system_raw,"
        "v.code_system,v.code_raw,v.code,v.value,v.numeric_value,"
        "v.units_of_measure_raw,v.units_of_measure "
        f"FROM {relation} AS k LEFT JOIN matched AS v "
        "ON v.patient_id=k.patient_id "
        "ORDER BY k.patient_id,v.source_record_id",
        [element_id],
    )
    previous_patient: str | None = None
    previous_record: str | None = None
    while batch := cursor.fetchmany(fetch_size):
        for row in batch:
            patient_id, index_encounter_id, source_record_id = row[:3]
            if patient_id != previous_patient:
                previous_patient = patient_id
                previous_record = None
            if source_record_id is None:
                yield CalendarVitalProjection(patient_id, index_encounter_id, None)
                continue
            if (
                not isinstance(source_record_id, str)
                or not source_record_id.strip()
                or source_record_id == previous_record
            ):
                raise ValueError(
                    "Matched vital source-record keys must be unique and nonblank"
                )
            previous_record = source_record_id
            yield CalendarVitalProjection(
                patient_id,
                index_encounter_id,
                CalendarVitalCandidate(*row[2:]),
            )

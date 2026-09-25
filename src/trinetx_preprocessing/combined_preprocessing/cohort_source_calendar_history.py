"""Stream raw diagnosis, laboratory or procedure history for patient indexes.

Call only on a validated, accepted canonical-source connection. Catalog
membership identifies candidates; it does not establish clinical truth,
complete capture, pre-index timing, or an observed negative.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import datetime

import duckdb

from .cohort_source_calendar_batch import _check_keys, _relation

_TABLES = {
    "diagnosis": "source_diagnosis",
    "lab": "source_lab_measurement",
    "procedure": "source_procedure",
}


@dataclass(frozen=True)
class CalendarHistoryCandidate:
    source_record_id: str
    source_encounter_id: str | None
    source_file: str | None
    raw_date: str | None
    event_datetime: datetime | None
    timestamp_precision: str | None
    code_system_raw: str | None
    code_system: str | None
    code_raw: str | None
    code: str | None
    raw_numeric_value: str | None
    raw_text_value: str | None
    numeric_value: float | None
    units_of_measure_raw: str | None
    units_of_measure: str | None


@dataclass(frozen=True)
class CalendarHistoryProjection:
    patient_id: str
    index_encounter_id: str
    candidate: CalendarHistoryCandidate | None


def iter_calendar_history_candidates(
    connection: duckdb.DuckDBPyConnection,
    *,
    index_relation: str,
    element_id: str,
    domain: str,
    fetch_size: int = 8192,
) -> Iterator[CalendarHistoryProjection]:
    """Preserve matched history across encounters and mark unmatched patients.

    This single-element interface is retained for existing callers. Use the
    candidate-set interface for a declared union of source concepts.
    """
    yield from iter_calendar_history_candidate_set(
        connection,
        index_relation=index_relation,
        element_ids=(element_id,),
        domain=domain,
        fetch_size=fetch_size,
    )


def iter_calendar_history_candidate_set(
    connection: duckdb.DuckDBPyConnection,
    *,
    index_relation: str,
    element_ids: Sequence[str],
    domain: str,
    fetch_size: int = 8192,
) -> Iterator[CalendarHistoryProjection]:
    """Stream the distinct raw records in an explicit catalog-element union.

    The caller supplies one original index encounter per patient. The source
    must already have passed its separate acceptance gate. No date filter is
    applied here, so the study can explicitly distinguish D-1 history from D
    and later evidence. Fully consume or close the iterator before reusing its
    DuckDB connection.
    """
    relation = _relation(index_relation)
    if not isinstance(domain, str) or domain not in _TABLES:
        raise ValueError("Calendar history domain must be diagnosis, lab or procedure")
    if (
        isinstance(element_ids, (str, bytes))
        or not isinstance(element_ids, Sequence)
        or not element_ids
        or any(not isinstance(item, str) or not item.strip() for item in element_ids)
        or len(set(element_ids)) != len(element_ids)
    ):
        raise ValueError("Calendar history needs distinct nonblank catalog IDs")
    if (
        isinstance(fetch_size, bool)
        or not isinstance(fetch_size, int)
        or fetch_size < 1
    ):
        raise ValueError("Calendar history fetch size must be positive")
    _check_keys(connection, relation, one_per_patient=True)
    catalog_rows = connection.execute(
        "SELECT element_id,count(*) FROM element_catalog "
        "WHERE element_id=ANY(?) AND domain=? GROUP BY element_id",
        [list(element_ids), domain],
    ).fetchall()
    if len(catalog_rows) != len(element_ids) or any(
        count != 1 for _, count in catalog_rows
    ):
        raise ValueError("Calendar history element is absent or ambiguous in catalog")

    table = _TABLES[domain]
    values = (
        "v.lab_result_num_val,v.lab_result_text_val,v.numeric_value,"
        "v.units_of_measure_raw,v.units_of_measure"
        if domain == "lab"
        else "NULL::VARCHAR,NULL::VARCHAR,NULL::DOUBLE,NULL::VARCHAR,NULL::VARCHAR"
    )
    cursor = connection.execute(
        "WITH matched AS (SELECT v.* FROM "
        f"{table} AS v WHERE EXISTS (SELECT 1 FROM element_membership AS m "
        "WHERE m.source_record_id=v.source_record_id AND m.element_id=ANY(?) "
        "AND m.include IS TRUE)) "
        "SELECT k.patient_id,k.encounter_id,v.source_record_id,v.encounter_id,"
        "v.source_file,v.date,v.event_datetime,v.timestamp_precision,"
        "v.code_system_raw,v.code_system,v.code_raw,v.code,"
        f"{values} FROM {relation} AS k LEFT JOIN matched AS v "
        "ON v.patient_id=k.patient_id "
        "ORDER BY k.patient_id,v.source_record_id",
        [list(element_ids)],
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
                yield CalendarHistoryProjection(patient_id, index_encounter_id, None)
                continue
            if (
                not isinstance(source_record_id, str)
                or not source_record_id.strip()
                or source_record_id == previous_record
            ):
                raise ValueError(
                    "Matched history source-record keys must be unique and nonblank"
                )
            previous_record = source_record_id
            yield CalendarHistoryProjection(
                patient_id,
                index_encounter_id,
                CalendarHistoryCandidate(*row[2:]),
            )

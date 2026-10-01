"""Lossless exact-key raw evidence transport without study eligibility rules.

Use only in an accepted read-only cohort-source session. The selector is an
explicit catalogue union and/or exact code-system/code union. A captured code
can be exposed without changing the immutable catalogue or rebuilding source.
Fully consume or close each stream before reusing its connection. Partial
consumption never establishes query completion or a clinical negative.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import date

import duckdb

from .cohort_source_calendar_batch import _check_keys, _relation

_TABLES = {
    "lab": "source_lab_measurement",
    "vital": "source_vital_measurement",
    "diagnosis": "source_diagnosis",
    "procedure": "source_procedure",
    "medication": "source_medication",
}


class SourceTransportError(RuntimeError):
    """A failed or incomplete stream cannot be interpreted as zero records."""

    state = "query_failed_or_incomplete"


@dataclass(frozen=True)
class CalendarSourceRecord:
    patient_id: str
    encounter_id: str
    state: str
    record: dict | None
    matched_element_ids: tuple[str, ...] = ()
    missing_fields: tuple[str, ...] = ()


def _usable(record, domain):
    raw = record.get("start_date" if domain == "medication" else "date")
    if record.get("timestamp_precision") != "date_only" or not isinstance(raw, str):
        return False
    try:
        date.fromisoformat(raw)
    except ValueError:
        return False
    if not record.get("source_record_id") or not record.get("source_file"):
        return False
    return domain not in ("lab", "vital") or record.get("numeric_value") is not None


def iter_calendar_source_records(
    connection: duckdb.DuckDBPyConnection,
    *,
    encounter_relation: str,
    domain: str,
    element_ids: Sequence[str] = (),
    code_selectors: Sequence[tuple[str, str]] = (),
    fetch_size: int = 8192,
) -> Iterator[CalendarSourceRecord]:
    """Retain every selected raw row, raw column and matched catalogue ID.

    Repeated patients are supported. Conflicting dates/types and unusable
    records remain raw evidence, independent of the strict gas classifier
    adapter. Missing tables or selector fields emit explicit states per key.
    Engine failures raise SourceTransportError, even after some rows were yielded.
    """
    relation = _relation(encounter_relation)
    if domain not in _TABLES:
        raise ValueError("Unsupported raw source transport domain")
    if type(fetch_size) is not int or fetch_size < 1:
        raise ValueError("Transport fetch size must be positive")
    if isinstance(element_ids, (str, bytes)) or not isinstance(element_ids, Sequence):
        raise ValueError("Catalogue selectors must be a sequence")
    if any(not isinstance(x, str) or not x.strip() for x in element_ids) or len(
        set(element_ids)
    ) != len(element_ids):
        raise ValueError("Catalogue selectors must be distinct nonblank IDs")
    if isinstance(code_selectors, (str, bytes)) or not isinstance(
        code_selectors, Sequence
    ):
        raise ValueError("Code selectors must be a sequence of exact pairs")
    if any(
        not isinstance(x, (tuple, list))
        or len(x) != 2
        or any(not isinstance(v, str) or not v.strip() for v in x)
        for x in code_selectors
    ):
        raise ValueError("Code selectors need nonblank code-system/code pairs")
    if not element_ids and not code_selectors:
        raise ValueError("An explicit finite selector union is required")
    _check_keys(connection, relation, one_per_patient=False)
    table = _TABLES[domain]
    try:
        tables = {x[0] for x in connection.execute("SHOW TABLES").fetchall()}
        unavailable = None
        missing = ()
        columns = []
        if table not in tables:
            unavailable = "unavailable_domain"
        else:
            columns = [x[0] for x in connection.execute(f"DESCRIBE {table}").fetchall()]
            required = {"patient_id", "encounter_id", "source_record_id"}
            if code_selectors:
                required |= {"code_system", "code"}
            missing = tuple(sorted(required - set(columns)))
            if element_ids:
                if not {"element_membership", "element_catalog"} <= tables:
                    missing += ("element_membership/element_catalog",)
                else:
                    available = {
                        x[0]
                        for x in connection.execute(
                            "SELECT element_id FROM element_catalog WHERE domain=?",
                            [domain],
                        ).fetchall()
                    }
                    missing += tuple(
                        "catalogue:" + x for x in element_ids if x not in available
                    )
            if missing:
                unavailable = "unavailable_field"
        if unavailable:
            cursor = connection.execute(
                f"SELECT patient_id,encounter_id FROM {relation} ORDER BY 1,2"
            )
            while batch := cursor.fetchmany(fetch_size):
                for patient, encounter in batch:
                    yield CalendarSourceRecord(
                        patient, encounter, unavailable, None, missing_fields=missing
                    )
            return
        quoted = [f'v."{x.replace(chr(34), chr(34) * 2)}"' for x in columns]
        parameters = []
        selectors = []
        membership = "[]::VARCHAR[]"
        if element_ids:
            membership = (
                "(SELECT list_sort(list(DISTINCT m.element_id)) "
                "FROM element_membership m "
                "WHERE m.source_record_id=v.source_record_id "
                "AND m.include IS TRUE AND m.element_id=ANY(?))"
            )
            parameters.append(list(element_ids))
            selectors.append("len(matched_element_ids)>0")
        for system, code in code_selectors:
            selectors.append("(v.code_system=? AND v.code=?)")
            parameters.extend((system, code))
        cursor = connection.execute(
            f"WITH keyed AS (SELECT v.* FROM {table} v JOIN {relation} k "
            "USING(patient_id,encounter_id)), "
            f"enriched AS (SELECT v.*,{membership} AS matched_element_ids "
            "FROM keyed v), selected AS (SELECT v.*, "
            "TRUE AS _transport_present FROM enriched v WHERE "
            + " OR ".join(selectors)
            + ") "
            "SELECT k.patient_id,k.encounter_id,v._transport_present,"
            f"v.matched_element_ids,{','.join(quoted)} FROM {relation} k "
            "LEFT JOIN selected v USING(patient_id,encounter_id) "
            "ORDER BY k.patient_id,k.encounter_id,v.source_record_id",
            parameters,
        )
        while batch := cursor.fetchmany(fetch_size):
            for row in batch:
                patient, encounter, present, ids = row[:4]
                if not present:
                    yield CalendarSourceRecord(patient, encounter, "zero_matches", None)
                else:
                    record = dict(zip(columns, row[4:], strict=True))
                    yield CalendarSourceRecord(
                        patient,
                        encounter,
                        "matched" if _usable(record, domain) else "matched_unusable",
                        record,
                        tuple(ids or ()),
                        tuple(
                            sorted(
                                {
                                    "source_file",
                                    "timestamp_precision",
                                    "start_date" if domain == "medication" else "date",
                                }
                                - set(columns)
                            )
                        ),
                    )
    except duckdb.Error as exc:
        raise SourceTransportError(
            "Source evidence query failed or is incomplete"
        ) from exc

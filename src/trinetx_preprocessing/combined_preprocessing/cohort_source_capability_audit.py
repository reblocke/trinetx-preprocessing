"""Aggregate timing and medication-field inventory for a canonical source.

The caller must open a validated cohort-source connection. This audit returns
no source rows, paths or identifiers and does not accept the original abstract
phenotype, its population, or medication activity.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass

import duckdb


@dataclass(frozen=True)
class PrecisionCapture:
    domain: str
    source_rows: int
    date_only_rows: int
    timestamp_labeled_rows: int
    parsed_timestamp_rows: int
    unparsed_timestamp_rows: int
    other_precision_rows: int


@dataclass(frozen=True)
class RawHeaderCapture:
    domain: str
    source_files: int
    files_with_date: int
    files_with_start_date: int
    files_with_end_date: int
    files_with_order_status: int
    files_with_status: int


@dataclass(frozen=True)
class MedicationFieldCapture:
    source_rows: int
    rows_with_end_date: int
    rows_with_order_status: int
    rows_with_status: int


@dataclass(frozen=True)
class CandidateSourceCapabilityAudit:
    encounter_starts: PrecisionCapture
    lab_events: PrecisionCapture
    arterial_pco2_candidates: PrecisionCapture
    arterial_ph_candidates: PrecisionCapture
    medication_starts: PrecisionCapture
    medication_fields: MedicationFieldCapture
    raw_headers: tuple[RawHeaderCapture, ...]


def _precision(
    connection: duckdb.DuckDBPyConnection,
    *,
    domain: str,
    table: str,
    precision: str,
    parsed: str,
    element_id: str | None = None,
) -> PrecisionCapture:
    # Table and column names are fixed below, never interpolated from callers.
    source = f"source.{precision}"
    parsed_source = f"source.{parsed}"
    membership_filter = (
        " WHERE EXISTS (SELECT 1 FROM element_membership AS membership "
        "WHERE membership.source_record_id=source.source_record_id "
        "AND membership.element_id=? AND membership.include IS TRUE)"
        if element_id is not None
        else ""
    )
    total, date_only, labeled, parsed_count, unparsed, other = connection.execute(
        f"SELECT count(*),"
        f"count(*) FILTER(WHERE {source}='date_only'),"
        f"count(*) FILTER(WHERE {source}='timestamp'),"
        f"count(*) FILTER(WHERE {source}='timestamp' AND {parsed_source} IS NOT NULL),"
        f"count(*) FILTER(WHERE {source}='timestamp' AND {parsed_source} IS NULL),"
        f"count(*) FILTER(WHERE {source} IS NULL OR "
        f"{source} NOT IN ('date_only','timestamp')) FROM {table} AS source"
        f"{membership_filter}",
        [element_id] if element_id is not None else [],
    ).fetchone()
    if total != date_only + labeled + other or labeled != parsed_count + unparsed:
        raise AssertionError("Source precision inventory does not reconcile")
    return PrecisionCapture(
        domain=domain,
        source_rows=int(total),
        date_only_rows=int(date_only),
        timestamp_labeled_rows=int(labeled),
        parsed_timestamp_rows=int(parsed_count),
        unparsed_timestamp_rows=int(unparsed),
        other_precision_rows=int(other),
    )


def audit_candidate_source_capabilities(
    connection: duckdb.DuckDBPyConnection,
) -> CandidateSourceCapabilityAudit:
    """Summarize source precision and medication capture without reading raw files.

    ``timestamp`` here means a non-date-only raw string was labeled as a
    timestamp. A parsed value alone does not prove clinical time, timezone,
    first-gas order or same-day medication activity. Raw header counts show
    whether fields were present in the source files; null canonical columns
    cannot be interpreted as observed negatives or open medication orders.
    """
    precision = (
        _precision(
            connection,
            domain="encounter_start",
            table="source_encounter",
            precision="start_timestamp_precision",
            parsed="start_datetime",
        ),
        _precision(
            connection,
            domain="lab_event",
            table="source_lab_measurement",
            precision="timestamp_precision",
            parsed="event_datetime",
        ),
        _precision(
            connection,
            domain="arterial_pco2_catalog_candidate",
            table="source_lab_measurement",
            precision="timestamp_precision",
            parsed="event_datetime",
            element_id="source.arterial_pco2",
        ),
        _precision(
            connection,
            domain="arterial_ph_catalog_candidate",
            table="source_lab_measurement",
            precision="timestamp_precision",
            parsed="event_datetime",
            element_id="source.arterial_ph",
        ),
        _precision(
            connection,
            domain="medication_start",
            table="source_medication",
            precision="start_timestamp_precision",
            parsed="start_datetime",
        ),
    )
    medication_rows = connection.execute(
        "SELECT count(*),"
        "count(*) FILTER(WHERE end_date IS NOT NULL AND trim(end_date)<>''),"
        "count(*) FILTER(WHERE order_status IS NOT NULL AND trim(order_status)<>''),"
        "count(*) FILTER(WHERE status IS NOT NULL AND trim(status)<>'') "
        "FROM source_medication"
    ).fetchone()
    if any(count > medication_rows[0] for count in medication_rows[1:]):
        raise AssertionError("Medication field capture exceeds source rows")
    headers = {domain: [] for domain in ("encounter", "labs", "meds")}
    for domain, header in connection.execute(
        "SELECT domain,header FROM source_file_inventory "
        "WHERE domain IN ('encounter','labs','meds')"
    ).fetchall():
        columns = frozenset(
            value.strip().lstrip("\ufeff").lower()
            for value in next(csv.reader([header]), ())
        )
        headers[domain].append(columns)
    raw_headers = tuple(
        RawHeaderCapture(
            domain=domain,
            source_files=len(files),
            files_with_date=sum("date" in columns for columns in files),
            files_with_start_date=sum("start_date" in columns for columns in files),
            files_with_end_date=sum("end_date" in columns for columns in files),
            files_with_order_status=sum("order_status" in columns for columns in files),
            files_with_status=sum("status" in columns for columns in files),
        )
        for domain, files in headers.items()
    )
    return CandidateSourceCapabilityAudit(
        encounter_starts=precision[0],
        lab_events=precision[1],
        arterial_pco2_candidates=precision[2],
        arterial_ph_candidates=precision[3],
        medication_starts=precision[4],
        medication_fields=MedicationFieldCapture(
            source_rows=int(medication_rows[0]),
            rows_with_end_date=int(medication_rows[1]),
            rows_with_order_status=int(medication_rows[2]),
            rows_with_status=int(medication_rows[3]),
        ),
        raw_headers=raw_headers,
    )

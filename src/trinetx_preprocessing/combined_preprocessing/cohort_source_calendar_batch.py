"""Bulk exact-key calendar gas candidates from an accepted cohort source.

The caller owns patient-index selection and must open the source through its
reviewed acceptance boundary. This adapter preserves raw gas evidence. It
does not approve source scope, units, specimens, linkage or a phenotype.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from uuid import uuid4

import duckdb

from .cohort_source_calendar_projection import (
    CalendarEncounterEvidence,
    CalendarGasCandidate,
    _observed_day,
)

_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
_ELEMENTS = frozenset({"source.arterial_pco2", "source.arterial_ph"})


def _relation(value: str) -> str:
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise ValueError("Calendar index relation must be a simple SQL identifier")
    return f'"{value}"'


def _check_keys(connection: duckdb.DuckDBPyConnection, relation: str) -> int:
    try:
        columns = connection.execute(
            f"DESCRIBE SELECT patient_id,encounter_id FROM {relation}"
        ).fetchall()
    except duckdb.Error as exc:
        raise ValueError("Calendar index relation lacks original key columns") from exc
    if [row[1] for row in columns] != ["VARCHAR", "VARCHAR"]:
        raise ValueError("Calendar index keys must retain original VARCHAR types")
    count, nonblank, patients, pairs = connection.execute(
        "SELECT count(*),"
        "count(*) FILTER(WHERE nullif(trim(patient_id),'') IS NOT NULL "
        "AND nullif(trim(encounter_id),'') IS NOT NULL),"
        "count(DISTINCT patient_id),"
        "count(DISTINCT (patient_id,encounter_id)) "
        f"FROM {relation}"
    ).fetchone()
    if count != nonblank or count != patients or count != pairs:
        raise ValueError(
            "Calendar index needs one nonblank exact encounter per patient"
        )
    return int(count)


def _check_catalog(connection: duckdb.DuckDBPyConnection) -> None:
    available = {
        element_id
        for (element_id,) in connection.execute(
            "SELECT element_id FROM element_catalog "
            "WHERE element_id IN ('source.arterial_pco2','source.arterial_ph')"
        ).fetchall()
    }
    if available != _ELEMENTS:
        raise ValueError("Cohort source lacks required arterial gas catalog elements")


def iter_calendar_population_evidence(
    connection: duckdb.DuckDBPyConnection,
    *,
    index_relation: str,
    fetch_size: int = 8192,
) -> Iterator[CalendarEncounterEvidence]:
    """Stream one raw gas projection per caller-selected patient/encounter.

    ``index_relation`` must be an existing one-row-per-patient relation with
    original VARCHAR ``patient_id`` and ``encounter_id`` columns. Caller-owned
    index and context decisions occur before this function. The function
    creates only temporary tables in the read-only source connection and drops
    them when the iterator is exhausted or closed. Fully consume or close the
    iterator before reusing the connection.
    """
    relation = _relation(index_relation)
    if (
        isinstance(fetch_size, bool)
        or not isinstance(fetch_size, int)
        or fetch_size < 1
    ):
        raise ValueError("Calendar projection fetch size must be positive")
    count = _check_keys(connection, relation)
    _check_catalog(connection)
    if count == 0:
        return
    suffix = uuid4().hex
    starts = f"calendar_starts_{suffix}"
    labs = f"calendar_labs_{suffix}"
    flags = f"calendar_flags_{suffix}"
    gases = f"calendar_gases_{suffix}"
    created: list[str] = []
    try:
        connection.execute(
            f"CREATE TEMP TABLE {starts} AS WITH observed AS ("
            "SELECT k.patient_id,k.encounter_id,"
            "e.encounter_id AS matched_encounter,e.start_timestamp_precision,"
            "coalesce(try_strptime(e.start_date,'%Y%m%d'),"
            "try_strptime(e.start_date,'%Y-%m-%d'))::DATE AS observed_day "
            f"FROM {relation} AS k LEFT JOIN source_encounter AS e "
            "ON k.patient_id=e.patient_id AND k.encounter_id=e.encounter_id) "
            "SELECT patient_id,encounter_id,count(matched_encounter) AS source_rows,"
            "count(matched_encounter) FILTER(WHERE observed_day IS NULL OR "
            "start_timestamp_precision IS DISTINCT FROM 'date_only') AS invalid_rows,"
            "strftime(min(observed_day),'%Y-%m-%d') AS first_start,"
            "strftime(max(observed_day),'%Y-%m-%d') AS last_start "
            "FROM observed GROUP BY patient_id,encounter_id"
        )
        created.append(starts)
        invalid = connection.execute(
            f"SELECT 1 FROM {starts} WHERE source_rows=0 OR invalid_rows>0 "
            "OR first_start!=last_start LIMIT 1"
        ).fetchone()
        if invalid is not None:
            raise ValueError(
                "Calendar index has absent, invalid or conflicting source starts"
            )
        connection.execute(
            f"CREATE TEMP TABLE {labs} AS SELECT lab.patient_id,lab.encounter_id,"
            "lab.source_record_id,lab.date,lab.timestamp_precision,"
            "lab.numeric_value,lab.units_of_measure,lab.units_of_measure_raw,"
            "lab.specimen,lab.specimen_id,lab.panel_id "
            "FROM source_lab_measurement AS lab "
            f"JOIN {relation} AS k ON lab.patient_id=k.patient_id "
            "AND lab.encounter_id=k.encounter_id"
        )
        created.append(labs)
        connection.execute(
            f"CREATE TEMP TABLE {flags} AS SELECT m.source_record_id,"
            "bool_or(m.element_id='source.arterial_pco2') AS pco2,"
            "bool_or(m.element_id='source.arterial_ph') AS ph "
            "FROM element_membership AS m "
            f"JOIN (SELECT DISTINCT source_record_id FROM {labs} "
            "WHERE source_record_id IS NOT NULL) AS selected "
            "ON m.source_record_id=selected.source_record_id "
            "WHERE m.include IS TRUE AND m.element_id IN "
            "('source.arterial_pco2','source.arterial_ph') "
            "GROUP BY m.source_record_id"
        )
        created.append(flags)
        connection.execute(
            f"CREATE TEMP TABLE {gases} AS SELECT lab.*,flags.pco2,flags.ph "
            f"FROM {labs} AS lab JOIN {flags} AS flags "
            "ON lab.source_record_id=flags.source_record_id"
        )
        created.append(gases)
        connection.execute(f"DROP TABLE {flags}")
        created.remove(flags)
        connection.execute(f"DROP TABLE {labs}")
        created.remove(labs)
        cursor = connection.execute(
            "SELECT s.patient_id,s.encounter_id,s.first_start,s.source_rows,"
            "g.source_record_id,g.date,g.timestamp_precision,g.numeric_value,"
            "g.units_of_measure,g.units_of_measure_raw,g.specimen,g.specimen_id,"
            "g.panel_id,g.pco2,g.ph "
            f"FROM {starts} AS s LEFT JOIN {gases} AS g "
            "ON s.patient_id=g.patient_id AND s.encounter_id=g.encounter_id "
            "ORDER BY s.patient_id,s.encounter_id,g.source_record_id"
        )
        current_key: tuple[str, str] | None = None
        current_start = None
        current_rows = 0
        candidates: list[CalendarGasCandidate] = []
        seen: set[str] = set()
        while batch := cursor.fetchmany(fetch_size):
            for row in batch:
                patient, encounter, raw_start, source_rows = row[:4]
                key = (patient, encounter)
                if key != current_key:
                    if current_key is not None:
                        yield CalendarEncounterEvidence(
                            current_key[0],
                            current_key[1],
                            current_start,
                            "date_only",
                            current_rows,
                            tuple(candidates),
                        )
                    current_key = key
                    current_start = _observed_day(
                        raw_start, "date_only", label="Encounter start"
                    )
                    current_rows = int(source_rows)
                    candidates = []
                    seen = set()
                record = row[4]
                if record is None:
                    continue
                if not isinstance(record, str) or not record.strip() or record in seen:
                    raise ValueError(
                        "Arterial source-record keys must be unique and nonblank"
                    )
                seen.add(record)
                pco2, ph = row[13:15]
                if bool(pco2) == bool(ph):
                    raise ValueError(
                        "One lab source record matches ambiguous arterial elements"
                    )
                candidates.append(
                    CalendarGasCandidate(
                        element_id="source.arterial_pco2"
                        if pco2
                        else "source.arterial_ph",
                        source_record_id=record,
                        event_date=_observed_day(
                            row[5], row[6], label="Arterial event"
                        ),
                        date_precision="date_only",
                        numeric_value=row[7],
                        units_of_measure=row[8],
                        units_of_measure_raw=row[9],
                        specimen=row[10],
                        specimen_id=row[11],
                        panel_id=row[12],
                    )
                )
        if current_key is not None:
            yield CalendarEncounterEvidence(
                current_key[0],
                current_key[1],
                current_start,
                "date_only",
                current_rows,
                tuple(candidates),
            )
    finally:
        for table in reversed(created):
            connection.execute(f"DROP TABLE IF EXISTS {table}")

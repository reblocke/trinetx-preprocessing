"""Aggregate candidate-population audit for a canonical cohort source.

The historical patient/index input must be authenticated by the caller. This
module returns category counts only and never chooses a new study index.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

import duckdb
import pandas as pd


@dataclass(frozen=True)
class CandidatePopulationAudit:
    historical_patients: int
    exact_index_present: int
    patient_present_index_missing: int
    patient_absent: int
    exact_index_keys_with_conflicting_starts: int
    exact_index_source_rows: int
    timestamp_start_rows: int
    date_only_start_rows: int
    other_precision_start_rows: int

    @property
    def complete_historical_key_coverage(self) -> bool:
        return self.patient_present_index_missing == self.patient_absent == 0


def audit_candidate_population(
    connection: duckdb.DuckDBPyConnection,
    historical_index: pd.DataFrame,
) -> CandidatePopulationAudit:
    """Compare original patient/index keys with unfiltered `source_encounter`.

    The connection should come from validated `open_cohort_source()`. Duplicate
    source records are retained for start-precision and conflict diagnostics.
    Exact key coverage alone does not accept the source scope, timing, or
    clinical phenotype.
    """
    if not isinstance(historical_index, pd.DataFrame):
        raise ValueError("Historical patient/index input must be a DataFrame")
    if not {"patient_id", "encounter_id"} <= set(historical_index.columns):
        raise ValueError("Historical patient/index input lacks original keys")
    relation = f"_glp1_historical_index_audit_{uuid4().hex}"
    connection.register(relation, historical_index[["patient_id", "encounter_id"]])
    try:
        total, distinct_patients, null_keys = connection.execute(
            f"SELECT count(*), count(DISTINCT patient_id), "
            f"count(*) FILTER(WHERE patient_id IS NULL OR encounter_id IS NULL) "
            f"FROM {relation}"
        ).fetchone()
        if null_keys or total != distinct_patients:
            raise ValueError("Historical input must have one nonnull index per patient")
        types = {
            row[0]: row[1]
            for row in connection.execute(f"DESCRIBE {relation}").fetchall()
        }
        if types != {"patient_id": "VARCHAR", "encounter_id": "VARCHAR"}:
            raise ValueError(
                "Historical patient/index keys must retain original strings"
            )
        blanks = connection.execute(
            f"SELECT count(*) FROM {relation} "
            "WHERE trim(patient_id)='' OR trim(encounter_id)=''"
        ).fetchone()[0]
        if blanks:
            raise ValueError("Historical input must have one nonnull index per patient")
        exact, changed, absent = connection.execute(
            f"""
            WITH source_keys AS (
                SELECT DISTINCT s.patient_id, s.encounter_id
                FROM source_encounter AS s
                SEMI JOIN {relation} AS h
                  ON s.patient_id = h.patient_id
                WHERE s.patient_id IS NOT NULL
            ), source_patients AS (
                SELECT DISTINCT patient_id FROM source_keys
            ), categories AS (
                SELECT sp.patient_id IS NOT NULL AS patient_present,
                       sk.encounter_id IS NOT NULL AS exact_index_present
                FROM {relation} AS h
                LEFT JOIN source_patients AS sp ON h.patient_id = sp.patient_id
                LEFT JOIN source_keys AS sk
                  ON h.patient_id = sk.patient_id AND h.encounter_id = sk.encounter_id
            )
            SELECT count(*) FILTER(WHERE exact_index_present),
                   count(*) FILTER(WHERE patient_present AND NOT exact_index_present),
                   count(*) FILTER(WHERE NOT patient_present)
            FROM categories
            """
        ).fetchone()
        if exact + changed + absent != total:
            raise AssertionError("Historical key coverage categories do not reconcile")
        conflict_keys, source_rows, timed, dated, other = connection.execute(
            f"""
            WITH matched AS (
                SELECT s.patient_id, s.encounter_id,
                       s.start_date, s.start_timestamp_precision
                FROM source_encounter AS s
                JOIN {relation} AS h
                  ON s.patient_id = h.patient_id
                 AND s.encounter_id = h.encounter_id
            ), conflicting AS (
                SELECT patient_id, encounter_id
                FROM matched
                GROUP BY patient_id, encounter_id
                HAVING count(DISTINCT start_date) > 1
            )
            SELECT (SELECT count(*) FROM conflicting),
                   count(*),
                   count(*) FILTER(WHERE start_timestamp_precision='timestamp'),
                   count(*) FILTER(WHERE start_timestamp_precision='date_only'),
                   count(*) FILTER(WHERE start_timestamp_precision IS NULL OR
                     start_timestamp_precision NOT IN ('timestamp','date_only'))
            FROM matched
            """
        ).fetchone()
        if timed + dated + other != source_rows:
            raise AssertionError(
                "Encounter-start precision categories do not reconcile"
            )
        return CandidatePopulationAudit(
            total,
            exact,
            changed,
            absent,
            conflict_keys,
            source_rows,
            timed,
            dated,
            other,
        )
    finally:
        connection.unregister(relation)

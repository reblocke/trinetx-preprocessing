"""Opt-in, source-bound acute-care return outcomes (contract v1)."""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import duckdb

from ..combined_preprocessing.builder import require_safe_output_location
from ..combined_preprocessing.cohort_source import validate_cohort_source
from ..combined_preprocessing.database import COMBINED_MANIFEST_FILENAME
from .builder import VARIANTS, code_identity, literal, sha256
from .compatibility import artifact_inventory, file_identity, no_symlinks
from .validation import (
    DAY_PRECISION_VALIDATION_VERSION,
    VALIDATION_CONTRACT_VERSION,
    validate_bundle,
)

RETURN_CONTRACT_VERSION = "1.0"
DAY_RETURN_CONTRACT_VERSION = "2.0"
RETURN_PARENT_VALIDATION_MEMORY_MIB = 4096
RETURN_PARENT_VALIDATION_DISTINCT_PARTITIONS = 32
RETURN_BUILDER_MEMORY_MIB = 1024
DAY_RETURN_BUILDER_MEMORY_MIB = 4096
HORIZONS = (30, 90, 365)
KINDS = ("inpatient", "ed_only", "any_ed", "acute_union")
CRITERIA = (
    "all_cause",
    "icd_hypercapnia",
    "abg_gt45",
    "abg_gt50",
    "abg_ge45",
    "abg_ge50",
    "vbg_gt45",
    "vbg_gt50",
    "vbg_ge45",
    "vbg_ge50",
    "any_gas_gt45",
    "any_gas_gt50",
    "any_gas_ge45",
    "any_gas_ge50",
    "any_hypercapnia",
)
RETURN_ICD_CODES = frozenset({"J96.02", "J96.12", "J96.22", "J96.92", "E66.2"})


def _require_source_capabilities(database: Path) -> None:
    """Do not interpret omitted concept-filtered codes as negative diagnoses."""
    with duckdb.connect(str(database), read_only=True) as source:
        available = {
            row[0]
            for row in source.execute(
                "SELECT upper(trim(code)) FROM element_rule "
                "WHERE include AND domain='diagnosis' AND match_type='exact' "
                "AND (code_system='*' OR "
                "upper(regexp_replace(code_system,'[^A-Za-z0-9]','','g'))="
                "'ICD10CM')"
            ).fetchall()
        }
        missing = sorted(RETURN_ICD_CODES - available)
        if missing:
            raise ValueError(
                "Canonical diagnosis catalog does not retain required return "
                "ICD codes: " + ", ".join(missing)
            )
        gas = {
            row[0]
            for row in source.execute(
                "SELECT element_id FROM element_catalog "
                "WHERE element_id IN ('source.arterial_pco2',"
                "'source.venous_pco2')"
            ).fetchall()
        }
        if gas != {"source.arterial_pco2", "source.venous_pco2"}:
            raise ValueError(
                "Canonical source lacks required specimen-specific gas sets"
            )


def _write_table(db: duckdb.DuckDBPyConnection, query: str, path: Path) -> None:
    db.execute(f"COPY ({query}) TO {literal(path)} (FORMAT PARQUET, COMPRESSION ZSTD)")


def _prepare_connection(
    work_dir: Path, *, memory_limit_mib: int = RETURN_BUILDER_MEMORY_MIB
) -> duckdb.DuckDBPyConnection:
    db = duckdb.connect()
    db.execute("SET threads=1")
    db.execute(f"SET memory_limit='{memory_limit_mib}MiB'")
    spill = work_dir / "spill"
    spill.mkdir(mode=0o700, parents=True, exist_ok=True)
    db.execute("SET temp_directory=?", [str(spill)])
    return db


def _create_episodes(
    db: duckdb.DuckDBPyConnection, bucket: int, partitions: int
) -> None:
    db.execute(
        f"""
        CREATE TEMP TABLE index_keys AS
        SELECT patient_id::VARCHAR AS patient_id,
               encounter_id::VARCHAR AS encounter_id,
               pat_enc_hash::VARCHAR AS index_event_id
        FROM index_file
        WHERE hash(patient_id::VARCHAR) % {partitions} = {bucket}
        """
    )
    db.execute(
        "CREATE TEMP TABLE index_patients AS SELECT DISTINCT patient_id FROM index_keys"
    )
    db.execute(
        """
        CREATE TEMP TABLE episode_source AS
        SELECT sha256(to_json([s.patient_id, s.encounter_id])) AS episode_id,
               s.patient_id, s.encounter_id, s.source_record_id,
               s.source_file, s.source_row_number, s.source_id,
               s.type AS source_type, s.start_datetime, s.end_datetime,
               s.start_timestamp_precision, s.end_timestamp_precision,
               s.start_date_derived_by_TriNetX,
               s.end_date_derived_by_TriNetX
        FROM preprocessed.source_encounter s
        SEMI JOIN index_patients p USING (patient_id)
        WHERE s.patient_id IS NOT NULL AND s.encounter_id IS NOT NULL
          AND (
            upper(trim(s.type)) IN
              ('IMP','INPAT','INPATIENT','EMER','ED','EMERGENCY')
            OR EXISTS (
              SELECT 1 FROM index_keys i
              WHERE i.patient_id=s.patient_id
                AND i.encounter_id=s.encounter_id
            )
          )
        """
    )
    db.execute(
        """
        CREATE TEMP TABLE episodes AS
        SELECT episode_id, patient_id, encounter_id,
               min(start_datetime) AS episode_start,
               CASE WHEN count(*) FILTER (WHERE end_datetime IS NULL) = 0
                    THEN max(end_datetime) END AS episode_end,
               CASE WHEN count(DISTINCT start_timestamp_precision) = 1
                    THEN min(start_timestamp_precision) END AS start_precision,
               CASE WHEN count(DISTINCT end_timestamp_precision) = 1
                    THEN min(end_timestamp_precision) END AS end_precision,
               bool_or(upper(trim(type)) IN ('IMP','INPAT','INPATIENT'))
                 AS has_inpatient,
               bool_or(upper(trim(type)) IN ('EMER','ED','EMERGENCY')) AS has_ed,
               count(DISTINCT start_datetime) AS distinct_starts,
               count(DISTINCT end_datetime) AS distinct_ends,
               bool_or(lower(trim(coalesce(start_date_derived_by_TriNetX,'')))
                   IN ('1','true','yes','y')) AS has_derived_start,
               bool_or(lower(trim(coalesce(end_date_derived_by_TriNetX,'')))
                   IN ('1','true','yes','y')) AS has_derived_end,
               count(*) AS source_record_count
        FROM (
            SELECT episode_id, patient_id, encounter_id, start_datetime,
                   end_datetime, start_timestamp_precision,
                   end_timestamp_precision, start_date_derived_by_TriNetX,
                   end_date_derived_by_TriNetX,
                   source_type AS type
            FROM episode_source
        ) s
        GROUP BY episode_id, patient_id, encounter_id
        """
    )
    db.execute(
        """
        CREATE TEMP TABLE index_episodes AS
        SELECT i.*, e.episode_id, e.episode_start, e.episode_end,
               e.end_precision, e.has_inpatient AS index_inpatient,
               e.has_ed AS index_ed,
               e.has_derived_end,
               e.distinct_starts, e.distinct_ends,
               CASE WHEN e.episode_id IS NULL THEN 'unlinked'
                    WHEN e.episode_start IS NULL OR e.episode_end IS NULL
                      THEN 'missing_episode_end'
                    WHEN e.has_derived_end THEN 'derived_episode_end'
                    WHEN e.distinct_starts > 1
                      AND NOT (e.has_ed AND e.has_inpatient)
                      THEN 'conflicting_episode_start'
                    WHEN e.distinct_ends > 1 AND NOT (e.has_ed AND e.has_inpatient)
                      THEN 'conflicting_episode_end'
                    WHEN e.episode_end < e.episode_start THEN 'invalid_episode_order'
                    WHEN e.end_precision NOT IN ('date_only','timestamp')
                      THEN 'unknown_end_precision'
                    ELSE 'available' END AS anchor_state
        FROM index_keys i LEFT JOIN episodes e
          ON i.patient_id=e.patient_id AND i.encounter_id=e.encounter_id
        """
    )


def _create_links(db: duckdb.DuckDBPyConnection) -> None:
    db.execute(
        """
        CREATE TEMP TABLE return_links AS
        SELECT i.index_event_id, i.patient_id AS index_patient_id,
               i.encounter_id AS index_encounter_id, i.episode_id AS index_episode_id,
               i.episode_end AS index_episode_end,
               i.end_precision AS index_end_precision,
               i.index_inpatient, i.index_ed,
               e.episode_id AS return_episode_id, e.patient_id, e.encounter_id,
               e.episode_start AS return_start,
               e.start_precision AS return_start_precision,
               e.episode_end AS return_end, e.end_precision AS return_end_precision,
               e.has_inpatient, e.has_ed,
               e.source_record_count,
               CASE WHEN e.episode_start IS NULL THEN 'missing_return_start'
                    WHEN e.has_derived_start THEN 'derived_return_start'
                    WHEN e.distinct_starts > 1 AND NOT (e.has_ed AND e.has_inpatient)
                      THEN 'conflicting_return_start'
                    WHEN e.start_precision NOT IN ('date_only','timestamp')
                      THEN 'unknown_return_precision'
                    WHEN e.episode_end IS NOT NULL
                      AND e.episode_end < e.episode_start
                      THEN 'invalid_return_episode_order'
                    WHEN e.episode_start::DATE = i.episode_end::DATE
                      AND (e.start_precision='date_only' OR i.end_precision='date_only')
                      THEN 'same_day_uncertain'
                    WHEN e.episode_start <= i.episode_end THEN 'overlap_or_prior'
                    WHEN e.episode_start > i.episode_end + INTERVAL 365 DAY
                      THEN 'outside_horizon'
                    ELSE 'confirmed' END AS temporal_state,
               (e.has_ed AND e.has_inpatient) AS evidenced_ed_inpatient,
               (e.has_ed AND NOT e.has_inpatient) AS ed_only,
               (e.has_inpatient AND i.index_ed AND NOT i.index_inpatient)
                 AS admission_after_ed_index,
               (e.has_inpatient AND i.index_inpatient) AS readmission_after_inpatient
        FROM index_episodes i JOIN episodes e USING (patient_id)
        WHERE i.anchor_state='available'
          AND e.episode_id <> i.episode_id
          AND (e.has_ed OR e.has_inpatient)
          AND (e.episode_start IS NULL OR
               (e.episode_start::DATE >= i.episode_end::DATE
                AND e.episode_start::DATE <=
                    (i.episode_end + INTERVAL 365 DAY)::DATE)
               OR (e.episode_start::DATE < i.episode_end::DATE
                   AND e.episode_end >= i.episode_end))
        """
    )
    if db.execute(
        "SELECT count(*) FROM (SELECT index_event_id, return_episode_id "
        "FROM return_links GROUP BY 1,2 HAVING count(*)>1)"
    ).fetchone()[0]:
        raise ValueError("Duplicate index-to-return episode link")


def _create_evidence(
    db: duckdb.DuckDBPyConnection, *, create_outcomes: bool = True
) -> None:
    db.execute(
        """
        CREATE TEMP TABLE return_episode_keys AS
        SELECT DISTINCT return_episode_id AS episode_id, patient_id, encounter_id,
               return_start, return_end
        FROM return_links
        """
    )
    db.execute(
        """
        CREATE TEMP TABLE diagnosis_evidence AS
        SELECT e.episode_id, d.patient_id, d.encounter_id,
               d.source_record_id, d.source_file, d.source_row_number,
               d.source_id, d.code_system, d.code, d.event_datetime,
               d.timestamp_precision,
               CASE WHEN e.return_start IS NULL THEN 'missing_episode_start'
                    WHEN e.return_end IS NULL THEN 'missing_episode_end'
                    WHEN d.event_datetime IS NULL THEN 'missing_date'
                    WHEN d.event_datetime::DATE < e.return_start::DATE
                      OR (e.return_end IS NOT NULL
                          AND d.event_datetime::DATE > e.return_end::DATE)
                      THEN 'outside_episode'
                    WHEN upper(regexp_replace(coalesce(d.code_system,''),
                         '[^A-Za-z0-9]','','g')) <> 'ICD10CM'
                      THEN 'other_code_system'
                    WHEN upper(trim(coalesce(d.code,''))) NOT IN
                         ('J96.02','J96.12','J96.22','J96.92','E66.2')
                      THEN 'other_code'
                    ELSE NULL END AS rejection_reason
        FROM preprocessed.source_diagnosis d
        JOIN return_episode_keys e USING (patient_id, encounter_id)
        """
    )
    db.execute(
        """
        CREATE TEMP TABLE gas_evidence AS
        WITH candidate AS (
          SELECT e.episode_id, l.patient_id, l.encounter_id,
                 l.source_record_id, l.source_file, l.source_row_number,
                 l.source_id, l.code_system, l.code, l.event_datetime,
                 l.timestamp_precision, l.specimen, l.specimen_id, l.panel_id,
                 l.numeric_value AS raw_value, l.units_of_measure AS raw_unit,
                 m.element_id,
                 CASE WHEN m.element_id='source.arterial_pco2' THEN 'abg'
                      WHEN m.element_id='source.venous_pco2' THEN 'vbg'
                      ELSE 'unspecified' END AS gas_kind,
                 lower(trim(coalesce(l.units_of_measure,''))) AS unit_key,
                 e.return_start, e.return_end
          FROM preprocessed.source_lab_measurement l
          JOIN return_episode_keys e USING (patient_id, encounter_id)
          JOIN preprocessed.element_membership m
            ON m.source_record_id=l.source_record_id AND m.include
           AND m.element_id IN ('source.arterial_pco2',
                                'source.venous_pco2',
                                'source.unspecified_blood_pco2')
        ), qualified AS (
          SELECT *,
                 count(DISTINCT gas_kind) OVER
                   (PARTITION BY source_record_id) AS catalog_specimen_count,
                 CASE WHEN unit_key IN
                    ('mmhg','mm hg','mm_hg','mm[hg]','torr') THEN raw_value
                   WHEN unit_key='kpa' THEN raw_value*7.5006168270417
                 END AS value_mmhg
          FROM candidate
        )
        SELECT episode_id, patient_id, encounter_id, source_record_id,
               source_file, source_row_number, source_id, code_system, code,
               event_datetime, timestamp_precision, specimen, specimen_id,
               panel_id, raw_value, raw_unit, element_id, gas_kind,
               value_mmhg,
               CASE WHEN return_start IS NULL THEN 'missing_episode_start'
                    WHEN return_end IS NULL THEN 'missing_episode_end'
                    WHEN event_datetime IS NULL THEN 'missing_date'
                    WHEN event_datetime::DATE < return_start::DATE
                      OR (return_end IS NOT NULL
                          AND event_datetime::DATE > return_end::DATE)
                      THEN 'outside_episode'
                    WHEN catalog_specimen_count > 1
                      THEN 'conflicting_catalog_specimen'
                    WHEN gas_kind='unspecified' THEN 'unspecified_specimen'
                    WHEN (gas_kind='abg' AND lower(coalesce(specimen,'')) LIKE '%ven%')
                      OR (gas_kind='vbg' AND lower(coalesce(specimen,'')) LIKE '%art%')
                      THEN 'contradictory_specimen'
                    WHEN raw_value IS NULL OR NOT isfinite(raw_value)
                      OR raw_value <= 0 THEN 'invalid_value'
                    WHEN value_mmhg IS NULL THEN 'unsupported_unit'
                    WHEN NOT isfinite(value_mmhg) THEN 'invalid_converted_value'
                    ELSE NULL END AS rejection_reason
        FROM qualified
        """
    )
    if not create_outcomes:
        return
    db.execute(
        """
        CREATE TEMP TABLE episode_outcomes AS
        SELECT e.episode_id,
               coalesce(d.icd_hypercapnia,false) AS icd_hypercapnia,
               g.abg_tested, g.vbg_tested,
               g.abg_gt45, g.abg_gt50, g.abg_ge45, g.abg_ge50,
               g.vbg_gt45, g.vbg_gt50, g.vbg_ge45, g.vbg_ge50
        FROM return_episode_keys e
        LEFT JOIN (
          SELECT episode_id, bool_or(rejection_reason IS NULL) AS icd_hypercapnia
          FROM diagnosis_evidence GROUP BY episode_id
        ) d USING (episode_id)
        LEFT JOIN (
          SELECT episode_id,
                 bool_or(gas_kind='abg' AND rejection_reason IS NULL)
                   AS abg_tested,
                 bool_or(gas_kind='vbg' AND rejection_reason IS NULL)
                   AS vbg_tested,
                 bool_or(gas_kind='abg' AND rejection_reason IS NULL
                         AND value_mmhg>45) AS abg_gt45,
                 bool_or(gas_kind='abg' AND rejection_reason IS NULL
                         AND value_mmhg>50) AS abg_gt50,
                 bool_or(gas_kind='abg' AND rejection_reason IS NULL
                         AND value_mmhg>=45) AS abg_ge45,
                 bool_or(gas_kind='abg' AND rejection_reason IS NULL
                         AND value_mmhg>=50) AS abg_ge50,
                 bool_or(gas_kind='vbg' AND rejection_reason IS NULL
                         AND value_mmhg>45) AS vbg_gt45,
                 bool_or(gas_kind='vbg' AND rejection_reason IS NULL
                         AND value_mmhg>50) AS vbg_gt50,
                 bool_or(gas_kind='vbg' AND rejection_reason IS NULL
                         AND value_mmhg>=45) AS vbg_ge45,
                 bool_or(gas_kind='vbg' AND rejection_reason IS NULL
                         AND value_mmhg>=50) AS vbg_ge50
          FROM gas_evidence GROUP BY episode_id
        ) g USING (episode_id)
        """
    )
    db.execute(
        """
        CREATE TEMP TABLE links_enriched AS
        SELECT l.*,
               o.icd_hypercapnia,
               o.abg_tested, o.vbg_tested,
               o.abg_gt45, o.abg_gt50, o.abg_ge45, o.abg_ge50,
               o.vbg_gt45, o.vbg_gt50, o.vbg_ge45, o.vbg_ge50,
               (o.abg_gt45 OR o.vbg_gt45) AS any_gas_gt45,
               (o.abg_gt50 OR o.vbg_gt50) AS any_gas_gt50,
               (o.abg_ge45 OR o.vbg_ge45) AS any_gas_ge45,
               (o.abg_ge50 OR o.vbg_ge50) AS any_gas_ge50,
               (o.icd_hypercapnia OR o.abg_ge45 OR o.vbg_ge50)
                 AS any_hypercapnia
        FROM return_links l LEFT JOIN episode_outcomes o
          ON l.return_episode_id=o.episode_id
        """
    )


def _summary_query() -> str:
    columns = [
        "i.index_event_id",
        "i.patient_id",
        "i.encounter_id",
        "i.episode_id AS index_episode_id",
        "i.episode_start AS index_episode_start",
        "i.episode_end AS index_episode_end",
        "i.end_precision AS index_end_precision",
        "i.anchor_state",
        "i.index_inpatient",
        "i.index_ed",
        "p.month_year_death",
        "o.last_observed_event_datetime",
        "CASE WHEN i.index_inpatient THEN 'readmission' "
        "WHEN i.index_ed THEN 'admission' ELSE 'not_applicable' END "
        "AS inpatient_event_term",
        "count(l.return_episode_id) FILTER (WHERE "
        "l.temporal_state='same_day_uncertain') AS same_day_uncertain_count",
        "count(l.return_episode_id) FILTER (WHERE "
        "l.temporal_state='overlap_or_prior') AS overlap_or_prior_count",
        "count(l.return_episode_id) FILTER (WHERE "
        "l.temporal_state='missing_return_start') AS undated_return_count",
        "count(l.return_episode_id) FILTER (WHERE "
        "l.temporal_state='derived_return_start') AS derived_return_start_count",
        "count(l.return_episode_id) FILTER (WHERE "
        "l.temporal_state='invalid_return_episode_order') "
        "AS invalid_return_episode_order_count",
    ]
    kind_predicates = {
        "inpatient": "l.has_inpatient",
        "ed_only": "l.ed_only",
        "any_ed": "l.has_ed",
        "acute_union": "(l.has_ed OR l.has_inpatient)",
    }
    for days in HORIZONS:
        columns.append(
            "CASE WHEN i.anchor_state<>'available' THEN 'index_unavailable' "
            "WHEN o.last_observed_event_datetime IS NULL THEN 'unobserved' "
            f"WHEN o.last_observed_event_datetime >= "
            f"i.episode_end + INTERVAL {days} DAY "
            "THEN 'observation_at_or_after_horizon' "
            "ELSE 'last_observation_before_horizon' END "
            f"AS outcome_followup_observation_{days}d"
        )
        for kind, kind_predicate in kind_predicates.items():
            observed = (
                f"l.temporal_state='confirmed' AND {kind_predicate} "
                f"AND l.return_start <= i.episode_end + INTERVAL {days} DAY"
            )
            for gas_kind, tested in (
                ("abg", "l.abg_tested"),
                ("vbg", "l.vbg_tested"),
                ("any_gas", "(l.abg_tested OR l.vbg_tested)"),
            ):
                columns.append(
                    f"count(l.return_episode_id) FILTER (WHERE {observed} "
                    f"AND {tested}) AS "
                    f"outcome_{kind}_{gas_kind}_tested_{days}d_count"
                )
            for criterion in CRITERIA:
                name = f"outcome_{kind}_{criterion}_{days}d"
                condition = (
                    f"l.temporal_state='confirmed' AND {kind_predicate} "
                    f"AND l.return_start <= i.episode_end + INTERVAL {days} DAY"
                )
                if criterion != "all_cause":
                    condition += f" AND l.{criterion}"
                count = f"count(l.return_episode_id) FILTER (WHERE {condition})"
                columns.append(f"{count} AS {name}_count")
                columns.append(
                    f"min(l.return_start::DATE) FILTER (WHERE {condition}) "
                    f"AS {name}_first_date"
                )
                columns.append(
                    f"min(l.return_start) FILTER (WHERE {condition} "
                    "AND l.return_start_precision='timestamp') "
                    f"AS {name}_first_timestamp"
                )
                if criterion in ("all_cause", "icd_hypercapnia"):
                    flag = f"({count}>0)"
                else:
                    tested = "(l.abg_tested OR l.vbg_tested)"
                    if criterion.startswith("abg_"):
                        tested = "l.abg_tested"
                    elif criterion.startswith("vbg_"):
                        tested = "l.vbg_tested"
                    testing_condition = (
                        f"l.temporal_state='confirmed' AND {kind_predicate} "
                        f"AND l.return_start <= i.episode_end + INTERVAL {days} DAY "
                        f"AND {tested}"
                    )
                    flag = (
                        f"CASE WHEN {count}>0 THEN true WHEN "
                        "count(l.return_episode_id) FILTER (WHERE "
                        f"{testing_condition})>0 "
                        "THEN false ELSE NULL END"
                    )
                columns.append(
                    f"CASE WHEN i.anchor_state='available' THEN {flag} "
                    f"ELSE NULL END AS {name}_flag"
                )
    group = ", ".join(str(i) for i in range(1, 14))
    return (
        "SELECT "
        + ",\n".join(columns)
        + " FROM index_episodes i LEFT JOIN links_enriched l "
        "ON i.index_event_id=l.index_event_id "
        "LEFT JOIN (SELECT patient_id, "
        "CASE WHEN count(DISTINCT month_year_death)=1 "
        "THEN min(month_year_death) END AS month_year_death "
        "FROM preprocessed.source_patient GROUP BY patient_id) p "
        "ON i.patient_id=p.patient_id "
        "LEFT JOIN (SELECT patient_id, max(last_event_datetime) "
        "AS last_observed_event_datetime FROM preprocessed.patient_observability "
        "GROUP BY patient_id) o ON i.patient_id=o.patient_id "
        f"GROUP BY {group}"
    )


def _build_partition(
    db: duckdb.DuckDBPyConnection,
    *,
    variant: str,
    bucket: int,
    partitions: int,
    output: Path,
) -> dict[str, dict[str, str | int]]:
    _create_episodes(db, bucket, partitions)
    _create_links(db)
    _create_evidence(db)
    prefix = f"{variant.lower()}_{bucket:04d}"
    paths = {
        "episode_source": output / f"{prefix}_episode_source.parquet",
        "episodes": output / f"{prefix}_episodes.parquet",
        "diagnosis_evidence": output / f"{prefix}_diagnosis_evidence.parquet",
        "gas_evidence": output / f"{prefix}_gas_evidence.parquet",
        "links": output / f"{prefix}_links.parquet",
        "summary": output / f"{prefix}_summary.parquet",
    }
    queries = {
        "episode_source": "SELECT * FROM episode_source",
        "episodes": "SELECT * FROM episodes",
        "diagnosis_evidence": "SELECT * FROM diagnosis_evidence",
        "gas_evidence": "SELECT * FROM gas_evidence",
        "links": "SELECT * FROM links_enriched",
        "summary": _summary_query(),
    }
    for name, path in paths.items():
        _write_table(db, queries[name], path)
    for table in (
        "index_keys",
        "index_patients",
        "episode_source",
        "episodes",
        "index_episodes",
        "return_links",
        "return_episode_keys",
        "diagnosis_evidence",
        "gas_evidence",
        "episode_outcomes",
        "links_enriched",
    ):
        db.execute(f"DROP TABLE {table}")
    return {
        name: {"sha256": sha256(path), "bytes": path.stat().st_size}
        for name, path in paths.items()
    }


def build_returns(
    *,
    database: Path,
    parent_bundle: Path,
    output_dir: Path,
    work_dir: Path,
    partitions: int = 32,
    resume: bool = False,
    contract_version: str = RETURN_CONTRACT_VERSION,
) -> dict:
    """Build both variants into a distinct external bundle with resumable parts."""
    if contract_version not in {RETURN_CONTRACT_VERSION, DAY_RETURN_CONTRACT_VERSION}:
        raise ValueError("Unsupported return contract version")
    if partitions < 1 or partitions > 1024:
        raise ValueError("Patient partition count must be from 1 to 1024")
    database, parent_bundle = no_symlinks(database), no_symlinks(parent_bundle)
    output_dir, work_dir = no_symlinks(output_dir), no_symlinks(work_dir)
    for path, label in ((output_dir, "return bundle"), (work_dir, "return work")):
        require_safe_output_location(path, artifact_label=label)
    if output_dir.exists():
        raise FileExistsError("Return output destination already exists")
    if (
        output_dir == work_dir
        or output_dir.is_relative_to(work_dir)
        or work_dir.is_relative_to(output_dir)
    ):
        raise ValueError("Return output and work locations must be separate")
    if any(
        output_dir.is_relative_to(input_path) or input_path.is_relative_to(output_dir)
        for input_path in (parent_bundle, database.parent)
    ):
        raise ValueError("Return output location overlaps immutable inputs")
    if any(
        work_dir.is_relative_to(input_path) or input_path.is_relative_to(work_dir)
        for input_path in (parent_bundle, database.parent)
    ):
        raise ValueError("Return work location overlaps immutable inputs")
    parent_report = validate_bundle(
        bundle=parent_bundle,
        work_dir=work_dir / f"parent-validation-{uuid.uuid4().hex}",
        memory_limit_mib=RETURN_PARENT_VALIDATION_MEMORY_MIB,
        distinct_count_partitions=RETURN_PARENT_VALIDATION_DISTINCT_PARTITIONS,
        validation_contract_version=(
            DAY_PRECISION_VALIDATION_VERSION
            if contract_version == DAY_RETURN_CONTRACT_VERSION
            else VALIDATION_CONTRACT_VERSION
        ),
    )
    if not parent_report["pass"]:
        raise ValueError("Parent encounter bundle failed validation")
    source = validate_cohort_source(database)
    if not source.valid or source.metadata is None:
        raise ValueError("Canonical cohort source failed validation")
    _require_source_capabilities(database)
    parent_manifest_path = parent_bundle / "manifest.json"
    parent_manifest = json.loads(parent_manifest_path.read_text())
    source_sidecar = database.parent / COMBINED_MANIFEST_FILENAME
    if parent_manifest.get("source_manifest_sha256") != sha256(source_sidecar):
        raise ValueError("Parent and canonical source identities differ")
    work_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    builder_memory_limit_mib = (
        DAY_RETURN_BUILDER_MEMORY_MIB
        if contract_version == DAY_RETURN_CONTRACT_VERSION
        else RETURN_BUILDER_MEMORY_MIB
    )
    with _prepare_connection(
        work_dir, memory_limit_mib=builder_memory_limit_mib
    ) as keycheck:
        for variant in VARIANTS:
            index_file = parent_bundle / f"encounter_features_{variant.lower()}.parquet"
            collisions = keycheck.execute(
                "SELECT count(*) FROM (SELECT pat_enc_hash FROM "
                f"read_parquet({literal(index_file)}) GROUP BY pat_enc_hash "
                "HAVING count(DISTINCT (patient_id::VARCHAR, "
                "encounter_id::VARCHAR))>1)"
            ).fetchone()[0]
            if collisions:
                raise ValueError("Original index hash collides across composite keys")
    identity = {
        "return_contract_version": contract_version,
        "parent_manifest_sha256": sha256(parent_manifest_path),
        "source_manifest_sha256": sha256(source_sidecar),
        "source_file_identity": list(file_identity(database)),
        "code_sha256": code_identity(),
        "partitions": partitions,
    }
    output_dir.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    staging = output_dir.parent / f".{output_dir.name}.return-staging"
    require_safe_output_location(staging, artifact_label="return staging")
    progress_path = staging / "progress.json"
    if staging.exists():
        if not resume:
            raise FileExistsError("Return staging exists; explicit --resume required")
        progress = json.loads(progress_path.read_text())
        if progress.get("identity") != identity:
            raise ValueError("Resume identity differs from current inputs/code/config")
    else:
        if resume:
            raise FileNotFoundError("No return staging to resume")
        staging.mkdir(mode=0o700)
        progress = {"identity": identity, "completed": {}}
        progress_path.write_text(json.dumps(progress, indent=2) + "\n")
    db = _prepare_connection(work_dir, memory_limit_mib=builder_memory_limit_mib)
    try:
        db.execute(f"ATTACH {literal(database)} AS preprocessed (READ_ONLY)")
        for variant in VARIANTS:
            index_file = parent_bundle / f"encounter_features_{variant.lower()}.parquet"
            db.execute(
                "CREATE OR REPLACE TEMP VIEW index_file AS "
                f"SELECT * FROM read_parquet({literal(index_file)})"
            )
            for bucket in range(partitions):
                key = f"{variant}:{bucket}"
                if key in progress["completed"]:
                    if set(progress["completed"][key]) != {
                        "episode_source",
                        "episodes",
                        "diagnosis_evidence",
                        "gas_evidence",
                        "links",
                        "summary",
                    }:
                        raise ValueError("Resume part receipt is incomplete")
                    for name, info in progress["completed"][key].items():
                        path = (
                            staging / f"{variant.lower()}_{bucket:04d}_{name}.parquet"
                        )
                        if not path.is_file() or sha256(path) != info["sha256"]:
                            raise ValueError("Resume part is missing or changed")
                    continue
                for name in (
                    "episode_source",
                    "episodes",
                    "diagnosis_evidence",
                    "gas_evidence",
                    "links",
                    "summary",
                ):
                    partial = staging / f"{variant.lower()}_{bucket:04d}_{name}.parquet"
                    if partial.is_symlink():
                        raise ValueError("Interrupted return part is a symlink")
                    if partial.exists():
                        partial.unlink()
                if contract_version == DAY_RETURN_CONTRACT_VERSION:
                    from .returns_v2 import build_partition_v2

                    build_partition = build_partition_v2
                else:
                    build_partition = _build_partition
                part = build_partition(
                    db,
                    variant=variant,
                    bucket=bucket,
                    partitions=partitions,
                    output=staging,
                )
                progress["completed"][key] = part
                temporary = progress_path.with_suffix(".tmp")
                temporary.write_text(json.dumps(progress, indent=2) + "\n")
                temporary.replace(progress_path)
            db.execute("DROP VIEW index_file")
    finally:
        db.close()
    if (
        list(file_identity(database)) != identity["source_file_identity"]
        or sha256(source_sidecar) != identity["source_manifest_sha256"]
        or sha256(parent_manifest_path) != identity["parent_manifest_sha256"]
        or code_identity() != identity["code_sha256"]
    ):
        raise ValueError("Input or code changed during return build")
    dictionary = {}
    with duckdb.connect() as inspect:
        for name in (
            "episode_source",
            "episodes",
            "diagnosis_evidence",
            "gas_evidence",
            "links",
            "summary",
        ):
            example = staging / f"full_data_0000_{name}.parquet"
            columns = inspect.execute(
                f"DESCRIBE SELECT * FROM read_parquet({literal(example)})"
            ).fetchall()
            if contract_version == DAY_RETURN_CONTRACT_VERSION:
                from .returns_v2 import dictionary_entry

                dictionary[name] = [
                    dictionary_entry(name, column, kind) for column, kind, *_ in columns
                ]
            else:
                dictionary[name] = [
                    {"column": column, "duckdb_type": kind, "role": "outcome"}
                    for column, kind, *_ in columns
                ]
    (staging / "data_dictionary.json").write_text(
        json.dumps(dictionary, indent=2) + "\n"
    )
    # The checkpoint is hashed in the manifest, preserving interruption evidence.
    manifest = {
        "kind": "return_outcomes",
        "status": "complete",
        "schema_version": contract_version,
        **identity,
        "variants": list(VARIANTS),
        "horizons_days": list(HORIZONS),
        "outputs": artifact_inventory(staging),
        "limitations": [
            "Observed returns only; forward capture is not proven complete"
        ],
    }
    (staging / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    if output_dir.exists():
        raise FileExistsError("Return output appeared during build")
    staging.rename(output_dir)
    return manifest

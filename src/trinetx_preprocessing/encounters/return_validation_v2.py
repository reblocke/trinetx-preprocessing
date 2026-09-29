"""Independent, bounded validation of calendar-day return outcome bundles."""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import duckdb

from ..combined_preprocessing.builder import require_safe_output_location
from ..combined_preprocessing.cohort_source import validate_cohort_source
from ..combined_preprocessing.database import COMBINED_MANIFEST_FILENAME
from .builder import VARIANTS, code_identity, literal, sha256
from .compatibility import file_identity, no_symlinks
from .return_parent_validation import DAY_PRECISION_VALIDATION_VERSION, validate_bundle
from .returns import (
    DAY_RETURN_CONTRACT_VERSION,
    RETURN_PARENT_VALIDATION_DISTINCT_PARTITIONS,
    RETURN_PARENT_VALIDATION_MEMORY_MIB,
    _require_source_capabilities,
)
from .returns_v2 import (
    DATED_POSSIBLE_STATES,
    TEMPORAL_STATES,
    V2_CRITERIA,
    dictionary_entry,
)

TABLES = (
    "episode_source",
    "episodes",
    "diagnosis_evidence",
    "gas_evidence",
    "links",
    "summary",
)


def _assert_equal_multiset(
    db: duckdb.DuckDBPyConnection, expected: str, actual: str, label: str
) -> None:
    different = db.execute(
        "SELECT count(*) FROM (("
        + expected
        + " EXCEPT ALL "
        + actual
        + ") UNION ALL ("
        + actual
        + " EXCEPT ALL "
        + expected
        + "))"
    ).fetchone()[0]
    if different:
        raise ValueError(f"Return v2 {label} multiset differs ({different})")


def _assert_zero(db: duckdb.DuckDBPyConnection, query: str, label: str) -> None:
    count = db.execute(query).fetchone()[0]
    if count:
        raise ValueError(f"Return v2 {label} differs ({count})")


def _check_partition_source(db: duckdb.DuckDBPyConnection) -> None:
    db.execute(
        """
        CREATE OR REPLACE TEMP VIEW expected_episode_source AS
        WITH relevant AS (
          SELECT DISTINCT s.patient_id, s.encounter_id
          FROM preprocessed.source_encounter s
          SEMI JOIN (SELECT DISTINCT patient_id FROM parent_index) p
            USING (patient_id)
          WHERE s.patient_id IS NOT NULL AND s.encounter_id IS NOT NULL
            AND (upper(trim(s.type)) IN
                   ('IMP','INPAT','INPATIENT','EMER','ED','EMERGENCY')
              OR EXISTS (SELECT 1 FROM parent_index i
                         WHERE i.patient_id=s.patient_id
                           AND i.encounter_id=s.encounter_id))
        )
        SELECT sha256(to_json([s.patient_id,s.encounter_id])) AS episode_id,
               s.patient_id, s.encounter_id, s.source_record_id,
               s.source_file, s.source_row_number, s.source_id,
               s.type AS source_type, s.start_datetime, s.end_datetime,
               s.start_timestamp_precision, s.end_timestamp_precision,
               s.start_date_derived_by_TriNetX,
               s.end_date_derived_by_TriNetX
        FROM preprocessed.source_encounter s
        JOIN relevant r USING (patient_id,encounter_id)
        """
    )
    _assert_equal_multiset(
        db,
        "SELECT * FROM expected_episode_source",
        "SELECT * FROM episode_source",
        "episode/source coverage",
    )
    _assert_zero(
        db,
        "SELECT count(*) FROM (SELECT source_record_id FROM episode_source "
        "GROUP BY 1 HAVING source_record_id IS NULL OR count(*)<>1)",
        "source encounter identity",
    )


def _check_partition_episodes(db: duckdb.DuckDBPyConnection) -> None:
    db.execute(
        """
        CREATE OR REPLACE TEMP VIEW reconstructed_episodes AS
        WITH classified AS (
          SELECT *, upper(trim(coalesce(source_type,''))) AS setting
          FROM episode_source
        ), grouped AS (
          SELECT episode_id, min(patient_id) AS patient_id,
                 min(encounter_id) AS encounter_id,
                 count(DISTINCT (patient_id,encounter_id)) AS composite_keys,
                 min(start_datetime) AS episode_start,
                 max(start_datetime) AS latest_possible_start,
                 CASE WHEN bool_or(end_datetime IS NULL) THEN NULL
                      ELSE max(end_datetime) END AS episode_end,
                 CASE WHEN bool_or(start_timestamp_precision IS NULL)
                        THEN NULL
                      WHEN count(DISTINCT start_timestamp_precision)>1
                        THEN 'mixed'
                      ELSE min(start_timestamp_precision) END AS start_precision,
                 CASE WHEN bool_or(end_timestamp_precision IS NULL)
                        THEN NULL
                      WHEN count(DISTINCT end_timestamp_precision)>1
                        THEN 'mixed'
                      ELSE min(end_timestamp_precision) END AS end_precision,
                 bool_or(setting IN ('IMP','INPAT','INPATIENT')) AS has_inpatient,
                 bool_or(setting IN ('EMER','ED','EMERGENCY')) AS has_ed,
                 bool_or(setting IN ('AMB','AMBULATORY','OUTPAT','OUTPATIENT'))
                   AS has_nonacute,
                 bool_or(setting NOT IN
                   ('IMP','INPAT','INPATIENT','EMER','ED','EMERGENCY',
                    'AMB','AMBULATORY','OUTPAT','OUTPATIENT'))
                   AS has_unknown_setting,
                 count(DISTINCT start_datetime) AS distinct_starts,
                 count(DISTINCT end_datetime) AS distinct_ends,
                 count(DISTINCT (start_datetime,end_datetime))
                   FILTER (WHERE setting IN ('EMER','ED','EMERGENCY'))
                   AS ed_intervals,
                 count(DISTINCT (start_datetime,end_datetime))
                   FILTER (WHERE setting IN ('IMP','INPAT','INPATIENT'))
                   AS ip_intervals,
                 min(start_datetime) FILTER
                   (WHERE setting IN ('EMER','ED','EMERGENCY')) AS ed_start,
                 min(end_datetime) FILTER
                   (WHERE setting IN ('EMER','ED','EMERGENCY')) AS ed_end,
                 min(start_datetime) FILTER
                   (WHERE setting IN ('IMP','INPAT','INPATIENT')) AS ip_start,
                 min(end_datetime) FILTER
                   (WHERE setting IN ('IMP','INPAT','INPATIENT')) AS ip_end,
                 bool_or(start_datetime IS NULL) AS has_missing_start,
                 bool_or(end_datetime IS NULL) AS has_missing_end,
                 bool_or(end_datetime<start_datetime) AS has_invalid_order,
                 bool_or(lower(trim(coalesce(start_date_derived_by_TriNetX,'')))
                   IN ('1','true','yes','y')) AS has_derived_start,
                 bool_or(lower(trim(coalesce(end_date_derived_by_TriNetX,'')))
                   IN ('1','true','yes','y')) AS has_derived_end,
                 count(*) AS source_record_count
          FROM classified GROUP BY episode_id
        )
        SELECT * EXCLUDE (composite_keys),
               CASE WHEN has_unknown_setting AND (has_ed OR has_inpatient)
                      THEN 'unsupported_setting_mix'
                    WHEN has_nonacute AND (has_ed OR has_inpatient)
                      THEN 'unsupported_setting_mix'
                    WHEN ed_intervals>1 OR ip_intervals>1
                      THEN 'conflicting_component_intervals'
                    WHEN has_invalid_order THEN 'invalid_episode_order'
                    WHEN has_ed AND has_inpatient AND
                         (ed_start IS NULL OR ip_start IS NULL
                          OR ed_end IS NULL OR ip_end IS NULL)
                      THEN 'incomplete_ed_inpatient_continuation'
                    WHEN has_ed AND has_inpatient AND
                         NOT (ed_start<=ip_start AND ip_start<=ed_end
                              AND ed_end<=ip_end)
                      THEN 'incoherent_ed_inpatient_continuation'
                    WHEN has_missing_start THEN 'missing_start'
                    WHEN has_missing_end THEN 'start_only'
                    ELSE 'coherent' END AS episode_state,
               composite_keys
        FROM grouped
        """
    )
    columns = [
        row[0] for row in db.execute("DESCRIBE SELECT * FROM episodes").fetchall()
    ]
    for column in columns:
        if column not in {
            row[0]
            for row in db.execute(
                "DESCRIBE SELECT * FROM reconstructed_episodes"
            ).fetchall()
        }:
            raise ValueError(
                f"Return v2 episode field missing in reconstruction: {column}"
            )
    _assert_equal_multiset(
        db,
        "SELECT " + ",".join(columns) + " FROM reconstructed_episodes",
        "SELECT " + ",".join(columns) + " FROM episodes",
        "episode derivation",
    )
    _assert_zero(
        db,
        "SELECT count(*) FROM reconstructed_episodes WHERE composite_keys<>1 "
        "OR episode_id IS DISTINCT FROM "
        "sha256(to_json([patient_id,encounter_id]))",
        "episode composite identity",
    )


def _check_partition_pairs(db: duckdb.DuckDBPyConnection) -> None:
    _assert_equal_multiset(
        db,
        "SELECT index_event_id,patient_id,encounter_id FROM parent_index",
        "SELECT index_event_id,patient_id,encounter_id FROM summary",
        "parent/summary keys",
    )
    _assert_zero(
        db,
        "SELECT count(*) FROM (SELECT patient_id,encounter_id FROM summary "
        "GROUP BY 1,2 HAVING count(*)<>1)",
        "duplicate summary keys",
    )
    _assert_equal_multiset(
        db,
        "SELECT s.index_event_id,e.episode_id FROM summary s "
        "JOIN episodes e USING (patient_id) "
        "WHERE s.anchor_state='available' "
        "AND e.episode_id<>s.index_episode_id "
        "AND (e.has_inpatient OR e.has_ed)",
        "SELECT index_event_id,return_episode_id FROM links",
        "complete candidate links",
    )
    _assert_zero(
        db,
        "SELECT count(*) FROM (SELECT index_event_id,return_episode_id "
        "FROM links GROUP BY 1,2 HAVING count(*)<>1)",
        "duplicate links",
    )
    _assert_zero(
        db,
        "SELECT count(*) FROM links l JOIN summary s USING (index_event_id) "
        "JOIN episodes e ON l.return_episode_id=e.episode_id WHERE "
        "l.index_patient_id IS DISTINCT FROM s.patient_id OR "
        "l.patient_id IS DISTINCT FROM e.patient_id OR "
        "l.patient_id IS DISTINCT FROM s.patient_id OR "
        "l.encounter_id IS DISTINCT FROM e.encounter_id OR "
        "l.return_start IS DISTINCT FROM e.episode_start OR "
        "l.return_end IS DISTINCT FROM e.episode_end OR "
        "l.days_after_index_end IS DISTINCT FROM "
        "date_diff('day',s.index_episode_end::DATE,e.episode_start::DATE)",
        "link identity and calendar geometry",
    )


def _check_partition_geometry(db: duckdb.DuckDBPyConnection) -> None:
    index_state = (
        "CASE WHEN e.episode_id IS NULL THEN 'unlinked' "
        "WHEN e.has_unknown_setting THEN 'unknown_index_setting' "
        "WHEN NOT (e.has_inpatient OR e.has_ed) AND e.has_nonacute "
        "THEN 'not_applicable' "
        "WHEN NOT (e.has_inpatient OR e.has_ed) "
        "THEN 'unknown_index_setting' "
        "WHEN e.episode_start IS NULL OR e.episode_end IS NULL "
        "THEN 'missing_episode_end' "
        "WHEN e.has_derived_end THEN 'derived_episode_end' "
        "WHEN e.episode_state<>'coherent' THEN e.episode_state "
        "WHEN e.start_precision IS NULL OR e.start_precision "
        "NOT IN ('date_only','timestamp') THEN 'unknown_start_precision' "
        "WHEN e.end_precision IS NULL OR e.end_precision "
        "NOT IN ('date_only','timestamp') THEN 'unknown_end_precision' "
        "ELSE 'available' END"
    )
    _assert_zero(
        db,
        "SELECT count(*) FROM summary s LEFT JOIN episodes e "
        "ON s.patient_id=e.patient_id AND s.encounter_id=e.encounter_id WHERE "
        f"s.anchor_state IS DISTINCT FROM ({index_state}) OR "
        "s.inpatient_event_term IS DISTINCT FROM "
        "(CASE WHEN e.has_inpatient THEN 'readmission' "
        "WHEN e.has_ed THEN 'admission' "
        "WHEN s.anchor_state='not_applicable' THEN 'not_applicable' "
        "ELSE 'unavailable' END) OR "
        "s.index_episode_id IS DISTINCT FROM e.episode_id OR "
        "s.index_episode_start IS DISTINCT FROM e.episode_start OR "
        "s.index_episode_end IS DISTINCT FROM e.episode_end OR "
        "s.index_end_precision IS DISTINCT FROM e.end_precision OR "
        "s.index_inpatient IS DISTINCT FROM e.has_inpatient OR "
        "s.index_ed IS DISTINCT FROM e.has_ed",
        "index anchor derivation",
    )
    temporal = (
        "CASE WHEN e.episode_start IS NULL THEN 'missing_return_start' "
        "WHEN e.has_derived_start THEN 'derived_return_start' "
        "WHEN e.episode_state NOT IN ('coherent','start_only') "
        "THEN e.episode_state "
        "WHEN e.start_precision IS NULL OR e.start_precision "
        "NOT IN ('date_only','timestamp') THEN 'unknown_return_precision' "
        "WHEN e.episode_start::DATE=s.index_episode_end::DATE "
        "THEN 'same_day_uncertain' "
        "WHEN e.episode_start::DATE<s.index_episode_end::DATE "
        "THEN 'overlap_or_prior' "
        "WHEN e.episode_start::DATE>s.index_episode_end::DATE "
        "+ INTERVAL 365 DAY THEN 'outside_horizon' "
        "ELSE 'confirmed' END"
    )
    _assert_zero(
        db,
        "SELECT count(*) FROM links l JOIN summary s USING (index_event_id) "
        "JOIN episodes e ON e.episode_id=l.return_episode_id WHERE "
        "s.anchor_state<>'available' OR "
        f"l.temporal_state IS DISTINCT FROM ({temporal}) OR "
        "l.index_encounter_id IS DISTINCT FROM s.encounter_id OR "
        "l.index_episode_id IS DISTINCT FROM s.index_episode_id OR "
        "l.index_episode_end IS DISTINCT FROM s.index_episode_end OR "
        "l.index_end_precision IS DISTINCT FROM s.index_end_precision OR "
        "l.index_inpatient IS DISTINCT FROM s.index_inpatient OR "
        "l.index_ed IS DISTINCT FROM s.index_ed OR "
        "l.return_start_precision IS DISTINCT FROM e.start_precision OR "
        "l.return_end_precision IS DISTINCT FROM e.end_precision OR "
        "l.return_episode_state IS DISTINCT FROM e.episode_state OR "
        "l.latest_possible_start IS DISTINCT FROM e.latest_possible_start OR "
        "l.return_has_missing_start IS DISTINCT FROM e.has_missing_start OR "
        "l.has_inpatient IS DISTINCT FROM e.has_inpatient OR "
        "l.has_ed IS DISTINCT FROM e.has_ed OR "
        "l.source_record_count IS DISTINCT FROM e.source_record_count OR "
        "l.evidenced_ed_inpatient IS DISTINCT FROM "
        "(e.has_ed AND e.has_inpatient) OR "
        "l.ed_only IS DISTINCT FROM (e.has_ed AND NOT e.has_inpatient) OR "
        "l.admission_after_ed_index IS DISTINCT FROM "
        "(e.has_inpatient AND s.index_ed AND NOT s.index_inpatient) OR "
        "l.readmission_after_inpatient IS DISTINCT FROM "
        "(e.has_inpatient AND s.index_inpatient)",
        "return timing and category derivation",
    )


def _check_partition_evidence(db: duckdb.DuckDBPyConnection) -> None:
    db.execute(
        "CREATE OR REPLACE TEMP VIEW return_keys AS SELECT DISTINCT "
        "patient_id,encounter_id,return_episode_id AS episode_id "
        "FROM links"
    )
    _assert_equal_multiset(
        db,
        "SELECT r.episode_id,d.source_record_id FROM "
        "preprocessed.source_diagnosis d JOIN return_keys r "
        "USING (patient_id,encounter_id)",
        "SELECT episode_id,source_record_id FROM diagnosis_evidence",
        "diagnosis source coverage",
    )
    _assert_equal_multiset(
        db,
        "SELECT r.episode_id,l.source_record_id,m.element_id FROM "
        "preprocessed.source_lab_measurement l JOIN return_keys r "
        "USING (patient_id,encounter_id) "
        "JOIN preprocessed.element_membership m "
        "ON m.source_record_id=l.source_record_id WHERE m.include "
        "AND m.element_id IN ('source.arterial_pco2',"
        "'source.venous_pco2','source.unspecified_blood_pco2')",
        "SELECT episode_id,source_record_id,element_id FROM gas_evidence",
        "gas source and catalog coverage",
    )
    _assert_equal_multiset(
        db,
        "SELECT r.episode_id,d.patient_id,d.encounter_id,d.source_record_id,"
        "d.source_file,d.source_row_number,d.source_id,d.code_system,d.code,"
        "d.event_datetime,d.timestamp_precision "
        "FROM preprocessed.source_diagnosis d "
        "JOIN return_keys r USING (patient_id,encounter_id)",
        "SELECT episode_id,patient_id,encounter_id,source_record_id,"
        "source_file,source_row_number,source_id,code_system,code,"
        "event_datetime,timestamp_precision FROM diagnosis_evidence",
        "diagnosis raw fields",
    )
    _assert_equal_multiset(
        db,
        "SELECT r.episode_id,l.patient_id,l.encounter_id,"
        "l.source_record_id,l.source_file,l.source_row_number,l.source_id,"
        "l.code_system,l.code,l.event_datetime,l.timestamp_precision,"
        "l.specimen,l.specimen_id,l.panel_id,l.numeric_value,"
        "l.units_of_measure,m.element_id FROM "
        "preprocessed.source_lab_measurement l "
        "JOIN return_keys r USING (patient_id,encounter_id) "
        "JOIN preprocessed.element_membership m "
        "ON m.source_record_id=l.source_record_id WHERE m.include "
        "AND m.element_id IN ('source.arterial_pco2',"
        "'source.venous_pco2','source.unspecified_blood_pco2')",
        "SELECT episode_id,patient_id,encounter_id,source_record_id,"
        "source_file,source_row_number,source_id,code_system,code,"
        "event_datetime,timestamp_precision,specimen,specimen_id,panel_id,"
        "raw_value,raw_unit,element_id FROM gas_evidence",
        "gas raw fields",
    )
    _assert_zero(
        db,
        "SELECT count(*) FROM gas_evidence WHERE gas_kind IS DISTINCT FROM "
        "CASE WHEN element_id='source.arterial_pco2' THEN 'abg' "
        "WHEN element_id='source.venous_pco2' THEN 'vbg' "
        "ELSE 'unspecified' END",
        "gas catalog specimen",
    )
    _assert_zero(
        db,
        "SELECT count(*) FROM gas_evidence WHERE "
        "value_mmhg IS DISTINCT FROM "
        "CASE WHEN lower(trim(coalesce(raw_unit,''))) "
        "IN ('mmhg','mm hg','mm_hg','mm[hg]','torr') THEN raw_value "
        "WHEN lower(trim(coalesce(raw_unit,'')))='kpa' "
        "THEN raw_value*7.5006168270417 ELSE NULL END",
        "gas unit normalization",
    )
    _assert_zero(
        db,
        "SELECT count(*) FROM diagnosis_evidence d JOIN episodes e "
        "USING (episode_id) WHERE d.rejection_reason IS DISTINCT FROM "
        "(CASE WHEN e.episode_start IS NULL THEN 'missing_episode_start' "
        "WHEN e.episode_end IS NULL THEN 'missing_episode_end' "
        "WHEN d.event_datetime IS NULL THEN 'missing_date' "
        "WHEN d.event_datetime::DATE<e.episode_start::DATE "
        "OR d.event_datetime::DATE>e.episode_end::DATE "
        "THEN 'outside_episode' "
        "WHEN upper(regexp_replace(coalesce(d.code_system,''),"
        "'[^A-Za-z0-9]','','g'))<>'ICD10CM' "
        "THEN 'other_code_system' "
        "WHEN upper(trim(coalesce(d.code,''))) NOT IN "
        "('J96.02','J96.12','J96.22','J96.92','E66.2') "
        "THEN 'other_code' "
        "WHEN d.timestamp_precision IS NULL OR "
        "d.timestamp_precision NOT IN ('date_only','timestamp') "
        "THEN 'unknown_event_precision' "
        "WHEN e.episode_state<>'coherent' "
        "THEN 'incoherent_return_episode' ELSE NULL END)",
        "diagnosis eligibility",
    )
    _assert_zero(
        db,
        "WITH item AS (SELECT g.*,e.episode_start,e.episode_end,"
        "e.episode_state,count(DISTINCT g.gas_kind) OVER "
        "(PARTITION BY g.source_record_id) AS specimen_catalogs "
        "FROM gas_evidence g JOIN episodes e USING (episode_id)) "
        "SELECT count(*) FROM item WHERE rejection_reason IS DISTINCT FROM "
        "(CASE WHEN episode_start IS NULL THEN 'missing_episode_start' "
        "WHEN episode_end IS NULL THEN 'missing_episode_end' "
        "WHEN event_datetime IS NULL THEN 'missing_date' "
        "WHEN event_datetime::DATE<episode_start::DATE "
        "OR event_datetime::DATE>episode_end::DATE "
        "THEN 'outside_episode' "
        "WHEN specimen_catalogs>1 THEN 'conflicting_catalog_specimen' "
        "WHEN gas_kind='unspecified' THEN 'unspecified_specimen' "
        "WHEN (gas_kind='abg' AND lower(coalesce(specimen,'')) LIKE '%ven%') "
        "OR (gas_kind='vbg' AND lower(coalesce(specimen,'')) LIKE '%art%') "
        "THEN 'contradictory_specimen' "
        "WHEN raw_value IS NULL OR NOT isfinite(raw_value) OR raw_value<=0 "
        "THEN 'invalid_value' "
        "WHEN value_mmhg IS NULL THEN 'unsupported_unit' "
        "WHEN NOT isfinite(value_mmhg) THEN 'invalid_converted_value' "
        "WHEN timestamp_precision IS NULL OR "
        "timestamp_precision NOT IN ('date_only','timestamp') "
        "THEN 'unknown_event_precision' "
        "WHEN episode_state<>'coherent' "
        "THEN 'incoherent_return_episode' ELSE NULL END)",
        "gas rejection reasons",
    )


def _check_partition_phenotypes(db: duckdb.DuckDBPyConnection) -> None:
    counts = []
    projected = []
    for specimen in ("abg", "vbg"):
        valid = f"gas_kind='{specimen}' AND rejection_reason IS NULL"
        counts.append(f"count(*) FILTER (WHERE {valid}) AS {specimen}_tested")
        projected.append(f"coalesce(g.{specimen}_tested,0)>0 AS {specimen}_tested")
        for suffix, comparison, threshold in (
            ("gt45", ">", 45),
            ("gt50", ">", 50),
            ("ge45", ">=", 45),
            ("ge50", ">=", 50),
        ):
            name = f"{specimen}_{suffix}"
            counts.append(
                f"count(*) FILTER (WHERE {valid} "
                f"AND value_mmhg{comparison}{threshold}) AS {name}"
            )
            projected.append(
                f"CASE WHEN coalesce(g.{specimen}_tested,0)>0 "
                f"THEN coalesce(g.{name},0)>0 ELSE NULL END AS {name}"
            )
    db.execute(
        "CREATE OR REPLACE TEMP VIEW reconstructed_phenotypes AS "
        "WITH gas_counts AS (SELECT episode_id, "
        + ", ".join(counts)
        + " FROM gas_evidence GROUP BY episode_id), "
        "diagnosis_counts AS (SELECT episode_id, "
        "count(*) FILTER (WHERE rejection_reason IS NULL)>0 AS positive "
        "FROM diagnosis_evidence GROUP BY episode_id) "
        "SELECT r.episode_id,coalesce(d.positive,false) "
        "AS icd_hypercapnia, "
        + ", ".join(projected)
        + " FROM (SELECT DISTINCT return_episode_id AS episode_id FROM links) r "
        "LEFT JOIN gas_counts g USING (episode_id) "
        "LEFT JOIN diagnosis_counts d USING (episode_id)"
    )
    direct = (
        "icd_hypercapnia",
        "abg_tested",
        "vbg_tested",
        *(
            f"{specimen}_{suffix}"
            for specimen in ("abg", "vbg")
            for suffix in ("gt45", "gt50", "ge45", "ge50")
        ),
    )
    mismatches = [f"l.{name} IS DISTINCT FROM p.{name}" for name in direct]
    for name, left, right in (
        ("any_gas_gt45", "abg_gt45", "vbg_gt45"),
        ("any_gas_gt50", "abg_gt50", "vbg_gt50"),
        ("any_gas_ge45", "abg_ge45", "vbg_ge45"),
        ("any_gas_ge50", "abg_ge50", "vbg_ge50"),
        ("gas_abg_gt45_or_vbg_gt50", "abg_gt45", "vbg_gt50"),
        ("gas_abg_ge45_or_vbg_ge50", "abg_ge45", "vbg_ge50"),
    ):
        result = (
            f"CASE WHEN p.{left} IS TRUE OR p.{right} IS TRUE THEN true "
            "WHEN p.abg_tested OR p.vbg_tested THEN false ELSE NULL END"
        )
        mismatches.append(f"l.{name} IS DISTINCT FROM ({result})")
    for name, abg, vbg in (
        ("icd_or_gas_strict", "abg_gt45", "vbg_gt50"),
        ("icd_or_gas_inclusive", "abg_ge45", "vbg_ge50"),
        ("any_hypercapnia", "abg_ge45", "vbg_ge50"),
    ):
        result = (
            f"CASE WHEN p.icd_hypercapnia OR p.{abg} IS TRUE "
            f"OR p.{vbg} IS TRUE THEN true "
            "WHEN p.abg_tested OR p.vbg_tested THEN false ELSE NULL END"
        )
        mismatches.append(f"l.{name} IS DISTINCT FROM ({result})")
    _assert_zero(
        db,
        "SELECT count(*) FROM links l JOIN reconstructed_phenotypes p "
        "ON l.return_episode_id=p.episode_id WHERE " + " OR ".join(mismatches),
        "episode/link phenotype truth tables",
    )


def _check_summary_states(db: duckdb.DuckDBPyConnection) -> None:
    aggregate = ", ".join(
        f"sum(CASE WHEN temporal_state='{state}' THEN 1 ELSE 0 END) AS {state}_count"
        for state in TEMPORAL_STATES
    )
    db.execute(
        "CREATE OR REPLACE TEMP VIEW expected_states AS "
        f"SELECT index_event_id,{aggregate} FROM links GROUP BY index_event_id"
    )
    mismatches = [
        f"s.{state}_count IS DISTINCT FROM coalesce(t.{state}_count,0)"
        for state in TEMPORAL_STATES
    ]
    mismatches.extend(
        (
            "s.undated_return_count IS DISTINCT FROM "
            "coalesce(t.missing_return_start_count,0)",
            "s.invalid_return_episode_order_count IS DISTINCT FROM "
            "coalesce(t.invalid_episode_order_count,0)",
        )
    )
    _assert_zero(
        db,
        "SELECT count(*) FROM summary s LEFT JOIN expected_states t "
        "USING (index_event_id) WHERE " + " OR ".join(mismatches),
        "temporal-state totals",
    )
    for kind, predicate in (
        ("inpatient", "has_inpatient"),
        ("ed_only", "ed_only"),
        ("any_ed", "has_ed"),
        ("acute_union", "(has_ed OR has_inpatient)"),
    ):
        db.execute(
            "CREATE TEMP TABLE expected_category_states AS "
            "SELECT index_event_id, "
            + ", ".join(
                f"sum(CASE WHEN temporal_state='{state}' THEN 1 ELSE 0 END) "
                f"AS {state}_n"
                for state in TEMPORAL_STATES
            )
            + f" FROM links WHERE {predicate} GROUP BY index_event_id"
        )
        differences = [
            f"s.outcome_{kind}_{state}_candidate_count IS DISTINCT FROM "
            f"coalesce(t.{state}_n,0)"
            for state in TEMPORAL_STATES
        ]
        try:
            _assert_zero(
                db,
                "SELECT count(*) FROM summary s LEFT JOIN "
                "expected_category_states t USING (index_event_id) WHERE "
                + " OR ".join(differences),
                f"{kind} temporal-state counts",
            )
        finally:
            db.execute("DROP TABLE expected_category_states")
    _assert_zero(
        db,
        "WITH death AS (SELECT patient_id,CASE WHEN "
        "count(DISTINCT month_year_death)=1 THEN min(month_year_death) "
        "END AS month_year_death FROM preprocessed.source_patient "
        "GROUP BY patient_id), observed AS (SELECT patient_id, "
        "max(last_event_datetime) AS last_observed_event_datetime "
        "FROM preprocessed.patient_observability GROUP BY patient_id) "
        "SELECT count(*) FROM summary s LEFT JOIN death d USING (patient_id) "
        "LEFT JOIN observed o USING (patient_id) WHERE "
        "s.month_year_death IS DISTINCT FROM d.month_year_death OR "
        "s.last_observed_event_datetime IS DISTINCT FROM "
        "o.last_observed_event_datetime",
        "death and observability source fields",
    )
    for days in (30, 90, 365):
        _assert_zero(
            db,
            "SELECT count(*) FROM summary WHERE "
            f"outcome_followup_observation_{days}d IS DISTINCT FROM "
            "(CASE WHEN anchor_state<>'available' THEN 'index_unavailable' "
            "WHEN last_observed_event_datetime IS NULL THEN 'unobserved' "
            "WHEN last_observed_event_datetime::DATE>= "
            f"index_episode_end::DATE+INTERVAL {days} DAY "
            "THEN 'observation_at_or_after_horizon' "
            "ELSE 'last_observation_before_horizon' END)",
            f"{days}-day observed follow-up state",
        )


def _check_summary_metric(
    db: duckdb.DuckDBPyConnection, *, kind: str, days: int
) -> None:
    categories = {
        "inpatient": "has_inpatient",
        "ed_only": "ed_only",
        "any_ed": "has_ed",
        "acute_union": "(has_ed OR has_inpatient)",
    }
    confirmed = (
        "temporal_state='confirmed' AND "
        f"days_after_index_end>=1 AND days_after_index_end<={days}"
    )
    possible = (
        "temporal_state NOT IN ('confirmed','same_day_uncertain',"
        "'overlap_or_prior','outside_horizon') AND "
        "(return_start IS NULL OR temporal_state='derived_return_start' OR "
        "(return_has_missing_start AND return_start::DATE "
        ">=index_episode_end::DATE+INTERVAL 1 DAY) OR "
        "(return_start::DATE<=index_episode_end::DATE "
        f"+ INTERVAL {days} DAY AND latest_possible_start::DATE "
        ">=index_episode_end::DATE+INTERVAL 1 DAY))"
    )
    aggregates = [
        "index_event_id",
        f"sum(CASE WHEN {possible} THEN 1 ELSE 0 END) AS possible_n",
        f"sum(CASE WHEN {confirmed} THEN 1 ELSE 0 END) AS confirmed_n",
    ]
    aggregates.extend(
        f"sum(CASE WHEN {possible} AND temporal_state='{state}' "
        f"THEN 1 ELSE 0 END) AS {state}_possible_n"
        for state in DATED_POSSIBLE_STATES
    )
    for criterion in V2_CRITERIA:
        qualifying = (
            confirmed
            if criterion == "all_cause"
            else (f"{confirmed} AND {criterion} IS TRUE")
        )
        aggregates.extend(
            (
                f"sum(CASE WHEN {qualifying} THEN 1 ELSE 0 END) AS {criterion}_n",
                f"min(CASE WHEN {qualifying} THEN return_start::DATE "
                f"ELSE NULL END) AS {criterion}_first",
            )
        )
        if criterion != "all_cause":
            unresolved = (
                "return_episode_state<>'coherent'"
                if criterion == "icd_hypercapnia"
                else f"{criterion} IS NULL"
            )
            aggregates.append(
                f"sum(CASE WHEN {confirmed} AND {unresolved} "
                f"THEN 1 ELSE 0 END) AS {criterion}_unknown"
            )
        if criterion not in {"all_cause", "icd_hypercapnia"}:
            aggregates.extend(
                (
                    f"sum(CASE WHEN {confirmed} AND {criterion} IS NOT NULL "
                    f"THEN 1 ELSE 0 END) AS {criterion}_tested",
                    f"sum(CASE WHEN {confirmed} AND "
                    "return_episode_state<>'coherent' "
                    f"THEN 1 ELSE 0 END) AS {criterion}_unavailable",
                )
            )
    db.execute(
        "CREATE TEMP TABLE expected_metric AS SELECT "
        + ", ".join(aggregates)
        + " FROM links WHERE "
        + categories[kind]
        + " GROUP BY index_event_id"
    )
    potential_n = "coalesce(e.possible_n,0)"
    confirmed_n = "coalesce(e.confirmed_n,0)"
    mismatches = [
        f"s.outcome_{kind}_possible_{days}d_count IS DISTINCT FROM "
        f"(CASE WHEN s.anchor_state='available' THEN {potential_n} "
        "ELSE NULL END)"
    ]
    mismatches.extend(
        f"s.outcome_{kind}_{state}_possible_{days}d_count "
        "IS DISTINCT FROM (CASE WHEN s.anchor_state='available' THEN "
        f"coalesce(e.{state}_possible_n,0) ELSE NULL END)"
        for state in DATED_POSSIBLE_STATES
    )
    for criterion in V2_CRITERIA:
        stem = f"outcome_{kind}_{criterion}_{days}d"
        n = f"coalesce(e.{criterion}_n,0)"
        first = f"e.{criterion}_first"
        mismatches.extend(
            (
                f"s.{stem}_count IS DISTINCT FROM "
                f"(CASE WHEN s.anchor_state='available' THEN {n} "
                "ELSE NULL END)",
                f"s.{stem}_first_date IS DISTINCT FROM "
                f"(CASE WHEN s.anchor_state='available' THEN {first} "
                "ELSE NULL END)",
                f"s.{stem}_first_timestamp IS NOT NULL",
                f"s.{stem}_days_to_first IS DISTINCT FROM "
                "(CASE WHEN s.anchor_state='available' THEN "
                f"date_diff('day',s.index_episode_end::DATE,{first}) "
                "ELSE NULL END)",
            )
        )
        if criterion == "all_cause":
            flag = (
                f"CASE WHEN {n}>0 THEN true WHEN {potential_n}>0 "
                "THEN NULL ELSE false END"
            )
        elif criterion == "icd_hypercapnia":
            unknown = f"coalesce(e.{criterion}_unknown,0)"
            flag = (
                f"CASE WHEN {n}>0 THEN true "
                f"WHEN {potential_n}>0 OR {unknown}>0 "
                "THEN NULL ELSE false END"
            )
        else:
            unknown = f"coalesce(e.{criterion}_unknown,0)"
            tested = f"coalesce(e.{criterion}_tested,0)"
            unavailable = f"coalesce(e.{criterion}_unavailable,0)"
            flag = (
                f"CASE WHEN {n}>0 THEN true "
                f"WHEN {potential_n}>0 OR {unknown}>0 OR {confirmed_n}=0 "
                "THEN NULL ELSE false END"
            )
            mismatches.extend(
                (
                    f"s.{stem}_tested_count IS DISTINCT FROM "
                    f"(CASE WHEN s.anchor_state='available' THEN {tested} "
                    "ELSE NULL END)",
                    f"s.{stem}_untested_count IS DISTINCT FROM "
                    f"(CASE WHEN s.anchor_state='available' THEN {unknown} "
                    "ELSE NULL END)",
                    f"s.{stem}_phenotype_unavailable_count IS DISTINCT FROM "
                    f"(CASE WHEN s.anchor_state='available' THEN {unavailable} "
                    "ELSE NULL END)",
                )
            )
        mismatches.append(
            f"s.{stem}_flag IS DISTINCT FROM "
            "(CASE WHEN s.anchor_state='available' THEN "
            f"{flag} ELSE NULL END)"
        )
    try:
        _assert_zero(
            db,
            "SELECT count(*) FROM summary s LEFT JOIN expected_metric e "
            "USING (index_event_id) WHERE " + " OR ".join(mismatches),
            f"{kind} {days}-day summary metrics",
        )
    finally:
        db.execute("DROP TABLE expected_metric")


def validate_returns_v2(
    *, bundle: Path, parent_bundle: Path, database: Path, work_dir: Path
) -> dict:
    """Validate every part without trusting its manifest or summary formulas."""
    bundle, parent_bundle = no_symlinks(bundle), no_symlinks(parent_bundle)
    database, work_dir = no_symlinks(database), no_symlinks(work_dir)
    require_safe_output_location(work_dir, artifact_label="return validation work")
    if any(
        work_dir.is_relative_to(path) or path.is_relative_to(work_dir)
        for path in (bundle, parent_bundle, database.parent)
    ):
        raise ValueError("Return validation work overlaps an input")
    work_dir.mkdir(mode=0o700, parents=True, exist_ok=False)
    manifest_path = bundle / "manifest.json"
    manifest_hash = sha256(manifest_path)
    manifest = json.loads(manifest_path.read_text())
    partitions = manifest.get("partitions")
    if (
        manifest.get("kind") != "return_outcomes"
        or manifest.get("status") != "complete"
        or manifest.get("schema_version") != DAY_RETURN_CONTRACT_VERSION
        or manifest.get("return_contract_version") != DAY_RETURN_CONTRACT_VERSION
        or manifest.get("variants") != list(VARIANTS)
        or manifest.get("horizons_days") != [30, 90, 365]
        or type(partitions) is not int
        or not 1 <= partitions <= 1024
        or manifest.get("code_sha256") != code_identity()
        or manifest.get("parent_manifest_sha256")
        != sha256(parent_bundle / "manifest.json")
        or manifest.get("source_manifest_sha256")
        != sha256(database.parent / COMBINED_MANIFEST_FILENAME)
        or manifest.get("source_file_identity") != list(file_identity(database))
    ):
        raise ValueError("Return v2 manifest or input identity differs")
    parent_manifest = json.loads((parent_bundle / "manifest.json").read_text())
    if (
        parent_manifest.get("source_manifest_sha256")
        != manifest["source_manifest_sha256"]
    ):
        raise ValueError("Parent and canonical source identities differ")
    parent = validate_bundle(
        bundle=parent_bundle,
        work_dir=work_dir / f"parent-validation-{uuid.uuid4().hex}",
        memory_limit_mib=RETURN_PARENT_VALIDATION_MEMORY_MIB,
        distinct_count_partitions=RETURN_PARENT_VALIDATION_DISTINCT_PARTITIONS,
        validation_contract_version=DAY_PRECISION_VALIDATION_VERSION,
    )
    if not parent["pass"]:
        raise ValueError("Parent encounter bundle failed v2 validation")
    source = validate_cohort_source(database)
    if not source.valid or source.metadata is None:
        raise ValueError("Canonical source failed validation")
    _require_source_capabilities(database)
    expected_names = {"data_dictionary.json", "progress.json"}
    expected_names.update(
        f"{variant.lower()}_{bucket:04d}_{table}.parquet"
        for variant in VARIANTS
        for bucket in range(partitions)
        for table in TABLES
    )
    if set(manifest.get("outputs", {})) != expected_names:
        raise ValueError("Return v2 artifact inventory differs")
    if {
        p.name for p in bundle.iterdir() if p.is_file() and not p.name.startswith("._")
    } != expected_names | {"manifest.json"}:
        raise ValueError("Return v2 directory inventory differs")
    for name, info in manifest["outputs"].items():
        path = no_symlinks(bundle / name)
        if path.stat().st_size != info.get("bytes") or sha256(path) != info.get(
            "sha256"
        ):
            raise ValueError(f"Return v2 artifact bytes differ: {name}")
    progress = json.loads((bundle / "progress.json").read_text())
    identity_names = (
        "return_contract_version",
        "parent_manifest_sha256",
        "source_manifest_sha256",
        "source_file_identity",
        "code_sha256",
        "partitions",
    )
    if progress.get("identity") != {name: manifest[name] for name in identity_names}:
        raise ValueError("Return v2 progress identity differs")
    if set(progress.get("completed", {})) != {
        f"{variant}:{bucket}" for variant in VARIANTS for bucket in range(partitions)
    }:
        raise ValueError("Return v2 completed parts differ")
    for variant in VARIANTS:
        for bucket in range(partitions):
            parts = progress["completed"][f"{variant}:{bucket}"]
            if set(parts) != set(TABLES) or any(
                parts[name]
                != manifest["outputs"][f"{variant.lower()}_{bucket:04d}_{name}.parquet"]
                for name in TABLES
            ):
                raise ValueError("Return v2 part receipt differs")
    dictionary = json.loads((bundle / "data_dictionary.json").read_text())
    totals = {}
    with duckdb.connect() as db:
        db.execute("SET threads=1")
        db.execute("SET memory_limit='4096MiB'")
        spill = work_dir / "spill"
        spill.mkdir(mode=0o700)
        db.execute("SET temp_directory=?", [str(spill)])
        db.execute(f"ATTACH {literal(database)} AS preprocessed (READ_ONLY)")
        for variant in VARIANTS:
            totals[variant] = 0
            parent_path = (
                parent_bundle / f"encounter_features_{variant.lower()}.parquet"
            )
            for bucket in range(partitions):
                for table in TABLES:
                    path = bundle / f"{variant.lower()}_{bucket:04d}_{table}.parquet"
                    db.execute(
                        f"CREATE OR REPLACE TEMP VIEW {table} AS "
                        f"SELECT * FROM read_parquet({literal(path)})"
                    )
                    actual = [
                        dictionary_entry(table, column, kind)
                        for column, kind, *_ in db.execute(
                            f"DESCRIBE SELECT * FROM {table}"
                        ).fetchall()
                    ]
                    if dictionary.get(table) != actual:
                        raise ValueError(f"Return v2 {table} dictionary differs")
                db.execute(
                    "CREATE OR REPLACE TEMP VIEW parent_index AS "
                    "SELECT patient_id::VARCHAR AS patient_id, "
                    "encounter_id::VARCHAR AS encounter_id, "
                    "pat_enc_hash::VARCHAR AS index_event_id FROM "
                    f"read_parquet({literal(parent_path)}) "
                    f"WHERE hash(patient_id::VARCHAR)%{partitions}={bucket}"
                )
                _check_partition_source(db)
                _check_partition_episodes(db)
                _check_partition_pairs(db)
                _check_partition_geometry(db)
                _check_partition_evidence(db)
                _check_partition_phenotypes(db)
                _check_summary_states(db)
                for days in (30, 90, 365):
                    for kind in ("inpatient", "ed_only", "any_ed", "acute_union"):
                        _check_summary_metric(db, kind=kind, days=days)
                totals[variant] += db.execute(
                    "SELECT count(*) FROM summary"
                ).fetchone()[0]
                for table in (
                    "reconstructed_phenotypes",
                    "expected_states",
                    "reconstructed_episodes",
                    "expected_episode_source",
                    "return_keys",
                    "parent_index",
                    *TABLES,
                ):
                    db.execute(f"DROP VIEW {table}")
    if (
        sha256(manifest_path) != manifest_hash
        or code_identity() != manifest["code_sha256"]
    ):
        raise ValueError("Return v2 manifest or code changed during validation")
    return {
        "pass": True,
        "validation_contract_version": DAY_RETURN_CONTRACT_VERSION,
        "bundle_manifest_sha256": manifest_hash,
        "parent_manifest_sha256": manifest["parent_manifest_sha256"],
        "source_manifest_sha256": manifest["source_manifest_sha256"],
        "variants": totals,
    }

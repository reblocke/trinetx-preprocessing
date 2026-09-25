"""Calendar-day return outcomes, isolated from the historical v1 implementation."""

from __future__ import annotations

import re
from pathlib import Path

import duckdb

from .returns import HORIZONS, _create_evidence, _write_table, sha256

ACUTE_TYPES = "('IMP','INPAT','INPATIENT','EMER','ED','EMERGENCY')"
INPATIENT_TYPES = "('IMP','INPAT','INPATIENT')"
ED_TYPES = "('EMER','ED','EMERGENCY')"
NONACUTE_TYPES = "('AMB','AMBULATORY','OUTPAT','OUTPATIENT')"
TRUE_VALUES = "('1','true','yes','y')"
V2_CRITERIA = (
    "all_cause",
    "icd_hypercapnia",
    *(
        f"{specimen}_{suffix}"
        for specimen in ("abg", "vbg")
        for suffix in ("gt45", "gt50", "ge45", "ge50")
    ),
    *(f"any_gas_{suffix}" for suffix in ("gt45", "gt50", "ge45", "ge50")),
    "gas_abg_gt45_or_vbg_gt50",
    "gas_abg_ge45_or_vbg_ge50",
    "icd_or_gas_strict",
    "icd_or_gas_inclusive",
    "any_hypercapnia",
)
TEMPORAL_STATES = (
    "confirmed",
    "same_day_uncertain",
    "overlap_or_prior",
    "outside_horizon",
    "missing_return_start",
    "derived_return_start",
    "unknown_return_precision",
    "unsupported_setting_mix",
    "conflicting_component_intervals",
    "invalid_episode_order",
    "incomplete_ed_inpatient_continuation",
    "incoherent_ed_inpatient_continuation",
    "missing_start",
)
DATED_POSSIBLE_STATES = (
    "unknown_return_precision",
    "unsupported_setting_mix",
    "conflicting_component_intervals",
    "invalid_episode_order",
    "incomplete_ed_inpatient_continuation",
    "incoherent_ed_inpatient_continuation",
)


def dictionary_entry(
    table: str, column: str, duckdb_type: str
) -> dict[str, str | None]:
    """Describe every v2 field, including its unit and unavailable state."""
    role = "outcome" if table in {"links", "summary"} else "evidence"
    definition = f"Retained {table} field {column} under the v2 return contract"
    unit = None
    null_semantics = "Source missingness or not applicable; never imputed"
    applicability = (
        "Every original index key in its own parent variant"
        if table == "summary"
        else "Observed source episode or candidate link in this patient partition"
    )
    if column in {"patient_id", "encounter_id", "index_event_id", "episode_id"}:
        role = "identity"
        definition = "Original composite-key member or deterministic record identity"
    elif column in {"episode_start", "episode_end", "return_start", "return_end"}:
        definition = "Observed source episode boundary; parsed time is provenance"
        unit = "calendar date with retained source timestamp"
    elif column in {
        "episode_state",
        "return_episode_state",
        "anchor_state",
        "temporal_state",
    }:
        definition = "Explicit episode, index-anchor, or return timing disposition"
        null_semantics = "NULL is invalid for a published disposition"
    elif column in {"raw_value", "value_mmhg"}:
        definition = (
            "Source numeric gas value"
            if column == "raw_value"
            else "Source gas converted using the accepted unit factor"
        )
        unit = "source unit" if column == "raw_value" else "mmHg"
    elif column == "rejection_reason":
        definition = "Reason clinical evidence cannot qualify the return phenotype"
        null_semantics = "NULL means the row met the evidence eligibility checks"
    elif column == "days_after_index_end":
        definition = "Integer calendar days from observed index end to return start"
        unit = "calendar days"
    elif column.startswith("outcome_followup_observation_"):
        definition = "Last observed event relative to this calendar-day horizon"
        null_semantics = "NULL only if the published row is malformed"
        applicability = "Every original index key; unavailable anchors are labeled"
    elif column.endswith("_first_timestamp"):
        definition = "Reserved compatibility field; no measured within-day time in v2"
        unit = "timestamp"
        null_semantics = "Always NULL under the calendar-day v2 contract"
    elif column.endswith("_first_date"):
        definition = "Earliest independently qualifying confirmed return start date"
        unit = "calendar date"
        null_semantics = "NULL if no qualifying confirmed event or index unavailable"
    elif column.endswith("_days_to_first"):
        definition = "Calendar days from index end to the first qualifying return"
        unit = "calendar days"
        null_semantics = "NULL if no qualifying confirmed event or index unavailable"
    elif column.endswith("_flag"):
        definition = "Three-state observed return or phenotype horizon result"
        applicability = "Inpatient or ED-only index with an available anchor"
        null_semantics = (
            "NULL means index unavailable, possible event unresolved, or "
            "criterion unevaluable; false is observed-set negative"
        )
    elif column.endswith("_count"):
        unit = "episodes"
        if column.startswith("outcome_") and not column.endswith("_candidate_count"):
            applicability = "Inpatient or ED-only index with an available anchor"
        if "possible_" in column:
            definition = "Unresolved candidate episodes that could enter the horizon"
        elif "untested" in column:
            definition = "Confirmed returns without an evaluable criterion result"
        elif "tested" in column:
            definition = "Confirmed returns with an evaluable criterion result"
        elif "phenotype_unavailable" in column:
            definition = (
                "Confirmed returns lacking a coherent observed evidence interval"
            )
        elif any(state in column for state in TEMPORAL_STATES):
            definition = "Candidate return episodes with the named temporal state"
        else:
            definition = "Confirmed observed qualifying return episodes"
        null_semantics = (
            "Nonnegative candidate count; zero if the index has no candidate links"
            if column.endswith("_candidate_count")
            else (
                "NULL for unavailable or not-applicable index outcomes; "
                "zero means no confirmed observed event"
                if column.startswith("outcome_")
                else "Nonnegative observed count"
            )
        )
    elif re.match(r"^(abg|vbg)_(gt|ge)(45|50)$", column):
        definition = "Specimen-specific three-state return episode gas threshold"
        unit = "mmHg"
        null_semantics = "NULL when no usable measurement of this specimen exists"
    return {
        "column": column,
        "duckdb_type": duckdb_type,
        "role": role,
        "definition": definition,
        "unit": unit,
        "null_semantics": null_semantics,
        "applicability": applicability,
    }


def _episodes(db: duckdb.DuckDBPyConnection, bucket: int, partitions: int) -> None:
    db.execute(
        "CREATE TEMP TABLE index_keys AS SELECT patient_id::VARCHAR patient_id, "
        "encounter_id::VARCHAR encounter_id, pat_enc_hash::VARCHAR index_event_id "
        "FROM index_file WHERE hash(patient_id::VARCHAR) % ? = ?",
        [partitions, bucket],
    )
    db.execute(
        "CREATE TEMP TABLE index_patients AS SELECT DISTINCT patient_id FROM index_keys"
    )
    db.execute(
        f"""
        CREATE TEMP TABLE episode_source AS
        WITH eligible AS (
          SELECT DISTINCT s.patient_id, s.encounter_id
          FROM preprocessed.source_encounter s
          SEMI JOIN index_patients p USING (patient_id)
          WHERE s.patient_id IS NOT NULL AND s.encounter_id IS NOT NULL
            AND (upper(trim(s.type)) IN {ACUTE_TYPES}
              OR EXISTS (SELECT 1 FROM index_keys i
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
        JOIN eligible e USING (patient_id,encounter_id)
        """
    )
    db.execute(
        f"""
        CREATE TEMP TABLE episodes AS
        WITH classified AS (
          SELECT *, upper(trim(coalesce(source_type,''))) AS setting,
                 upper(trim(coalesce(source_type,''))) IN {ED_TYPES} AS is_ed,
                 upper(trim(coalesce(source_type,''))) IN {INPATIENT_TYPES} AS is_ip,
                 upper(trim(coalesce(source_type,''))) IN {NONACUTE_TYPES}
                   AS is_nonacute
          FROM episode_source
        ), grouped AS (
          SELECT episode_id, patient_id, encounter_id,
                 min(start_datetime) AS episode_start,
                 max(start_datetime) AS latest_possible_start,
                 CASE WHEN count(*) FILTER (WHERE end_datetime IS NULL)=0
                      THEN max(end_datetime) END AS episode_end,
                 CASE WHEN count(*) FILTER
                        (WHERE start_timestamp_precision IS NULL)>0 THEN NULL
                      WHEN count(DISTINCT start_timestamp_precision)>1
                        THEN 'mixed'
                      ELSE min(start_timestamp_precision) END AS start_precision,
                 CASE WHEN count(*) FILTER
                        (WHERE end_timestamp_precision IS NULL)>0 THEN NULL
                      WHEN count(DISTINCT end_timestamp_precision)>1
                        THEN 'mixed'
                      ELSE min(end_timestamp_precision) END AS end_precision,
                 bool_or(is_ip) AS has_inpatient,
                 bool_or(is_ed) AS has_ed,
                 bool_or(is_nonacute) AS has_nonacute,
                 bool_or(NOT (is_ip OR is_ed OR is_nonacute))
                   AS has_unknown_setting,
                 count(DISTINCT start_datetime) AS distinct_starts,
                 count(DISTINCT end_datetime) AS distinct_ends,
                 count(DISTINCT (start_datetime,end_datetime))
                   FILTER (WHERE is_ed) AS ed_intervals,
                 count(DISTINCT (start_datetime,end_datetime))
                   FILTER (WHERE is_ip) AS ip_intervals,
                 min(start_datetime) FILTER (WHERE is_ed) AS ed_start,
                 min(end_datetime) FILTER (WHERE is_ed) AS ed_end,
                 min(start_datetime) FILTER (WHERE is_ip) AS ip_start,
                 min(end_datetime) FILTER (WHERE is_ip) AS ip_end,
                 bool_or(start_datetime IS NULL) AS has_missing_start,
                 bool_or(end_datetime IS NULL) AS has_missing_end,
                 bool_or(end_datetime < start_datetime) AS has_invalid_order,
                 bool_or(lower(trim(coalesce(
                   start_date_derived_by_TriNetX,''))) IN {TRUE_VALUES})
                   AS has_derived_start,
                 bool_or(lower(trim(coalesce(
                   end_date_derived_by_TriNetX,''))) IN {TRUE_VALUES})
                   AS has_derived_end,
                 count(*) AS source_record_count
          FROM classified GROUP BY episode_id,patient_id,encounter_id
        )
        SELECT *, CASE
          WHEN has_unknown_setting AND (has_ed OR has_inpatient)
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
          ELSE 'coherent' END AS episode_state
        FROM grouped
        """
    )
    db.execute(
        """
        CREATE TEMP TABLE index_episodes AS
        SELECT i.*, e.episode_id, e.episode_start, e.episode_end,
               e.start_precision, e.end_precision,
               e.has_inpatient AS index_inpatient,
               e.has_ed AS index_ed, e.has_derived_end,
               e.distinct_starts, e.distinct_ends,
               e.episode_state,
               CASE WHEN e.episode_id IS NULL THEN 'unlinked'
                    WHEN e.has_unknown_setting THEN 'unknown_index_setting'
                    WHEN NOT (e.has_inpatient OR e.has_ed)
                      AND e.has_nonacute THEN 'not_applicable'
                    WHEN NOT (e.has_inpatient OR e.has_ed)
                      THEN 'unknown_index_setting'
                    WHEN e.episode_start IS NULL OR e.episode_end IS NULL
                      THEN 'missing_episode_end'
                    WHEN e.has_derived_end THEN 'derived_episode_end'
                    WHEN e.episode_state NOT IN ('coherent')
                      THEN e.episode_state
                    WHEN e.start_precision NOT IN ('date_only','timestamp')
                      OR e.start_precision IS NULL
                      THEN 'unknown_start_precision'
                    WHEN e.end_precision NOT IN ('date_only','timestamp')
                      OR e.end_precision IS NULL
                      THEN 'unknown_end_precision'
                    ELSE 'available' END AS anchor_state
        FROM index_keys i LEFT JOIN episodes e
          ON i.patient_id=e.patient_id AND i.encounter_id=e.encounter_id
        """
    )


def _links(db: duckdb.DuckDBPyConnection) -> None:
    db.execute(
        """
        CREATE TEMP TABLE return_links AS
        SELECT i.index_event_id, i.patient_id AS index_patient_id,
               i.encounter_id AS index_encounter_id,
               i.episode_id AS index_episode_id,
               i.episode_end AS index_episode_end,
               i.end_precision AS index_end_precision,
               i.index_inpatient, i.index_ed,
               e.episode_id AS return_episode_id, e.patient_id, e.encounter_id,
               e.episode_start AS return_start,
               e.latest_possible_start,
               e.start_precision AS return_start_precision,
               e.episode_end AS return_end,
               e.end_precision AS return_end_precision,
               e.episode_state AS return_episode_state,
               e.has_inpatient, e.has_ed, e.source_record_count,
               date_diff('day',i.episode_end::DATE,e.episode_start::DATE)
                 AS days_after_index_end,
               CASE WHEN e.episode_start IS NULL THEN 'missing_return_start'
                    WHEN e.has_derived_start THEN 'derived_return_start'
                    WHEN e.episode_state NOT IN ('coherent','start_only')
                      THEN e.episode_state
                    WHEN e.start_precision NOT IN ('date_only','timestamp')
                      OR e.start_precision IS NULL
                      THEN 'unknown_return_precision'
                    WHEN e.episode_start::DATE=i.episode_end::DATE
                      THEN 'same_day_uncertain'
                    WHEN e.episode_start::DATE<i.episode_end::DATE
                      THEN 'overlap_or_prior'
                    WHEN e.episode_start::DATE>
                         i.episode_end::DATE + INTERVAL 365 DAY
                      THEN 'outside_horizon'
                    ELSE 'confirmed' END AS temporal_state,
               (e.has_ed AND e.has_inpatient) AS evidenced_ed_inpatient,
               (e.has_ed AND NOT e.has_inpatient) AS ed_only,
               (e.has_inpatient AND i.index_ed AND NOT i.index_inpatient)
                 AS admission_after_ed_index,
               (e.has_inpatient AND i.index_inpatient)
                 AS readmission_after_inpatient
        FROM index_episodes i JOIN episodes e USING (patient_id)
        WHERE i.anchor_state='available'
          AND e.episode_id<>i.episode_id
          AND (e.has_ed OR e.has_inpatient)
        """
    )
    if db.execute(
        "SELECT count(*) FROM (SELECT index_event_id,return_episode_id "
        "FROM return_links GROUP BY 1,2 HAVING count(*)<>1)"
    ).fetchone()[0]:
        raise ValueError("Duplicate index-to-return episode link")


def _evidence(db: duckdb.DuckDBPyConnection) -> None:
    _create_evidence(db, create_outcomes=False)
    for table in ("diagnosis_evidence", "gas_evidence"):
        db.execute(
            f"UPDATE {table} SET rejection_reason='unknown_event_precision' "
            "WHERE rejection_reason IS NULL AND "
            "(timestamp_precision IS NULL OR "
            "timestamp_precision NOT IN ('date_only','timestamp'))"
        )
        db.execute(
            f"UPDATE {table} AS d SET "
            "rejection_reason='incoherent_return_episode' "
            "FROM episodes e WHERE d.episode_id=e.episode_id "
            "AND d.rejection_reason IS NULL AND e.episode_state<>'coherent'"
        )
    metrics = []
    for specimen in ("abg", "vbg"):
        valid = f"gas_kind='{specimen}' AND rejection_reason IS NULL"
        metrics.append(f"count(*) FILTER (WHERE {valid}) AS {specimen}_tested_count")
        for suffix, operator, threshold in (
            ("gt45", ">", 45),
            ("gt50", ">", 50),
            ("ge45", ">=", 45),
            ("ge50", ">=", 50),
        ):
            metrics.append(
                f"count(*) FILTER (WHERE {valid} AND value_mmhg{operator}"
                f"{threshold}) AS {specimen}_{suffix}_positive_count"
            )
    gas_select = [
        "(coalesce(g.abg_tested_count,0)>0) AS abg_tested",
        "(coalesce(g.vbg_tested_count,0)>0) AS vbg_tested",
    ]
    for specimen in ("abg", "vbg"):
        for suffix in ("gt45", "gt50", "ge45", "ge50"):
            gas_select.append(
                f"CASE WHEN coalesce(g.{specimen}_tested_count,0)>0 "
                f"THEN coalesce(g.{specimen}_{suffix}_positive_count,0)>0 "
                f"ELSE NULL END AS {specimen}_{suffix}"
            )
    db.execute(
        "CREATE TEMP TABLE episode_outcomes AS "
        "WITH diagnoses AS (SELECT episode_id, "
        "bool_or(rejection_reason IS NULL) AS icd_hypercapnia "
        "FROM diagnosis_evidence GROUP BY episode_id), "
        "gases AS (SELECT episode_id, "
        + ", ".join(metrics)
        + " FROM gas_evidence GROUP BY episode_id) "
        "SELECT e.episode_id, coalesce(d.icd_hypercapnia,false) "
        "AS icd_hypercapnia, "
        + ", ".join(gas_select)
        + " FROM return_episode_keys e LEFT JOIN diagnoses d "
        "USING (episode_id) LEFT JOIN gases g USING (episode_id)"
    )
    unions = {}
    for suffix in ("gt45", "gt50", "ge45", "ge50"):
        unions[f"any_gas_{suffix}"] = (
            f"CASE WHEN o.abg_{suffix} IS TRUE OR o.vbg_{suffix} IS TRUE "
            "THEN true WHEN o.abg_tested OR o.vbg_tested THEN false "
            "ELSE NULL END"
        )
    for name, abg_suffix, vbg_suffix in (
        ("gas_abg_gt45_or_vbg_gt50", "gt45", "gt50"),
        ("gas_abg_ge45_or_vbg_ge50", "ge45", "ge50"),
    ):
        unions[name] = (
            f"CASE WHEN o.abg_{abg_suffix} IS TRUE "
            f"OR o.vbg_{vbg_suffix} IS TRUE THEN true "
            "WHEN o.abg_tested OR o.vbg_tested THEN false ELSE NULL END"
        )
    unions["icd_or_gas_strict"] = (
        "CASE WHEN o.icd_hypercapnia THEN true ELSE "
        + unions["gas_abg_gt45_or_vbg_gt50"]
        + " END"
    )
    unions["icd_or_gas_inclusive"] = (
        "CASE WHEN o.icd_hypercapnia THEN true ELSE "
        + unions["gas_abg_ge45_or_vbg_ge50"]
        + " END"
    )
    unions["any_hypercapnia"] = unions["icd_or_gas_inclusive"]
    fields = ["l.*", "o.icd_hypercapnia", "o.abg_tested", "o.vbg_tested"]
    fields.extend(
        f"o.{specimen}_{suffix}"
        for specimen in ("abg", "vbg")
        for suffix in ("gt45", "gt50", "ge45", "ge50")
    )
    fields.extend(f"{expression} AS {name}" for name, expression in unions.items())
    db.execute(
        "CREATE TEMP TABLE links_enriched AS SELECT "
        + ", ".join(fields)
        + " FROM return_links l LEFT JOIN episode_outcomes o "
        "ON l.return_episode_id=o.episode_id"
    )


def _metric_tables(db: duckdb.DuckDBPyConnection) -> list[str]:
    """Aggregate one category and horizon at a time to bound planner memory."""
    predicates = {
        "inpatient": "has_inpatient",
        "ed_only": "ed_only",
        "any_ed": "has_ed",
        "acute_union": "(has_ed OR has_inpatient)",
    }
    tables = []
    for kind, kind_predicate in predicates.items():
        name = f"states_{kind}"
        tables.append(name)
        columns = ["index_event_id"] + [
            f"count(*) FILTER (WHERE temporal_state='{state}') AS {state}_count"
            for state in TEMPORAL_STATES
        ]
        db.execute(
            f"CREATE TEMP TABLE {name} AS SELECT "
            + ", ".join(columns)
            + " FROM links_enriched WHERE "
            + kind_predicate
            + " GROUP BY index_event_id"
        )
    for days in HORIZONS:
        for kind, kind_predicate in predicates.items():
            name = f"metric_{kind}_{days}"
            tables.append(name)
            base = (
                "temporal_state='confirmed' AND "
                f"days_after_index_end BETWEEN 1 AND {days}"
            )
            potential = (
                "temporal_state NOT IN ('confirmed','same_day_uncertain',"
                "'overlap_or_prior','outside_horizon') AND "
                "(return_start IS NULL OR temporal_state='derived_return_start' "
                "OR (return_start::DATE <= index_episode_end::DATE "
                f"+ INTERVAL {days} DAY AND latest_possible_start::DATE "
                ">= index_episode_end::DATE + INTERVAL 1 DAY))"
            )
            columns = [
                "index_event_id",
                f"count(*) FILTER (WHERE {potential}) AS possible_count",
                f"count(*) FILTER (WHERE {base}) AS confirmed_count",
            ]
            columns.extend(
                f"count(*) FILTER (WHERE {potential} AND "
                f"temporal_state='{state}') AS {state}_possible_count"
                for state in DATED_POSSIBLE_STATES
            )
            for criterion in V2_CRITERIA:
                positive = (
                    base
                    if criterion == "all_cause"
                    else (f"{base} AND {criterion} IS TRUE")
                )
                columns.extend(
                    (
                        f"count(*) FILTER (WHERE {positive}) AS {criterion}_count",
                        f"min(return_start::DATE) FILTER (WHERE {positive}) "
                        f"AS {criterion}_first_date",
                    )
                )
                if criterion != "all_cause":
                    unknown = (
                        f"{base} AND return_episode_state<>'coherent'"
                        if criterion == "icd_hypercapnia"
                        else f"{base} AND {criterion} IS NULL"
                    )
                    columns.append(
                        f"count(*) FILTER (WHERE {unknown}) "
                        f"AS {criterion}_unknown_count"
                    )
                if criterion not in ("all_cause", "icd_hypercapnia"):
                    columns.extend(
                        (
                            f"count(*) FILTER (WHERE {base} AND "
                            f"{criterion} IS NOT NULL) "
                            f"AS {criterion}_tested_count",
                            f"count(*) FILTER (WHERE {base} AND "
                            "return_episode_state<>'coherent') "
                            f"AS {criterion}_unavailable_count",
                        )
                    )
            db.execute(
                f"CREATE TEMP TABLE {name} AS SELECT "
                + ", ".join(columns)
                + " FROM links_enriched WHERE "
                + kind_predicate
                + " GROUP BY index_event_id"
            )
    return tables


def _summary_query() -> str:
    fields = [
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
        "WHEN i.index_ed THEN 'admission' "
        "WHEN i.anchor_state='not_applicable' THEN 'not_applicable' "
        "ELSE 'unavailable' END AS inpatient_event_term",
    ]
    joins = []
    for kind in ("inpatient", "ed_only", "any_ed", "acute_union"):
        alias = f"t_{kind}"
        joins.append(
            f"LEFT JOIN states_{kind} {alias} "
            f"ON i.index_event_id={alias}.index_event_id"
        )
        for state in TEMPORAL_STATES:
            fields.append(
                f"coalesce({alias}.{state}_count,0) "
                f"AS outcome_{kind}_{state}_candidate_count"
            )
    for state in TEMPORAL_STATES:
        fields.append(f"coalesce(t.{state}_count,0) AS {state}_count")
    fields.extend(
        (
            "coalesce(t.missing_return_start_count,0) AS undated_return_count",
            "coalesce(t.invalid_episode_order_count,0) "
            "AS invalid_return_episode_order_count",
        )
    )
    for days in HORIZONS:
        fields.append(
            "CASE WHEN i.anchor_state<>'available' THEN 'index_unavailable' "
            "WHEN o.last_observed_event_datetime IS NULL THEN 'unobserved' "
            "WHEN o.last_observed_event_datetime::DATE >= "
            f"i.episode_end::DATE + INTERVAL {days} DAY "
            "THEN 'observation_at_or_after_horizon' "
            "ELSE 'last_observation_before_horizon' END "
            f"AS outcome_followup_observation_{days}d"
        )
        for kind in ("inpatient", "ed_only", "any_ed", "acute_union"):
            alias = f"m_{kind}_{days}"
            joins.append(
                f"LEFT JOIN metric_{kind}_{days} {alias} "
                "ON i.index_event_id=" + alias + ".index_event_id"
            )
            possible = f"coalesce({alias}.possible_count,0)"
            confirmed = f"coalesce({alias}.confirmed_count,0)"
            fields.append(
                "CASE WHEN i.anchor_state='available' THEN "
                f"{possible} ELSE NULL END AS "
                f"outcome_{kind}_possible_{days}d_count"
            )
            for state in DATED_POSSIBLE_STATES:
                fields.append(
                    "CASE WHEN i.anchor_state='available' THEN "
                    f"coalesce({alias}.{state}_possible_count,0) ELSE NULL "
                    f"END AS outcome_{kind}_{state}_possible_{days}d_count"
                )
            for criterion in V2_CRITERIA:
                stem = f"outcome_{kind}_{criterion}_{days}d"
                count = f"coalesce({alias}.{criterion}_count,0)"
                first = f"{alias}.{criterion}_first_date"
                fields.extend(
                    (
                        "CASE WHEN i.anchor_state='available' THEN "
                        f"{count} ELSE NULL END AS {stem}_count",
                        "CASE WHEN i.anchor_state='available' THEN "
                        f"{first} ELSE NULL END AS {stem}_first_date",
                        f"CAST(NULL AS TIMESTAMP) AS {stem}_first_timestamp",
                        "CASE WHEN i.anchor_state='available' THEN "
                        f"date_diff('day',i.episode_end::DATE,{first}) "
                        f"ELSE NULL END AS {stem}_days_to_first",
                    )
                )
                if criterion == "all_cause":
                    flag = (
                        f"CASE WHEN {count}>0 THEN true "
                        f"WHEN {possible}>0 THEN NULL ELSE false END"
                    )
                elif criterion == "icd_hypercapnia":
                    unknown = f"coalesce({alias}.{criterion}_unknown_count,0)"
                    flag = (
                        f"CASE WHEN {count}>0 THEN true "
                        f"WHEN {possible}>0 OR {unknown}>0 THEN NULL "
                        "ELSE false END"
                    )
                else:
                    unknown = f"coalesce({alias}.{criterion}_unknown_count,0)"
                    tested = f"coalesce({alias}.{criterion}_tested_count,0)"
                    unavailable = f"coalesce({alias}.{criterion}_unavailable_count,0)"
                    flag = (
                        f"CASE WHEN {count}>0 THEN true "
                        f"WHEN {possible}>0 OR {unknown}>0 "
                        f"OR {confirmed}=0 THEN NULL ELSE false END"
                    )
                    fields.extend(
                        (
                            "CASE WHEN i.anchor_state='available' THEN "
                            f"{tested} ELSE NULL END AS {stem}_tested_count",
                            "CASE WHEN i.anchor_state='available' THEN "
                            f"{unknown} ELSE NULL END AS {stem}_untested_count",
                            "CASE WHEN i.anchor_state='available' THEN "
                            f"{unavailable} ELSE NULL END AS "
                            f"{stem}_phenotype_unavailable_count",
                        )
                    )
                fields.append(
                    "CASE WHEN i.anchor_state='available' THEN "
                    f"{flag} ELSE NULL END AS {stem}_flag"
                )
    return (
        "SELECT " + ", ".join(fields) + " FROM index_episodes i "
        "LEFT JOIN (SELECT index_event_id, "
        + ", ".join(
            "count(*) FILTER (WHERE temporal_state='"
            + state
            + "') AS "
            + state
            + "_count"
            for state in TEMPORAL_STATES
        )
        + " FROM links_enriched GROUP BY index_event_id) t "
        "ON i.index_event_id=t.index_event_id "
        "LEFT JOIN (SELECT patient_id,CASE WHEN "
        "count(DISTINCT month_year_death)=1 "
        "THEN min(month_year_death) END AS month_year_death "
        "FROM preprocessed.source_patient GROUP BY patient_id) p "
        "ON i.patient_id=p.patient_id "
        "LEFT JOIN (SELECT patient_id,max(last_event_datetime) "
        "AS last_observed_event_datetime "
        "FROM preprocessed.patient_observability GROUP BY patient_id) o "
        "ON i.patient_id=o.patient_id " + " ".join(joins)
    )


def build_partition_v2(
    db: duckdb.DuckDBPyConnection,
    *,
    variant: str,
    bucket: int,
    partitions: int,
    output: Path,
) -> dict[str, dict[str, str | int]]:
    _episodes(db, bucket, partitions)
    _links(db)
    _evidence(db)
    metric_tables = _metric_tables(db)
    prefix = f"{variant.lower()}_{bucket:04d}"
    queries = {
        "episode_source": "SELECT * FROM episode_source",
        "episodes": "SELECT * FROM episodes",
        "diagnosis_evidence": "SELECT * FROM diagnosis_evidence",
        "gas_evidence": "SELECT * FROM gas_evidence",
        "links": "SELECT * FROM links_enriched",
        "summary": _summary_query(),
    }
    paths = {name: output / f"{prefix}_{name}.parquet" for name in queries}
    for name, query in queries.items():
        _write_table(db, query, paths[name])
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
    for table in metric_tables:
        db.execute(f"DROP TABLE {table}")
    return {
        name: {"sha256": sha256(path), "bytes": path.stat().st_size}
        for name, path in paths.items()
    }

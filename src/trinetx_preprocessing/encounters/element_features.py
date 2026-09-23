"""Encounter-linked evidence for traditional and GLP-1 source elements."""

from __future__ import annotations

import logging

import duckdb

from ..filesystem import remove_tree_strict
from .compatibility import no_symlinks

LOGGER = logging.getLogger(__name__)

DOMAINS = {
    "labs": "source_lab_measurement",
    "vitals": "source_vital_measurement",
    "diagnosis": "source_diagnosis",
    "procedure": "source_procedure",
    "medications": "source_medication",
}


def quote(value):
    return "'" + str(value).replace("'", "''") + "'"


def identifier(value):
    return '"' + value.replace('"', '""') + '"'


def _partition_files(directory):
    files = sorted(
        str(p) for p in directory.glob("*.parquet") if not p.name.startswith("._")
    )
    if not files:
        raise ValueError("Element evidence partition has no data files")
    return files


def _evidence_select(source, membership, domain, days):
    # Materialize the bounded source/membership join before expanding encounters.
    # Neither input is deduplicated: membership and source multiplicity survive.
    return f"""
        WITH matched AS MATERIALIZED (
            SELECT source.*, membership.element_id
            FROM {source} AS source
            JOIN {membership} AS membership USING (source_record_id)
            WHERE membership.include
              AND starts_with(membership.element_id, 'source.')
        )
          SELECT anchor.index_event_id, anchor.index_date, source.element_id,
                 source.source_record_id, source.source_file, source.source_row_number,
                 source.patient_id, source.encounter_id AS source_encounter_id,
                 source.event_datetime, source.timestamp_precision,
                 source.numeric_value, source.units_of_measure,
                 source.code_system_raw, source.code_raw, source.specimen,
                 source.specimen_id, source.panel_id, source.order_status,
                 source.status, source.route, source.brand, source.strength,
                 source.start_date, source.end_date, source.lab_result_text_val,
                 source.text_value, {quote(domain)} AS domain,
                 (source.event_datetime::DATE <= anchor.index_date
                  AND source.event_datetime::DATE >=
                      anchor.index_date - INTERVAL {days} DAY) AS in_baseline_window
          FROM encounter_anchor AS anchor
          JOIN matched AS source ON source.patient_id=anchor.patient_id
          WHERE (
              source.encounter_id=anchor.encounter_id
              OR (source.event_datetime::DATE <= anchor.index_date
                  AND source.event_datetime::DATE >=
                      anchor.index_date::DATE - INTERVAL {days} DAY)
            )
    """


def _partition_input(connection, query, path, key, partitions):
    rows = connection.execute(f"""
        COPY (SELECT *, hash({key}) % {partitions} AS evidence_bucket
              FROM ({query})) TO {quote(path)}
        (FORMAT PARQUET, PARTITION_BY (evidence_bucket), ROW_GROUP_SIZE 16384)
    """).fetchone()[0]
    LOGGER.info("Partitioned element input %s: %s rows", path.name, rows)


def _materialize_element_rows(connection, config, scratch, partitions):
    members = scratch / "membership"
    _partition_input(
        connection,
        """
        SELECT source_record_id, element_id, include
        FROM preprocessed.element_membership
        WHERE include AND starts_with(element_id, 'source.')
          AND source_record_id IS NOT NULL
    """,
        members,
        "source_record_id",
        partitions,
    )
    empty = _evidence_select(
        "preprocessed.source_lab_measurement",
        "preprocessed.element_membership",
        "labs",
        config.measurement_lookback_days,
    )
    connection.execute(
        "CREATE OR REPLACE TABLE encounter_element_evidence AS "
        f"SELECT * FROM ({empty}) WHERE false"
    )
    for domain, table in DOMAINS.items():
        days = (
            config.measurement_lookback_days
            if domain in {"labs", "vitals"}
            else config.lookback_days
        )
        source_path = scratch / domain
        # This semi join only removes patients that cannot join any anchor.
        _partition_input(
            connection,
            f"""
            SELECT source.* FROM preprocessed.{table} source
            SEMI JOIN encounter_anchor anchor USING(patient_id)
            WHERE source.source_record_id IS NOT NULL
        """,
            source_path,
            "source_record_id",
            partitions,
        )
        for bucket in range(partitions):
            source = source_path / f"evidence_bucket={bucket}"
            membership = members / f"evidence_bucket={bucket}"
            if not source.exists() or not membership.exists():
                continue
            connection.read_parquet(
                _partition_files(source), hive_partitioning=False
            ).create_view("_element_source", replace=True)
            connection.read_parquet(
                _partition_files(membership), hive_partitioning=False
            ).create_view("_element_membership", replace=True)
            connection.execute(
                "INSERT INTO encounter_element_evidence "
                + _evidence_select(
                    "_element_source", "_element_membership", domain, days
                )
            )
            if (bucket + 1) % 8 == 0:
                LOGGER.info(
                    "Completed element evidence %s partitions %s/%s",
                    domain,
                    bucket + 1,
                    partitions,
                )
        LOGGER.info("Completed element evidence domain %s", domain)
        connection.execute("DROP VIEW IF EXISTS _element_source")
        connection.execute("DROP VIEW IF EXISTS _element_membership")
        remove_tree_strict(source_path)


def build_element_evidence(connection, config, *, scratch, partitions=64):
    """Bound joins by source ID and summary groups by encounter ID.

    Every matching source/membership pair shares one source-ID bucket. Every
    encounter summary shares one encounter-ID bucket. SQL predicates, raw fields,
    multiplicity and deterministic latest-record rules are unchanged.
    """
    if not isinstance(partitions, int) or partitions < 1:
        raise ValueError("Element evidence partitions must be positive")
    scratch = no_symlinks(scratch)
    scratch.mkdir(parents=True, exist_ok=False)
    flush = connection.execute(
        "SELECT current_setting('partitioned_write_flush_threshold')"
    ).fetchone()[0]
    connection.execute("SET partitioned_write_flush_threshold=16384")
    try:
        _materialize_element_rows(connection, config, scratch, partitions)
        inventory = _build_element_summary(connection, scratch, partitions)
    except BaseException:
        try:
            connection.execute("SET partitioned_write_flush_threshold=?", [flush])
        except duckdb.TransactionException:
            pass
        raise
    else:
        connection.execute("SET partitioned_write_flush_threshold=?", [flush])
    remove_tree_strict(scratch)
    return inventory


def _build_element_summary(connection, scratch, partitions):
    catalog = connection.execute("""
        SELECT DISTINCT element_id, domain FROM preprocessed.element_catalog
        WHERE starts_with(element_id,'source.')
        ORDER BY element_id
    """).fetchall()
    expressions = []
    inventory = []
    for element, domain in catalog:
        name = "element_" + element.removeprefix("source.").replace(".", "_")
        condition = f"element_id={quote(element)}"
        count_name = name + "_record_count"
        expressions.append(
            f"count(*) FILTER (WHERE {condition}) AS {identifier(count_name)}"
        )
        columns = [count_name]
        if domain in {"lab", "labs", "vital", "vitals"}:
            for value, ending in [
                ("numeric_value", "latest_raw_value"),
                ("event_datetime", "latest_date"),
                ("units_of_measure", "latest_unit"),
            ]:
                col = name + "_" + ending
                # Select fields from the same deterministic last record, even
                # when that record's value/unit is missing.
                expressions.append(
                    f"first({value} ORDER BY event_datetime DESC NULLS LAST, "
                    f"source_record_id DESC) FILTER (WHERE {condition} "
                    "AND in_baseline_window) "
                    f"AS {identifier(col)}"
                )
                columns.append(col)
        inventory.append(
            {
                "element_id": element,
                "columns": ["source_" + c for c in columns],
                "evidence": "encounter_element_evidence",
                "semantics": "Documented source records; counts are not clinic"
                "al absence or eligibility",
                "numeric_values": "Raw values with explicit units; normalized summa"
                "ries are separate",
            }
        )
    query = (
        "SELECT index_event_id, "
        + ", ".join(expressions)
        + " FROM {source} GROUP BY index_event_id"
    )
    connection.execute(
        "CREATE OR REPLACE TABLE element_summary AS SELECT * FROM ("
        + query.format(source="encounter_element_evidence")
        + ") WHERE false"
    )
    summary_path = scratch / "summary"
    _partition_input(
        connection,
        """
        SELECT index_event_id, element_id, event_datetime, source_record_id,
               numeric_value, units_of_measure, in_baseline_window
        FROM encounter_element_evidence
    """,
        summary_path,
        "index_event_id",
        partitions,
    )
    for bucket in range(partitions):
        path = summary_path / f"evidence_bucket={bucket}"
        if not path.exists():
            continue
        connection.read_parquet(
            _partition_files(path), hive_partitioning=False
        ).create_view("_element_summary", replace=True)
        connection.execute(
            "INSERT INTO element_summary " + query.format(source="_element_summary")
        )
    connection.execute("DROP VIEW IF EXISTS _element_summary")
    return inventory


def add_availability_inventory(
    connection, inventory, *, scratch, partitions=64, subpartitions=4
):
    """Represent zero matches separately from missing domains/history.

    Keep each encounter's evidence and coverage in one bounded key partition.
    Distinct evidence is exact within each partition, and the partition counts
    can be added without a global billion-row distinct hash table.
    """
    if not isinstance(partitions, int) or partitions < 1:
        raise ValueError("Availability partitions must be positive")
    if not isinstance(subpartitions, int) or subpartitions < 1:
        raise ValueError("Availability subpartitions must be positive")
    scratch = no_symlinks(scratch)
    scratch.mkdir(parents=True, exist_ok=False)
    totals = {}
    for domain, state, count in connection.execute(
        "SELECT domain,history_state,count(*) FROM encounter_source_coverage "
        "GROUP BY 1,2"
    ).fetchall():
        totals.setdefault(domain, {})[state] = count
    observed = {}
    flush = connection.execute(
        "SELECT current_setting('partitioned_write_flush_threshold')"
    ).fetchone()[0]
    connection.execute("SET partitioned_write_flush_threshold=16384")
    try:
        evidence_path = scratch / "evidence"
        coverage_path = scratch / "coverage"
        _partition_input(
            connection,
            "SELECT index_event_id,element_id,domain FROM encounter_element_evidence",
            evidence_path,
            "index_event_id",
            partitions,
        )
        _partition_input(
            connection,
            "SELECT index_event_id,domain,history_state FROM encounter_source_coverage",
            coverage_path,
            "index_event_id",
            partitions,
        )
        for bucket in range(partitions):
            evidence = evidence_path / f"evidence_bucket={bucket}"
            coverage = coverage_path / f"evidence_bucket={bucket}"
            if not evidence.exists() or not coverage.exists():
                continue
            connection.read_parquet(
                _partition_files(evidence), hive_partitioning=False
            ).create_view("_availability_evidence", replace=True)
            connection.read_parquet(
                _partition_files(coverage), hive_partitioning=False
            ).create_view("_availability_coverage", replace=True)
            # A small number of physical files avoids partition-writer file
            # proliferation. Each encounter is still deduplicated in one of
            # the finer hash slices, keeping the distinct table bounded.
            for subbucket in range(subpartitions):
                fine_bucket = bucket + partitions * subbucket
                for element, domain, state, count in connection.execute(f"""
                    SELECT e.element_id, e.domain, c.history_state, count(*)
                    FROM (SELECT DISTINCT index_event_id,element_id,domain
                          FROM _availability_evidence
                          WHERE hash(index_event_id) %
                                {partitions * subpartitions} = {fine_bucket}) e
                    JOIN _availability_coverage c
                      ON e.index_event_id=c.index_event_id AND e.domain=c.domain
                    GROUP BY 1,2,3
                """).fetchall():
                    counts = observed.setdefault(element, {})
                    counts[state] = counts.get(state, 0) + count
            if (bucket + 1) % 16 == 0:
                LOGGER.info(
                    "Completed availability partitions %s/%s",
                    bucket + 1,
                    partitions,
                )
        connection.execute("DROP VIEW IF EXISTS _availability_evidence")
        connection.execute("DROP VIEW IF EXISTS _availability_coverage")
    except BaseException:
        try:
            connection.execute("SET partitioned_write_flush_threshold=?", [flush])
        except duckdb.TransactionException:
            pass
        raise
    else:
        connection.execute("SET partitioned_write_flush_threshold=?", [flush])
    catalog = dict(
        connection.execute(
            "SELECT element_id,domain FROM preprocessed.element_catalog "
            "WHERE starts_with(element_id,'source.')"
        ).fetchall()
    )
    domains = {"lab": "labs", "vital": "vitals", "medication": "medications"}
    for row in inventory:
        element = row["element_id"]
        domain = domains.get(catalog[element], catalog[element])
        if domain not in totals:
            raise ValueError("Required element lacks a source coverage domain")
        row.update(
            {
                "contract_version": "1.0",
                "domain": domain,
                "availability_table": "encounter_source_coverage",
                "availability_join": "index_event_id + domain",
                "availability_states": [
                    {
                        "history_state": state,
                        "observed_matches": observed.get(element, {}).get(state, 0),
                        "zero_matching_records": n
                        - observed.get(element, {}).get(state, 0),
                    }
                    for state, n in totals[domain].items()
                ],
                "anchor_precision": "calendar day",
                "baseline_lookback_days": 365 if domain in {"labs", "vitals"} else 730,
                "context": "Inclusive baseline days plus same-encounter records "
                "outside baseline; latest raw values require in_baseline_window",
                "source_dates": "event_datetime with timestamp_precision; "
                "raw dates retained",
            }
        )
    remove_tree_strict(scratch)
    return inventory

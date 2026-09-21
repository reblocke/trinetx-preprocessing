"""Encounter-linked evidence for traditional and GLP-1 source elements."""

from __future__ import annotations

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


def build_element_evidence(connection, config):
    selects = []
    for domain, table in DOMAINS.items():
        days = (
            config.measurement_lookback_days
            if domain in {"labs", "vitals"}
            else config.lookback_days
        )
        selects.append(f"""
          SELECT anchor.index_event_id, anchor.index_date, membership.element_id,
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
          JOIN preprocessed.{table} AS source ON source.patient_id=anchor.patient_id
          JOIN preprocessed.element_membership AS membership USING(source_record_id)
          WHERE membership.include
            AND starts_with(membership.element_id,'source.')
            AND (
              source.encounter_id=anchor.encounter_id
              OR (source.event_datetime::DATE <= anchor.index_date
                  AND source.event_datetime::DATE >=
                      anchor.index_date::DATE - INTERVAL {days} DAY)
            )
        """)
    connection.execute(
        "CREATE OR REPLACE TABLE encounter_element_evidence AS "
        + " UNION ALL ".join(selects)
    )
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
    connection.execute(
        "CREATE OR REPLACE TABLE element_summary AS SELECT index_event_id, "
        + ", ".join(expressions)
        + " FROM encounter_element_evidence GROUP BY index_event_id"
    )
    return inventory


def add_availability_inventory(connection, inventory):
    """Represent zero matches separately from missing domains/history.

    Aggregate observed states once. Subtract these from domain totals instead
    of materializing the element-by-encounter Cartesian product.
    """
    totals = {}
    for domain, state, count in connection.execute(
        "SELECT domain,history_state,count(*) FROM encounter_source_coverage "
        "GROUP BY 1,2"
    ).fetchall():
        totals.setdefault(domain, {})[state] = count
    observed = {}
    for element, domain, state, count in connection.execute("""
        SELECT e.element_id, e.domain, c.history_state, count(*)
        FROM (SELECT DISTINCT index_event_id,element_id,domain
              FROM encounter_element_evidence) e
        JOIN encounter_source_coverage c
          ON e.index_event_id=c.index_event_id AND e.domain=c.domain
        GROUP BY 1,2,3
    """).fetchall():
        observed.setdefault(element, {})[state] = count
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
    return inventory

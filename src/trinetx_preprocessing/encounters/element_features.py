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
        "CREATE TABLE encounter_element_evidence AS " + " UNION ALL ".join(selects)
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
        "CREATE TABLE element_summary AS SELECT index_event_id, "
        + ", ".join(expressions)
        + " FROM encounter_element_evidence GROUP BY index_event_id"
    )
    return inventory

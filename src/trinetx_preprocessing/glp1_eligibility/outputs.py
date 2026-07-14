"""Study-ready file materialization and aggregate GLP-1 summaries."""

from __future__ import annotations

import csv
import html
import json
from pathlib import Path

import duckdb

from ..filesystem import write_text_atomic

OUTPUT_TABLES = (
    "analysis_glp1_eligibility",
    "eligibility_evidence_long",
    "cohort_hypercapnia_encounter",
)


def write_build_outputs(
    connection: duckdb.DuckDBPyConnection,
    output_dir: Path,
) -> tuple[Path, ...]:
    """Write the required non-database outputs into a staging directory."""

    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for table in OUTPUT_TABLES:
        path = root / f"{table}.parquet"
        connection.execute(
            f"COPY {_identifier(table)} TO {_sql_string(str(path))} "
            "(FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 250000)"
        )
        paths.append(path)

    cohort_flow_path = root / "cohort_flow.csv"
    connection.execute(
        f"COPY cohort_flow TO {_sql_string(str(cohort_flow_path))} "
        "(FORMAT CSV, HEADER TRUE)"
    )
    paths.append(cohort_flow_path)

    dictionary_path = root / "data_dictionary.csv"
    _write_data_dictionary(connection, dictionary_path)
    paths.append(dictionary_path)

    qa_path = root / "data_quality_report.html"
    write_text_atomic(qa_path, _quality_report_html(connection))
    paths.append(qa_path)

    manifest_path = root / "run_manifest.json"
    write_text_atomic(
        manifest_path,
        json.dumps(_run_manifest(connection), indent=2, default=str) + "\n",
    )
    paths.append(manifest_path)
    return tuple(paths)


def summarize_database(database_path: Path) -> dict[str, object]:
    """Return aggregate study counts without patient identifiers."""

    path = Path(database_path)
    if not path.is_file():
        raise FileNotFoundError(f"GLP-1 database not found: {path}")
    connection = duckdb.connect(str(path), read_only=True)
    try:
        manifest = connection.execute(
            "SELECT run_id, status, rule_set_version FROM run_manifest"
        ).fetchone()
        return {
            "run_id": manifest[0],
            "status": manifest[1],
            "rule_set_version": manifest[2],
            "hypercapnia_encounters": _count(
                connection, "cohort_hypercapnia_encounter"
            ),
            "patient_index_events": _count(
                connection, "cohort_hypercapnia_patient_index"
            ),
            "primary_obesity_hypercapnia": _count(
                connection, "analysis_primary_obesity_hypercapnia"
            ),
            "evidence_rows": _count(connection, "eligibility_evidence_long"),
        }
    finally:
        connection.close()


def _write_data_dictionary(
    connection: duckdb.DuckDBPyConnection, path: Path
) -> None:
    tables = (*OUTPUT_TABLES, "cohort_hypercapnia_patient_index", "cohort_flow")
    placeholders = ", ".join("?" for _ in tables)
    rows = connection.execute(
        f"""
        SELECT table_name, ordinal_position, column_name, data_type,
               is_nullable, '' AS description
        FROM information_schema.columns
        WHERE table_schema = 'main' AND table_name IN ({placeholders})
        ORDER BY table_name, ordinal_position
        """,
        list(tables),
    ).fetchall()
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "table_name",
                "ordinal_position",
                "column_name",
                "data_type",
                "is_nullable",
                "description",
            ]
        )
        writer.writerows(rows)


def _quality_report_html(connection: duckdb.DuckDBPyConnection) -> str:
    source_rows = connection.execute(
        """
        SELECT logical_domain, count(*) AS files, sum(row_count) AS rows
        FROM source_file_inventory
        GROUP BY logical_domain ORDER BY logical_domain
        """
    ).fetchall()
    flow_rows = connection.execute(
        """
        SELECT stage, row_count, unique_patient_count,
               percent_of_previous_stage, reason_for_loss
        FROM cohort_flow ORDER BY stage_order
        """
    ).fetchall()
    gas_quality = connection.execute(
        """
        SELECT
            count(*) AS considered,
            count(*) FILTER (WHERE unit_usable) AS unit_usable,
            count(*) FILTER (WHERE plausible_value) AS plausible,
            count(*) FILTER (WHERE NOT unit_usable) AS incompatible_unit,
            count(*) FILTER (
                WHERE unit_usable AND NOT plausible_value
            ) AS implausible_value
        FROM normalized_gas_measurement
        """
    ).fetchone()
    return f"""<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>GLP-1 eligibility data quality</title>
<style>body{{font-family:system-ui,sans-serif;max-width:1100px;margin:2rem auto}}
table{{border-collapse:collapse;width:100%;margin-bottom:2rem}}
th,td{{border:1px solid #bbb;padding:.4rem;text-align:left}}</style></head>
<body><h1>GLP-1 eligibility data quality</h1>
<p>This report contains aggregate counts only. It does not include identifiers
or row-level examples.</p>
<h2>Source inventory</h2>{_html_table(('Domain','Files','Rows'), source_rows)}
<h2>Cohort flow</h2>{_html_table(
        ('Stage','Rows','Patients','Percent previous','Reason for loss'), flow_rows
    )}
<h2>Gas normalization</h2>{_html_table(
        ('Considered','Unit usable','Plausible','Incompatible unit','Implausible'),
        (gas_quality,),
    )}</body></html>\n"""


def _html_table(headers: tuple[str, ...], rows: tuple[tuple, ...] | list[tuple]) -> str:
    header = "".join(f"<th>{html.escape(value)}</th>" for value in headers)
    body = "".join(
        "<tr>"
        + "".join(
            f"<td>{html.escape(str(value if value is not None else ''))}</td>"
            for value in row
        )
        + "</tr>"
        for row in rows
    )
    return f"<table><thead><tr>{header}</tr></thead><tbody>{body}</tbody></table>"


def _run_manifest(connection: duckdb.DuckDBPyConnection) -> dict[str, object]:
    cursor = connection.execute("SELECT * FROM run_manifest")
    row = cursor.fetchone()
    if row is None:
        raise ValueError("run_manifest table is empty.")
    return dict(zip([column[0] for column in cursor.description], row, strict=True))


def _count(connection: duckdb.DuckDBPyConnection, relation: str) -> int:
    row = connection.execute(
        f"SELECT COUNT(*) FROM {_identifier(relation)}"
    ).fetchone()
    return int(row[0])


def _identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _sql_string(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"

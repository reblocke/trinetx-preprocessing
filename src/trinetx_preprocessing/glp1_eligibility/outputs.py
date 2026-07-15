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

COLUMN_DESCRIPTIONS = {
    "run_id": "Deterministic identifier for the code, config, and input inventory.",
    "index_event_id": "Deterministic identifier for the selected patient index event.",
    "patient_id": "Source patient identifier; confidential in real-data outputs.",
    "encounter_id": "Source identifier for the selected encounter.",
    "index_date": "Date of the selected first qualifying index event.",
    "event_date": "Date or timestamp of the source or derived evidence event.",
    "rule_id": "Stable identifier for the source component or derived rule.",
    "status": "Canonical met, not_met, indeterminate, or cohort status.",
    "certainty": "Evidence certainty assigned by the versioned phenotype rule.",
    "source_file": "Relative source export path retained for provenance.",
    "source_record_hash": "Stable hash of the source file and normalized source row.",
    "code_system": "Source terminology system after normalization where applicable.",
    "code": "Source clinical code used by the evidence record.",
    "days_from_index": "Signed whole days from index date to evidence date.",
    "is_pre_index": "Whether the evidence occurred on or before the index date.",
    "evidence_rank": "Deterministic evidence order within index event and component.",
    "provenance_json": "Structured rule-specific provenance not represented elsewhere.",
}


def write_build_outputs(
    connection: duckdb.DuckDBPyConnection,
    output_dir: Path,
    *,
    write_parquet: bool = True,
    write_html_qa: bool = True,
) -> tuple[Path, ...]:
    """Write the required non-database outputs into a staging directory."""

    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    if write_parquet:
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

    if write_html_qa:
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
            "SELECT run_id, status, rule_set_version, warning_count "
            "FROM run_manifest"
        ).fetchone()
        indication_counts = connection.execute(
            """
            SELECT
                count(*) FILTER (WHERE ind_fda_disease_specific_any),
                count(*) FILTER (WHERE ind_guideline_any),
                count(*) FILTER (WHERE ind_rct_any),
                count(*) FILTER (WHERE glp1_ever_ordered_pre_index)
            FROM analysis_primary_obesity_hypercapnia
            """
        ).fetchone()
        payer_route_counts = dict(
            connection.execute(
                """
                SELECT payer_route_model, count(*)
                FROM analysis_primary_obesity_hypercapnia
                GROUP BY payer_route_model ORDER BY payer_route_model
                """
            ).fetchall()
        )
        return {
            "run_id": manifest[0],
            "status": manifest[1],
            "rule_set_version": manifest[2],
            "warning_count": manifest[3],
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
            "disease_specific_fda": indication_counts[0],
            "guideline_supported": indication_counts[1],
            "rct_supported": indication_counts[2],
            "glp1_ordered_pre_index": indication_counts[3],
            "payer_route_counts": payer_route_counts,
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
               is_nullable
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
        writer.writerows(
            (*row, _column_description(row[0], row[2])) for row in rows
        )


def _column_description(table_name: str, column_name: str) -> str:
    if column_name in COLUMN_DESCRIPTIONS:
        return COLUMN_DESCRIPTIONS[column_name]
    readable = column_name.replace("_", " ")
    if column_name.startswith("ind_"):
        return f"Nullable indication result for {readable[4:]}."
    if column_name.endswith("_status"):
        return f"Canonical phenotype status for {readable[:-7]}."
    if column_name.endswith("_certainty"):
        return f"Evidence certainty for {readable[:-10]}."
    if column_name.startswith("has_"):
        return f"Data-availability indicator for {readable[4:]}."
    if column_name.endswith("_date") or column_name.endswith("_datetime"):
        return f"Date or timestamp for {readable.rsplit(' ', 1)[0]}."
    return f"{readable.capitalize()} in `{table_name}`."


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
    date_coverage = connection.execute(
        """
        SELECT logical_domain, min(min_event_date), max(max_event_date)
        FROM source_file_inventory
        GROUP BY logical_domain ORDER BY logical_domain
        """
    ).fetchall()
    code_systems = connection.execute(
        """
        WITH codes AS (
            SELECT 'lab' AS domain, code_system FROM source_lab_measurement
            UNION ALL SELECT 'vital', code_system FROM source_vital_measurement
            UNION ALL SELECT 'diagnosis', code_system FROM source_diagnosis
            UNION ALL SELECT 'procedure', code_system FROM source_procedure
            UNION ALL SELECT 'medication', code_system FROM source_medication
        )
        SELECT domain, coalesce(nullif(trim(code_system), ''), '<missing>'),
               count(*)
        FROM codes GROUP BY domain, code_system ORDER BY domain, count(*) DESC
        """
    ).fetchall()
    unmapped_codes = connection.execute(
        """
        SELECT logical_domain, code_system, code, estimated_count, max_error
        FROM unmapped_code_frequency
        ORDER BY logical_domain, estimated_count DESC, code_system, code
        """
    ).fetchall()
    unit_rows = connection.execute(
        """
        WITH units AS (
            SELECT 'lab' AS domain, units_of_measure AS unit
            FROM source_lab_measurement
            UNION ALL
            SELECT 'vital', units_of_measure FROM source_vital_measurement
        ), ranked AS (
            SELECT domain, coalesce(nullif(trim(unit), ''), '<missing>') AS unit,
                   count(*) AS rows,
                   row_number() OVER (
                       PARTITION BY domain ORDER BY count(*) DESC, unit
                   ) AS rank
            FROM units GROUP BY domain, unit
        )
        SELECT domain, unit, rows FROM ranked WHERE rank <= 20
        ORDER BY domain, rows DESC, unit
        """
    ).fetchall()
    duplicate_rows = connection.execute(
        """
        WITH records AS (
            SELECT 'lab' AS domain, source_record_hash
            FROM source_lab_measurement
            UNION ALL SELECT 'vital', source_record_hash
            FROM source_vital_measurement
            UNION ALL SELECT 'diagnosis', source_record_hash
            FROM source_diagnosis
            UNION ALL SELECT 'procedure', source_record_hash
            FROM source_procedure
            UNION ALL SELECT 'medication', source_record_hash
            FROM source_medication
        ), duplicate_groups AS (
            SELECT domain, source_record_hash, count(*) AS rows
            FROM records GROUP BY domain, source_record_hash HAVING count(*) > 1
        )
        SELECT domain, sum(rows - 1) AS duplicate_rows
        FROM duplicate_groups GROUP BY domain ORDER BY domain
        """
    ).fetchall()
    pairing_rows = connection.execute(
        """
        SELECT coalesce(abg_pairing_method, '<unpaired>'),
               coalesce(abg_pairing_quality, '<unpaired>'), count(*)
        FROM cohort_hypercapnia_encounter
        GROUP BY abg_pairing_method, abg_pairing_quality
        ORDER BY count(*) DESC
        """
    ).fetchall()
    bmi_rows = connection.execute(
        """
        SELECT coalesce(bmi_source, '<missing>'), count(*)
        FROM analysis_glp1_eligibility
        GROUP BY bmi_source ORDER BY count(*) DESC
        """
    ).fetchall()
    missingness_rows = connection.execute(
        """
        SELECT field, observed_n, missing_n, total_n, missing_percent
        FROM analysis_missingness ORDER BY field
        """
    ).fetchall()
    certainty_rows = connection.execute(
        """
        SELECT evidence_tier, certainty, status, count(*)
        FROM eligibility_evidence_long
        WHERE component IN ('derived_status', 'derived_rule')
        GROUP BY evidence_tier, certainty, status
        ORDER BY evidence_tier, certainty, status
        """
    ).fetchall()
    sensitivity_rows = connection.execute(
        """
        SELECT
            count(*) AS candidate_encounters,
            count(*) FILTER (WHERE primary_cohort_status = 'included')
                AS primary_included,
            count(*) FILTER (WHERE later_hypercapnia_sensitivity_case)
                AS later_hypercapnia,
            count(*) FILTER (WHERE vbg_only_sensitivity_case) AS vbg_only,
            count(*) FILTER (WHERE cardiac_arrest_context) AS cardiac_arrest,
            count(*) FILTER (WHERE major_trauma_context) AS major_trauma,
            count(*) FILTER (WHERE procedure_sedation_context)
                AS procedure_sedation,
            count(*) FILTER (WHERE postoperative_context) AS postoperative,
            count(*) FILTER (WHERE probable_venous_specimen)
                AS probable_venous
        FROM cohort_hypercapnia_encounter
        """
    ).fetchall()
    schema_rows = connection.execute(
        """
        SELECT logical_domain, count(*) AS files,
               count(*) FILTER (WHERE load_status = 'loaded') AS loaded,
               count(*) FILTER (WHERE warning IS NOT NULL) AS warnings
        FROM source_file_inventory
        GROUP BY logical_domain ORDER BY logical_domain
        """
    ).fetchall()
    concept_rows = connection.execute(
        """
        SELECT domain, concept_set_id, matched_rows, required
        FROM concept_match_summary ORDER BY domain, concept_set_id
        """
    ).fetchall()
    warning_rows = connection.execute(
        """
        SELECT warning_code, message FROM build_warning
        ORDER BY warning_code, message
        """
    ).fetchall()
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
<h2>Source schema and load status</h2>{_html_table(
        ('Domain','Files','Loaded','Warnings'), schema_rows
    )}
<h2>Retained source date coverage</h2>{_html_table(
        ('Domain','First retained event','Last retained event'), date_coverage
    )}
<h2>Cohort flow</h2>{_html_table(
        ('Stage','Rows','Patients','Percent previous','Reason for loss'), flow_rows
    )}
<h2>Gas normalization</h2>{_html_table(
        ('Considered','Unit usable','Plausible','Incompatible unit','Implausible'),
        (gas_quality,),
    )}
    <h2>Concept-matched code systems</h2>{_html_table(
        ('Domain','Code system','Rows'), code_systems
    )}
<h2>High-frequency unmapped source codes</h2>{_html_table(
        ('Domain','Code system','Code','Estimated rows','Maximum error'),
        unmapped_codes,
    )}
<p>These PHI-safe aggregate frequencies use a bounded Space-Saving summary
collected during the input inventory scan. Counts with nonzero maximum error are
estimates; no patient identifiers or row examples are retained.</p>
<h2>Concept-set match coverage</h2>{_html_table(
        ('Domain','Concept set','Matched rows','Required'), concept_rows
    )}
<h2>Build warnings</h2>{_html_table(('Warning code','Message'), warning_rows)}
<h2>Top retained units</h2>{_html_table(('Domain','Unit','Rows'), unit_rows)}
<h2>Duplicate retained records</h2>{_html_table(
        ('Domain','Rows beyond first identical source hash'), duplicate_rows
    )}
<h2>Blood-gas pairing</h2>{_html_table(
        ('Pairing method','Pairing quality','Encounters'), pairing_rows
    )}
<h2>BMI source distribution</h2>{_html_table(('BMI source','Rows'), bmi_rows)}
<h2>Phenotype missingness</h2>{_html_table(
        ('Field','Observed','Missing','Total','Missing percent'), missingness_rows
    )}
<h2>Derived phenotype certainty</h2>{_html_table(
        ('Evidence tier','Certainty','Status','Rows'), certainty_rows
    )}
<h2>Sensitivity cohorts</h2>{_html_table(
        (
            'Candidates','Primary','Later hypercapnia','VBG only',
            'Cardiac arrest','Major trauma','Procedure/sedation',
            'Postoperative','Probable venous specimen'
        ),
        sensitivity_rows,
    )}
<h2>Site heterogeneity</h2>
<p>The current export contract does not provide a reliable site/HCO field in
the retained analytic sources. Site heterogeneity remains unclassifiable unless
an approved source mapping is supplied.</p></body></html>\n"""


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

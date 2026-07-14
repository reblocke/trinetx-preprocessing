"""Aggregate terminology coverage checks for a GLP-1 build."""

from __future__ import annotations

import json
from collections.abc import Sequence

import duckdb


def build_concept_match_summary(
    connection: duckdb.DuckDBPyConnection,
    required_concept_set_ids: Sequence[str],
) -> tuple[str, ...]:
    """Persist concept matches and warn when a required set has no rows."""

    connection.execute(
        """
        CREATE OR REPLACE TEMP TABLE required_concept_set (
            concept_set_id VARCHAR PRIMARY KEY
        )
        """
    )
    connection.executemany(
        "INSERT INTO required_concept_set VALUES (?)",
        [(value,) for value in required_concept_set_ids],
    )
    connection.execute(
        """
        CREATE OR REPLACE TABLE concept_match_summary AS
        WITH source_codes AS (
            SELECT 'lab' AS domain, code_system, code, source_record_hash
            FROM source_lab_measurement
            UNION ALL SELECT 'vital', code_system, code, source_record_hash
            FROM source_vital_measurement
            UNION ALL SELECT 'diagnosis', code_system, code, source_record_hash
            FROM source_diagnosis
            UNION ALL SELECT 'procedure', code_system, code, source_record_hash
            FROM source_procedure
            UNION ALL SELECT 'medication', code_system, code, source_record_hash
            FROM source_medication
        ), matches AS (
            SELECT concept.concept_set_id, concept.domain,
                   source.source_record_hash
            FROM concept_set AS concept
            JOIN source_codes AS source
              ON source.domain = concept.domain
             AND regexp_replace(
                    upper(trim(source.code_system)), '[^A-Z0-9]', '', 'g'
                 ) = concept.code_system
             AND (
                    (concept.match_type = 'exact'
                     AND upper(trim(source.code)) = concept.code)
                 OR (concept.match_type = 'prefix'
                     AND starts_with(upper(trim(source.code)), concept.code))
                 OR (concept.match_type = 'regex'
                     AND regexp_matches(upper(trim(source.code)), concept.code))
             )
            WHERE concept.include
        ), configured AS (
            SELECT DISTINCT concept_set_id, domain
            FROM concept_set WHERE include
        )
        SELECT
            configured.concept_set_id,
            configured.domain,
            count(DISTINCT matches.source_record_hash) AS matched_rows,
            required.concept_set_id IS NOT NULL AS required
        FROM configured
        LEFT JOIN matches USING (concept_set_id, domain)
        LEFT JOIN required_concept_set AS required USING (concept_set_id)
        GROUP BY configured.concept_set_id, configured.domain,
                 required.concept_set_id
        ORDER BY configured.domain, configured.concept_set_id
        """
    )
    missing = tuple(
        row[0]
        for row in connection.execute(
            """
            SELECT concept_set_id FROM concept_match_summary
            WHERE required AND matched_rows = 0 ORDER BY concept_set_id
            """
        ).fetchall()
    )
    connection.execute(
        "DELETE FROM build_warning WHERE warning_code = 'required_concept_no_match'"
    )
    run_id = connection.execute("SELECT run_id FROM run_manifest").fetchone()[0]
    messages = tuple(
        f"Required concept set {concept_set_id!r} matched no retained source rows."
        for concept_set_id in missing
    )
    if missing:
        connection.executemany(
            "INSERT INTO build_warning VALUES (?, ?, ?, ?)",
            [
                (
                    run_id,
                    "required_concept_no_match",
                    message,
                    json.dumps({"concept_set_id": concept_set_id}),
                )
                for concept_set_id, message in zip(missing, messages, strict=True)
            ],
        )
    connection.execute(
        "UPDATE run_manifest SET warning_count = (SELECT count(*) FROM build_warning)"
    )
    connection.execute("DROP TABLE required_concept_set")
    return messages

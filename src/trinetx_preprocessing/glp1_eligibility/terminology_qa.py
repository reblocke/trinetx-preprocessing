"""Aggregate terminology coverage checks for a GLP-1 build."""

from __future__ import annotations

import json
import tempfile
from collections.abc import Sequence
from pathlib import Path

import duckdb

from ..filesystem import remove_tree_strict
from .monitoring import RunStateWriter

_CONCEPT_MATCH_BUCKET_COUNT = 32
_DIRECT_CONCEPT_MATCH_MAX_ROWS = 1_000_000
_TERMINOLOGY_QA_SCRATCH_PREFIX = ".trinetx-glp1-terminology-qa-"
_SOURCE_TABLE_BY_DOMAIN = {
    "lab": "source_lab_measurement",
    "vital": "source_vital_measurement",
    "diagnosis": "source_diagnosis",
    "procedure": "source_procedure",
    "medication": "source_medication",
}


def build_concept_match_summary(
    connection: duckdb.DuckDBPyConnection,
    required_concept_set_ids: Sequence[str],
    *,
    state: RunStateWriter | None = None,
) -> tuple[str, ...]:
    """Persist exact concept-match counts with bounded intermediate state."""

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
        CREATE OR REPLACE TEMP TABLE concept_match_partial (
            concept_set_id VARCHAR,
            domain VARCHAR,
            matched_rows UBIGINT
        )
        """
    )
    connection.execute(
        """
        CREATE OR REPLACE TEMP TABLE source_hash_partial (
            domain VARCHAR,
            distinct_source_hashes UBIGINT
        )
        """
    )
    connection.execute(
        """
        CREATE OR REPLACE TEMP TABLE source_domain_total (
            domain VARCHAR PRIMARY KEY,
            source_rows UBIGINT,
            null_hash_rows UBIGINT
        )
        """
    )

    temp_directory_value = connection.execute(
        "SELECT current_setting('temp_directory')"
    ).fetchone()[0]
    temp_directory = Path(str(temp_directory_value)).resolve()
    temp_directory.mkdir(parents=True, exist_ok=True)
    scratch = Path(
        tempfile.mkdtemp(prefix=_TERMINOLOGY_QA_SCRATCH_PREFIX, dir=temp_directory)
    )
    try:
        domains = tuple(_SOURCE_TABLE_BY_DOMAIN)
        for index, domain in enumerate(domains):
            if state is not None:
                state.update(
                    phase="terminology_qa",
                    current_domain=domain,
                    completed_units=index,
                    total_units=len(domains),
                    message="Reducing exact concept-match counts by hash bucket.",
                )
            domain_scratch = scratch / domain
            try:
                source_table = _SOURCE_TABLE_BY_DOMAIN[domain]
                source_rows = int(
                    connection.execute(
                        f"SELECT count(*) FROM {_identifier(source_table)}"
                    ).fetchone()[0]
                )
                null_hash_rows = int(
                    connection.execute(
                        f"SELECT count(*) FROM {_identifier(source_table)} "
                        "WHERE source_record_hash IS NULL"
                    ).fetchone()[0]
                )
                connection.execute(
                    "INSERT INTO source_domain_total VALUES (?, ?, ?)",
                    [domain, source_rows, null_hash_rows],
                )
                if source_rows <= _DIRECT_CONCEPT_MATCH_MAX_ROWS:
                    _reduce_domain_matches_direct(
                        connection,
                        domain=domain,
                        source_table=source_table,
                    )
                else:
                    _stage_domain_matches(
                        connection,
                        domain=domain,
                        source_table=source_table,
                        output_dir=domain_scratch,
                    )
                    _reduce_domain_matches(
                        connection,
                        domain=domain,
                        partition_root=domain_scratch,
                    )
            finally:
                if domain_scratch.exists():
                    remove_tree_strict(
                        domain_scratch,
                        context=f"GLP-1 terminology QA {domain} scratch",
                    )

        _materialize_concept_match_summary(connection)
        _materialize_source_duplicate_summary(connection)
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
            "DELETE FROM build_warning "
            "WHERE warning_code = 'required_concept_no_match'"
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
                    for concept_set_id, message in zip(
                        missing, messages, strict=True
                    )
                ],
            )
        connection.execute(
            "UPDATE run_manifest "
            "SET warning_count = (SELECT count(*) FROM build_warning)"
        )
        if state is not None:
            state.update(
                phase="terminology_qa_complete",
                current_domain=None,
                completed_units=len(domains),
                total_units=len(domains),
                message="Exact concept-match summary completed.",
            )
        return messages
    finally:
        if scratch.exists():
            remove_tree_strict(scratch, context="GLP-1 terminology QA scratch")
        connection.execute("DROP TABLE IF EXISTS concept_match_partial")
        connection.execute("DROP TABLE IF EXISTS source_hash_partial")
        connection.execute("DROP TABLE IF EXISTS source_domain_total")
        connection.execute("DROP TABLE IF EXISTS required_concept_set")


def _stage_domain_matches(
    connection: duckdb.DuckDBPyConnection,
    *,
    domain: str,
    source_table: str,
    output_dir: Path,
) -> None:
    """Write one domain's concept matches to deterministic hash buckets."""

    matches = _domain_match_rows_sql(
        domain=domain,
        source_table=source_table,
        include_bucket=True,
    )
    connection.execute(
        f"""
        COPY (
            {matches}
        ) TO {_sql_string(str(output_dir))} (
            FORMAT PARQUET,
            PARTITION_BY (match_bucket),
            COMPRESSION SNAPPY,
            ROW_GROUP_SIZE 250000
        )
        """
    )


def _reduce_domain_matches_direct(
    connection: duckdb.DuckDBPyConnection,
    *,
    domain: str,
    source_table: str,
) -> None:
    """Reduce a small domain without paying partition I/O overhead."""

    connection.execute(
        f"""
        INSERT INTO source_hash_partial
        SELECT
            {_sql_string(domain)} AS domain,
            count(DISTINCT source_record_hash) AS distinct_source_hashes
        FROM {_identifier(source_table)}
        """
    )

    matches = _domain_match_rows_sql(
        domain=domain,
        source_table=source_table,
        include_bucket=False,
    )
    connection.execute(
        f"""
        INSERT INTO concept_match_partial
        SELECT
            concept_set_id,
            {_sql_string(domain)} AS domain,
            count(DISTINCT source_record_hash) AS matched_rows
        FROM ({matches})
        WHERE concept_set_id IS NOT NULL
        GROUP BY concept_set_id
        """
    )


def _reduce_domain_matches(
    connection: duckdb.DuckDBPyConnection,
    *,
    domain: str,
    partition_root: Path,
) -> None:
    """Count distinct hashes one bounded partition at a time."""

    for bucket in range(_CONCEPT_MATCH_BUCKET_COUNT):
        partition_dir = partition_root / f"match_bucket={bucket}"
        files = sorted(
            path
            for path in partition_dir.glob("*.parquet")
            if not path.name.startswith("._")
        )
        if not files:
            continue
        parquet_paths = ", ".join(_sql_string(str(path)) for path in files)
        connection.execute(
            f"""
            INSERT INTO source_hash_partial
            SELECT
                {_sql_string(domain)} AS domain,
                count(DISTINCT source_record_hash) AS distinct_source_hashes
            FROM read_parquet([{parquet_paths}])
            """
        )
        connection.execute(
            f"""
            INSERT INTO concept_match_partial
            SELECT
                concept_set_id,
                {_sql_string(domain)} AS domain,
                count(DISTINCT source_record_hash) AS matched_rows
            FROM read_parquet([{parquet_paths}])
            WHERE concept_set_id IS NOT NULL
            GROUP BY concept_set_id
            """
        )


def _domain_match_rows_sql(
    *,
    domain: str,
    source_table: str,
    include_bucket: bool,
) -> str:
    bucket_projection = (
        f",\n            hash(source.source_record_hash) % "
        f"{_CONCEPT_MATCH_BUCKET_COUNT} AS match_bucket"
        if include_bucket
        else ""
    )
    return f"""
        SELECT
            concept.concept_set_id,
            source.source_record_hash{bucket_projection}
        FROM {_identifier(source_table)} AS source
        LEFT JOIN concept_set AS concept
          ON concept.domain = {_sql_string(domain)}
         AND concept.include
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
        WHERE source.source_record_hash IS NOT NULL
    """


def _materialize_concept_match_summary(
    connection: duckdb.DuckDBPyConnection,
) -> None:
    connection.execute(
        """
        CREATE OR REPLACE TABLE concept_match_summary AS
        WITH configured AS (
            SELECT DISTINCT concept_set_id, domain
            FROM concept_set WHERE include
        ), totals AS (
            SELECT concept_set_id, domain, sum(matched_rows) AS matched_rows
            FROM concept_match_partial
            GROUP BY concept_set_id, domain
        )
        SELECT
            configured.concept_set_id,
            configured.domain,
            coalesce(totals.matched_rows, 0)::UBIGINT AS matched_rows,
            required.concept_set_id IS NOT NULL AS required
        FROM configured
        LEFT JOIN totals USING (concept_set_id, domain)
        LEFT JOIN required_concept_set AS required USING (concept_set_id)
        ORDER BY configured.domain, configured.concept_set_id
        """
    )


def _materialize_source_duplicate_summary(
    connection: duckdb.DuckDBPyConnection,
) -> None:
    connection.execute(
        """
        CREATE OR REPLACE TABLE source_duplicate_summary AS
        WITH distinct_totals AS (
            SELECT domain, sum(distinct_source_hashes) AS distinct_source_hashes
            FROM source_hash_partial
            GROUP BY domain
        )
        SELECT
            total.domain,
            (
                total.source_rows
                - coalesce(distinct_hash.distinct_source_hashes, 0)
                - CASE WHEN total.null_hash_rows > 0 THEN 1 ELSE 0 END
            )::UBIGINT AS duplicate_rows
        FROM source_domain_total AS total
        LEFT JOIN distinct_totals AS distinct_hash USING (domain)
        ORDER BY total.domain
        """
    )


def _identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _sql_string(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"

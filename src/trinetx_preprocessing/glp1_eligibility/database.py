"""DuckDB metadata and terminology bootstrap for GLP-1 builds."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import duckdb

from .concept_sets import ConceptSetCatalog
from .config import GLP1Config
from .provenance import InputInventory


def initialize_database(
    database_path: Path,
    *,
    run_id: str,
    input_root: Path,
    config: GLP1Config,
    inventory: InputInventory,
    catalog: ConceptSetCatalog,
    git_sha: str,
    concept_catalog_sha256: str,
) -> duckdb.DuckDBPyConnection:
    """Create metadata tables in a new or resumable DuckDB database."""

    database_path.parent.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect(str(database_path))
    connection.execute("SET preserve_insertion_order = false")
    connection.execute(
        f"SET memory_limit = '{config.runtime.duckdb_memory_limit_mib}MiB'"
    )
    connection.execute(f"SET threads = {config.runtime.duckdb_threads}")
    temp_dir = database_path.parent / ".duckdb_tmp"
    temp_dir.mkdir(exist_ok=True)
    connection.execute("SET temp_directory = ?", [str(temp_dir)])

    _create_metadata_schema(connection)
    now = datetime.now(timezone.utc).isoformat()
    connection.execute("DELETE FROM run_manifest")
    connection.execute(
        """
        INSERT INTO run_manifest (
            run_id, run_started_at, run_completed_at, pipeline_git_sha,
            schema_version, rule_set_version, labels_as_of,
            payer_policy_as_of, config_sha256, concept_catalog_sha256,
            input_root, input_manifest_sha256, study_start, study_end,
            source_min_date, source_max_date, status, warning_count, error_count,
            duckdb_memory_limit_mib, duckdb_threads
        ) VALUES (
            ?, ?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL,
            'building', 0, 0, ?, ?
        )
        """,
        [
            run_id,
            now,
            git_sha,
            config.schema_version,
            config.rule_set_version,
            config.labels_as_of.isoformat(),
            config.payer_policy_as_of.isoformat(),
            config.sha256,
            concept_catalog_sha256,
            str(Path(input_root).resolve()),
            inventory.sha256,
            config.study.study_start.isoformat() if config.study.study_start else None,
            config.study.study_end.isoformat() if config.study.study_end else None,
            config.runtime.duckdb_memory_limit_mib,
            config.runtime.duckdb_threads,
        ],
    )

    connection.execute("DELETE FROM source_file_inventory")
    connection.executemany(
        """
        INSERT INTO source_file_inventory VALUES (
            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
        )
        """,
        [
            (
                run_id,
                item.logical_domain,
                item.source_file,
                item.source_file_sha256,
                item.file_size_bytes,
                item.source_mtime_ns,
                item.row_count,
                json.dumps(item.column_names),
                item.detected_schema_version,
                item.min_event_date,
                item.max_event_date,
                item.load_status,
                item.warning,
            )
            for item in inventory.files
        ],
    )

    connection.execute("DELETE FROM concept_set")
    connection.executemany(
        """
        INSERT INTO concept_set VALUES (
            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
        )
        """,
        [
            (
                concept.concept_set_id,
                concept.domain,
                concept.code_system,
                concept.code,
                concept.match_type,
                concept.include,
                concept.description,
                concept.source_authority,
                concept.source_version,
                (
                    concept.effective_start.isoformat()
                    if concept.effective_start
                    else None
                ),
                concept.effective_end.isoformat() if concept.effective_end else None,
                concept.notes,
                concept.source_file,
                concept.source_row,
            )
            for concept in catalog.concepts
        ],
    )
    connection.execute("DELETE FROM phenotype_rule")
    connection.execute(
        "INSERT INTO phenotype_rule VALUES (?, ?, ?)",
        [
            catalog.phenotype_rules["schema_version"],
            catalog.phenotype_rules.get("rule_set_version"),
            json.dumps(catalog.phenotype_rules, sort_keys=True),
        ],
    )
    connection.execute("DELETE FROM build_warning")
    connection.execute("DELETE FROM unmapped_code_frequency")
    if inventory.unmapped_code_frequencies:
        connection.executemany(
            "INSERT INTO unmapped_code_frequency VALUES (?, ?, ?, ?, ?, ?)",
            [
                (
                    run_id,
                    frequency.logical_domain,
                    frequency.code_system,
                    frequency.code,
                    frequency.estimated_count,
                    frequency.max_error,
                )
                for frequency in inventory.unmapped_code_frequencies
            ],
        )
    return connection


def mark_database_complete(connection: duckdb.DuckDBPyConnection) -> None:
    """Mark the single run manifest row complete."""

    connection.execute(
        """
        UPDATE run_manifest
        SET run_completed_at = ?, status = 'complete'
        """,
        [datetime.now(timezone.utc).isoformat()],
    )


def _create_metadata_schema(connection: duckdb.DuckDBPyConnection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS run_manifest (
            run_id VARCHAR PRIMARY KEY,
            run_started_at TIMESTAMPTZ NOT NULL,
            run_completed_at TIMESTAMPTZ,
            pipeline_git_sha VARCHAR NOT NULL,
            schema_version VARCHAR NOT NULL,
            rule_set_version VARCHAR NOT NULL,
            labels_as_of DATE NOT NULL,
            payer_policy_as_of DATE NOT NULL,
            config_sha256 VARCHAR NOT NULL,
            concept_catalog_sha256 VARCHAR NOT NULL,
            input_root VARCHAR NOT NULL,
            input_manifest_sha256 VARCHAR NOT NULL,
            study_start DATE,
            study_end DATE,
            source_min_date TIMESTAMP,
            source_max_date TIMESTAMP,
            status VARCHAR NOT NULL,
            warning_count BIGINT NOT NULL,
            error_count BIGINT NOT NULL,
            duckdb_memory_limit_mib INTEGER,
            duckdb_threads INTEGER
        )
        """
    )
    connection.execute(
        "ALTER TABLE run_manifest ADD COLUMN IF NOT EXISTS "
        "duckdb_memory_limit_mib INTEGER"
    )
    connection.execute(
        "ALTER TABLE run_manifest ADD COLUMN IF NOT EXISTS duckdb_threads INTEGER"
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS source_file_inventory (
            run_id VARCHAR NOT NULL,
            logical_domain VARCHAR NOT NULL,
            source_file VARCHAR NOT NULL,
            source_file_sha256 VARCHAR NOT NULL,
            file_size_bytes UBIGINT NOT NULL,
            source_mtime_ns UBIGINT NOT NULL,
            row_count UBIGINT NOT NULL,
            column_names JSON NOT NULL,
            detected_schema_version VARCHAR NOT NULL,
            min_event_date TIMESTAMP,
            max_event_date TIMESTAMP,
            load_status VARCHAR NOT NULL,
            warning VARCHAR
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS concept_set (
            concept_set_id VARCHAR NOT NULL,
            domain VARCHAR NOT NULL,
            code_system VARCHAR NOT NULL,
            code VARCHAR NOT NULL,
            match_type VARCHAR NOT NULL,
            include BOOLEAN NOT NULL,
            description VARCHAR NOT NULL,
            source_authority VARCHAR NOT NULL,
            source_version VARCHAR NOT NULL,
            effective_start DATE,
            effective_end DATE,
            notes VARCHAR,
            source_file VARCHAR NOT NULL,
            source_row INTEGER NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS phenotype_rule (
            schema_version VARCHAR NOT NULL,
            rule_set_version VARCHAR,
            rules JSON NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS build_warning (
            run_id VARCHAR NOT NULL,
            warning_code VARCHAR NOT NULL,
            message VARCHAR NOT NULL,
            details_json JSON NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS unmapped_code_frequency (
            run_id VARCHAR NOT NULL,
            logical_domain VARCHAR NOT NULL,
            code_system VARCHAR NOT NULL,
            code VARCHAR NOT NULL,
            estimated_count UBIGINT NOT NULL,
            max_error UBIGINT NOT NULL
        )
        """
    )

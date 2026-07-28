"""DuckDB materialization for the canonical combined preprocessing product."""

from __future__ import annotations

import csv
import hashlib
import json
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator, Mapping

import duckdb
import pandas as pd

from .. import __version__
from ..config import DEFAULT_COMBINED_DUCKDB_MEMORY_LIMIT_MIB, Config
from ..filesystem import remove_tree_strict, write_text_atomic
from ..profiling import current_git_code_state_sha256
from ..regression import CsvHashResult
from ..storage import resolve_work_table
from ..work_manifest import work_manifest_path
from .contract import (
    COMBINED_SCHEMA_VERSION,
    DATABASE_MANIFEST_SCHEMA_VERSION,
    PREPROCESSED_ENCOUNTER_TABLE,
    CompatibilityOutput,
    compatibility_outputs,
    final_output_columns,
)
from .elements import (
    CONCEPT_DOMAIN_BY_PIPELINE_DOMAIN,
    ENCOUNTER_FLOW_COLUMNS,
    ENCOUNTER_FLOW_DUCKDB_TYPES,
    MEMBERSHIP_COLUMNS,
    SOURCE_EVENT_COLUMNS,
    SOURCE_EVENT_DUCKDB_TYPES,
    SOURCE_TABLE_BY_DOMAIN,
    catalog_rows,
    load_combined_catalog,
)
from .scratch import COMBINED_DUCKDB_SPILL_PREFIX

COMBINED_MANIFEST_FILENAME = "trinetx_preprocessed_manifest.json"
COMBINED_DUCKDB_THREADS = 1
COMBINED_AVAILABILITY_BUCKET_COUNT = 64
COMBINED_AVAILABILITY_ROW_GROUP_SIZE = 250_000
COMBINED_COUNT_TABLES = (
    PREPROCESSED_ENCOUNTER_TABLE,
    "rfs_membership",
    "element_catalog",
    "element_rule",
    "element_membership",
    "encounter_availability",
    "patient_observability",
    "source_observability_event",
    "compatibility_output_manifest",
    *SOURCE_TABLE_BY_DOMAIN.values(),
    "source_encounter_flow",
)


@contextmanager
def open_combined_database(
    database_path: Path,
    *,
    read_only: bool = False,
    memory_limit_mib: int = DEFAULT_COMBINED_DUCKDB_MEMORY_LIMIT_MIB,
    preserve_insertion_order: bool = False,
) -> Iterator[duckdb.DuckDBPyConnection]:
    """Open a combined-product database with bounded, cleaned spill storage."""

    path = Path(database_path)
    spill_path = path.parent / (
        f"{COMBINED_DUCKDB_SPILL_PREFIX}{path.name}-{uuid.uuid4().hex}"
    )
    connection = duckdb.connect(str(path), read_only=read_only)
    try:
        connection.execute("SET memory_limit = ?", [f"{memory_limit_mib}MiB"])
        connection.execute("SET temp_directory = ?", [str(spill_path)])
        connection.execute(
            "SET preserve_insertion_order = ?",
            [preserve_insertion_order],
        )
        connection.execute("SET threads = ?", [COMBINED_DUCKDB_THREADS])
        yield connection
    finally:
        connection.close()
        if spill_path.exists():
            remove_tree_strict(
                spill_path,
                context="Combined DuckDB spill directory",
            )


def create_combined_database(
    config: Config,
    database_path: Path,
    *,
    compatibility_hashes: Mapping[str, CsvHashResult],
    compatibility_output_dir: Path | None = None,
    published_output_dir: Path | None = None,
) -> dict[str, Any]:
    """Create a complete combined database from current pipeline artifacts."""

    catalog = load_combined_catalog(config)
    work_manifest = _read_work_manifest(config)
    code_state = current_git_code_state_sha256()
    if code_state is None:
        raise RuntimeError("Cannot fingerprint the current pipeline code state.")
    run_id = _combined_run_id(
        work_manifest=work_manifest,
        catalog_sha256=catalog.sha256,
        code_state=code_state,
    )
    database_path.parent.mkdir(parents=True, exist_ok=True)
    with open_combined_database(
        database_path,
        memory_limit_mib=config.combined.duckdb_memory_limit_mib,
        preserve_insertion_order=True,
    ) as connection:
        _create_manifest_table(
            connection,
            config=config,
            published_output_dir=published_output_dir or config.output_dir,
            run_id=run_id,
            code_state=code_state,
            catalog_sha256=catalog.sha256,
            work_manifest=work_manifest,
        )
        _load_compatibility_output_manifest(connection, compatibility_hashes)
        _load_compatibility_observations(
            connection,
            compatibility_output_dir or config.output_dir,
        )
        _load_element_catalog(connection, catalog_rows(catalog))
        _load_source_tables(connection, config)
        _load_encounter_flow(connection, config)
        _load_observability_events(connection, config)

    with open_combined_database(
        database_path,
        memory_limit_mib=config.combined.duckdb_memory_limit_mib,
        preserve_insertion_order=True,
    ) as connection:
        _load_element_membership(connection, config)
        _create_rfs_membership(connection)

    with open_combined_database(
        database_path,
        memory_limit_mib=config.combined.duckdb_memory_limit_mib,
        preserve_insertion_order=True,
    ) as connection:
        _create_availability_tables(connection, config)
        _create_compatibility_views(connection)
        _create_data_dictionary(connection)
        _create_quality_summary(connection)
        connection.execute(
            """
            UPDATE preprocessing_manifest
            SET status = 'complete', completed_at = ?
            """,
            [datetime.now(UTC).isoformat()],
        )
        connection.execute("CHECKPOINT")
        counts = combined_database_counts(connection)
    return {
        "schema_version": DATABASE_MANIFEST_SCHEMA_VERSION,
        "combined_schema_version": COMBINED_SCHEMA_VERSION,
        "run_id": run_id,
        "status": "complete",
        "database": str(database_path),
        "database_size_bytes": database_path.stat().st_size,
        "catalog_sha256": catalog.sha256,
        "git_code_state_sha256": code_state,
        "duckdb_memory_limit_mib": config.combined.duckdb_memory_limit_mib,
        "duckdb_threads": 1,
        "counts": counts,
    }


def write_combined_manifest(
    config: Config,
    payload: dict[str, Any],
    *,
    output_dir: Path | None = None,
) -> Path:
    """Write a PHI-safe sidecar manifest for quick status inspection."""

    path = (output_dir or config.output_dir) / COMBINED_MANIFEST_FILENAME
    write_text_atomic(path, json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return path


def refresh_database_work_manifest_fingerprint(
    database_path: Path,
    config: Config,
) -> None:
    """Synchronize embedded provenance after staged CSV fingerprints change."""

    work_manifest = _read_work_manifest(config)
    work_manifest_sha256 = hashlib.sha256(
        json.dumps(work_manifest, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    with open_combined_database(
        database_path,
        memory_limit_mib=config.combined.duckdb_memory_limit_mib,
    ) as connection:
        connection.execute(
            "UPDATE preprocessing_manifest SET source_work_manifest_sha256 = ?",
            [work_manifest_sha256],
        )
        connection.execute("CHECKPOINT")


def export_compatibility_outputs(
    database_path: Path,
    output_dir: Path,
    *,
    memory_limit_mib: int = DEFAULT_COMBINED_DUCKDB_MEMORY_LIMIT_MIB,
) -> list[Path]:
    """Regenerate all 36 historical CSVs from the canonical database."""

    output_root = Path(output_dir)
    written: list[Path] = []
    with open_combined_database(
        database_path,
        read_only=True,
        memory_limit_mib=memory_limit_mib,
    ) as connection:
        for output in compatibility_outputs():
            destination = output_root / output.relative_path
            destination.parent.mkdir(parents=True, exist_ok=True)
            temporary = destination.with_name(f".{destination.name}.tmp")
            if temporary.exists():
                temporary.unlink()
            query = _compatibility_select_sql(output, include_order=True)
            connection.execute(
                f"COPY ({query}) TO {_sql_string(str(temporary))} "
                "(FORMAT CSV, HEADER true, DELIMITER ',', NULL '')"
            )
            temporary.replace(destination)
            written.append(destination)
    return written


def inspect_combined_database(
    database_path: Path,
    *,
    memory_limit_mib: int = DEFAULT_COMBINED_DUCKDB_MEMORY_LIMIT_MIB,
) -> dict[str, Any]:
    """Return aggregate status and table counts without exposing row data."""

    path = Path(database_path)
    if not path.is_file():
        raise FileNotFoundError(path)
    with open_combined_database(
        path,
        read_only=True,
        memory_limit_mib=memory_limit_mib,
    ) as connection:
        manifest_columns = {
            row[1]
            for row in connection.execute(
                "PRAGMA table_info('preprocessing_manifest')"
            ).fetchall()
        }
        manifest = connection.execute(
            "SELECT * FROM preprocessing_manifest LIMIT 1"
        ).fetchdf()
        if manifest.empty:
            raise ValueError("Combined database has no preprocessing manifest row.")
        row = manifest.iloc[0].to_dict()
        return {
            "database": str(path.resolve()),
            "database_size_bytes": path.stat().st_size,
            "run_id": row.get("run_id"),
            "status": row.get("status"),
            "combined_schema_version": row.get("combined_schema_version"),
            "package_version": row.get("package_version"),
            "completed_at": _json_value(row.get("completed_at")),
            "duckdb_memory_limit_mib": row.get("duckdb_memory_limit_mib"),
            "duckdb_threads": row.get("duckdb_threads"),
            "manifest_columns": sorted(manifest_columns),
            "counts": combined_database_counts(connection),
        }


def _create_manifest_table(
    connection: duckdb.DuckDBPyConnection,
    *,
    config: Config,
    published_output_dir: Path,
    run_id: str,
    code_state: str,
    catalog_sha256: str,
    work_manifest: dict[str, Any],
) -> None:
    connection.execute(
        """
        CREATE TABLE preprocessing_manifest (
            run_id VARCHAR PRIMARY KEY,
            status VARCHAR NOT NULL,
            started_at TIMESTAMPTZ NOT NULL,
            completed_at TIMESTAMPTZ,
            combined_schema_version VARCHAR NOT NULL,
            package_version VARCHAR NOT NULL,
            git_code_state_sha256 VARCHAR NOT NULL,
            source_work_manifest_sha256 VARCHAR NOT NULL,
            element_catalog_sha256 VARCHAR NOT NULL,
            data_root VARCHAR NOT NULL,
            work_root VARCHAR NOT NULL,
            output_root VARCHAR NOT NULL,
            duckdb_memory_limit_mib INTEGER NOT NULL,
            duckdb_threads INTEGER NOT NULL
        )
        """
    )
    work_manifest_sha256 = hashlib.sha256(
        json.dumps(work_manifest, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    connection.execute(
        "INSERT INTO preprocessing_manifest VALUES (?, 'building', ?, NULL, "
        "?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            run_id,
            datetime.now(UTC).isoformat(),
            COMBINED_SCHEMA_VERSION,
            __version__,
            code_state,
            work_manifest_sha256,
            catalog_sha256,
            str(config.data_dir),
            str(config.work_dir),
            str(published_output_dir),
            config.combined.duckdb_memory_limit_mib,
            1,
        ],
    )
    inventory = pd.DataFrame(work_manifest.get("inputs", []))
    if inventory.empty:
        inventory = pd.DataFrame(
            columns=["domain", "path", "size_bytes", "mtime_ns", "header"]
        )
    connection.register("source_inventory_frame", inventory)
    connection.execute(
        "CREATE TABLE source_file_inventory AS SELECT * FROM source_inventory_frame"
    )
    connection.unregister("source_inventory_frame")


def _load_compatibility_observations(
    connection: duckdb.DuckDBPyConnection,
    output_dir: Path,
) -> None:
    columns = final_output_columns()
    column_sql = ", ".join(_identifier(column) for column in columns)
    connection.execute(
        f"""
        CREATE TABLE {PREPROCESSED_ENCOUNTER_TABLE} (
            compatibility_output_key VARCHAR NOT NULL,
            setting VARCHAR NOT NULL,
            rfs_category VARCHAR NOT NULL,
            output_variant VARCHAR NOT NULL,
            source_row_order UBIGINT NOT NULL,
            {", ".join(f"{_identifier(column)} VARCHAR" for column in columns)}
        )
        """
    )
    for output in compatibility_outputs():
        path = output_dir / output.relative_path
        _require_csv_header(path, columns)
        source = (
            f"read_csv({_sql_string(str(path))}, header=true, all_varchar=true, "
            "null_padding=false)"
        )
        connection.execute(
            f"""
            INSERT INTO {PREPROCESSED_ENCOUNTER_TABLE}
            SELECT
                {_sql_string(output.key)},
                {_sql_string(output.setting)},
                {_sql_string(output.category)},
                {_sql_string(output.variant)},
                row_number() OVER () - 1,
                {column_sql}
            FROM {source}
            """
        )


def _load_compatibility_output_manifest(
    connection: duckdb.DuckDBPyConnection,
    hashes: Mapping[str, CsvHashResult],
) -> None:
    expected_keys = {output.key for output in compatibility_outputs()}
    if set(hashes) != expected_keys:
        missing = sorted(expected_keys - set(hashes))
        extra = sorted(set(hashes) - expected_keys)
        raise ValueError(
            "Compatibility hashes do not match the 36-output contract; "
            f"missing={missing}, extra={extra}."
        )
    rows = [
        {
            "compatibility_output_key": output.key,
            "normalized_sha256": hashes[output.key].hash,
            "row_count": hashes[output.key].row_count,
            "columns_json": json.dumps(list(hashes[output.key].columns)),
        }
        for output in compatibility_outputs()
    ]
    frame = pd.DataFrame(rows)
    connection.register("compatibility_manifest_frame", frame)
    connection.execute(
        "CREATE TABLE compatibility_output_manifest AS "
        "SELECT * FROM compatibility_manifest_frame"
    )
    connection.unregister("compatibility_manifest_frame")


def _load_element_catalog(
    connection: duckdb.DuckDBPyConnection,
    rows: list[dict[str, Any]],
) -> None:
    frame = pd.DataFrame(rows)
    connection.register("element_registry_frame", frame)
    connection.execute(
        """
        CREATE TABLE element_catalog AS
        SELECT
            element_id,
            element_kind,
            value_kind,
            legacy_column,
            min(concept_set_id) AS concept_set_id,
            min(domain) AS domain,
            min(description) AS description,
            min(source_authority) AS source_authority,
            min(source_version) AS source_version,
            min(notes) AS notes
        FROM element_registry_frame
        GROUP BY element_id, element_kind, value_kind, legacy_column
        """
    )
    connection.execute(
        """
        CREATE TABLE element_rule AS
        SELECT
            concat(element_id, ':', source_file, ':', source_row) AS rule_id,
            element_id,
            concept_set_id,
            domain,
            code_system,
            code,
            match_type,
            include,
            description,
            source_authority,
            source_version,
            effective_start,
            effective_end,
            notes,
            source_file,
            source_row
        FROM element_registry_frame
        WHERE element_kind = 'source_concept'
        """
    )
    connection.unregister("element_registry_frame")


def _load_source_tables(
    connection: duckdb.DuckDBPyConnection,
    config: Config,
) -> None:
    for domain, table_name in SOURCE_TABLE_BY_DOMAIN.items():
        path = resolve_work_table(config, f"combined_{table_name}.csv")
        if not path.is_file():
            raise FileNotFoundError(
                f"Unified source table is missing for {domain}: {path}"
            )
        _create_source_table_from_work_path(connection, table_name, path)


def _load_encounter_flow(
    connection: duckdb.DuckDBPyConnection,
    config: Config,
) -> None:
    path = resolve_work_table(config, "combined_encounter_flow.csv")
    if not path.is_file():
        raise FileNotFoundError(f"Unified encounter-flow table is missing: {path}")
    source = _work_path_source(path)
    expressions = []
    for column in ENCOUNTER_FLOW_COLUMNS:
        column_type = ENCOUNTER_FLOW_DUCKDB_TYPES[column]
        identifier = _identifier(column)
        expressions.append(f"try_cast({identifier} AS {column_type}) AS {identifier}")
    connection.execute(
        "CREATE TABLE source_encounter_flow AS SELECT "
        + ", ".join(expressions)
        + f" FROM {source}"
    )


def _load_element_membership(
    connection: duckdb.DuckDBPyConnection,
    config: Config,
) -> None:
    connection.execute(
        "CREATE TABLE element_membership ("
        + ", ".join(
            f"{_identifier(column)} "
            + ("BOOLEAN" if column == "include" else "VARCHAR")
            for column in MEMBERSHIP_COLUMNS
        )
        + ")"
    )
    for domain in SOURCE_TABLE_BY_DOMAIN:
        path = resolve_work_table(
            config,
            f"combined_element_membership_{domain}.csv",
        )
        if domain in {"encounter", "patient"} and not path.is_file():
            continue
        if not path.is_file():
            raise FileNotFoundError(
                f"Unified element membership is missing for {domain}: {path}"
            )
        source = _work_path_source(path)
        columns = ", ".join(_identifier(column) for column in MEMBERSHIP_COLUMNS)
        connection.execute(
            f"INSERT INTO element_membership SELECT {columns} FROM {source}"
        )


def _load_observability_events(
    connection: duckdb.DuckDBPyConnection,
    config: Config,
) -> None:
    connection.execute(
        """
        CREATE TABLE source_observability_event (
            patient_id VARCHAR,
            logical_domain VARCHAR,
            event_datetime TIMESTAMP,
            timestamp_precision VARCHAR,
            event_count UBIGINT
        )
        """
    )
    for domain in CONCEPT_DOMAIN_BY_PIPELINE_DOMAIN:
        path = resolve_work_table(config, f"combined_observability_{domain}.csv")
        if not path.is_file():
            raise FileNotFoundError(
                f"Unified observability table is missing for {domain}: {path}"
            )
        source = _work_path_source(path)
        connection.execute(
            """
            INSERT INTO source_observability_event
            SELECT
                patient_id,
                logical_domain,
                try_cast(event_datetime AS TIMESTAMP) AS event_datetime,
                timestamp_precision,
                sum(try_cast(event_count AS UBIGINT))::UBIGINT AS event_count
            FROM
            """
            + source
            + """
            GROUP BY
                patient_id,
                logical_domain,
                event_datetime,
                timestamp_precision
            """
        )


def _create_rfs_membership(connection: duckdb.DuckDBPyConnection) -> None:
    connection.execute(
        f"""
        CREATE TABLE rfs_membership AS
        SELECT
            compatibility_output_key,
            setting,
            rfs_category,
            output_variant,
            source_row_order,
            patient_id,
            encounter_id,
            qualify_date
        FROM {PREPROCESSED_ENCOUNTER_TABLE}
        """
    )


def _create_availability_tables(
    connection: duckdb.DuckDBPyConnection,
    config: Config,
) -> None:
    diagnosis_path = resolve_work_table(
        config,
        "analysis_diagnosis_availability.csv",
    )
    lab_path = resolve_work_table(config, "analysis_lab_availability.csv")
    if not diagnosis_path.is_file() or not lab_path.is_file():
        raise FileNotFoundError(
            "Combined preprocessing requires diagnosis and lab availability indexes."
        )
    _create_encounter_availability(
        connection,
        diagnosis_path=diagnosis_path,
        lab_path=lab_path,
    )
    connection.execute(
        """
        CREATE TABLE patient_observability AS
        SELECT
            patient_id,
            logical_domain,
            sum(event_count)::UBIGINT AS event_count,
            min(event_datetime) AS first_event_datetime,
            max(event_datetime) AS last_event_datetime
        FROM source_observability_event
        GROUP BY patient_id, logical_domain
        """
    )


def _create_encounter_availability(
    connection: duckdb.DuckDBPyConnection,
    *,
    diagnosis_path: Path,
    lab_path: Path,
) -> None:
    """Create exact diagnosis/lab flags through bounded hash partitions."""

    connection.execute("SET preserve_insertion_order = false")
    connection.execute(
        f"SET partitioned_write_max_open_files = {COMBINED_AVAILABILITY_BUCKET_COUNT}"
    )
    spill_root = Path(
        connection.execute("SELECT current_setting('temp_directory')").fetchone()[0]
    )
    spill_root.mkdir(parents=True, exist_ok=True)
    partition_root = spill_root / "encounter-availability"
    try:
        connection.execute(
            f"""
            COPY (
                SELECT
                    encounter_id,
                    1::UTINYINT AS has_diagnosis,
                    0::UTINYINT AS has_lab,
                    hash(encounter_id) % {COMBINED_AVAILABILITY_BUCKET_COUNT}
                        AS availability_bucket
                FROM {_work_path_source(diagnosis_path)}
                WHERE encounter_id IS NOT NULL
                UNION ALL
                SELECT
                    encounter_id,
                    0::UTINYINT AS has_diagnosis,
                    1::UTINYINT AS has_lab,
                    hash(encounter_id) % {COMBINED_AVAILABILITY_BUCKET_COUNT}
                        AS availability_bucket
                FROM {_work_path_source(lab_path)}
                WHERE encounter_id IS NOT NULL
            ) TO {_sql_string(str(partition_root))}
            (
                FORMAT PARQUET,
                PARTITION_BY (availability_bucket),
                COMPRESSION ZSTD,
                ROW_GROUP_SIZE {COMBINED_AVAILABILITY_ROW_GROUP_SIZE}
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE encounter_availability (
                encounter_id VARCHAR NOT NULL,
                has_diagnosis BOOLEAN NOT NULL,
                has_lab BOOLEAN NOT NULL,
                has_diagnosis_or_lab BOOLEAN NOT NULL
            )
            """
        )
        for bucket in range(COMBINED_AVAILABILITY_BUCKET_COUNT):
            bucket_path = (
                partition_root / f"availability_bucket={bucket}" / "data_*.parquet"
            )
            if not any(bucket_path.parent.glob("data_*.parquet")):
                continue
            connection.execute(
                f"""
                INSERT INTO encounter_availability
                SELECT
                    encounter_id,
                    max(has_diagnosis) = 1 AS has_diagnosis,
                    max(has_lab) = 1 AS has_lab,
                    max(has_diagnosis) = 1 OR max(has_lab) = 1
                        AS has_diagnosis_or_lab
                FROM read_parquet({_sql_string(str(bucket_path))})
                GROUP BY encounter_id
                """
            )
    finally:
        if partition_root.exists():
            remove_tree_strict(
                partition_root,
                context="Combined encounter-availability partitions",
            )


def _create_compatibility_views(connection: duckdb.DuckDBPyConnection) -> None:
    for output in compatibility_outputs():
        connection.execute(
            f"CREATE VIEW {_identifier(output.view_name)} AS "
            + _compatibility_select_sql(output, include_order=False)
        )


def _create_data_dictionary(connection: duckdb.DuckDBPyConnection) -> None:
    rows: list[dict[str, str]] = []
    for table_name in (
        "preprocessing_manifest",
        "source_file_inventory",
        "source_encounter_flow",
        PREPROCESSED_ENCOUNTER_TABLE,
        "rfs_membership",
        "element_catalog",
        "element_rule",
        "element_membership",
        "encounter_availability",
        "patient_observability",
        "source_observability_event",
        "compatibility_output_manifest",
        *SOURCE_TABLE_BY_DOMAIN.values(),
    ):
        for column in connection.execute(
            f"PRAGMA table_info({_sql_string(table_name)})"
        ).fetchall():
            rows.append(
                {
                    "table_name": table_name,
                    "column_name": str(column[1]),
                    "data_type": str(column[2]),
                    "description": _column_description(table_name, str(column[1])),
                }
            )
    frame = pd.DataFrame(rows)
    connection.register("data_dictionary_frame", frame)
    connection.execute(
        "CREATE TABLE data_dictionary AS SELECT * FROM data_dictionary_frame"
    )
    connection.unregister("data_dictionary_frame")


def _create_quality_summary(connection: duckdb.DuckDBPyConnection) -> None:
    rows = []
    for table_name in (
        "preprocessing_manifest",
        "source_file_inventory",
        "source_encounter_flow",
        PREPROCESSED_ENCOUNTER_TABLE,
        "rfs_membership",
        "element_catalog",
        "element_rule",
        "element_membership",
        "encounter_availability",
        "patient_observability",
        "source_observability_event",
        "compatibility_output_manifest",
        *SOURCE_TABLE_BY_DOMAIN.values(),
    ):
        count = int(
            connection.execute(
                f"SELECT count(*) FROM {_identifier(table_name)}"
            ).fetchone()[0]
        )
        rows.append((table_name, count))
    connection.execute(
        "CREATE TABLE preprocessing_quality_summary "
        "(metric VARCHAR NOT NULL, value UBIGINT NOT NULL)"
    )
    connection.executemany(
        "INSERT INTO preprocessing_quality_summary VALUES (?, ?)",
        [(f"rows.{name}", count) for name, count in rows],
    )


def combined_database_counts(
    connection: duckdb.DuckDBPyConnection,
) -> dict[str, int]:
    """Return the exact aggregate table-count contract stored in the sidecar."""

    return {
        table: int(
            connection.execute(f"SELECT count(*) FROM {_identifier(table)}").fetchone()[
                0
            ]
        )
        for table in COMBINED_COUNT_TABLES
    }


def _compatibility_select_sql(
    output: CompatibilityOutput,
    *,
    include_order: bool,
) -> str:
    columns = ", ".join(_identifier(column) for column in final_output_columns())
    query = (
        f"SELECT {columns} FROM {PREPROCESSED_ENCOUNTER_TABLE} "
        f"WHERE compatibility_output_key = {_sql_string(output.key)}"
    )
    if include_order:
        query += " ORDER BY source_row_order"
    return query


def _create_table_from_work_path(
    connection: duckdb.DuckDBPyConnection,
    table_name: str,
    path: Path,
) -> None:
    connection.execute(
        f"CREATE TABLE {_identifier(table_name)} AS SELECT * FROM "
        f"{_work_path_source(path)}"
    )


def _create_source_table_from_work_path(
    connection: duckdb.DuckDBPyConnection,
    table_name: str,
    path: Path,
) -> None:
    source = _work_path_source(path)
    expressions = []
    for column in SOURCE_EVENT_COLUMNS:
        column_type = SOURCE_EVENT_DUCKDB_TYPES[column]
        identifier = _identifier(column)
        if column_type == "VARCHAR":
            expressions.append(f"cast({identifier} AS VARCHAR) AS {identifier}")
        else:
            expressions.append(
                f"try_cast({identifier} AS {column_type}) AS {identifier}"
            )
    connection.execute(
        f"CREATE TABLE {_identifier(table_name)} AS SELECT "
        + ", ".join(expressions)
        + f" FROM {source}"
    )


def _work_path_source(path: Path) -> str:
    if path.suffix.lower() == ".parquet":
        return f"read_parquet({_sql_string(str(path))})"
    return (
        f"read_csv({_sql_string(str(path))}, header=true, all_varchar=true, "
        "null_padding=false)"
    )


def _require_csv_header(path: Path, columns: tuple[str, ...]) -> None:
    if not path.is_file():
        raise FileNotFoundError(f"Missing compatibility output: {path}")
    with path.open(newline="", encoding="utf-8-sig") as handle:
        header = tuple(next(csv.reader(handle), ()))
    if header != columns:
        raise ValueError(
            f"Compatibility output schema mismatch for {path}: "
            f"expected {len(columns)} ordered columns, found {len(header)}."
        )


def _read_work_manifest(config: Config) -> dict[str, Any]:
    path = work_manifest_path(config)
    if not path.is_file():
        raise FileNotFoundError(f"Missing current pipeline work manifest: {path}")
    payload = json.loads(path.read_text())
    if not isinstance(payload, dict):
        raise ValueError(f"Invalid pipeline work manifest: {path}")
    return payload


def _combined_run_id(
    *,
    work_manifest: dict[str, Any],
    catalog_sha256: str,
    code_state: str,
) -> str:
    stable_work_identity = {
        key: work_manifest.get(key)
        for key in (
            "schema_version",
            "intermediate_schema_version",
            "package_version",
            "git_code_state_sha256",
            "runtime_versions",
            "ruleset",
            "combined_element_catalog_sha256",
            "config_hash",
            "inputs",
        )
    }
    payload = json.dumps(
        {
            "combined_schema_version": COMBINED_SCHEMA_VERSION,
            "work_identity": stable_work_identity,
            "element_catalog_sha256": catalog_sha256,
            "git_code_state_sha256": code_state,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode()).hexdigest()[:24]


def _column_description(table_name: str, column_name: str) -> str:
    if (
        table_name == PREPROCESSED_ENCOUNTER_TABLE
        and column_name in final_output_columns()
    ):
        return f"Historical 534-column compatibility field: {column_name}."
    if column_name == "source_record_id":
        return "Stable file-and-row source record identifier."
    if column_name == "patient_id":
        return "Source patient identifier; confidential row-level field."
    if column_name == "encounter_id":
        return "Source encounter identifier; confidential row-level field."
    return f"{table_name}.{column_name}."


def _identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _sql_string(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _json_value(value: Any) -> Any:
    if value is None or pd.isna(value):
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value

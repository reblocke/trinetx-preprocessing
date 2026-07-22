"""Aggregate contract validation for combined preprocessing databases."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import duckdb

from ..regression import hash_csv_with_metadata
from .contract import (
    COMBINED_SCHEMA_VERSION,
    PREPROCESSED_ENCOUNTER_TABLE,
    compatibility_outputs,
    final_output_columns,
)
from .elements import (
    SOURCE_EVENT_COLUMNS,
    SOURCE_EVENT_DUCKDB_TYPES,
    SOURCE_TABLE_BY_DOMAIN,
)


@dataclass(frozen=True)
class CombinedValidationResult:
    """PHI-safe aggregate validation result."""

    valid: bool
    errors: tuple[str, ...]
    warnings: tuple[str, ...]
    counts: dict[str, int]


def validate_preprocessed_database(
    database_path: Path,
    *,
    compatibility_output_dir: Path | None = None,
) -> CombinedValidationResult:
    """Validate schema, referential integrity, and optional CSV exports."""

    path = Path(database_path)
    if not path.is_file():
        return CombinedValidationResult(
            valid=False,
            errors=(f"Database does not exist: {path}",),
            warnings=(),
            counts={},
        )

    errors: list[str] = []
    warnings: list[str] = []
    counts: dict[str, int] = {}
    connection = duckdb.connect(str(path), read_only=True)
    try:
        required_tables = {
            "preprocessing_manifest",
            PREPROCESSED_ENCOUNTER_TABLE,
            "rfs_membership",
            "source_file_inventory",
            "element_catalog",
            "element_rule",
            "element_membership",
            "encounter_availability",
            "patient_observability",
            "source_observability_event",
            "data_dictionary",
            "preprocessing_quality_summary",
            "compatibility_output_manifest",
            *SOURCE_TABLE_BY_DOMAIN.values(),
        }
        existing = {
            str(row[0])
            for row in connection.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'main'"
            ).fetchall()
        }
        missing_tables = sorted(required_tables - existing)
        if missing_tables:
            errors.append("Missing required tables: " + ", ".join(missing_tables))
            return CombinedValidationResult(False, tuple(errors), (), counts)

        manifest = connection.execute(
            "SELECT status, combined_schema_version, count(*) "
            "FROM preprocessing_manifest GROUP BY ALL"
        ).fetchall()
        if len(manifest) != 1:
            errors.append("preprocessing_manifest must contain exactly one run.")
        else:
            status, schema_version, manifest_count = manifest[0]
            if status != "complete":
                errors.append(f"Database status is not complete: {status}")
            if schema_version != COMBINED_SCHEMA_VERSION:
                errors.append(
                    "Combined schema version mismatch: "
                    f"{schema_version} != {COMBINED_SCHEMA_VERSION}"
                )
            if int(manifest_count) != 1:
                errors.append("preprocessing_manifest contains duplicate rows.")

        encounter_columns = _table_columns(connection, PREPROCESSED_ENCOUNTER_TABLE)
        expected_metadata = (
            "compatibility_output_key",
            "setting",
            "rfs_category",
            "output_variant",
            "source_row_order",
        )
        expected_columns = (*expected_metadata, *final_output_columns())
        if encounter_columns != expected_columns:
            errors.append("preprocessed_encounter ordered schema is invalid.")

        observation_count = _count(connection, PREPROCESSED_ENCOUNTER_TABLE)
        counts[PREPROCESSED_ENCOUNTER_TABLE] = observation_count
        membership_count = _count(connection, "rfs_membership")
        counts["rfs_membership"] = membership_count
        if membership_count != observation_count:
            errors.append(
                "rfs_membership does not reconcile to encounter observations."
            )

        inconsistent_rfs = int(
            connection.execute(
                f"SELECT count(*) FROM {PREPROCESSED_ENCOUNTER_TABLE} "
                "WHERE coalesce(RFS, '') <> rfs_category"
            ).fetchone()[0]
        )
        if inconsistent_rfs:
            errors.append(
                f"{inconsistent_rfs} observations disagree with RFS membership."
            )

        output_keys = {output.key for output in compatibility_outputs()}
        observed_keys = {
            str(row[0])
            for row in connection.execute(
                f"SELECT DISTINCT compatibility_output_key "
                f"FROM {PREPROCESSED_ENCOUNTER_TABLE}"
            ).fetchall()
        }
        unknown_keys = sorted(observed_keys - output_keys)
        if unknown_keys:
            errors.append("Unexpected compatibility output keys are present.")

        compatibility_manifest = {
            str(key): (str(hash_value), int(row_count), tuple(json.loads(columns)))
            for key, hash_value, row_count, columns in connection.execute(
                "SELECT compatibility_output_key, normalized_sha256, row_count, "
                "columns_json FROM compatibility_output_manifest"
            ).fetchall()
        }
        if set(compatibility_manifest) != output_keys:
            errors.append(
                "compatibility_output_manifest does not contain exactly 36 outputs."
            )

        for output in compatibility_outputs():
            view_columns = _table_columns(connection, output.view_name)
            if view_columns != final_output_columns():
                errors.append(f"Compatibility view schema mismatch: {output.view_name}")
            count = int(
                connection.execute(
                    f"SELECT count(*) FROM {_identifier(output.view_name)}"
                ).fetchone()[0]
            )
            counts[f"compatibility.{output.key}"] = count
            expected = compatibility_manifest.get(output.key)
            if expected is not None:
                _, expected_count, expected_columns = expected
                if count != expected_count:
                    errors.append(
                        f"Compatibility view row count mismatch: {output.key}"
                    )
                if expected_columns != final_output_columns():
                    errors.append(
                        f"Stored compatibility schema mismatch: {output.key}"
                    )

        source_union = " UNION ALL ".join(
            f"SELECT source_record_id FROM {_identifier(table_name)}"
            for table_name in SOURCE_TABLE_BY_DOMAIN.values()
        )
        orphan_memberships = int(
            connection.execute(
                "SELECT count(*) FROM element_membership AS membership "
                f"LEFT JOIN ({source_union}) AS source USING (source_record_id) "
                "WHERE source.source_record_id IS NULL"
            ).fetchone()[0]
        )
        if orphan_memberships:
            errors.append(
                f"element_membership contains {orphan_memberships} orphan rows."
            )

        duplicate_source_ids = int(
            connection.execute(
                "SELECT count(*) FROM ("
                "SELECT source_record_id FROM ("
                + source_union
                + ") GROUP BY source_record_id HAVING count(*) > 1)"
            ).fetchone()[0]
        )
        if duplicate_source_ids:
            errors.append(
                f"Source tables contain {duplicate_source_ids} duplicate record IDs."
            )

        for domain, table_name in SOURCE_TABLE_BY_DOMAIN.items():
            count = _count(connection, table_name)
            counts[table_name] = count
            observed_schema = _table_schema(connection, table_name)
            expected_schema = tuple(
                (column, SOURCE_EVENT_DUCKDB_TYPES[column])
                for column in SOURCE_EVENT_COLUMNS
            )
            if observed_schema != expected_schema:
                errors.append(f"{table_name} ordered typed schema is invalid.")
            missing_provenance = int(
                connection.execute(
                    f"SELECT count(*) FROM {_identifier(table_name)} "
                    "WHERE source_record_id IS NULL OR source_file IS NULL "
                    "OR source_row_number IS NULL"
                ).fetchone()[0]
            )
            if missing_provenance:
                errors.append(
                    f"{table_name} has {missing_provenance} rows without provenance."
                )
            if count == 0 and domain in {"labs", "encounter", "patient"}:
                warnings.append(f"Required source table is empty: {table_name}")

        catalog_count = _count(connection, "element_catalog")
        counts["element_catalog"] = catalog_count
        rule_count = _count(connection, "element_rule")
        counts["element_rule"] = rule_count
        membership_rows = _count(connection, "element_membership")
        counts["element_membership"] = membership_rows
        duplicate_elements = int(
            connection.execute(
                "SELECT count(*) FROM (SELECT element_id FROM element_catalog "
                "GROUP BY element_id HAVING count(*) > 1)"
            ).fetchone()[0]
        )
        if duplicate_elements:
            errors.append(
                f"element_catalog contains {duplicate_elements} duplicate element IDs."
            )
        unknown_elements = int(
            connection.execute(
                "SELECT count(*) FROM element_membership AS membership "
                "LEFT JOIN element_catalog AS catalog USING (element_id) "
                "WHERE catalog.element_id IS NULL"
            ).fetchone()[0]
        )
        if unknown_elements:
            errors.append(
                f"element_membership references {unknown_elements} unknown elements."
            )

        if compatibility_output_dir is not None:
            _validate_compatibility_files(
                connection,
                Path(compatibility_output_dir),
                errors,
                counts,
                compatibility_manifest,
            )
    finally:
        connection.close()
    return CombinedValidationResult(
        valid=not errors,
        errors=tuple(errors),
        warnings=tuple(warnings),
        counts=counts,
    )


def _validate_compatibility_files(
    connection: duckdb.DuckDBPyConnection,
    output_dir: Path,
    errors: list[str],
    counts: dict[str, int],
    compatibility_manifest: dict[str, tuple[str, int, tuple[str, ...]]],
) -> None:
    for output in compatibility_outputs():
        path = output_dir / output.relative_path
        if not path.is_file():
            errors.append(f"Missing compatibility CSV: {output.key}")
            continue
        metadata = hash_csv_with_metadata(path)
        counts[f"csv.{output.key}"] = metadata.row_count
        database_count = int(
            connection.execute(
                f"SELECT count(*) FROM {_identifier(output.view_name)}"
            ).fetchone()[0]
        )
        if metadata.row_count != database_count:
            errors.append(f"Compatibility CSV row count mismatch: {output.key}")
        if metadata.columns != final_output_columns():
            errors.append(f"Compatibility CSV schema mismatch: {output.key}")
        expected = compatibility_manifest.get(output.key)
        if expected is None:
            continue
        expected_hash, expected_count, expected_columns = expected
        if metadata.hash != expected_hash:
            errors.append(f"Compatibility CSV hash mismatch: {output.key}")
        if metadata.row_count != expected_count:
            errors.append(
                f"Compatibility CSV stored row count mismatch: {output.key}"
            )
        if metadata.columns != expected_columns:
            errors.append(f"Compatibility CSV stored schema mismatch: {output.key}")


def _table_columns(
    connection: duckdb.DuckDBPyConnection,
    table_name: str,
) -> tuple[str, ...]:
    return tuple(
        str(row[1])
        for row in connection.execute(
            f"PRAGMA table_info({_sql_string(table_name)})"
        ).fetchall()
    )


def _table_schema(
    connection: duckdb.DuckDBPyConnection,
    table_name: str,
) -> tuple[tuple[str, str], ...]:
    return tuple(
        (str(row[1]), str(row[2]).upper())
        for row in connection.execute(
            f"PRAGMA table_info({_sql_string(table_name)})"
        ).fetchall()
    )


def _count(connection: duckdb.DuckDBPyConnection, table_name: str) -> int:
    return int(
        connection.execute(
            f"SELECT count(*) FROM {_identifier(table_name)}"
        ).fetchone()[0]
    )


def _identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _sql_string(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"

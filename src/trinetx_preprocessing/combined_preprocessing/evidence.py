"""PHI-safe aggregate evidence for the combined preprocessing contract."""

from __future__ import annotations

import json
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb

from ..filesystem import remove_tree_strict, write_text_atomic
from ..regression import hash_csv_with_metadata
from .contract import compatibility_outputs, final_output_columns
from .database import inspect_combined_database, open_combined_database
from .scratch import COMBINED_VALIDATION_PREFIX
from .validation import validate_preprocessed_database

EVIDENCE_SCHEMA_VERSION = 1
_DIRECT_ELEMENT_MEMBERSHIP_MAX_ROWS = 2_000_000
_ELEMENT_MEMBERSHIP_BUCKET_COUNT = 64


def capture_compatibility_evidence(output_dir: Path) -> dict[str, Any]:
    """Hash the exact 36-file compatibility contract without retaining row data."""

    tables = []
    for output in compatibility_outputs():
        metadata = hash_csv_with_metadata(Path(output_dir) / output.relative_path)
        if metadata.columns != final_output_columns():
            raise ValueError(f"Compatibility schema mismatch: {output.key}")
        tables.append(
            {
                "key": output.key,
                "normalized_sha256": metadata.hash,
                "row_count": metadata.row_count,
                "columns": list(metadata.columns),
            }
        )
    return {
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "scope": "combined_compatibility_outputs",
        "table_count": len(tables),
        "total_rows": sum(int(table["row_count"]) for table in tables),
        "tables": tables,
    }


def verify_compatibility_evidence(
    database_path: Path,
    output_dir: Path,
    baseline_path: Path,
) -> dict[str, Any]:
    """Compare current compatibility CSVs to a prior aggregate baseline."""

    baseline = _load_compatibility_evidence(baseline_path)
    current = capture_compatibility_evidence(output_dir)
    baseline_tables = _tables_by_key(baseline)
    current_tables = _tables_by_key(current)
    missing = sorted(set(baseline_tables) - set(current_tables))
    extra = sorted(set(current_tables) - set(baseline_tables))
    shared = sorted(set(baseline_tables) & set(current_tables))
    hash_mismatched = [
        key
        for key in shared
        if baseline_tables[key]["normalized_sha256"]
        != current_tables[key]["normalized_sha256"]
    ]
    row_count_mismatched = [
        key
        for key in shared
        if baseline_tables[key]["row_count"] != current_tables[key]["row_count"]
    ]
    columns_mismatched = [
        key
        for key in shared
        if baseline_tables[key]["columns"] != current_tables[key]["columns"]
    ]
    database_validation = validate_preprocessed_database(
        database_path,
        compatibility_output_dir=output_dir,
    )
    exact = not (
        missing
        or extra
        or hash_mismatched
        or row_count_mismatched
        or columns_mismatched
    )
    return {
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "ready": exact and database_validation.valid,
        "database": inspect_combined_database(database_path),
        "database_validation": {
            "valid": database_validation.valid,
            "errors": list(database_validation.errors),
            "warnings": list(database_validation.warnings),
        },
        "baseline_table_count": int(baseline["table_count"]),
        "current_table_count": int(current["table_count"]),
        "baseline_total_rows": int(baseline["total_rows"]),
        "current_total_rows": int(current["total_rows"]),
        "missing": missing,
        "extra": extra,
        "hash_mismatched": hash_mismatched,
        "row_count_mismatched": row_count_mismatched,
        "columns_mismatched": columns_mismatched,
    }


def inspect_element_completeness(database_path: Path) -> dict[str, Any]:
    """Summarize catalog, rule, and observed-membership coverage without IDs."""

    path = Path(database_path)
    validation = validate_preprocessed_database(path)
    if not path.is_file():
        return {
            "schema_version": EVIDENCE_SCHEMA_VERSION,
            "generated_at": datetime.now(UTC).isoformat(),
            "complete": False,
            "errors": list(validation.errors),
        }
    with open_combined_database(path, read_only=True) as connection:
        catalog_rows = connection.execute(
            """
            WITH rule_counts AS (
                SELECT
                    element_id,
                    count(*)::BIGINT AS rule_count,
                    count(*) FILTER (WHERE include)::BIGINT AS include_rule_count
                FROM element_rule
                GROUP BY element_id
            )
            SELECT
                catalog.element_id,
                catalog.concept_set_id,
                catalog.domain,
                catalog.description,
                coalesce(rules.rule_count, 0) AS rule_count,
                coalesce(rules.include_rule_count, 0) AS include_rule_count
            FROM element_catalog AS catalog
            LEFT JOIN rule_counts AS rules USING (element_id)
            WHERE catalog.element_kind = 'source_concept'
            ORDER BY catalog.domain, catalog.element_id
            """
        ).fetchall()
        membership_row_count = int(
            connection.execute("SELECT count(*) FROM element_membership").fetchone()[0]
        )
        membership_counts = {
            str(row[0]): int(row[1])
            for row in connection.execute(
                "SELECT element_id, count(*)::BIGINT FROM element_membership "
                "GROUP BY element_id"
            ).fetchall()
        }
        matched_source_counts = _count_distinct_membership_sources(
            connection,
            membership_row_count=membership_row_count,
        )
        elements = [
            {
                "element_id": str(row[0]),
                "concept_set_id": str(row[1]),
                "domain": str(row[2]),
                "description": str(row[3]),
                "rule_count": int(row[4]),
                "include_rule_count": int(row[5]),
                "membership_count": membership_counts.get(str(row[0]), 0),
                "matched_source_record_count": matched_source_counts.get(
                    str(row[0]),
                    0,
                ),
            }
            for row in catalog_rows
        ]
        historical_count = int(
            connection.execute(
                "SELECT count(*) FROM element_catalog "
                "WHERE element_kind = 'historical_derived'"
            ).fetchone()[0]
        )
    missing_rules = [
        element["element_id"] for element in elements if int(element["rule_count"]) == 0
    ]
    missing_included_rules = [
        element["element_id"]
        for element in elements
        if int(element["include_rule_count"]) == 0
    ]
    unobserved = [
        element["element_id"]
        for element in elements
        if int(element["membership_count"]) == 0
    ]
    return {
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "complete": validation.valid
        and not missing_included_rules
        and historical_count == len(final_output_columns()),
        "database_validation_errors": list(validation.errors),
        "database_validation_warnings": list(validation.warnings),
        "source_element_count": len(elements),
        "source_rule_count": sum(int(element["rule_count"]) for element in elements),
        "source_include_rule_count": sum(
            int(element["include_rule_count"]) for element in elements
        ),
        "historical_element_count": historical_count,
        "elements_without_rules": missing_rules,
        "elements_without_included_rules": missing_included_rules,
        "elements_without_observed_matches": unobserved,
        "elements": elements,
    }


def _count_distinct_membership_sources(
    connection: duckdb.DuckDBPyConnection,
    *,
    membership_row_count: int,
) -> dict[str, int]:
    """Count exact distinct source records per element with bounded memory."""

    if membership_row_count <= _DIRECT_ELEMENT_MEMBERSHIP_MAX_ROWS:
        return {
            str(row[0]): int(row[1])
            for row in connection.execute(
                "SELECT element_id, count(DISTINCT source_record_id)::BIGINT "
                "FROM element_membership GROUP BY element_id"
            ).fetchall()
        }

    temp_directory = Path(
        str(
            connection.execute("SELECT current_setting('temp_directory')").fetchone()[0]
        )
    )
    temp_directory.mkdir(parents=True, exist_ok=True)
    scratch = Path(
        tempfile.mkdtemp(
            prefix=COMBINED_VALIDATION_PREFIX,
            dir=temp_directory,
        )
    )
    partition_root = scratch / "membership"
    matched_source_counts: dict[str, int] = {}
    try:
        connection.execute(
            f"""
            COPY (
                SELECT
                    element_id,
                    source_record_id,
                    hash(source_record_id) % {_ELEMENT_MEMBERSHIP_BUCKET_COUNT}
                        AS source_bucket
                FROM element_membership
                WHERE source_record_id IS NOT NULL
            ) TO {_sql_string(str(partition_root))} (
                FORMAT PARQUET,
                PARTITION_BY (source_bucket),
                COMPRESSION SNAPPY,
                ROW_GROUP_SIZE 250000
            )
            """
        )
        for bucket in range(_ELEMENT_MEMBERSHIP_BUCKET_COUNT):
            bucket_directory = partition_root / f"source_bucket={bucket}"
            files = sorted(
                path
                for path in bucket_directory.glob("*.parquet")
                if not path.name.startswith("._")
            )
            if not files:
                continue
            paths = ", ".join(_sql_string(str(path)) for path in files)
            rows = connection.execute(
                "SELECT element_id, count(*)::BIGINT FROM ("
                "SELECT element_id, source_record_id "
                f"FROM read_parquet([{paths}], hive_partitioning=false) "
                "GROUP BY element_id, source_record_id) "
                "GROUP BY element_id"
            ).fetchall()
            for element_id, distinct_count in rows:
                key = str(element_id)
                matched_source_counts[key] = matched_source_counts.get(key, 0) + int(
                    distinct_count
                )
    finally:
        if scratch.exists():
            remove_tree_strict(
                scratch,
                context="Combined element-completeness scratch",
            )
    return matched_source_counts


def write_evidence(path: Path, payload: dict[str, Any]) -> Path:
    """Write an aggregate evidence payload atomically."""

    destination = Path(path)
    write_text_atomic(destination, json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return destination


def _load_compatibility_evidence(path: Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text())
    if not isinstance(payload, dict):
        raise ValueError(f"Invalid compatibility evidence: {path}")
    if payload.get("schema_version") != EVIDENCE_SCHEMA_VERSION:
        raise ValueError(f"Unsupported compatibility evidence schema: {path}")
    if payload.get("scope") != "combined_compatibility_outputs":
        raise ValueError(f"Unexpected compatibility evidence scope: {path}")
    tables = payload.get("tables")
    if not isinstance(tables, list) or len(tables) != len(compatibility_outputs()):
        raise ValueError(f"Compatibility evidence must contain 36 tables: {path}")
    return payload


def _tables_by_key(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    tables = payload["tables"]
    result = {str(table["key"]): table for table in tables}
    if len(result) != len(tables):
        raise ValueError("Compatibility evidence contains duplicate table keys.")
    return result


def _sql_string(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"

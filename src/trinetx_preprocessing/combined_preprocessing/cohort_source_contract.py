"""Versioned table contract for downstream cohort-source consumers.

This module intentionally contains only stable, row-level source surfaces.
Historical compatibility views and pipeline work tables remain implementation
details of combined preprocessing rather than consumer dependencies.
"""

from __future__ import annotations

import hashlib
import json

from .elements import (
    ENCOUNTER_FLOW_COLUMNS,
    ENCOUNTER_FLOW_DUCKDB_TYPES,
    MEMBERSHIP_COLUMNS,
    SOURCE_EVENT_COLUMNS,
    SOURCE_EVENT_DUCKDB_TYPES,
    SOURCE_TABLE_BY_DOMAIN,
)

COHORT_SOURCE_SCHEMA_VERSION = "1.0"

_SOURCE_EVENT_SCHEMA = tuple(
    (column, SOURCE_EVENT_DUCKDB_TYPES[column]) for column in SOURCE_EVENT_COLUMNS
)

_PREPROCESSING_MANIFEST_SCHEMA = (
    ("run_id", "VARCHAR"),
    ("status", "VARCHAR"),
    ("started_at", "TIMESTAMP WITH TIME ZONE"),
    ("completed_at", "TIMESTAMP WITH TIME ZONE"),
    ("combined_schema_version", "VARCHAR"),
    ("cohort_source_schema_version", "VARCHAR"),
    ("cohort_source_schema_sha256", "VARCHAR"),
    ("cohort_source_catalog_sha256", "VARCHAR"),
    ("glp1_catalog_sha256", "VARCHAR"),
    ("package_version", "VARCHAR"),
    ("git_code_state_sha256", "VARCHAR"),
    ("source_work_manifest_sha256", "VARCHAR"),
    ("element_catalog_sha256", "VARCHAR"),
    ("data_root", "VARCHAR"),
    ("work_root", "VARCHAR"),
    ("output_root", "VARCHAR"),
    ("duckdb_memory_limit_mib", "INTEGER"),
    ("duckdb_core_memory_limit_mib", "INTEGER"),
    ("duckdb_threads", "INTEGER"),
)

COHORT_SOURCE_TABLE_SCHEMAS: dict[str, tuple[tuple[str, str], ...]] = {
    "preprocessing_manifest": _PREPROCESSING_MANIFEST_SCHEMA,
    "source_file_inventory": (
        ("domain", "VARCHAR"),
        ("path", "VARCHAR"),
        ("size_bytes", "UBIGINT"),
        ("mtime_ns", "UBIGINT"),
        ("header", "VARCHAR"),
    ),
    "source_patient": _SOURCE_EVENT_SCHEMA,
    "source_encounter": _SOURCE_EVENT_SCHEMA,
    **{
        table_name: _SOURCE_EVENT_SCHEMA
        for domain, table_name in SOURCE_TABLE_BY_DOMAIN.items()
        if domain not in {"encounter", "patient"}
    },
    "source_encounter_flow": tuple(
        (column, ENCOUNTER_FLOW_DUCKDB_TYPES[column])
        for column in ENCOUNTER_FLOW_COLUMNS
    ),
    "element_catalog": (
        ("element_id", "VARCHAR"),
        ("element_kind", "VARCHAR"),
        ("value_kind", "VARCHAR"),
        ("legacy_column", "VARCHAR"),
        ("concept_set_id", "VARCHAR"),
        ("domain", "VARCHAR"),
        ("description", "VARCHAR"),
        ("source_authority", "VARCHAR"),
        ("source_version", "VARCHAR"),
        ("notes", "VARCHAR"),
    ),
    "element_rule": (
        ("rule_id", "VARCHAR"),
        ("element_id", "VARCHAR"),
        ("concept_set_id", "VARCHAR"),
        ("domain", "VARCHAR"),
        ("code_system", "VARCHAR"),
        ("code", "VARCHAR"),
        ("match_type", "VARCHAR"),
        ("include", "BOOLEAN"),
        ("description", "VARCHAR"),
        ("source_authority", "VARCHAR"),
        ("source_version", "VARCHAR"),
        ("effective_start", "DATE"),
        ("effective_end", "DATE"),
        ("notes", "VARCHAR"),
        ("source_file", "VARCHAR"),
        ("source_row", "BIGINT"),
    ),
    "element_membership": tuple(
        (column, "BOOLEAN" if column == "include" else "VARCHAR")
        for column in MEMBERSHIP_COLUMNS
    ),
    "source_observability_event": (
        ("patient_id", "VARCHAR"),
        ("logical_domain", "VARCHAR"),
        ("event_datetime", "TIMESTAMP"),
        ("timestamp_precision", "VARCHAR"),
        ("event_count", "UBIGINT"),
    ),
    "patient_observability": (
        ("patient_id", "VARCHAR"),
        ("logical_domain", "VARCHAR"),
        ("event_count", "UBIGINT"),
        ("first_event_datetime", "TIMESTAMP"),
        ("last_event_datetime", "TIMESTAMP"),
    ),
    "encounter_availability": (
        ("encounter_id", "VARCHAR"),
        ("has_diagnosis", "BOOLEAN"),
        ("has_lab", "BOOLEAN"),
        ("has_diagnosis_or_lab", "BOOLEAN"),
    ),
}
COHORT_SOURCE_TABLES = tuple(COHORT_SOURCE_TABLE_SCHEMAS)


def cohort_source_schema_sha256() -> str:
    """Return the canonical digest of the public cohort-source table schema."""

    payload = json.dumps(
        {
            "schema_version": COHORT_SOURCE_SCHEMA_VERSION,
            "tables": COHORT_SOURCE_TABLE_SCHEMAS,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(payload).hexdigest()

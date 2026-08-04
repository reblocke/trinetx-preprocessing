"""Read-only, versioned access to canonical cohort-source data.

The cohort-source surface deliberately stops at validated source data and
provenance. It does not construct cohorts or encode study-specific inclusion
logic, so downstream studies can evolve independently while retaining a
single, inspectable source product.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import duckdb

from ..config import DEFAULT_COMBINED_DUCKDB_MEMORY_LIMIT_MIB
from .builder import require_safe_output_location
from .cohort_source_contract import (
    COHORT_SOURCE_SCHEMA_VERSION,
    COHORT_SOURCE_TABLE_SCHEMAS,
    cohort_source_schema_sha256,
)
from .contract import COMBINED_SCHEMA_VERSION, DATABASE_MANIFEST_SCHEMA_VERSION
from .database import COMBINED_MANIFEST_FILENAME, open_combined_database


@dataclass(frozen=True)
class CohortSourceMetadata:
    """Versioned provenance required before a cohort consumer reads rows."""

    database_path: Path
    database_size_bytes: int
    run_id: str
    completed_at: str
    combined_schema_version: str
    cohort_source_schema_version: str
    cohort_source_schema_sha256: str
    cohort_source_catalog_sha256: str
    glp1_catalog_sha256: str
    package_version: str
    git_code_state_sha256: str
    source_work_manifest_sha256: str

    def to_dict(self) -> dict[str, str | int]:
        """Return a JSON-ready, PHI-safe metadata payload."""

        return {
            "database": str(self.database_path),
            "database_size_bytes": self.database_size_bytes,
            "run_id": self.run_id,
            "completed_at": self.completed_at,
            "combined_schema_version": self.combined_schema_version,
            "cohort_source_schema_version": self.cohort_source_schema_version,
            "cohort_source_schema_sha256": self.cohort_source_schema_sha256,
            "cohort_source_catalog_sha256": self.cohort_source_catalog_sha256,
            "glp1_catalog_sha256": self.glp1_catalog_sha256,
            "package_version": self.package_version,
            "git_code_state_sha256": self.git_code_state_sha256,
            "source_work_manifest_sha256": self.source_work_manifest_sha256,
        }


@dataclass(frozen=True)
class CohortSourceValidationResult:
    """PHI-safe validation outcome for a canonical cohort-source database."""

    valid: bool
    errors: tuple[str, ...]
    metadata: CohortSourceMetadata | None
    required_elements: tuple[str, ...]


class CohortSourceValidationError(ValueError):
    """Raised when a database cannot safely serve as a cohort-source product."""

    def __init__(self, result: CohortSourceValidationResult) -> None:
        self.result = result
        super().__init__("Invalid cohort source: " + "; ".join(result.errors))


@dataclass(frozen=True)
class CohortSource:
    """An open read-only cohort-source connection with verified metadata."""

    connection: duckdb.DuckDBPyConnection
    metadata: CohortSourceMetadata


def validate_cohort_source(
    database_path: Path,
    *,
    required_elements: Iterable[str] = (),
    expected_catalog_sha256: str | None = None,
    memory_limit_mib: int = DEFAULT_COMBINED_DUCKDB_MEMORY_LIMIT_MIB,
    spill_root: Path | None = None,
) -> CohortSourceValidationResult:
    """Validate a terminal canonical product for downstream cohort use.

    Validation is metadata- and schema-focused: it opens only the published
    DuckDB and its adjacent sidecar, never raw TriNetX exports or pipeline work
    tables. ``expected_catalog_sha256`` lets a downstream project pin the
    merged source catalog that its cohort definition was written against.
    """

    path = Path(database_path)
    required, normalization_errors = _normalize_required_elements(required_elements)
    errors = list(normalization_errors)
    if path.is_symlink() or not path.is_file():
        errors.append(f"Cohort-source database must be a regular file: {path}")
        return _validation_result(errors, None, required)
    _guard_cohort_source_spill_locations(path, spill_root=spill_root, errors=errors)
    if errors:
        return _validation_result(errors, None, required)

    sidecar = _load_sidecar(path.parent / COMBINED_MANIFEST_FILENAME, errors)
    if sidecar is None:
        return _validation_result(errors, None, required)

    try:
        with open_combined_database(
            path,
            read_only=True,
            memory_limit_mib=memory_limit_mib,
            spill_root=spill_root,
        ) as connection:
            metadata = _validate_database_contract(
                connection,
                database_path=path,
                sidecar=sidecar,
                required_elements=required,
                expected_catalog_sha256=expected_catalog_sha256,
                errors=errors,
            )
    except (duckdb.Error, OSError, ValueError) as exc:
        errors.append(f"Cannot validate cohort-source database {path}: {exc}")
        metadata = None
    return _validation_result(errors, metadata, required)


def _guard_cohort_source_spill_locations(
    database_path: Path,
    *,
    spill_root: Path | None,
    errors: list[str],
) -> None:
    """Reject repository-local locations before read-only DuckDB opens spill.

    ``open_combined_database`` creates an owned spill directory beside the
    database by default. The public consumer surface must therefore apply the
    same confidential-artifact guard as the CLI, including a caller-provided
    spill root.
    """

    locations = [(database_path.parent, "cohort-source database/spill directory")]
    if spill_root is not None:
        locations.append((Path(spill_root), "cohort-source spill directory"))
    for location, artifact_label in locations:
        try:
            require_safe_output_location(location, artifact_label=artifact_label)
        except ValueError as exc:
            errors.append(str(exc))


@contextmanager
def open_cohort_source(
    database_path: Path,
    *,
    required_elements: Iterable[str] = (),
    expected_catalog_sha256: str | None = None,
    memory_limit_mib: int = DEFAULT_COMBINED_DUCKDB_MEMORY_LIMIT_MIB,
    spill_root: Path | None = None,
) -> Iterator[CohortSource]:
    """Open a validated cohort source as a bounded, read-only connection.

    The yielded ``CohortSource.connection`` is suitable for downstream SQL
    reads. Its temporary DuckDB spill directory uses the existing combined
    preprocessing cleanup lifecycle and is removed when the context exits.
    """

    result = validate_cohort_source(
        database_path,
        required_elements=required_elements,
        expected_catalog_sha256=expected_catalog_sha256,
        memory_limit_mib=memory_limit_mib,
        spill_root=spill_root,
    )
    if not result.valid or result.metadata is None:
        raise CohortSourceValidationError(result)
    with open_combined_database(
        Path(database_path),
        read_only=True,
        memory_limit_mib=memory_limit_mib,
        spill_root=spill_root,
    ) as connection:
        yield CohortSource(connection=connection, metadata=result.metadata)


def _validation_result(
    errors: list[str],
    metadata: CohortSourceMetadata | None,
    required_elements: tuple[str, ...],
) -> CohortSourceValidationResult:
    return CohortSourceValidationResult(
        valid=not errors,
        errors=tuple(errors),
        metadata=metadata,
        required_elements=required_elements,
    )


def _normalize_required_elements(
    elements: Iterable[str],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    if isinstance(elements, str):
        raw_elements: Iterable[str] = (elements,)
    else:
        raw_elements = elements
    normalized: list[str] = []
    errors: list[str] = []
    for element in raw_elements:
        if not isinstance(element, str) or not element.strip():
            errors.append("Required cohort-source element IDs must be non-empty text.")
            continue
        candidate = element.strip()
        if candidate not in normalized:
            normalized.append(candidate)
    return tuple(normalized), tuple(errors)


def _load_sidecar(path: Path, errors: list[str]) -> dict[str, object] | None:
    if path.is_symlink() or not path.is_file():
        errors.append(f"Missing cohort-source product sidecar: {path}")
        return None
    try:
        payload = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"Cannot read cohort-source product sidecar {path}: {exc}")
        return None
    if not isinstance(payload, dict):
        errors.append(f"Cohort-source product sidecar must be a JSON object: {path}")
        return None
    return payload


def _validate_database_contract(
    connection: duckdb.DuckDBPyConnection,
    *,
    database_path: Path,
    sidecar: dict[str, object],
    required_elements: tuple[str, ...],
    expected_catalog_sha256: str | None,
    errors: list[str],
) -> CohortSourceMetadata | None:
    existing_tables = {
        str(row[0])
        for row in connection.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'main'"
        ).fetchall()
    }
    missing_tables = sorted(set(COHORT_SOURCE_TABLE_SCHEMAS) - existing_tables)
    if missing_tables:
        errors.append(
            "Cohort-source database is missing required tables: "
            + ", ".join(missing_tables)
        )
        return None

    schema_mismatches = []
    for table_name, expected_schema in COHORT_SOURCE_TABLE_SCHEMAS.items():
        if _table_schema(connection, table_name) != expected_schema:
            schema_mismatches.append(table_name)
    if schema_mismatches:
        errors.append(
            "Cohort-source table schema mismatch: " + ", ".join(schema_mismatches)
        )
        return None

    manifest_rows = connection.execute(
        "SELECT "
        + ", ".join(_identifier(column) for column, _ in _manifest_schema())
        + " FROM preprocessing_manifest"
    ).fetchall()
    if len(manifest_rows) != 1:
        errors.append(
            "Cohort-source preprocessing_manifest must contain exactly one run."
        )
        return None
    embedded = dict(zip((column for column, _ in _manifest_schema()), manifest_rows[0]))
    metadata = _metadata_from_embedded(database_path, embedded, errors)
    if metadata is None:
        return None

    _validate_embedded_manifest(
        embedded,
        expected_catalog_sha256=expected_catalog_sha256,
        errors=errors,
    )
    _validate_sidecar(
        sidecar,
        database_path=database_path,
        embedded=embedded,
        errors=errors,
    )
    _validate_required_elements(connection, required_elements, errors)
    return metadata


def _manifest_schema() -> tuple[tuple[str, str], ...]:
    return COHORT_SOURCE_TABLE_SCHEMAS["preprocessing_manifest"]


def _metadata_from_embedded(
    database_path: Path,
    embedded: dict[str, Any],
    errors: list[str],
) -> CohortSourceMetadata | None:
    required_text_fields = (
        "run_id",
        "combined_schema_version",
        "cohort_source_schema_version",
        "cohort_source_schema_sha256",
        "cohort_source_catalog_sha256",
        "glp1_catalog_sha256",
        "package_version",
        "git_code_state_sha256",
        "source_work_manifest_sha256",
    )
    invalid_fields = [
        field
        for field in required_text_fields
        if not isinstance(embedded.get(field), str) or not str(embedded[field])
    ]
    completed_at = embedded.get("completed_at")
    if completed_at is None:
        invalid_fields.append("completed_at")
    if invalid_fields:
        errors.append(
            "Cohort-source preprocessing manifest has invalid fields: "
            + ", ".join(invalid_fields)
        )
        return None
    return CohortSourceMetadata(
        database_path=database_path.resolve(strict=False),
        database_size_bytes=database_path.stat().st_size,
        run_id=str(embedded["run_id"]),
        completed_at=_isoformat_value(completed_at),
        combined_schema_version=str(embedded["combined_schema_version"]),
        cohort_source_schema_version=str(embedded["cohort_source_schema_version"]),
        cohort_source_schema_sha256=str(embedded["cohort_source_schema_sha256"]),
        cohort_source_catalog_sha256=str(embedded["cohort_source_catalog_sha256"]),
        glp1_catalog_sha256=str(embedded["glp1_catalog_sha256"]),
        package_version=str(embedded["package_version"]),
        git_code_state_sha256=str(embedded["git_code_state_sha256"]),
        source_work_manifest_sha256=str(embedded["source_work_manifest_sha256"]),
    )


def _validate_embedded_manifest(
    embedded: dict[str, Any],
    *,
    expected_catalog_sha256: str | None,
    errors: list[str],
) -> None:
    expected_values = {
        "status": "complete",
        "combined_schema_version": COMBINED_SCHEMA_VERSION,
        "cohort_source_schema_version": COHORT_SOURCE_SCHEMA_VERSION,
        "cohort_source_schema_sha256": cohort_source_schema_sha256(),
        "cohort_source_catalog_sha256": embedded["element_catalog_sha256"],
    }
    mismatched = [
        field
        for field, expected in expected_values.items()
        if embedded.get(field) != expected
    ]
    if mismatched:
        errors.append(
            "Cohort-source preprocessing manifest mismatches the contract for: "
            + ", ".join(sorted(mismatched))
        )
    if expected_catalog_sha256 is not None and (
        embedded.get("cohort_source_catalog_sha256") != expected_catalog_sha256
    ):
        errors.append(
            "Cohort-source catalog digest does not match the requested value."
        )


def _validate_sidecar(
    sidecar: dict[str, object],
    *,
    database_path: Path,
    embedded: dict[str, Any],
    errors: list[str],
) -> None:
    expected_values = {
        "schema_version": DATABASE_MANIFEST_SCHEMA_VERSION,
        "combined_schema_version": embedded["combined_schema_version"],
        "cohort_source_schema_version": embedded["cohort_source_schema_version"],
        "cohort_source_schema_sha256": embedded["cohort_source_schema_sha256"],
        "cohort_source_catalog_sha256": embedded["cohort_source_catalog_sha256"],
        "glp1_catalog_sha256": embedded["glp1_catalog_sha256"],
        "catalog_sha256": embedded["element_catalog_sha256"],
        "run_id": embedded["run_id"],
        "status": embedded["status"],
        "git_code_state_sha256": embedded["git_code_state_sha256"],
    }
    mismatched = [
        field
        for field, expected in expected_values.items()
        if sidecar.get(field) != expected
    ]
    if mismatched:
        errors.append(
            "Cohort-source product sidecar disagrees with the embedded manifest for: "
            + ", ".join(sorted(mismatched))
        )
    expected_database = database_path.resolve(strict=False)
    sidecar_database = sidecar.get("database")
    if not isinstance(sidecar_database, str) or (
        Path(sidecar_database).resolve(strict=False) != expected_database
    ):
        errors.append("Cohort-source product sidecar database path is invalid.")
    if sidecar.get("database_size_bytes") != database_path.stat().st_size:
        errors.append("Cohort-source product sidecar database size is invalid.")


def _validate_required_elements(
    connection: duckdb.DuckDBPyConnection,
    required_elements: tuple[str, ...],
    errors: list[str],
) -> None:
    if not required_elements:
        return
    catalog = {
        str(element_id): str(element_kind)
        for element_id, element_kind in connection.execute(
            "SELECT element_id, element_kind FROM element_catalog"
        ).fetchall()
    }
    missing = sorted(set(required_elements) - set(catalog))
    if missing:
        errors.append(
            "Cohort-source catalog is missing required element IDs: "
            + ", ".join(missing)
        )
    required_source_elements = [
        element_id
        for element_id in required_elements
        if catalog.get(element_id) == "source_concept"
    ]
    if not required_source_elements:
        return
    included_elements = {
        str(row[0])
        for row in connection.execute(
            "SELECT DISTINCT element_id FROM element_rule "
            "WHERE coalesce(include, false)"
        ).fetchall()
    }
    excluded = sorted(set(required_source_elements) - included_elements)
    if excluded:
        errors.append(
            "Cohort-source catalog has required elements without an included rule: "
            + ", ".join(excluded)
        )


def _table_schema(
    connection: duckdb.DuckDBPyConnection,
    table_name: str,
) -> tuple[tuple[str, str], ...]:
    return tuple(
        (str(row[1]), str(row[2]))
        for row in connection.execute(
            f"PRAGMA table_info({_sql_string(table_name)})"
        ).fetchall()
    )


def _identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _sql_string(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _isoformat_value(value: object) -> str:
    if hasattr(value, "isoformat"):
        return str(value.isoformat())
    return str(value)

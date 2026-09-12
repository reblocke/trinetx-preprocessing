"""Deterministic comparison of raw-reference and canonical-source GLP outputs."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import duckdb

from .outputs import OUTPUT_TABLES

_DATABASE_NAME = "glp1_hypercapnia.duckdb"
_CONTRACT_TABLES = (
    "source_file_inventory",
    "unmapped_code_frequency",
    "concept_match_summary",
    "source_duplicate_summary",
    "build_warning",
    "concept_set",
    "phenotype_rule",
    "source_lab_measurement",
    "source_encounter",
    "source_patient",
    "source_vital_measurement",
    "source_diagnosis",
    "source_procedure",
    "source_medication",
    "source_cohort_flow_base",
    "raw_diagnosis_observability",
    "raw_labs_observability",
    "raw_vitals_observability",
    "raw_procedure_observability",
    "raw_medication_observability",
    *OUTPUT_TABLES,
    "cohort_flow",
)
_OPERATIONAL_COLUMNS = frozenset({"run_id", "index_event_id"})
_OPERATIONAL_MANIFEST_KEYS = frozenset(
    {"run_id", "run_started_at", "run_completed_at", "input_root"}
)


@dataclass(frozen=True)
class ParityResult:
    """PHI-safe result for one complete source-mode comparison."""

    valid: bool
    errors: tuple[str, ...]
    tables_checked: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "valid": self.valid,
            "errors": list(self.errors),
            "tables_checked": list(self.tables_checked),
        }


def compare_glp1_reference_outputs(
    raw_output: Path,
    canonical_output: Path,
) -> ParityResult:
    """Compare every contracted table and public output without PHI disclosure.

    The two builds have intentionally distinct run and index-event identifiers.
    Those operational identifiers are excluded only after exact schemas are
    checked. All source evidence, clinical values, multiplicities, dates,
    missingness, QA counts, and non-operational manifest fields remain exact.
    """

    raw_root = Path(raw_output)
    canonical_root = Path(canonical_output)
    errors: list[str] = []
    _compare_output_inventory(raw_root, canonical_root, errors)
    _compare_json_manifest(raw_root, canonical_root, errors)
    raw_database = raw_root / _DATABASE_NAME
    canonical_database = canonical_root / _DATABASE_NAME
    if not raw_database.is_file() or not canonical_database.is_file():
        errors.append("Both output roots must contain glp1_hypercapnia.duckdb.")
        return ParityResult(False, tuple(errors), ())

    checked: list[str] = []
    raw = duckdb.connect(str(raw_database), read_only=True)
    canonical = duckdb.connect(str(canonical_database), read_only=True)
    try:
        for table_name in _CONTRACT_TABLES:
            _compare_table(raw, canonical, table_name, errors)
            checked.append(table_name)
        _compare_run_manifest(raw, canonical, errors)
    finally:
        raw.close()
        canonical.close()
    return ParityResult(not errors, tuple(errors), tuple(checked))


def _compare_output_inventory(
    raw_root: Path,
    canonical_root: Path,
    errors: list[str],
) -> None:
    for root, label in ((raw_root, "raw"), (canonical_root, "canonical")):
        if not root.is_dir():
            errors.append(f"{label} output root is not a directory: {root}")
    if errors:
        return
    raw_files = {path.name for path in raw_root.iterdir() if path.is_file()}
    canonical_files = {path.name for path in canonical_root.iterdir() if path.is_file()}
    if raw_files != canonical_files:
        errors.append("Published output file inventories differ.")
    for root, label, files in (
        (raw_root, "raw", raw_files),
        (canonical_root, "canonical", canonical_files),
    ):
        empty = sorted(name for name in files if (root / name).stat().st_size == 0)
        if empty:
            errors.append(f"{label} output contains empty files: {', '.join(empty)}")


def _compare_json_manifest(
    raw_root: Path,
    canonical_root: Path,
    errors: list[str],
) -> None:
    paths = (raw_root / "run_manifest.json", canonical_root / "run_manifest.json")
    if not all(path.is_file() for path in paths):
        errors.append("Both output roots must contain run_manifest.json.")
        return
    try:
        raw = json.loads(paths[0].read_text())
        canonical = json.loads(paths[1].read_text())
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"Cannot read output run manifest: {exc}")
        return
    if not isinstance(raw, dict) or not isinstance(canonical, dict):
        errors.append("Output run manifests must be JSON objects.")
        return
    raw_stable = {
        key: value
        for key, value in raw.items()
        if key not in _OPERATIONAL_MANIFEST_KEYS
    }
    canonical_stable = {
        key: value
        for key, value in canonical.items()
        if key not in _OPERATIONAL_MANIFEST_KEYS
    }
    if raw_stable != canonical_stable:
        errors.append(
            "Output run manifests differ outside declared operational fields."
        )


def _compare_table(
    raw: duckdb.DuckDBPyConnection,
    canonical: duckdb.DuckDBPyConnection,
    table_name: str,
    errors: list[str],
) -> None:
    raw_schema = _table_schema(raw, table_name)
    canonical_schema = _table_schema(canonical, table_name)
    if raw_schema is None or canonical_schema is None:
        errors.append(f"Missing contracted table: {table_name}")
        return
    if raw_schema != canonical_schema:
        errors.append(f"Schema differs for table: {table_name}")
        return
    columns = [name for name, _ in raw_schema if name not in _OPERATIONAL_COLUMNS]
    projection = ", ".join(_identifier(name) for name in columns)
    raw_rows = raw.execute(
        f"SELECT {projection} FROM {_identifier(table_name)} ORDER BY ALL"
    ).fetchall()
    canonical_rows = canonical.execute(
        f"SELECT {projection} FROM {_identifier(table_name)} ORDER BY ALL"
    ).fetchall()
    if raw_rows != canonical_rows:
        errors.append(f"Rows differ for table: {table_name}")


def _compare_run_manifest(
    raw: duckdb.DuckDBPyConnection,
    canonical: duckdb.DuckDBPyConnection,
    errors: list[str],
) -> None:
    raw_schema = _table_schema(raw, "run_manifest")
    canonical_schema = _table_schema(canonical, "run_manifest")
    if raw_schema != canonical_schema or raw_schema is None:
        errors.append("Schema differs for table: run_manifest")
        return
    columns = [
        name for name, _ in raw_schema if name not in _OPERATIONAL_MANIFEST_KEYS
    ]
    projection = ", ".join(_identifier(name) for name in columns)
    raw_rows = raw.execute(
        f"SELECT {projection} FROM run_manifest ORDER BY ALL"
    ).fetchall()
    canonical_rows = canonical.execute(
        f"SELECT {projection} FROM run_manifest ORDER BY ALL"
    ).fetchall()
    if raw_rows != canonical_rows:
        errors.append("Rows differ for table: run_manifest")


def _table_schema(
    connection: duckdb.DuckDBPyConnection,
    table_name: str,
) -> tuple[tuple[str, str], ...] | None:
    rows = connection.execute(
        "SELECT column_name, data_type FROM information_schema.columns "
        "WHERE table_schema = 'main' AND table_name = ? ORDER BY ordinal_position",
        [table_name],
    ).fetchall()
    if not rows:
        return None
    return tuple((str(name), str(data_type)) for name, data_type in rows)


def _identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'

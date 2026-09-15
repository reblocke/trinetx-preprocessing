"""Deterministic comparison of raw-reference and canonical-source GLP outputs."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import duckdb

from ..combined_preprocessing.builder import require_safe_output_location
from ..combined_preprocessing.database import open_combined_database
from ..verification.multiset import exact_difference_counts
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
_OPERATIONAL_COLUMNS = frozenset({"run_id"})
_OPERATIONAL_MANIFEST_KEYS = frozenset(
    {"run_id", "run_started_at", "run_completed_at", "input_root"}
)
_STABLE_PUBLIC_ARTIFACTS = (
    "cohort_flow.csv",
    "data_dictionary.csv",
    "data_quality_report.html",
)


@dataclass(frozen=True)
class ParityResult:
    """PHI-safe result for one complete source-mode comparison."""

    valid: bool
    errors: tuple[str, ...]
    tables_checked: tuple[str, ...]
    table_evidence: dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {
            "valid": self.valid,
            "errors": list(self.errors),
            "tables_checked": list(self.tables_checked),
            "table_evidence": self.table_evidence,
            "comparison": "exact_partitioned_multiset",
        }


def compare_glp1_reference_outputs(
    raw_output: Path,
    canonical_output: Path,
    *,
    expected_producer_revisions: tuple[str, str] | None = None,
    scratch_root: Path | None = None,
    progress=None,
) -> ParityResult:
    """Compare every contracted table and public output without PHI disclosure.

    The two builds have intentionally distinct run identifiers. Only run IDs
    are excluded after exact schema checks. Index-event IDs are deterministic
    from patient, encounter and date and remain part of exact comparison.
    All source evidence, clinical values, multiplicities, dates,
    missingness, QA counts, and non-operational manifest fields remain exact.
    A verifier with a raw-code reuse proof may supply both expected producer
    revisions. In that case every stored producer value is checked against its
    expected revision before excluding that provenance field from row equality.
    """

    raw_root = Path(raw_output)
    canonical_root = Path(canonical_output)
    errors: list[str] = []
    _compare_output_inventory(raw_root, canonical_root, errors)
    _compare_json_manifest(
        raw_root, canonical_root, errors, expected_producer_revisions
    )
    _compare_stable_public_artifacts(raw_root, canonical_root, errors)
    raw_database = raw_root / _DATABASE_NAME
    canonical_database = canonical_root / _DATABASE_NAME
    if not raw_database.is_file() or not canonical_database.is_file():
        errors.append("Both output roots must contain glp1_hypercapnia.duckdb.")
        return ParityResult(False, tuple(errors), ())

    checked: list[str] = []
    evidence: dict[str, object] = {}
    for root in (raw_root, canonical_root):
        require_safe_output_location(root, artifact_label="GLP parity/spill")
    scratch_root = (
        Path(scratch_root) if scratch_root is not None else canonical_root.parent
    )
    require_safe_output_location(scratch_root, artifact_label="GLP parity scratch")
    scratch_root.mkdir(parents=True, exist_ok=True)
    with open_combined_database(
        raw_database, read_only=True, memory_limit_mib=2048, spill_root=scratch_root
    ) as raw:
        literal = str(canonical_database.resolve()).replace("'", "''")
        raw.execute(f"ATTACH '{literal}' AS verification_candidate (READ_ONLY)")
        canonical = duckdb.connect(str(canonical_database), read_only=True)
        try:
            for table_name in _CONTRACT_TABLES:
                if progress:
                    progress(
                        {
                            "phase": "table_start",
                            "table": table_name,
                            "tables_completed": len(checked),
                            "total_tables": len(_CONTRACT_TABLES),
                        }
                    )
                evidence[table_name] = _compare_table(
                    raw,
                    canonical,
                    table_name,
                    errors,
                    expected_producer_revisions,
                    scratch_root=scratch_root,
                    progress=(lambda event: progress({**event, "table": table_name}))
                    if progress
                    else None,
                )
                checked.append(table_name)
                if progress:
                    progress(
                        {
                            "phase": "table_complete",
                            "table": table_name,
                            "tables_completed": len(checked),
                            "total_tables": len(_CONTRACT_TABLES),
                            "evidence": evidence[table_name],
                        }
                    )
            _compare_run_manifest(raw, canonical, errors, expected_producer_revisions)
            for root, label, catalog in (
                (raw_root, "raw", "main"),
                (canonical_root, "canonical", "verification_candidate.main"),
            ):
                for table in OUTPUT_TABLES:
                    path = root / f"{table}.parquet"
                    if path.exists():
                        literal = str(path.resolve()).replace("'", "''")
                        left = f"SELECT * FROM {catalog}.{_identifier(table)}"
                        right = f"SELECT * FROM read_parquet('{literal}')"
                        left_schema = [
                            r[:2] for r in raw.execute("DESCRIBE " + left).fetchall()
                        ]
                        right_schema = [
                            r[:2] for r in raw.execute("DESCRIBE " + right).fetchall()
                        ]
                        if left_schema != right_schema:
                            errors.append(
                                f"Published Parquet schema differs: {label}.{table}"
                            )
                            continue
                        difference = _difference_counts(
                            raw,
                            left,
                            right,
                            scratch_root=scratch_root,
                            progress=(
                                lambda event: progress(
                                    {**event, "table": f"{label}.{table}.parquet"}
                                )
                            )
                            if progress
                            else None,
                        )
                        evidence[f"{label}.{table}.parquet"] = difference
                        if any(difference.values()):
                            errors.append(f"Published Parquet differs: {label}.{table}")
        finally:
            canonical.close()
    return ParityResult(not errors, tuple(errors), tuple(checked), evidence)


def _difference_counts(
    connection, left: str, right: str, *, scratch_root=None, progress=None
) -> dict[str, int]:
    """Compare complete typed rows exactly, using bounded partitions at scale."""
    return exact_difference_counts(
        connection, left, right, scratch_root=scratch_root, progress=progress
    )


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
    # AppleDouble files are filesystem metadata, never published study outputs.
    raw_files = {
        path.name
        for path in raw_root.iterdir()
        if path.is_file() and not path.name.startswith("._")
    }
    canonical_files = {
        path.name
        for path in canonical_root.iterdir()
        if path.is_file() and not path.name.startswith("._")
    }
    required = {
        _DATABASE_NAME,
        "run_manifest.json",
        *_STABLE_PUBLIC_ARTIFACTS,
        *(f"{name}.parquet" for name in OUTPUT_TABLES),
    }
    for files, label in ((raw_files, "raw"), (canonical_files, "canonical")):
        if files != required:
            errors.append(
                f"{label} published output inventory must contain "
                "exactly the eight contracted files."
            )
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
    expected_producer_revisions: tuple[str, str] | None = None,
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
    operational = _OPERATIONAL_MANIFEST_KEYS
    if expected_producer_revisions is not None:
        for manifest, revision in zip(
            (raw, canonical), expected_producer_revisions, strict=True
        ):
            if manifest.get("pipeline_git_sha") != revision:
                errors.append("Output manifest has an unexpected producer revision.")
        operational = operational | {"pipeline_git_sha"}
    raw_stable = {key: value for key, value in raw.items() if key not in operational}
    canonical_stable = {
        key: value for key, value in canonical.items() if key not in operational
    }
    if raw_stable != canonical_stable:
        errors.append(
            "Output run manifests differ outside declared operational fields."
        )


def _compare_stable_public_artifacts(
    raw_root: Path,
    canonical_root: Path,
    errors: list[str],
) -> None:
    """Require byte identity for public artifacts with no run-specific fields."""

    for name in _STABLE_PUBLIC_ARTIFACTS:
        raw_path = raw_root / name
        canonical_path = canonical_root / name
        if not raw_path.is_file() or not canonical_path.is_file():
            errors.append(f"Both output roots must contain {name}.")
            continue
        if raw_path.read_bytes() != canonical_path.read_bytes():
            errors.append(f"Contents differ for stable public artifact: {name}")


def _compare_table(
    raw: duckdb.DuckDBPyConnection,
    canonical: duckdb.DuckDBPyConnection,
    table_name: str,
    errors: list[str],
    expected_producer_revisions: tuple[str, str] | None = None,
    *,
    scratch_root=None,
    progress=None,
) -> dict[str, object] | None:
    raw_schema = _table_schema(raw, table_name)
    canonical_schema = _table_schema(canonical, table_name)
    if raw_schema is None or canonical_schema is None:
        errors.append(f"Missing contracted table: {table_name}")
        return
    if raw_schema != canonical_schema:
        errors.append(f"Schema differs for table: {table_name}")
        return
    operational = _OPERATIONAL_COLUMNS
    if expected_producer_revisions is not None and any(
        name == "pipeline_git_sha" for name, _ in raw_schema
    ):
        _check_producer_revisions(
            raw, canonical, table_name, expected_producer_revisions, errors
        )
        operational = operational | {"pipeline_git_sha"}
    columns = [name for name, _ in raw_schema if name not in operational]
    projection = ", ".join(_identifier(name) for name in columns)
    left = f"SELECT {projection} FROM {_identifier(table_name)}"
    right = (
        f"SELECT {projection} FROM "
        f"verification_candidate.main.{_identifier(table_name)}"
    )
    difference = _difference_counts(
        raw, left, right, scratch_root=scratch_root, progress=progress
    )
    if any(difference.values()):
        errors.append(f"Rows differ for table: {table_name}")
    return {
        "schema": raw_schema,
        "row_count": int(
            raw.execute(f"SELECT count(*) FROM {_identifier(table_name)}").fetchone()[0]
        ),
        **difference,
    }


def _compare_run_manifest(
    raw: duckdb.DuckDBPyConnection,
    canonical: duckdb.DuckDBPyConnection,
    errors: list[str],
    expected_producer_revisions: tuple[str, str] | None = None,
) -> None:
    raw_schema = _table_schema(raw, "run_manifest")
    canonical_schema = _table_schema(canonical, "run_manifest")
    if raw_schema != canonical_schema or raw_schema is None:
        errors.append("Schema differs for table: run_manifest")
        return
    operational = _OPERATIONAL_MANIFEST_KEYS
    if expected_producer_revisions is not None:
        _check_producer_revisions(
            raw, canonical, "run_manifest", expected_producer_revisions, errors
        )
        operational = operational | {"pipeline_git_sha"}
    columns = [name for name, _ in raw_schema if name not in operational]
    projection = ", ".join(_identifier(name) for name in columns)
    raw_rows = raw.execute(
        f"SELECT {projection} FROM run_manifest ORDER BY ALL"
    ).fetchall()
    canonical_rows = canonical.execute(
        f"SELECT {projection} FROM run_manifest ORDER BY ALL"
    ).fetchall()
    if raw_rows != canonical_rows:
        errors.append("Rows differ for table: run_manifest")


def _check_producer_revisions(raw, canonical, table, revisions, errors):
    """Validate provenance before allowing a proven raw-reference reuse."""
    for connection, revision in zip((raw, canonical), revisions, strict=True):
        count = connection.execute(
            f"SELECT count(*) FROM {_identifier(table)} "
            "WHERE pipeline_git_sha IS DISTINCT FROM ?",
            [revision],
        ).fetchone()[0]
        if count:
            errors.append(f"Unexpected producer revision in table: {table}")


def _table_schema(
    connection: duckdb.DuckDBPyConnection,
    table_name: str,
) -> tuple[tuple[str, str], ...] | None:
    rows = connection.execute(
        "SELECT column_name, data_type FROM information_schema.columns "
        "WHERE table_catalog = current_database() AND table_schema = 'main' "
        "AND table_name = ? ORDER BY ordinal_position",
        [table_name],
    ).fetchall()
    if not rows:
        return None
    return tuple((str(name), str(data_type)) for name, data_type in rows)


def _identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'

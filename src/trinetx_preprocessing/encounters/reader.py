"""Read accepted encounter products without selecting a study population."""

from __future__ import annotations

import json
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

import duckdb
import pandas as pd
import pyarrow.parquet as pq

from trinetx_preprocessing.encounters.acceptance import (
    required_output_name,
    verify_accepted_bundle,
    verify_companion_schema,
    verify_feature_schema,
    verify_output,
)


def _read_columns(
    path: Path, columns: list[str] | None, available: set[str]
) -> pd.DataFrame:
    if columns is not None:
        if not isinstance(columns, list) or len(columns) != len(set(columns)):
            raise ValueError("Requested columns must be a list without duplicates")
        missing = sorted(set(columns) - available)
        if missing:
            raise ValueError(f"Requested encounter columns are absent: {missing}")
    frame = pd.read_parquet(path, columns=columns)
    if columns is not None and list(frame.columns) != columns:
        raise ValueError("Parquet reader changed the requested column order")
    return frame


def read_encounters(
    output_dir: Path,
    *,
    variant: str,
    receipt_path: Path,
    expected_receipt_sha256: str,
    validation_report_path: Path,
    columns: list[str] | None = None,
    coverage_policy: str = "complete_linkage",
) -> pd.DataFrame:
    """Read the caller-trusted, accepted feature product with no study filtering.

    The caller obtains the expected receipt digest from its trusted release
    configuration. Original patient_id/encounter_id remain the stable keys;
    callers explicitly sort when row order matters.
    """
    root = Path(output_dir)
    manifest = verify_accepted_bundle(
        root,
        receipt_path=receipt_path,
        expected_receipt_sha256=expected_receipt_sha256,
        validation_report_path=validation_report_path,
        variant=variant,
        coverage_policy=coverage_policy,
    )
    name = required_output_name(variant)
    path = verify_output(root, manifest, name)
    schema = verify_feature_schema(root, manifest, variant, path)
    frame = _read_columns(path, columns, set(schema))
    verify_output(root, manifest, name)
    return frame


def read_encounter_companion(
    output_dir: Path,
    *,
    variant: str,
    table: str,
    receipt_path: Path,
    expected_receipt_sha256: str,
    validation_report_path: Path,
    columns: list[str] | None = None,
    coverage_policy: str = "complete_linkage",
) -> pd.DataFrame:
    """Read accepted evidence or coverage with the same manifest boundary."""
    root = Path(output_dir)
    manifest = verify_accepted_bundle(
        root,
        receipt_path=receipt_path,
        expected_receipt_sha256=expected_receipt_sha256,
        validation_report_path=validation_report_path,
        variant=variant,
        coverage_policy=coverage_policy,
    )
    name = required_output_name(variant, table)
    path = verify_output(root, manifest, name)
    schema = verify_companion_schema(path, table)
    frame = _read_columns(path, columns, set(schema))
    verify_output(root, manifest, name)
    return frame


@contextmanager
def scan_accepted_encounter_bundle(
    connection: duckdb.DuckDBPyConnection,
    output_dir: Path,
    *,
    variant: str,
    companion_tables: Sequence[str],
    receipt_path: Path,
    expected_receipt_sha256: str,
    validation_report_path: Path,
    coverage_policy: str = "complete_linkage",
) -> Iterator[dict[str, str]]:
    """Yield temporary DuckDB views over verified feature and companion files.

    Views are lazy, so a study can filter and join evidence without loading an
    entire companion into pandas. The caller owns the DuckDB connection and
    its memory/spill configuration. The views exist only inside this context;
    the exact accepted receipt and consumed file identities are checked again
    when it closes. This is a trusted input interface, not study selection.
    """
    if not isinstance(connection, duckdb.DuckDBPyConnection):
        raise ValueError("Accepted bundle scan needs a DuckDB connection")
    if not isinstance(companion_tables, Sequence) or isinstance(companion_tables, str):
        raise ValueError("Companion tables must be a sequence without duplicates")
    tables = tuple(companion_tables)
    if (
        any(not isinstance(table, str) for table in tables)
        or len(tables) != len(set(tables))
        or "features" in tables
    ):
        raise ValueError("Companion tables must be a sequence without duplicates")
    root = Path(output_dir)
    names = {"features": required_output_name(variant)}
    names.update({table: required_output_name(variant, table) for table in tables})
    manifest = verify_accepted_bundle(
        root,
        receipt_path=receipt_path,
        expected_receipt_sha256=expected_receipt_sha256,
        validation_report_path=validation_report_path,
        variant=variant,
        coverage_policy=coverage_policy,
    )
    paths = {
        table: verify_output(root, manifest, name) for table, name in names.items()
    }
    verify_feature_schema(root, manifest, variant, paths["features"])
    for table in tables:
        verify_companion_schema(paths[table], table)

    views: dict[str, str] = {}
    try:
        for table, path in paths.items():
            view = f"_accepted_bundle_{uuid4().hex}"
            connection.from_parquet(str(path)).create_view(view)
            views[table] = view
        yield dict(views)
    finally:
        try:
            verify_accepted_bundle(
                root,
                receipt_path=receipt_path,
                expected_receipt_sha256=expected_receipt_sha256,
                validation_report_path=validation_report_path,
                variant=variant,
                coverage_policy=coverage_policy,
            )
            for name in (*names.values(), "data_dictionary.json"):
                verify_output(root, manifest, name)
        finally:
            for view in views.values():
                connection.execute(f'DROP VIEW IF EXISTS "{view}"')


def read_encounters_development(
    output_dir: Path, *, variant: str, columns: list[str] | None = None
) -> pd.DataFrame:
    """Explicitly read an unaccepted legacy base or enriched development bundle.

    This interface is for development and reproduction only. Production and
    report paths never fall back to it after an acceptance failure.
    """
    name = required_output_name(variant)
    root = Path(output_dir)
    manifest_path = root / "manifest.json"
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise ValueError("Development encounter manifest is missing")
    manifest = json.loads(manifest_path.read_text())
    if manifest.get("schema_version") != "2.0" or manifest.get("status") != "complete":
        raise ValueError("Development encounter bundle is incomplete or unsupported")
    kind = manifest.get("kind")
    if kind not in {"legacy_base", "encounter_features"}:
        raise ValueError("Development reader requires explicit legacy or enriched kind")
    path = verify_output(root, manifest, name)
    schema = pq.read_schema(path)
    if not {"patient_id", "encounter_id", "pat_enc_hash"} <= set(schema.names):
        raise ValueError("Development encounter product lacks original linkage keys")
    if kind == "encounter_features":
        if manifest.get("feature_contract_version") != "1.0":
            raise ValueError("Unsupported development feature contract")
        verify_feature_schema(root, manifest, variant, path)
    return _read_columns(path, columns, set(schema.names))

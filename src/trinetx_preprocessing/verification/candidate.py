"""Validate and publish an existing terminal staging product without rebuilding."""

from __future__ import annotations

import json
from pathlib import Path

from ..combined_preprocessing import builder
from ..combined_preprocessing.cohort_source import _validate_database_contract
from ..combined_preprocessing.database import (
    COMBINED_MANIFEST_FILENAME,
    open_combined_database,
)
from ..combined_preprocessing.elements import load_combined_catalog
from ..config import Config
from ..work_manifest import _identity, work_manifest_path
from .policy import ROOT, code_fingerprint, git, sha


def candidate_preflight(
    database: Path, config: Config, producer: str, *, root: Path = ROOT
) -> dict:
    """Check persisted producer evidence; never edit or invent a manifest."""
    if git("status", "--porcelain", root=root).strip():
        raise ValueError("Candidate reuse requires a clean, committed checkout")
    for path in (database.parent, config.work_dir, config.output_dir):
        builder.require_safe_output_location(path, artifact_label="candidate product")
    state_path = database.parent.with_name(database.parent.name + ".state.json")
    state = json.loads(state_path.read_text())
    paths = builder._combined_build_paths(
        config.output_dir, build_identity=state["build_identity"]
    )
    if paths.staging_output != database.parent:
        raise ValueError("Candidate is not the recorded staging directory")
    if state["phase"] not in {"compatibility_export", "validation"}:
        raise ValueError("Candidate has not finished source and compatibility export")
    if paths.publication_journal.exists() or paths.backup_output.exists():
        raise ValueError("An interrupted publication must be recovered first")
    sidecar = json.loads((database.parent / COMBINED_MANIFEST_FILENAME).read_text())
    if sidecar != state["manifest"]:
        raise ValueError("Candidate sidecar differs from exported checkpoint")
    destination = config.output_dir / database.name
    if Path(sidecar["database"]) != destination:
        raise ValueError("Candidate publication destination differs from configuration")
    builder._require_file_state_current(
        database, state["database_stat"], label="candidate database"
    )
    builder._require_compatibility_state_current(database.parent, state)
    producer_sha = (
        git("rev-parse", f"{producer}^{{commit}}", root=root).decode().strip()
    )
    if code_fingerprint(producer_sha, root=root) != sidecar["git_code_state_sha256"]:
        raise ValueError("Recorded producer code hash does not match producer commit")
    source_digest = code_fingerprint(producer_sha, root=root, materialization=True)
    if source_digest != code_fingerprint("HEAD", root=root, materialization=True):
        raise ValueError("Materialization changed: a fresh canonical build is required")
    work_bytes = work_manifest_path(config).read_bytes()
    work = json.loads(work_bytes)
    identity = _identity(config)
    for key, value in identity.items():
        if key != "git_code_state_sha256" and work.get(key) != value:
            raise ValueError(f"Candidate work identity changed: {key}")
    if work["git_code_state_sha256"] != sidecar["git_code_state_sha256"]:
        raise ValueError("Work and database producer identities disagree")
    catalog = load_combined_catalog(config)
    errors: list[str] = []
    with open_combined_database(database, read_only=True, memory_limit_mib=2048) as con:
        # Check declared destination independently before validating physical staging.
        row = con.execute(
            "SELECT output_root, source_work_manifest_sha256 "
            "FROM preprocessing_manifest"
        ).fetchone()
        if row is None or Path(row[0]) != config.output_dir:
            raise ValueError("Embedded publication destination is inconsistent")
        if row[1] != sha(work):
            raise ValueError("Work manifest no longer matches the completed database")
        metadata = _validate_database_contract(
            con,
            database_path=database,
            sidecar={**sidecar, "database": str(database.resolve())},
            required_elements=(),
            expected_catalog_sha256=catalog.sha256,
            errors=errors,
        )
    if errors or metadata is None:
        raise ValueError("Candidate contract failed: " + "; ".join(errors))
    return {
        "valid": True,
        "scope": "candidate_materialization_reuse",
        "producer_commit": producer_sha,
        "consumer_commit": git("rev-parse", "HEAD", root=root).decode().strip(),
        "materialization_sha256": source_digest,
        "work_manifest_sha256": sha(work),
        "input_inventory_sha256": sha(work["inputs"]),
        "catalog_sha256": catalog.sha256,
        "database_size_bytes": database.stat().st_size,
        "source_certification": "pending; reuse is not scientific acceptance",
    }


def promote_candidate(database: Path, config: Config, producer: str) -> dict:
    """Use the existing publication journal and work/output locks."""
    with builder._canonical_build_lock(config):
        receipt = candidate_preflight(database, config, producer)
        if config.output_dir.exists() and any(config.output_dir.iterdir()):
            raise ValueError("Candidate promotion will not replace an existing product")
        state = json.loads(
            database.parent.with_name(database.parent.name + ".state.json").read_text()
        )
        paths = builder._combined_build_paths(
            config.output_dir, build_identity=state["build_identity"]
        )
        builder._publish_staged_product(
            paths,
            published_output=config.output_dir,
            database_name=database.name,
            replace_existing=False,
        )
        return {**receipt, "promoted": True}

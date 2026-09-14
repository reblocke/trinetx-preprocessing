"""Reuse completed raw evidence after an adapter-only verification failure."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import duckdb

from ..combined_preprocessing.builder import require_safe_output_location
from ..combined_preprocessing.glp1_adapter import canonical_inventory_from_preprocessed
from ..glp1_eligibility.builder import _validate_reusable_output
from ..glp1_eligibility.concept_sets import load_concept_sets
from ..glp1_eligibility.config import load_glp1_config
from .policy import code_fingerprint


def reuse_raw_reference(
    previous_receipt: Path,
    *,
    plan: dict,
    source_identity: dict,
    database: Path,
    raw_input: Path,
    config_path: Path,
) -> tuple[Path, dict, dict]:
    """Validate borrowed outputs without copying them or rescanning raw files.

    The prior run must have failed in the canonical build, after completing the
    raw build. All raw-producing code, dependencies, configuration, catalog and
    source identities must still match. The original producer revision remains
    in every artifact; the receipt explicitly records the reuse proof.
    """
    previous_receipt = Path(previous_receipt).absolute()
    if any(p.is_symlink() for p in (previous_receipt, *previous_receipt.parents)):
        raise ValueError("Raw-reference reuse does not accept symlinked receipts")
    require_safe_output_location(
        previous_receipt.parent, artifact_label="Prior verification receipts"
    )
    payload = previous_receipt.read_bytes()
    prior = json.loads(payload)
    if (
        prior.get("schema_version") != 1
        or prior.get("status") != "failed"
        or prior.get("phase") != "glp1_canonical"
        or not prior.get("private_full_data")
        or prior.get("plan", {}).get("head") != plan["base"]
    ):
        raise ValueError(
            "Reuse requires a canonical-build failure at the base revision"
        )
    if prior.get("source_identity") != source_identity:
        raise ValueError("Canonical source identity changed since the reference build")
    if (
        prior.get("config_sha256")
        != hashlib.sha256(config_path.read_bytes()).hexdigest()
    ):
        raise ValueError("GLP-1 configuration changed since the reference build")
    completed = [s for s in prior["steps"] if s["name"] == "glp1_raw"]
    if len(completed) != 1:
        raise ValueError("Prior receipt must contain one completed raw-reference build")
    result = completed[0]["result"]
    producer = result.get("producer_revision", prior["plan"]["head"])
    old_fingerprint = code_fingerprint(producer, raw_reference=True)
    if old_fingerprint != code_fingerprint(plan["head"], raw_reference=True):
        raise ValueError(
            "Raw-producing code or dependencies changed; rebuild reference"
        )
    output = Path(
        prior.get("raw_reference_reuse", {}).get(
            "output", previous_receipt.parent / ".verification-outputs/raw"
        )
    ).absolute()
    if any(p.is_symlink() for p in (output, *output.parents)):
        raise ValueError("Raw-reference reuse does not accept symlinked outputs")
    require_safe_output_location(output, artifact_label="Completed raw reference")
    config = load_glp1_config(config_path)
    catalog = load_concept_sets(config.concept_sets_dir)
    inventory = canonical_inventory_from_preprocessed(database, catalog=catalog)
    paths, summary = _validate_reusable_output(
        output, config=config, run_id=result["run_id"]
    )
    manifest = json.loads((output / "run_manifest.json").read_text())
    expected = {
        "run_id": result["run_id"],
        "pipeline_git_sha": producer,
        "config_sha256": config.sha256,
        "concept_catalog_sha256": catalog.sha256,
        "input_manifest_sha256": inventory.sha256,
        "input_root": str(raw_input.resolve()),
        "status": "complete",
    }
    if any(manifest.get(k) != v for k, v in expected.items()):
        raise ValueError("Completed reference manifest does not match the reuse inputs")
    with duckdb.connect(
        str(output / config.output.database_name), read_only=True
    ) as con:
        columns = ", ".join(expected)
        rows = con.execute(f"SELECT {columns} FROM run_manifest").fetchall()
    if rows != [tuple(expected.values())]:
        raise ValueError("Reference database provenance disagrees with its manifest")
    if (
        any(summary.get(k) != v for k, v in result["counts"].items())
        or summary["warning_count"] != result["warnings"]
    ):
        raise ValueError("Reference counts disagree with the completed build receipt")
    proof = {
        "output": str(output),
        "prior_receipt_sha256": hashlib.sha256(payload).hexdigest(),
        "producer_revision": producer,
        "consumer_revision": plan["head"],
        "raw_code_sha256": old_fingerprint,
        "manifest_sha256": hashlib.sha256(
            (output / "run_manifest.json").read_bytes()
        ).hexdigest(),
        "files": {
            p.name: {"size": p.stat().st_size, "mtime_ns": p.stat().st_mtime_ns}
            for p in paths
        },
        "cleanup": "borrowed reference retained; only new run outputs are owned",
    }
    return (
        output,
        {**result, "producer_revision": producer, "reused_existing": True},
        proof,
    )

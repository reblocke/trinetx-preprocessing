"""Exact retained-reference proof and separate upstream return product sealing."""

from __future__ import annotations

import json
import math
import uuid
from pathlib import Path

import pyarrow.parquet as pq

from ..combined_preprocessing.builder import require_safe_output_location
from ..filesystem import fsync_directory_strict, write_text_atomic
from .builder import VARIANTS, literal, sha256
from .compatibility import no_symlinks
from .return_acceptance import (
    REQUIRED_GATES,
    TABLES,
    canonical_digest,
    verify_accepted_return_bundle,
    verify_return_output,
)
from .return_execution import _connection
from .return_validation_v2 import _assert_equal_multiset


def _reference_manifest(bundle, receipt_path, expected_receipt_sha256, report_path):
    if sha256(no_symlinks(receipt_path)) != expected_receipt_sha256:
        raise ValueError("Retained reference receipt differs from trusted digest")
    receipt = json.loads(receipt_path.read_text())
    if receipt.get("acceptance_contract_version") == "1.0":
        return verify_accepted_return_bundle(
            bundle,
            variant="FULL_DATA",
            receipt_path=receipt_path,
            expected_receipt_sha256=expected_receipt_sha256,
            validation_report_path=report_path,
        )
    if "acceptance_contract_version" in receipt:
        raise ValueError("Unsupported reference acceptance contract")
    # Explicit, immutable historical C4 receipt. It is never rewritten or
    # promoted into acceptance of a redesigned producer.
    if (
        receipt.get("pass") is not True
        or receipt.get("config", {}).get("contract_version") != "2.0"
        or receipt.get("source_and_parent_after_equal") is not True
        or receipt.get("source_and_parent_before")
        != receipt.get("source_and_parent_after")
        or receipt.get("return_validation_sha256") != sha256(no_symlinks(report_path))
        or receipt.get("output_manifest_sha256")
        != sha256(no_symlinks(bundle / "manifest.json"))
    ):
        raise ValueError("Unsupported or inconsistent historical return reference seal")
    report = json.loads(report_path.read_text())
    manifest = json.loads((bundle / "manifest.json").read_text())
    if (
        report.get("pass") is not True
        or report.get("validation_contract_version") != "2.0"
        or report.get("bundle_manifest_sha256") != receipt["output_manifest_sha256"]
        or manifest.get("code_sha256") != receipt.get("gates", {}).get("code_sha256")
        or manifest.get("parent_manifest_sha256")
        != receipt["source_and_parent_before"].get("parent_manifest_sha256")
        or manifest.get("source_manifest_sha256")
        != receipt["source_and_parent_before"].get("source_sidecar_sha256")
    ):
        raise ValueError("Historical reference validation bindings differ")
    return {
        **manifest,
        "source_database_sha256": receipt["source_and_parent_before"][
            "source_database_sha256"
        ],
    }


def compare_retained_reference(
    *,
    bundle: Path,
    reference_bundle: Path,
    reference_receipt_path: Path,
    expected_reference_receipt_sha256: str,
    reference_validation_report_path: Path,
    work_dir: Path,
    report_path: Path,
    events=None,
    memory_limit_mib=3072,
    threads=1,
) -> dict:
    """Compare all six typed row multisets for both independent variants."""
    from .return_resources import check_settings

    check_settings(memory_limit_mib, threads)
    bundle, reference_bundle = no_symlinks(bundle), no_symlinks(reference_bundle)
    report_path, work_dir = no_symlinks(report_path), no_symlinks(work_dir)
    for path in (report_path.parent, work_dir):
        require_safe_output_location(path, artifact_label="retained return comparison")
        if any(
            path.is_relative_to(p) or p.is_relative_to(path)
            for p in (bundle, reference_bundle)
        ):
            raise ValueError("Return comparison evidence overlaps an input")
    if report_path.exists():
        raise FileExistsError("Historical comparison reports cannot be overwritten")
    reference = _reference_manifest(
        reference_bundle,
        reference_receipt_path,
        expected_reference_receipt_sha256,
        reference_validation_report_path,
    )
    candidate = json.loads((bundle / "manifest.json").read_text())
    initial = {
        "candidate": sha256(bundle / "manifest.json"),
        "reference": sha256(reference_bundle / "manifest.json"),
    }
    for manifest, root in ((candidate, bundle), (reference, reference_bundle)):
        if (
            manifest.get("kind") != "return_outcomes"
            or manifest.get("status") != "complete"
            or manifest.get("schema_version") != "2.0"
            or manifest.get("return_contract_version") != "2.0"
            or manifest.get("variants") != list(VARIANTS)
            or manifest.get("horizons_days") != [30, 90, 365]
            or type(manifest.get("partitions")) is not int
            or not 1 <= manifest["partitions"] <= 1024
        ):
            raise ValueError("Retained return comparison contracts differ")
        expected = {"data_dictionary.json", "progress.json"} | {
            f"{v.lower()}_{b:04d}_{t}.parquet"
            for v in VARIANTS
            for b in range(manifest["partitions"])
            for t in TABLES
        }
        if set(manifest.get("outputs", {})) != expected:
            raise ValueError("Retained return comparison inventory differs")
        for name in expected:
            verify_return_output(root, manifest, name)
    for field in (
        "source_manifest_sha256",
        "parent_manifest_sha256",
        "source_database_sha256",
    ):
        if candidate.get(field) != reference.get(field):
            raise ValueError("Retained reference source/parent provenance differs")
    groups = math.gcd(candidate["partitions"], reference["partitions"])
    checked = []
    with _connection(
        work_dir,
        memory_limit_mib=memory_limit_mib,
        threads=threads,
        events=events,
        phase="reference_comparison",
    ) as db:
        for variant in VARIANTS:
            for table in TABLES:
                for bucket in range(groups):
                    paths = []
                    for root, manifest in (
                        (reference_bundle, reference),
                        (bundle, candidate),
                    ):
                        files = [
                            root / f"{variant.lower()}_{b:04d}_{table}.parquet"
                            for b in range(bucket, manifest["partitions"], groups)
                        ]
                        paths.append(files)
                    schema = pq.read_schema(paths[0][0])
                    if any(
                        not pq.read_schema(p).equals(schema, check_metadata=False)
                        for files in paths
                        for p in files
                    ):
                        raise ValueError("Retained reference typed schema differs")
                    queries = [
                        "SELECT * FROM read_parquet(["
                        + ",".join(literal(p) for p in files)
                        + "])"
                        for files in paths
                    ]
                    _assert_equal_multiset(
                        db, *queries, f"retained {variant} {table} group {bucket}"
                    )
                    checked.append(
                        {
                            "variant": variant,
                            "table": table,
                            "group": bucket,
                            "pass": True,
                        }
                    )
                    if events:
                        events.emit(
                            "reference",
                            "comparison_complete",
                            variant=variant,
                            table=table,
                            bucket=bucket,
                        )
    for root, manifest in ((bundle, candidate), (reference_bundle, reference)):
        for name in manifest["outputs"]:
            verify_return_output(root, manifest, name)
    if initial != {
        "candidate": sha256(bundle / "manifest.json"),
        "reference": sha256(reference_bundle / "manifest.json"),
    }:
        raise ValueError("Reference comparison manifests changed")
    if sha256(reference_receipt_path) != expected_reference_receipt_sha256:
        raise ValueError("Reference acceptance changed during comparison")
    result = {
        "pass": True,
        "comparison_contract_version": "1.0",
        "method": "exact typed bidirectional EXCEPT ALL",
        "bundle_manifest_sha256": initial["candidate"],
        "reference_manifest_sha256": initial["reference"],
        "reference_acceptance_sha256": expected_reference_receipt_sha256,
        "comparisons": checked,
        "scientific_tolerances_changed": False,
        "physical_parquet_encoding_compared": False,
    }
    write_text_atomic(report_path, json.dumps(result, sort_keys=True, indent=2) + "\n")
    fsync_directory_strict(report_path.parent)
    return result


def seal_return_product(
    *,
    bundle: Path,
    inputs,
    validation_report_path: Path,
    comparison_report_path: Path,
    receipt_path: Path,
    runtime_report_path: Path,
    expected_runtime_report_sha256: str,
    unchanged_inputs_report_path: Path,
    expected_unchanged_inputs_sha256: str,
) -> dict:
    """Seal upstream product evidence; downstream release certification is later.

    Runtime evidence must be explicitly supplied and independently trusted by the
    controller. No synthetic success replaces a failed private gate.
    """
    receipt_path = no_symlinks(receipt_path)
    require_safe_output_location(
        receipt_path.parent, artifact_label="return acceptance seal"
    )
    if receipt_path.exists():
        raise FileExistsError("Acceptance receipts are immutable")
    for source in (bundle, inputs.parent_bundle, inputs.database.parent):
        if receipt_path.parent.is_relative_to(source) or source.is_relative_to(
            receipt_path.parent
        ):
            raise ValueError("Return acceptance seal overlaps an input")
    report = json.loads(no_symlinks(validation_report_path).read_text())
    comparison = json.loads(no_symlinks(comparison_report_path).read_text())
    manifest_hash = sha256(no_symlinks(bundle / "manifest.json"))
    if (
        report.get("pass") is not True
        or comparison.get("pass") is not True
        or report.get("bundle_manifest_sha256") != manifest_hash
        or comparison.get("bundle_manifest_sha256") != manifest_hash
    ):
        raise ValueError("Return validation or retained reference gate did not pass")
    if sha256(no_symlinks(runtime_report_path)) != expected_runtime_report_sha256:
        raise ValueError("Runtime evidence differs from trusted digest")
    runtime = json.loads(runtime_report_path.read_text())
    if (
        runtime.get("status") != "passed"
        or runtime.get("bundle_manifest_sha256") != manifest_hash
        or not isinstance(runtime.get("candidate_total_seconds"), (int, float))
        or isinstance(runtime["candidate_total_seconds"], bool)
        or not isinstance(runtime.get("baseline_build_validate_seconds"), (int, float))
        or isinstance(runtime["baseline_build_validate_seconds"], bool)
        or not math.isfinite(runtime["candidate_total_seconds"])
        or not math.isfinite(runtime["baseline_build_validate_seconds"])
        or not 0
        < runtime["candidate_total_seconds"]
        < runtime["baseline_build_validate_seconds"]
    ):
        raise ValueError("Measured runtime improvement gate did not pass")
    if (
        sha256(no_symlinks(unchanged_inputs_report_path))
        != expected_unchanged_inputs_sha256
    ):
        raise ValueError("Unchanged-input proof differs from trusted digest")
    unchanged = json.loads(unchanged_inputs_report_path.read_text())
    inputs.check_unchanged()
    if (
        unchanged.get("pass") is not True
        or unchanged.get("input_proof_version") != "1.0"
        or unchanged.get("inputs_sha256") != canonical_digest(inputs.receipt["inputs"])
        or unchanged.get("file_stats") != inputs.file_stats
        or unchanged.get("prerequisite_receipt_sha256") != inputs.receipt_sha256
    ):
        raise ValueError("Unchanged-input byte proof does not cover this execution")
    binding = {
        k: report[k]
        for k in (
            "schema_version",
            "return_contract_version",
            "bundle_manifest_sha256",
            "parent_manifest_sha256",
            "source_manifest_sha256",
            "source_database_sha256",
            "identities",
            "original_keys",
            "artifact_inventory_sha256",
        )
    }
    evidence = {
        "source_validation": inputs.receipt_sha256,
        "parent_validation": inputs.receipt_sha256,
        "artifact_validation": sha256(validation_report_path),
        "original_keys": sha256(validation_report_path),
        "retained_reference": sha256(comparison_report_path),
        "unchanged_inputs": expected_unchanged_inputs_sha256,
    }
    receipt = {
        **binding,
        "kind": "return_outcomes_acceptance",
        "status": "accepted",
        "acceptance_contract_version": "1.0",
        "validation_report_sha256": sha256(validation_report_path),
        "gates": {
            g: {"status": "pass", "evidence_sha256": evidence[g]}
            for g in REQUIRED_GATES
        },
        "runtime_evidence_sha256": expected_runtime_report_sha256,
        "release_verification": (
            "pending downstream installed consumer and committed-pin certification"
        ),
    }
    # Candidate receipt stays external; self-check every actual product artifact
    # before its final immutable publication.
    draft = receipt_path.with_name(receipt_path.name + f".pending-{uuid.uuid4().hex}")
    write_text_atomic(draft, json.dumps(receipt, sort_keys=True, indent=2) + "\n")
    verify_accepted_return_bundle(
        bundle,
        variant="FULL_DATA",
        receipt_path=draft,
        expected_receipt_sha256=sha256(draft),
        validation_report_path=validation_report_path,
    )
    # Artifact/key verification can take time on a full product. Recheck the
    # previously byte-proven input identities immediately before publication.
    inputs.check_unchanged()
    draft.replace(receipt_path)
    fsync_directory_strict(receipt_path.parent)
    return receipt

"""Authenticated prerequisite reuse bound to unchanged input bytes and dependencies."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from ..combined_preprocessing.builder import require_safe_output_location
from ..combined_preprocessing.cohort_source import validate_cohort_source
from ..combined_preprocessing.database import COMBINED_MANIFEST_FILENAME
from ..filesystem import fsync_directory_strict, write_text_atomic
from .builder import sha256
from .compatibility import file_identity, no_symlinks
from .return_acceptance import canonical_digest
from .return_evidence import component_identities
from .return_parent_validation import DAY_PRECISION_VALIDATION_VERSION, validate_bundle
from .returns import _require_source_capabilities


def input_inventory(database: Path, parent_bundle: Path) -> dict:
    """Complete immutable source/parent byte proof, including filesystem sidecars."""
    files = {
        "source_database": no_symlinks(database),
        "source_manifest": no_symlinks(database.parent / COMBINED_MANIFEST_FILENAME),
    }
    for path in sorted(no_symlinks(parent_bundle).rglob("*")):
        no_symlinks(path)
        if path.is_file():
            files["parent/" + str(path.relative_to(parent_bundle))] = path
    return {
        n: {"bytes": p.stat().st_size, "sha256": sha256(p)} for n, p in files.items()
    }


def _stats(database, parent_bundle):
    paths = [
        database,
        database.parent / COMBINED_MANIFEST_FILENAME,
        *[p for p in sorted(parent_bundle.rglob("*")) if p.is_file()],
    ]
    return {
        str(p): [*file_identity(no_symlinks(p)), p.stat().st_ctime_ns] for p in paths
    }


@dataclass(frozen=True)
class VerifiedPrerequisites:
    database: Path
    parent_bundle: Path
    receipt_path: Path
    receipt_sha256: str
    receipt: dict
    file_stats: dict

    def check_unchanged(self, *, complete_bytes=False):
        if sha256(no_symlinks(self.receipt_path)) != self.receipt_sha256:
            raise ValueError("Authenticated prerequisite receipt changed")
        if _stats(self.database, self.parent_bundle) != self.file_stats:
            raise ValueError("Source or parent changed during execution")
        if (
            complete_bytes
            and input_inventory(self.database, self.parent_bundle)
            != self.receipt["inputs"]
        ):
            raise ValueError("Source or parent bytes changed during execution")
        current = component_identities()
        for role, identity in self.receipt["dependencies"].items():
            if role in current and current[role] != identity:
                raise ValueError("Prerequisite validation dependencies changed")

    def prove_unchanged_bytes(self, report_path: Path) -> dict:
        report_path = no_symlinks(report_path)
        require_safe_output_location(
            report_path.parent, artifact_label="unchanged input proof"
        )
        if report_path.exists():
            raise FileExistsError("Unchanged-input proofs are immutable")
        self.check_unchanged(complete_bytes=True)
        report = {
            "pass": True,
            "input_proof_version": "1.0",
            "inputs_sha256": canonical_digest(self.receipt["inputs"]),
            "file_stats": self.file_stats,
            "prerequisite_receipt_sha256": self.receipt_sha256,
        }
        write_text_atomic(
            report_path, json.dumps(report, sort_keys=True, indent=2) + "\n"
        )
        fsync_directory_strict(report_path.parent)
        return report


def prepare_prerequisites(
    *,
    database: Path,
    parent_bundle: Path,
    receipt_path: Path,
    work_dir: Path,
    reuse_receipt_path: Path | None = None,
    expected_reuse_sha256: str | None = None,
) -> VerifiedPrerequisites:
    database, parent_bundle = no_symlinks(database), no_symlinks(parent_bundle)
    receipt_path, work_dir = no_symlinks(receipt_path), no_symlinks(work_dir)
    for path in (receipt_path.parent, work_dir):
        require_safe_output_location(
            path, artifact_label="return prerequisite evidence"
        )
        if any(
            path.is_relative_to(p) or p.is_relative_to(path)
            for p in (database.parent, parent_bundle)
        ):
            raise ValueError("Prerequisite evidence overlaps immutable inputs")
    if receipt_path.exists():
        raise FileExistsError("Historical prerequisite receipts cannot be overwritten")
    if (reuse_receipt_path is None) != (expected_reuse_sha256 is None):
        raise ValueError("Reuse requires both explicit receipt and trusted SHA-256")
    before = _stats(database, parent_bundle)
    inputs = input_inventory(database, parent_bundle)
    identities = component_identities()
    dependencies = {
        k: identities[k]
        for k in ("parent_validator", "source_validator", "environment", "contract")
    }
    sidecar = json.loads((database.parent / COMBINED_MANIFEST_FILENAME).read_text())
    dependencies["catalog"] = canonical_digest(sidecar)
    parent_manifest = json.loads((parent_bundle / "manifest.json").read_text())
    if (
        parent_manifest.get("source_manifest_sha256")
        != inputs["source_manifest"]["sha256"]
    ):
        raise ValueError("Parent and canonical source provenance differ")
    if reuse_receipt_path is not None:
        path = no_symlinks(reuse_receipt_path)
        if sha256(path) != expected_reuse_sha256:
            raise ValueError("Prerequisite receipt differs from trusted digest")
        old = json.loads(path.read_text())
        if (
            old.get("prerequisite_contract_version") != "1.0"
            or old.get("status") != "validated"
            or old.get("inputs") != inputs
            or old.get("dependencies") != dependencies
            or old.get("parent_report", {}).get("pass") is not True
            or old.get("source_report", {}).get("valid") is not True
            or old.get("source_report", {}).get("required_return_capabilities")
            is not True
        ):
            raise ValueError(
                "Prerequisite reuse dependencies or validated scope differ"
            )
        source_report, parent_report = old["source_report"], old["parent_report"]
        reused_from = expected_reuse_sha256
    else:
        source = validate_cohort_source(database)
        if not source.valid or source.metadata is None:
            raise ValueError("Canonical cohort source failed validation")
        _require_source_capabilities(database)
        parent_report = validate_bundle(
            bundle=parent_bundle,
            work_dir=work_dir,
            memory_limit_mib=4096,
            distinct_count_partitions=32,
            validation_contract_version=DAY_PRECISION_VALIDATION_VERSION,
        )
        if parent_report.get("pass") is not True:
            raise ValueError("Return parent validation failed")
        source_report = {
            "valid": True,
            "metadata": source.metadata.to_dict(),
            "required_return_capabilities": True,
        }
        reused_from = None
    if _stats(database, parent_bundle) != before:
        raise ValueError("Prerequisite inputs changed during validation")
    receipt = {
        "prerequisite_contract_version": "1.0",
        "status": "validated",
        "inputs": inputs,
        "dependencies": dependencies,
        "parent_report": parent_report,
        "source_report": source_report,
        "reused_from_sha256": reused_from,
    }
    write_text_atomic(
        receipt_path, json.dumps(receipt, sort_keys=True, indent=2) + "\n"
    )
    fsync_directory_strict(receipt_path.parent)
    return VerifiedPrerequisites(
        database, parent_bundle, receipt_path, sha256(receipt_path), receipt, before
    )

"""Shared, manifest-bound acceptance boundary for encounter consumers.

The caller supplies a trusted receipt SHA-256. A receipt discovered next to a
bundle is never trusted implicitly. This module verifies acceptance evidence;
it does not perform or claim the private release gates.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import duckdb
import pyarrow.parquet as pq

from .builder import EVIDENCE_TABLES, SCHEMA_VERSION, VARIANTS
from .compatibility import digest

ACCEPTANCE_CONTRACT_VERSION = "1.0"
FEATURE_CONTRACT_VERSION = "1.0"
REQUIRED_GATES = frozenset(
    {"artifact_validation", "retained_reference", "source_coverage", "installed_pair"}
)
COVERAGE_POLICIES = frozenset({"complete_linkage", "approved_incomplete_linkage"})
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


def _regular_file(path: Path) -> Path:
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError(
            f"Required acceptance artifact is not a regular file: {path.name}"
        )
    return path


def _sha256(value: object, label: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ValueError(f"Invalid {label} SHA-256")
    return value


def _json(path: Path) -> dict:
    value = json.loads(_regular_file(path).read_text())
    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object: {path.name}")
    return value


def required_output_name(variant: str, table: str = "features") -> str:
    if variant not in VARIANTS:
        raise ValueError("variant must be FULL_DATA or AFTER_EXCLUSION")
    if table == "features":
        return f"encounter_features_{variant.lower()}.parquet"
    if table not in (*EVIDENCE_TABLES, "encounter_source_coverage"):
        raise ValueError(f"Unsupported encounter evidence table: {table}")
    return f"encounter_features_{variant.lower()}_{table}.parquet"


def verify_output(bundle: Path, manifest: dict, name: str) -> Path:
    """Verify exactly the artifact about to be consumed, including metadata."""
    info = manifest.get("outputs", {}).get(name)
    if not isinstance(info, dict):
        raise ValueError(f"Required encounter output missing: {name}")
    expected = _sha256(info.get("sha256"), f"{name} output")
    size = info.get("bytes")
    if type(size) is not int or size < 0:
        raise ValueError(f"Invalid output size: {name}")
    path = _regular_file(Path(bundle) / name)
    if path.stat().st_size != size or digest(path) != expected:
        raise ValueError(f"Encounter output differs from accepted manifest: {name}")
    return path


def verify_feature_schema(
    bundle: Path, manifest: dict, variant: str, path: Path
) -> dict[str, str]:
    """Inspect Parquet metadata against the accepted dictionary without loading rows."""
    dictionary_path = verify_output(bundle, manifest, "data_dictionary.json")
    dictionary = json.loads(dictionary_path.read_text())
    entries = dictionary.get(variant)
    if not isinstance(entries, list) or not entries:
        raise ValueError(f"Feature dictionary missing variant {variant}")
    expected = {entry.get("column"): entry.get("dtype") for entry in entries}
    if len(expected) != len(entries) or any(
        not k or not v for k, v in expected.items()
    ):
        raise ValueError("Feature dictionary has invalid or repeated columns")
    if any(
        expected.get(key) != "VARCHAR"
        for key in ("patient_id", "encounter_id", "pat_enc_hash")
    ):
        raise ValueError("Feature dictionary lacks original string linkage identifiers")
    frozen = load_artifact_contract()["features"][variant]
    if expected != frozen:
        raise ValueError(
            f"Encounter feature dictionary differs from versioned {variant} contract"
        )
    with duckdb.connect() as connection:
        rows = connection.execute(
            "DESCRIBE SELECT * FROM read_parquet(?)", [str(path)]
        ).fetchall()
    actual = {name: dtype for name, dtype, *_ in rows}
    if actual != frozen:
        missing = sorted(set(frozen) - set(actual))
        extra = sorted(set(actual) - set(frozen))
        wrong = sorted(
            k for k in frozen.keys() & actual.keys() if frozen[k] != actual[k]
        )
        raise ValueError(
            f"Encounter feature schema differs from contract: missing={missing}, "
            f"extra={extra}, wrong_type={wrong}"
        )
    return actual


def load_artifact_contract() -> dict:
    contract = json.loads(
        Path(__file__).with_name("artifact_contract.json").read_text()
    )
    if (
        contract.get("version") != "1.0"
        or set(contract.get("tables", {}))
        != {*EVIDENCE_TABLES, "encounter_source_coverage"}
        or set(contract.get("features", {})) != set(VARIANTS)
    ):
        raise ValueError("Unsupported encounter evidence contract")
    return contract


def verify_companion_schema(path: Path, table: str) -> dict[str, str]:
    """Check an evidence or coverage Parquet schema without reading rows."""
    expected = load_artifact_contract()["tables"].get(table)
    if expected is None:
        raise ValueError(f"Unsupported encounter companion table: {table}")
    actual = {field.name: str(field.type) for field in pq.read_schema(path)}
    if actual != expected:
        missing = sorted(set(expected) - set(actual))
        extra = sorted(set(actual) - set(expected))
        wrong_type = sorted(
            key
            for key in actual.keys() & expected.keys()
            if actual[key] != expected[key]
        )
        raise ValueError(
            f"{Path(path).name} schema differs: missing={missing}, "
            f"extra={extra}, wrong_type={wrong_type}"
        )
    return actual


def verify_accepted_bundle(
    bundle: Path,
    *,
    receipt_path: Path,
    expected_receipt_sha256: str,
    validation_report_path: Path,
    variant: str,
    coverage_policy: str = "complete_linkage",
) -> dict:
    """Verify a caller-trusted acceptance receipt for this exact bundle/variant."""
    required_output_name(variant)
    if coverage_policy not in COVERAGE_POLICIES:
        raise ValueError("Unsupported encounter coverage policy")
    receipt_path = _regular_file(receipt_path)
    if digest(receipt_path) != _sha256(expected_receipt_sha256, "trusted receipt"):
        raise ValueError("Acceptance receipt identity differs from trusted expectation")
    receipt = _json(receipt_path)
    manifest_path = _regular_file(Path(bundle) / "manifest.json")
    manifest = _json(manifest_path)
    if (
        manifest.get("schema_version") != SCHEMA_VERSION
        or manifest.get("status") != "complete"
        or manifest.get("kind") != "encounter_features"
        or manifest.get("feature_contract_version") != FEATURE_CONTRACT_VERSION
    ):
        raise ValueError("Unsupported, legacy or incomplete encounter feature bundle")
    if (
        receipt.get("acceptance_contract_version") != ACCEPTANCE_CONTRACT_VERSION
        or receipt.get("status") != "accepted"
        or receipt.get("bundle_manifest_sha256") != digest(manifest_path)
        or receipt.get("product")
        != {
            "schema_version": SCHEMA_VERSION,
            "kind": "encounter_features",
            "feature_contract_version": FEATURE_CONTRACT_VERSION,
        }
        or receipt.get("outputs") != manifest.get("outputs")
        or receipt.get("source") != manifest.get("source")
        or receipt.get("compatibility") != manifest.get("compatibility")
    ):
        raise ValueError("Acceptance receipt does not bind this feature manifest")
    if (
        set(receipt.get("variants", [])) != set(VARIANTS)
        or variant not in receipt["variants"]
    ):
        raise ValueError("Acceptance receipt does not cover required variants")
    if receipt.get("coverage_policy") != coverage_policy:
        raise ValueError("Acceptance receipt has a different coverage policy")
    coverage = receipt.get("coverage")
    if (
        not isinstance(coverage, dict)
        or coverage.get("policy") != coverage_policy
        or coverage.get("pass") is not True
        or (
            coverage_policy == "complete_linkage"
            and (
                coverage.get("complete_patient_linkage") is not True
                or coverage.get("complete_encounter_linkage") is not True
            )
        )
        or (
            coverage_policy == "approved_incomplete_linkage"
            and not coverage.get("approved_exception")
        )
    ):
        raise ValueError("Acceptance coverage does not satisfy the declared policy")
    gates = receipt.get("gates")
    if (
        not isinstance(gates, dict)
        or set(gates) != REQUIRED_GATES
        or any(
            not isinstance(gate, dict)
            or gate.get("pass") is not True
            or _SHA256.fullmatch(str(gate.get("evidence_sha256", ""))) is None
            for gate in gates.values()
        )
    ):
        raise ValueError("Acceptance receipt lacks a passing mandatory production gate")
    report_path = _regular_file(validation_report_path)
    if digest(report_path) != gates["artifact_validation"]["evidence_sha256"]:
        raise ValueError("Artifact validation report differs from acceptance receipt")
    report = _json(report_path)
    if (
        report.get("pass") is not True
        or report.get("validation_contract_version") != ACCEPTANCE_CONTRACT_VERSION
        or report.get("bundle_manifest_sha256") != receipt["bundle_manifest_sha256"]
        or report.get("schema_version") != SCHEMA_VERSION
        or report.get("feature_contract_version") != FEATURE_CONTRACT_VERSION
        or report.get("kind") != "encounter_features"
        or report.get("outputs") != manifest["outputs"]
        or report.get("source") != manifest["source"]
        or report.get("compatibility") != manifest["compatibility"]
        or report.get("producer_code_sha256") != manifest.get("code_sha256")
        or set(report.get("variants", {})) != set(VARIANTS)
        or any(report["variants"][name].get("pass") is not True for name in VARIANTS)
    ):
        raise ValueError(
            "Artifact validation report does not establish required contract"
        )
    if (
        not isinstance(receipt.get("producer_revision"), str)
        or not receipt["producer_revision"]
    ):
        raise ValueError("Acceptance receipt lacks historical producer revision")
    if (
        not isinstance(receipt.get("validator_revision"), str)
        or not receipt["validator_revision"]
    ):
        raise ValueError("Acceptance receipt lacks validator revision")
    if (
        not isinstance(receipt.get("consumer_revision"), str)
        or not receipt["consumer_revision"]
    ):
        raise ValueError("Acceptance receipt lacks tested consumer revision")
    if (
        not isinstance(receipt.get("reference_comparison"), dict)
        or not all(
            receipt["reference_comparison"].get(key)
            for key in (
                "contract_version",
                "contract_sha256",
                "bundle_manifest_sha256",
                "report_sha256",
            )
        )
        or receipt["reference_comparison"].get("pass") is not True
        or receipt["reference_comparison"]["report_sha256"]
        != gates["retained_reference"]["evidence_sha256"]
        or receipt["reference_comparison"]["bundle_manifest_sha256"]
        != digest(manifest_path)
    ):
        raise ValueError("Acceptance receipt lacks bound retained-reference evidence")
    if (
        digest(manifest_path) != receipt["bundle_manifest_sha256"]
        or digest(receipt_path) != expected_receipt_sha256
    ):
        raise ValueError("Encounter acceptance changed during verification")
    return manifest

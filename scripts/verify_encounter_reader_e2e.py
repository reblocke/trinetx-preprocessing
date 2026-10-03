#!/usr/bin/env python3
"""Installed shared encounter reader E2E with retained real-Parquet expectations."""

from __future__ import annotations

import argparse
import json
import platform
import sys
from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq

from trinetx_preprocessing.encounters.acceptance import load_artifact_contract
from trinetx_preprocessing.encounters.compatibility import digest


def _write(path, data):
    path.write_text(json.dumps(data, sort_keys=True) + "\n")


def _identity(path):
    return {"bytes": path.stat().st_size, "sha256": digest(path)}


def _rebind_synthetic_acceptance(root, trust):
    """Refresh identities so a mutation reaches the substantive reader check."""
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["outputs"] = {name: _identity(root / name) for name in manifest["outputs"]}
    _write(manifest_path, manifest)
    report_path = trust["validation_report_path"]
    report = json.loads(report_path.read_text())
    report["outputs"] = manifest["outputs"]
    report["bundle_manifest_sha256"] = digest(manifest_path)
    _write(report_path, report)
    receipt_path = trust["receipt_path"]
    receipt = json.loads(receipt_path.read_text())
    receipt["outputs"] = manifest["outputs"]
    receipt["bundle_manifest_sha256"] = digest(manifest_path)
    receipt["reference_comparison"]["bundle_manifest_sha256"] = digest(manifest_path)
    receipt["gates"]["artifact_validation"]["evidence_sha256"] = digest(report_path)
    _write(receipt_path, receipt)
    trust["expected_receipt_sha256"] = digest(receipt_path)


def _arrow_type(name):
    if name == "date32[day]":
        return pa.date32()
    if name == "timestamp[us]":
        return pa.timestamp("us")
    duckdb_types = {
        "FLOAT": pa.float32(),
        "BIGINT": pa.int64(),
        "DOUBLE": pa.float64(),
        "VARCHAR": pa.string(),
        "TIMESTAMP": pa.timestamp("us"),
        "BOOLEAN": pa.bool_(),
        "TINYINT": pa.int8(),
        "DATE": pa.date32(),
        "INTEGER": pa.int32(),
    }
    if name in duckdb_types:
        return duckdb_types[name]
    return pa.type_for_alias(name)


def build_fixture(tmp_path):
    root = tmp_path / "bundle"
    root.mkdir()
    outputs = {}
    for variant in ("FULL_DATA", "AFTER_EXCLUSION"):
        stem = f"encounter_features_{variant.lower()}"
        feature = root / f"{stem}.parquet"
        schema = load_artifact_contract()["features"][variant]
        populated = {
            "patient_id": ["001", "001"],
            "encounter_id": ["A", "B"],
            "pat_enc_hash": ["001-A", "001-B"],
            "niv_proc": [1, 0],
        }
        pq.write_table(
            pa.table(
                {
                    name: pa.array(
                        populated.get(name, [None, None]), type=_arrow_type(dtype)
                    )
                    for name, dtype in schema.items()
                }
            ),
            feature,
        )
        outputs[feature.name] = _identity(feature)
        evidence = root / f"{stem}_medication_component_evidence.parquet"
        schema = load_artifact_contract()["tables"]["medication_component_evidence"]
        values = {}
        for name, dtype in schema.items():
            value = {"index_event_id": "001-A", "source_record_hash": "m1"}.get(name)
            values[name] = pa.array([value], type=_arrow_type(dtype))
        pq.write_table(pa.table(values), evidence)
        outputs[evidence.name] = _identity(evidence)
    dictionary = {
        variant: [
            {"column": key, "dtype": dtype}
            for key, dtype in load_artifact_contract()["features"][variant].items()
        ]
        for variant in ("FULL_DATA", "AFTER_EXCLUSION")
    }
    dictionary_path = root / "data_dictionary.json"
    _write(dictionary_path, dictionary)
    outputs[dictionary_path.name] = _identity(dictionary_path)
    manifest = {
        "schema_version": "2.0",
        "status": "complete",
        "kind": "encounter_features",
        "feature_contract_version": "1.0",
        "source": {"synthetic": True},
        "compatibility": {"synthetic": True},
        "code_sha256": "c" * 64,
        "outputs": outputs,
    }
    manifest_path = root / "manifest.json"
    _write(manifest_path, manifest)
    report = {
        "pass": True,
        "validation_contract_version": "1.0",
        "bundle_manifest_sha256": digest(manifest_path),
        "schema_version": "2.0",
        "feature_contract_version": "1.0",
        "kind": "encounter_features",
        "outputs": outputs,
        "source": manifest["source"],
        "compatibility": manifest["compatibility"],
        "producer_code_sha256": manifest["code_sha256"],
        "variants": {v: {"pass": True} for v in ("FULL_DATA", "AFTER_EXCLUSION")},
    }
    report_path = tmp_path / "validation.json"
    _write(report_path, report)
    gates = {
        key: {"pass": True, "evidence_sha256": "a" * 64}
        for key in (
            "artifact_validation",
            "retained_reference",
            "source_coverage",
            "installed_pair",
        )
    }
    gates["artifact_validation"]["evidence_sha256"] = digest(report_path)
    receipt = {
        "acceptance_contract_version": "1.0",
        "status": "accepted",
        "bundle_manifest_sha256": digest(manifest_path),
        "product": {
            "schema_version": "2.0",
            "kind": "encounter_features",
            "feature_contract_version": "1.0",
        },
        "outputs": outputs,
        "source": manifest["source"],
        "compatibility": manifest["compatibility"],
        "variants": ["FULL_DATA", "AFTER_EXCLUSION"],
        "coverage_policy": "complete_linkage",
        "coverage": {
            "policy": "complete_linkage",
            "pass": True,
            "complete_patient_linkage": True,
            "complete_encounter_linkage": True,
        },
        "gates": gates,
        "producer_revision": "synthetic-producer",
        "validator_revision": "synthetic-validator",
        "consumer_revision": "synthetic-consumer",
        "reference_comparison": {
            "contract_version": "1.0",
            "contract_sha256": "b" * 64,
            "report_sha256": "a" * 64,
            "pass": True,
            "bundle_manifest_sha256": digest(manifest_path),
        },
    }
    receipt_path = tmp_path / "acceptance.json"
    _write(receipt_path, receipt)
    trust = {
        "receipt_path": receipt_path,
        "expected_receipt_sha256": digest(receipt_path),
        "validation_report_path": report_path,
    }
    return root, trust


def run(root):
    from trinetx_preprocessing.encounters.reader import (
        read_encounter_companion,
        read_encounters,
        read_encounters_development,
        scan_accepted_encounter_bundle,
    )

    bundle, trust = build_fixture(root)
    rejected = []

    def reject(label, action):
        try:
            action()
        except (ValueError, FileNotFoundError):
            rejected.append(label)
        else:
            raise AssertionError(f"Did not reject {label}")

    for variant in ("FULL_DATA", "AFTER_EXCLUSION"):
        frame = read_encounters(
            bundle, variant=variant, columns=["encounter_id", "patient_id"], **trust
        )
        assert frame.to_dict("list") == {
            "encounter_id": ["A", "B"],
            "patient_id": ["001", "001"],
        }
        companion = read_encounter_companion(
            bundle, variant=variant, table="medication_component_evidence", **trust
        )
        assert companion.source_record_hash.tolist() == ["m1"]
        assert companion.index_event_id.tolist() == ["001-A"]
        assert read_encounters_development(
            bundle, variant=variant, columns=["patient_id"]
        ).patient_id.tolist() == ["001", "001"]
    reject(
        "wrong trust",
        lambda: read_encounters(
            bundle,
            variant="FULL_DATA",
            **{**trust, "expected_receipt_sha256": "0" * 64},
        ),
    )
    for columns in (["missing"], ["patient_id", "patient_id"]):
        reject(
            "invalid projection",
            lambda: read_encounters(
                bundle, variant="FULL_DATA", columns=columns, **trust
            ),
        )
    feature = bundle / "encounter_features_full_data.parquet"
    original = feature.read_bytes()
    feature.write_bytes(original + b"changed")
    reject(
        "changed feature", lambda: read_encounters(bundle, variant="FULL_DATA", **trust)
    )
    feature.write_bytes(original)
    manifest_path = bundle / "manifest.json"
    original_manifest = manifest_path.read_bytes()
    manifest = json.loads(original_manifest)
    _write(manifest_path, {**manifest, "kind": "legacy_base"})
    reject(
        "legacy production has no fallback",
        lambda: read_encounters(bundle, variant="FULL_DATA", **trust),
    )
    manifest_path.write_bytes(original_manifest)
    receipt_path = trust["receipt_path"]
    original_receipt = receipt_path.read_bytes()
    receipt = json.loads(original_receipt)
    receipt["gates"]["source_coverage"]["pass"] = False
    _write(receipt_path, receipt)
    reject(
        "failed gate",
        lambda: read_encounters(
            bundle,
            variant="FULL_DATA",
            **{**trust, "expected_receipt_sha256": digest(receipt_path)},
        ),
    )
    receipt_path.write_bytes(original_receipt)
    companion = (
        bundle / "encounter_features_full_data_medication_component_evidence.parquet"
    )
    companion_bytes = companion.read_bytes()
    with duckdb.connect() as db:
        with scan_accepted_encounter_bundle(
            db,
            bundle,
            variant="FULL_DATA",
            companion_tables=("medication_component_evidence",),
            **trust,
        ) as views:
            assert db.execute(
                f'SELECT patient_id, encounter_id FROM "{views["features"]}" '
                "ORDER BY encounter_id"
            ).fetchall() == [("001", "A"), ("001", "B")]
            assert db.execute(
                "SELECT source_record_hash FROM "
                f'"{views["medication_component_evidence"]}"'
            ).fetchall() == [("m1",)]

        def altered_scan():
            with scan_accepted_encounter_bundle(
                db,
                bundle,
                variant="FULL_DATA",
                companion_tables=("medication_component_evidence",),
                **trust,
            ) as views:
                db.execute(f'SELECT count(*) FROM "{views["features"]}"').fetchone()
                companion.write_bytes(companion_bytes + b"changed during scan")

        reject("changed lazy source", altered_scan)
        companion.write_bytes(companion_bytes)
        assert db.execute(
            "SELECT count(*) FROM information_schema.views "
            "WHERE table_name LIKE '_accepted_bundle_%'"
        ).fetchone() == (0,)
        # Refresh trust to reach schema checks independently of byte rejection.
        saved = {
            p: p.read_bytes()
            for p in (manifest_path, receipt_path, trust["validation_report_path"])
        }
        pq.write_table(pq.read_table(companion).drop(["source_record_hash"]), companion)
        _rebind_synthetic_acceptance(bundle, trust)

        def invalid_scan():
            with scan_accepted_encounter_bundle(
                db,
                bundle,
                variant="FULL_DATA",
                companion_tables=("medication_component_evidence",),
                **trust,
            ):
                raise AssertionError("Invalid schema opened")

        reject("invalid companion schema", invalid_scan)
        companion.write_bytes(companion_bytes)
        for path, data in saved.items():
            path.write_bytes(data)
        trust["expected_receipt_sha256"] = digest(receipt_path)
    return {
        "status": "passed",
        "rejections": rejected,
        "expected_variant_rows": {"FULL_DATA": 2, "AFTER_EXCLUSION": 2},
    }


def main():
    import os

    import trinetx_preprocessing

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifact_dir", type=Path)
    parser.add_argument("--require-installed", action="store_true")
    args = parser.parse_args()
    installed = Path(trinetx_preprocessing.__file__).is_relative_to(Path(sys.prefix))
    if args.require_installed and (not installed or "PYTHONPATH" in os.environ):
        parser.error("Require noneditable upstream package with PYTHONPATH removed")
    try:
        args.artifact_dir.mkdir(parents=True, exist_ok=False)
    except OSError as exc:
        parser.error(f"Choose a fresh artifact directory: {exc}")
    result = {
        "command": sys.argv,
        "python": sys.version,
        "platform": platform.platform(),
        "installed_noneditable": installed,
    }
    try:
        result.update(run(args.artifact_dir), exit_status=0)
    except Exception as exc:
        result.update(
            status="failed", error=f"{type(exc).__name__}: {exc}", exit_status=1
        )
    (args.artifact_dir / "runner.py").write_bytes(Path(__file__).read_bytes())
    result["inventory"] = {
        str(p.relative_to(args.artifact_dir)): {
            "bytes": p.stat().st_size,
            "sha256": digest(p),
        }
        for p in sorted(args.artifact_dir.rglob("*"))
        if p.is_file()
    }
    _write(args.artifact_dir / "receipt.json", result)
    print(json.dumps({k: v for k, v in result.items() if k != "inventory"}, indent=2))
    return result["exit_status"]


if __name__ == "__main__":
    raise SystemExit(main())

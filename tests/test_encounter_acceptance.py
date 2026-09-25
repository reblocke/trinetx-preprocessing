"""Real-Parquet acceptance and mutation checks for the shared consumer contract."""

import json
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from trinetx_preprocessing.encounters.acceptance import (
    load_artifact_contract,
    required_output_name,
    verify_accepted_bundle,
    verify_feature_schema,
    verify_output,
)
from trinetx_preprocessing.encounters.compatibility import digest


def _write(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, sort_keys=True) + "\n")


def _inventory(path: Path) -> dict:
    return {"bytes": path.stat().st_size, "sha256": digest(path)}


def _arrow_type(name):
    return {
        "FLOAT": pa.float32(),
        "BIGINT": pa.int64(),
        "DOUBLE": pa.float64(),
        "VARCHAR": pa.string(),
        "TIMESTAMP": pa.timestamp("us"),
        "BOOLEAN": pa.bool_(),
        "TINYINT": pa.int8(),
        "DATE": pa.date32(),
        "INTEGER": pa.int32(),
    }[name]


@pytest.fixture
def accepted(tmp_path):
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    outputs = {}
    for variant in ("FULL_DATA", "AFTER_EXCLUSION"):
        path = bundle / required_output_name(variant)
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
            path,
        )
        outputs[path.name] = _inventory(path)
    dictionary = {
        variant: [
            {"column": column, "dtype": dtype}
            for column, dtype in load_artifact_contract()["features"][variant].items()
        ]
        for variant in ("FULL_DATA", "AFTER_EXCLUSION")
    }
    dictionary_path = bundle / "data_dictionary.json"
    _write(dictionary_path, dictionary)
    outputs[dictionary_path.name] = _inventory(dictionary_path)
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
    _write(bundle / "manifest.json", manifest)
    report = {
        "pass": True,
        "validation_contract_version": "1.0",
        "bundle_manifest_sha256": digest(bundle / "manifest.json"),
        "schema_version": "2.0",
        "feature_contract_version": "1.0",
        "kind": "encounter_features",
        "outputs": outputs,
        "source": manifest["source"],
        "compatibility": manifest["compatibility"],
        "producer_code_sha256": manifest["code_sha256"],
        "variants": {name: {"pass": True} for name in ("FULL_DATA", "AFTER_EXCLUSION")},
    }
    report_path = tmp_path / "validation.json"
    _write(report_path, report)
    gates = {
        name: {"pass": True, "evidence_sha256": "a" * 64}
        for name in (
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
        "bundle_manifest_sha256": digest(bundle / "manifest.json"),
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
            "bundle_manifest_sha256": digest(bundle / "manifest.json"),
        },
    }
    receipt_path = tmp_path / "acceptance.json"
    _write(receipt_path, receipt)
    return bundle, report_path, receipt_path


def _verify(paths, **overrides):
    bundle, report, receipt = paths
    arguments = {
        "receipt_path": receipt,
        "expected_receipt_sha256": digest(receipt),
        "validation_report_path": report,
        "variant": "FULL_DATA",
    }
    arguments.update(overrides)
    return verify_accepted_bundle(bundle, **arguments)


def test_accepted_real_parquet_preserves_original_repeated_keys(accepted):
    manifest = _verify(accepted)
    path = verify_output(accepted[0], manifest, required_output_name("FULL_DATA"))
    verify_feature_schema(accepted[0], manifest, "FULL_DATA", path)
    frame = pd.read_parquet(path, columns=["patient_id", "encounter_id"])
    assert frame.to_dict("list") == {
        "patient_id": ["001", "001"],
        "encounter_id": ["A", "B"],
    }
    manifest = _verify(accepted, variant="AFTER_EXCLUSION")
    path = verify_output(accepted[0], manifest, required_output_name("AFTER_EXCLUSION"))
    verify_feature_schema(accepted[0], manifest, "AFTER_EXCLUSION", path)


@pytest.mark.parametrize("kind", ["legacy_base", None, "unknown"])
def test_rejects_legacy_or_unknown_kind(accepted, kind):
    path = accepted[0] / "manifest.json"
    manifest = json.loads(path.read_text())
    if kind is None:
        del manifest["kind"]
    else:
        manifest["kind"] = kind
    _write(path, manifest)
    with pytest.raises(ValueError, match="legacy|manifest"):
        _verify(accepted)


@pytest.mark.parametrize(
    "field,value",
    [
        ("status", "incomplete"),
        ("schema_version", "3.0"),
        ("feature_contract_version", "2.0"),
    ],
)
def test_rejects_unsupported_manifest(accepted, field, value):
    path = accepted[0] / "manifest.json"
    manifest = json.loads(path.read_text())
    manifest[field] = value
    _write(path, manifest)
    with pytest.raises(ValueError, match="Unsupported"):
        _verify(accepted)


def test_rejects_wrong_trust_policy_gate_and_variant(accepted):
    with pytest.raises(ValueError, match="trusted"):
        _verify(accepted, expected_receipt_sha256="0" * 64)
    with pytest.raises(ValueError, match="coverage policy"):
        _verify(accepted, coverage_policy="approved_incomplete_linkage")
    with pytest.raises(ValueError, match="variant"):
        _verify(accepted, variant="patient_index")
    receipt_path = accepted[2]
    receipt = json.loads(receipt_path.read_text())
    receipt["gates"]["installed_pair"]["pass"] = False
    _write(receipt_path, receipt)
    with pytest.raises(ValueError, match="mandatory production gate"):
        _verify(accepted)


def test_rejects_changed_report_manifest_or_product(accepted):
    report_path = accepted[1]
    report_path.write_text(report_path.read_text() + " ")
    with pytest.raises(ValueError, match="report differs"):
        _verify(accepted)
    report_path.write_text(report_path.read_text().rstrip())
    # Restore the original report bytes before separately mutating the manifest.
    _write(report_path, json.loads(report_path.read_text()))
    manifest_path = accepted[0] / "manifest.json"
    manifest_path.write_text(manifest_path.read_text() + " ")
    with pytest.raises(ValueError, match="manifest"):
        _verify(accepted)


def test_rejects_changed_parquet_and_schema_even_with_matching_checksum(accepted):
    manifest = _verify(accepted)
    path = accepted[0] / required_output_name("FULL_DATA")
    path.write_bytes(path.read_bytes() + b"changed")
    with pytest.raises(ValueError, match="differs"):
        verify_output(accepted[0], manifest, path.name)
    frame = pd.DataFrame(
        {
            "patient_id": [1],
            "encounter_id": ["A"],
            "pat_enc_hash": ["1-A"],
            "niv_proc": [1],
        }
    )
    frame.to_parquet(path, index=False)
    manifest["outputs"][path.name] = _inventory(path)
    _write(accepted[0] / "manifest.json", manifest)
    with pytest.raises(ValueError, match="manifest"):
        _verify(accepted)
    with pytest.raises(ValueError, match="schema differs"):
        verify_feature_schema(accepted[0], manifest, "FULL_DATA", path)

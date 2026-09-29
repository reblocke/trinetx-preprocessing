#!/usr/bin/env python3
"""Retained direct/staged/recovered return execution E2E; synthetic only.

Failure expectations: duplicate/null raw values survive exact stage proofs;
removed, changed, extra and misrouted rows fail verification. Original variants
remain independent. Direct and staged outputs match the existing clinical oracle.
Changed stage bytes are never reused. Checkpointed validation must recheck bytes.
"""

from __future__ import annotations

import argparse
import json
import platform
import runpy
import sys
from pathlib import Path

import duckdb

from trinetx_preprocessing.encounters.builder import literal, sha256

ROOT = Path(__file__).resolve().parents[1]


def run(root):
    from trinetx_preprocessing.encounters.return_source_stage import (
        attach_source_partition,
        create_source_stage,
        verify_source_stage,
    )
    from trinetx_preprocessing.encounters.return_validation_v2 import (
        TABLES,
        _assert_equal_multiset,
    )
    from trinetx_preprocessing.encounters.returns_v2 import build_partition_v2

    root.mkdir(parents=True, exist_ok=False)
    (root / "canonical").mkdir()
    source = root / "canonical" / "source.duckdb"
    parent = root / "parent"
    parent.mkdir()
    fixture = runpy.run_path(str(ROOT / "tests/test_encounter_returns.py"))["_source"]
    clinical = runpy.run_path(str(ROOT / "scripts/verify_return_v2_partition_e2e.py"))
    with duckdb.connect() as db:
        fixture(db, str(source))
        clinical["_extend_fixture"](db)
        # Raw duplicate lab/membership values must remain duplicates. They are
        # staged here and retained in both routes for multiplicity comparison.
        db.execute(
            "INSERT INTO preprocessed.source_lab_measurement "
            "SELECT * FROM preprocessed.source_lab_measurement LIMIT 1"
        )
        db.execute(
            "INSERT INTO preprocessed.element_membership "
            "SELECT * FROM preprocessed.element_membership LIMIT 1"
        )
        for include in ("FALSE", "NULL"):
            db.execute(
                "INSERT INTO preprocessed.element_membership "
                f"SELECT * REPLACE ({include} AS include) "
                "FROM preprocessed.element_membership LIMIT 1"
            )
        db.execute(
            "INSERT INTO preprocessed.element_membership "
            "SELECT * REPLACE ('unrelated.element' AS element_id) "
            "FROM preprocessed.element_membership LIMIT 1"
        )
        for variant, clause in (
            ("FULL_DATA", ""),
            ("AFTER_EXCLUSION", " WHERE patient_id='p'"),
        ):
            target = parent / f"encounter_features_{variant.lower()}.parquet"
            db.execute(
                f"COPY (SELECT * FROM fixture_index{clause}) "
                f"TO {literal(target)} (FORMAT PARQUET)"
            )
    stage = root / "stage"
    identity = {"source_fixture_sha256": sha256(source)}
    receipt = create_source_stage(
        database=source,
        parent_bundle=parent,
        output_dir=stage,
        work_dir=root / "stage-work",
        partitions=3,
        identity=identity,
    )
    verify_source_stage(
        stage,
        expected_manifest_sha256=sha256(stage / "manifest.json"),
        identity=identity,
        database=source,
        parent_bundle=parent,
        work_dir=root / "verify-work",
    )
    with duckdb.connect() as db:
        members = f"read_parquet({literal(stage / '*_element_membership.parquet')})"
        assert (
            db.execute(
                f"SELECT count(*) FROM {members} WHERE element_id='unrelated.element'"
            ).fetchone()[0]
            == 0
        )
        assert (
            db.execute(
                f"SELECT count(*) FROM {members} WHERE include IS NULL"
            ).fetchone()[0]
            == 1
        )
        assert (
            db.execute(
                f"SELECT count(*) FROM {members} WHERE include=FALSE"
            ).fetchone()[0]
            >= 1
        )
    rejected = []
    # Byte rebind reaches exact source reconciliation, rather than stopping at
    # an old artifact hash. Expected source and original patient routing stay fixed.
    manifest = json.loads((stage / "manifest.json").read_text())
    candidate = next(
        stage / n
        for n in manifest["outputs"]
        if "source_diagnosis" in n and manifest["outputs"][n]["rows"] > 0
    )
    original = candidate.read_bytes()
    for label, query in (
        ("missing stage row", "SELECT * FROM saved OFFSET 1"),
        (
            "duplicate stage row",
            "SELECT * FROM saved UNION ALL SELECT * FROM saved LIMIT 1000000",
        ),
        ("changed typed value", "SELECT * REPLACE ('wrong' AS code) FROM saved"),
        (
            "coercible changed type",
            "SELECT * REPLACE "
            "(source_row_number::VARCHAR AS source_row_number) FROM saved",
        ),
        ("misrouted patient", "SELECT * REPLACE ('outside' AS patient_id) FROM saved"),
    ):
        with duckdb.connect() as db:
            db.execute(
                "CREATE TABLE saved AS SELECT * "
                f"FROM read_parquet({literal(candidate)})"
            )
            candidate.unlink()
            db.execute(f"COPY ({query}) TO {literal(candidate)} (FORMAT PARQUET)")
            manifest["schemas"]["source_diagnosis"] = [
                [r[0], r[1]]
                for r in db.execute(
                    f"DESCRIBE SELECT * FROM read_parquet({literal(candidate)})"
                ).fetchall()
            ]
        manifest["outputs"][candidate.name].update(
            bytes=candidate.stat().st_size, sha256=sha256(candidate)
        )
        (stage / "manifest.json").write_text(json.dumps(manifest) + "\n")
        try:
            verify_source_stage(
                stage,
                expected_manifest_sha256=sha256(stage / "manifest.json"),
                identity=identity,
                database=source,
                parent_bundle=parent,
                work_dir=root / f"verify-{len(rejected)}",
            )
        except ValueError:
            rejected.append(label)
        else:
            raise AssertionError(f"Did not reject {label}")
        candidate.write_bytes(original)
    # Restore the original trusted receipt and verify before downstream use.
    (stage / "manifest.json").write_text(
        json.dumps(receipt, sort_keys=True, indent=2) + "\n"
    )
    verify_source_stage(
        stage,
        expected_manifest_sha256=sha256(stage / "manifest.json"),
        identity=identity,
    )
    for variant in ("FULL_DATA", "AFTER_EXCLUSION"):
        for route in ("direct", "staged"):
            output = root / f"{variant}-{route}"
            output.mkdir()
            for bucket in range(3):
                with duckdb.connect() as db:
                    if route == "direct":
                        db.execute(
                            f"ATTACH {literal(source)} AS preprocessed (READ_ONLY)"
                        )
                    else:
                        attach_source_partition(
                            db,
                            stage,
                            bucket=bucket,
                            expected_manifest_sha256=sha256(stage / "manifest.json"),
                            identity=identity,
                        )
                    index_path = (
                        parent / f"encounter_features_{variant.lower()}.parquet"
                    )
                    db.execute(
                        "CREATE TEMP VIEW index_file AS SELECT * "
                        f"FROM read_parquet({literal(index_path)})"
                    )
                    build_partition_v2(
                        db, variant=variant, bucket=bucket, partitions=3, output=output
                    )
        with duckdb.connect() as db:
            for table in TABLES:
                left_path = root / f"{variant}-direct" / f"*_{table}.parquet"
                right_path = root / f"{variant}-staged" / f"*_{table}.parquet"
                left = f"SELECT * FROM read_parquet({literal(left_path)})"
                right = f"SELECT * FROM read_parquet({literal(right_path)})"
                _assert_equal_multiset(db, left, right, f"{variant} {table}")
    from trinetx_preprocessing.encounters.return_validation_execution import (
        validate_partition_materialized,
    )

    for variant in ("FULL_DATA", "AFTER_EXCLUSION"):
        for bucket in range(3):
            with duckdb.connect() as db:
                attach_source_partition(
                    db,
                    stage,
                    bucket=bucket,
                    expected_manifest_sha256=sha256(stage / "manifest.json"),
                    identity=identity,
                )
                for table in TABLES:
                    path = (
                        root
                        / f"{variant}-staged"
                        / f"{variant.lower()}_{bucket:04d}_{table}.parquet"
                    )
                    db.execute(
                        f"CREATE TEMP VIEW {table} AS SELECT * "
                        f"FROM read_parquet({literal(path)})"
                    )
                path = parent / f"encounter_features_{variant.lower()}.parquet"
                db.execute(
                    "CREATE TEMP VIEW parent_index AS SELECT patient_id,encounter_id,"
                    "pat_enc_hash AS index_event_id "
                    f"FROM read_parquet({literal(path)}) "
                    f"WHERE hash(patient_id::VARCHAR)%3={bucket}"
                )
                validate_partition_materialized(db)
    # Signed partition evidence: untouched work is reusable; changes to any
    # bound dependency or artifact, and edited signatures, force revalidation.
    from trinetx_preprocessing.encounters.return_evidence import PartitionCheckpoints

    checkpoint_root = root / "checkpoints"
    checkpoints = PartitionCheckpoints(
        checkpoint_root, key_path=root / "checkpoint-auth.key"
    )
    artifacts = {
        "summary": root / "FULL_DATA-staged" / "full_data_0000_summary.parquet"
    }
    binding = {"producer": "p1", "validator": "v1", "source": "source1"}
    assert not checkpoints.reusable("FULL_DATA:0", binding, artifacts)
    checkpoints.complete("FULL_DATA:0", binding, artifacts, {"pass": True})
    reopened = PartitionCheckpoints(
        checkpoint_root, key_path=root / "checkpoint-auth.key"
    )
    assert reopened.reusable("FULL_DATA:0", binding, artifacts)
    assert not reopened.reusable(
        "FULL_DATA:0", {**binding, "validator": "v2"}, artifacts
    )
    assert not reopened.reusable(
        "FULL_DATA:0", {**binding, "source": "source2"}, artifacts
    )
    artifact = artifacts["summary"]
    original = artifact.read_bytes()
    artifact.write_bytes(original + b"changed")
    assert not reopened.reusable("FULL_DATA:0", binding, artifacts)
    artifact.write_bytes(original)
    checkpoint = next(checkpoint_root.glob("*.json"))
    altered = json.loads(checkpoint.read_text())
    altered["payload"]["result"] = {"pass": False}
    checkpoint.write_text(json.dumps(altered))
    assert not reopened.reusable("FULL_DATA:0", binding, artifacts)
    return {
        "status": "passed",
        "stage_corruptions_rejected": rejected,
        "exact_routes": ["direct", "staged"],
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("artifact_dir", type=Path)
    p.add_argument("--require-installed", action="store_true")
    args = p.parse_args()
    if args.artifact_dir.exists():
        p.error("Artifact directory exists; retain it and choose a new destination")
    import importlib.metadata
    import os

    import trinetx_preprocessing

    installed = Path(trinetx_preprocessing.__file__).is_relative_to(Path(sys.prefix))
    if args.require_installed and (not installed or "PYTHONPATH" in os.environ):
        p.error("Require noneditable installed package and removed PYTHONPATH")
    result = {
        "command": sys.argv,
        "python": sys.version,
        "platform": platform.platform(),
        "script_sha256": sha256(Path(__file__)),
    }
    try:
        result.update(run(args.artifact_dir))
        result["exit_status"] = 0
    except Exception as exc:
        result.update(
            status="failed", error=f"{type(exc).__name__}: {exc}", exit_status=1
        )
    args.artifact_dir.mkdir(parents=True, exist_ok=True)
    (args.artifact_dir / "runner.py").write_bytes(Path(__file__).read_bytes())
    result["schema"] = "trinetx-return-e2e-v1"
    result["installed_noneditable"] = installed
    result["packages"] = {
        n: importlib.metadata.version(n)
        for n in ("duckdb", "pyarrow", "pandas", "numpy", "trinetx-preprocessing")
    }
    result["fixture_code_sha256"] = {
        str(p.relative_to(ROOT)): sha256(p)
        for p in (
            ROOT / "tests/test_cohort_source.py",
            ROOT / "tests/test_return_parent_validation.py",
            ROOT / "tests/test_encounter_returns.py",
            ROOT / "scripts/verify_return_v2_partition_e2e.py",
        )
        if p.exists()
    }
    result["inventory"] = {
        str(p.relative_to(args.artifact_dir)): {
            "sha256": sha256(p),
            "bytes": p.stat().st_size,
        }
        for p in sorted(args.artifact_dir.rglob("*"))
        if p.is_file() and p.suffix != ".key"
    }
    (args.artifact_dir / "e2e.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({k: v for k, v in result.items() if k != "inventory"}, indent=2))
    return result["exit_status"]


if __name__ == "__main__":
    raise SystemExit(main())

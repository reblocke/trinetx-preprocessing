#!/usr/bin/env python3
"""Complete encounter bundle and CLI regressions with retained independent oracles."""

from __future__ import annotations

import argparse
import json
import runpy
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from trinetx_preprocessing.encounters.builder import VARIANTS, sha256
from trinetx_preprocessing.encounters.cli import validate_main
from trinetx_preprocessing.encounters.validation import validate_bundle

ROOT = Path(__file__).resolve().parents[1]


def prepare(path, *, corrupt=None):
    fixture = runpy.run_path(str(ROOT / "tests/test_encounter_validation.py"))
    path.mkdir()
    bundle, _ = fixture["_make_bundle"](path)
    qa = {}
    for variant in VARIANTS:
        stem = f"encounter_features_{variant.lower()}"
        features = pq.read_table(bundle / (stem + ".parquet"))
        original = features.to_pylist()[0]
        second = {name: None for name in features.column_names}
        second.update(
            patient_id="q",
            encounter_id="e",
            pat_enc_hash="q-e",
            source_element_hba1c_record_count=0,
            source_element_bmi_record_count=1,
        )
        third = {name: None for name in features.column_names}
        third.update(patient_id="z", encounter_id="e", pat_enc_hash="z-e")
        if corrupt == "compensating":
            original["source_element_hba1c_record_count"] = 0
            second["source_element_hba1c_record_count"] = 1
        elif corrupt == "absent_zero":
            third["source_element_hba1c_record_count"] = 0
        elif corrupt == "present_null":
            second["source_element_hba1c_record_count"] = None
        expanded = pa.Table.from_pylist(
            [original, second, third], schema=features.schema
        )
        pq.write_table(expanded, bundle / (stem + ".parquet"))
        qa[variant] = {
            "rows": 3,
            "null_counts": {
                name: expanded[name].null_count for name in expanded.column_names
            },
        }
        ep = bundle / (stem + "_encounter_element_evidence.parquet")
        evidence = pq.read_table(ep)
        extra = evidence.to_pylist()[1]
        extra["index_event_id"] = "q-e"
        pq.write_table(
            pa.Table.from_pylist(
                evidence.to_pylist() + [extra], schema=evidence.schema
            ),
            ep,
        )
        cp = bundle / (stem + "_encounter_source_coverage.parquet")
        coverage = pq.read_table(cp)
        records = coverage.to_pylist()
        extra = []
        for key in ("q-e", "z-e"):
            for row in records:
                extra.append({**row, "index_event_id": key})
        pq.write_table(
            pa.Table.from_pylist(records + extra, schema=coverage.schema), cp
        )
        ip = bundle / (stem + "_element_inventory.json")
        inventory = json.loads(ip.read_text())
        for entry in inventory:
            matched = 1 if entry["element_id"] == "source.hba1c" else 2
            entry["availability_states"][0].update(
                observed_matches=matched, zero_matching_records=3 - matched
            )
        ip.write_text(json.dumps(inventory) + "\n")
    (bundle / "quality_summary.json").write_text(json.dumps(qa) + "\n")
    fixture["_refresh_manifest"](bundle)
    return bundle


def run(root):
    root.mkdir(parents=True, exist_ok=False)
    good = prepare(root / "good")
    assert validate_bundle(bundle=good, work_dir=root / "good-work")["pass"]
    for mutation in ("compensating", "absent_zero", "present_null"):
        bundle = prepare(root / mutation, corrupt=mutation)
        try:
            validate_bundle(bundle=bundle, work_dir=root / (mutation + "-work"))
        except ValueError:
            pass
        else:
            raise AssertionError("Incorrect per-encounter count accepted: " + mutation)
    report = root / "cli-work" / "reports" / "pass.json"
    assert (
        validate_main(
            [
                "--bundle",
                str(good),
                "--work-dir",
                str(report.parents[1]),
                "--report",
                str(report),
            ]
        )
        == 0
    )
    assert json.loads(report.read_text())["pass"]
    failed = root / "failure-work" / "reports" / "fail.json"
    assert (
        validate_main(
            [
                "--bundle",
                str(root / "absent_zero" / "bundle"),
                "--work-dir",
                str(failed.parents[1]),
                "--report",
                str(failed),
            ]
        )
        == 1
    )
    assert json.loads(failed.read_text())["pass"] is False
    return {
        "status": "passed",
        "exit_status": 0,
        "mutations_rejected": ["compensating", "absent_zero", "present_null"],
    }


def main():
    import platform
    import sys

    parser = argparse.ArgumentParser()
    parser.add_argument("artifact_dir", type=Path)
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--receipt-sha256")
    args = parser.parse_args()
    if args.verify:
        receipt_path = args.artifact_dir / "receipt.json"
        if not args.receipt_sha256 or sha256(receipt_path) != args.receipt_sha256:
            raise ValueError("E2E receipt differs from trusted digest")
        saved = json.loads(receipt_path.read_text())
        actual = {
            str(p.relative_to(args.artifact_dir)): sha256(p)
            for p in args.artifact_dir.rglob("*")
            if p.is_file() and p != receipt_path
        }
        if actual != saved["inventory"] or saved["status"] != "passed":
            raise ValueError("E2E artifacts or status differ")
        if saved["source_before"] != saved["source_after"]:
            raise ValueError("Source changed during E2E")
        print("Retained E2E receipt and artifact hashes verified")
        return 0
    source_paths = sorted((ROOT / "src").rglob("*.py"))
    source_before = {str(p.relative_to(ROOT)): sha256(p) for p in source_paths}
    result = {"status": "failed", "exit_status": 1}
    try:
        result.update(run(args.artifact_dir))
    except Exception as exc:
        result["failure"] = f"{type(exc).__name__}: {exc}"
    result.update(
        command=sys.argv,
        python=platform.python_version(),
        runner_sha256=sha256(Path(__file__)),
        fixture_sha256=sha256(ROOT / "tests/test_encounter_validation.py"),
    )
    (args.artifact_dir / "runner.py").write_bytes(Path(__file__).read_bytes())
    result["source_before"] = source_before
    result["source_after"] = {str(p.relative_to(ROOT)): sha256(p) for p in source_paths}
    if result["source_before"] != result["source_after"]:
        result.update(
            status="failed", exit_status=1, failure="Source changed during E2E"
        )
    result["inventory"] = {
        str(p.relative_to(args.artifact_dir)): sha256(p)
        for p in args.artifact_dir.rglob("*")
        if p.is_file()
    }
    (args.artifact_dir / "receipt.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({k: v for k, v in result.items() if k != "inventory"}, indent=2))
    return result["exit_status"]


if __name__ == "__main__":
    raise SystemExit(main())

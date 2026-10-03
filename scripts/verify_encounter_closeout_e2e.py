#!/usr/bin/env python3
"""Complete encounter bundle and CLI regressions with retained independent oracles."""

from __future__ import annotations

import argparse
import json
import runpy
import shutil
import subprocess
import sys
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from trinetx_preprocessing.encounters.builder import VARIANTS, sha256
from trinetx_preprocessing.encounters.cli import validate_main
from trinetx_preprocessing.encounters.validation import validate_bundle

ROOT = Path(__file__).resolve().parents[1]


def check_runner_artifact_history(root):
    """Exercise real CLI lifecycles with a bounded adversarial payload fixture."""
    project = root / "cli-lifecycle"
    scripts = project / "scripts"
    scripts.mkdir(parents=True)
    fixtures = project / "tests"
    fixtures.mkdir()
    for name in (
        "test_cohort_source_calendar_history.py",
        "test_encounter_validation.py",
    ):
        shutil.copy2(ROOT / "tests" / name, fixtures / name)
    wrapper = project / "invoke.py"
    shutil.copy2(ROOT / "tests/fixtures/e2e_runner_payload.py", wrapper)
    observations = []

    def inventory(path):
        return {
            str(p.relative_to(path)): sha256(p)
            for p in sorted(path.rglob("*"))
            if p.is_file()
        }

    def invoke(command, log):
        result = subprocess.run(command, capture_output=True, text=True, timeout=60)
        log.write_text(result.stdout + result.stderr)
        return result.returncode

    for name in (
        "calendar_transport",
        "encounter_closeout",
        "encounter_reader",
        "return_reader",
        "return_execution",
        "return_product",
    ):
        driver = scripts / ("verify_" + name + "_e2e.py")
        shutil.copy2(ROOT / "scripts" / driver.name, driver)
        for status in ("passed", "failed"):
            output = project / (name + "-existing-" + status)
            output.mkdir()
            (output / "nested").mkdir()
            (output / "nested/sentinel").write_bytes(b"preserve every artifact\n")
            for filename in ("receipt.json", "e2e.json"):
                (output / filename).write_text(json.dumps({"status": status}) + "\n")
            (output / "runner.py").write_text("# Retained original runner\n")
            before = inventory(output)
            command = [sys.executable, str(wrapper), str(driver), str(output)]
            exit_status = invoke(command, project / (output.name + ".log"))
            assert exit_status == 2, (name, status, exit_status)
            assert inventory(output) == before, (name, status, "artifacts changed")
            observations.append(
                {
                    "runner": name,
                    "case": status,
                    "command": command,
                    "exit_status": exit_status,
                    "preserved": before,
                }
            )
        file_output = project / (name + "-file")
        file_output.write_bytes(b"retained file\n")
        link_output = project / (name + "-link")
        link_output.symlink_to(file_output)
        for output in (file_output, link_output):
            command = [sys.executable, str(wrapper), str(driver), str(output)]
            assert invoke(command, project / (output.name + ".log")) == 2
            assert file_output.read_bytes() == b"retained file\n"
            observations.append(
                {
                    "runner": name,
                    "case": "existing_symlink"
                    if output == link_output
                    else "existing_file",
                    "command": command,
                    "exit_status": 2,
                    "target_sha256": sha256(file_output),
                }
            )
        assert link_output.is_symlink() and link_output.readlink() == file_output
        # The link is fixture setup, not an E2E artifact to preserve or upload.
        link_output.unlink()

        output = project / (name + "-fresh-failure")
        command = [sys.executable, str(wrapper), str(driver), str(output), "--fail"]
        assert invoke(command, project / (output.name + ".log")) == 1
        receipt = output / (
            "receipt.json"
            if name in ("calendar_transport", "encounter_closeout", "encounter_reader")
            else "e2e.json"
        )
        saved = json.loads(receipt.read_text())
        assert saved["status"] == "failed" and saved["exit_status"] == 1
        assert "Deliberate synthetic" in saved.get("failure", saved.get("error", ""))
        assert sha256(output / "runner.py") == sha256(driver)
        observations.append(
            {
                "runner": name,
                "case": "fresh_failure",
                "command": command,
                "exit_status": 1,
                "receipt_sha256": sha256(receipt),
            }
        )

        output = project / (name + "-race")
        ready = project / (name + "-ready")
        ready.mkdir()
        command = [
            sys.executable,
            str(wrapper),
            str(driver),
            str(output),
            "--race-ready",
            str(ready),
        ]
        processes = [
            subprocess.Popen(
                command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
            )
            for _ in range(2)
        ]
        for number, process in enumerate(processes):
            try:
                log, _ = process.communicate(timeout=60)
            except subprocess.TimeoutExpired:
                for child in processes:
                    child.kill()
                    child.wait()
                raise
            (project / (output.name + f"-{number}.log")).write_text(log)
        assert sorted(p.returncode for p in processes) == [0, 2], name
        winner = next(p for p in processes if p.returncode == 0)
        saved = json.loads((output / receipt.name).read_text())
        assert saved["status"] == "passed" and saved["exit_status"] == 0
        assert (
            json.loads((output / "fixture-payload.json").read_text())["owner_pid"]
            == winner.pid
        )
        assert sha256(output / "runner.py") == sha256(driver)
        observations.append(
            {
                "runner": name,
                "case": "concurrent_claim",
                "command": command,
                "exit_statuses": [0, 2],
                "receipt_sha256": sha256(output / receipt.name),
            }
        )
    (project / "observations.json").write_text(
        json.dumps(observations, indent=2) + "\n"
    )
    return observations


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


def check_cli_report_history(root, bundle, *, name, nested, expected_exit):
    work = root / (name + "-work")
    report = work / "reports" / "validation.json" if nested else root / (name + ".json")
    arguments = [
        "--bundle",
        str(bundle),
        "--work-dir",
        str(work),
        "--report",
        str(report),
    ]
    assert validate_main(arguments) == expected_exit
    original_bytes = report.read_bytes()
    assert json.loads(original_bytes)["pass"] is (expected_exit == 0)
    original_sha256 = sha256(report)
    fresh_work = root / (name + "-fresh-work")
    for requested_work in (work, fresh_work):
        arguments[arguments.index("--work-dir") + 1] = str(requested_work)
        try:
            validate_main(arguments)
        except SystemExit as exc:
            assert exc.code == 2
        else:
            raise AssertionError("Existing validation report destination accepted")
        assert report.read_bytes() == original_bytes
        assert sha256(report) == original_sha256
    assert not fresh_work.exists()
    return {
        "case": name,
        "initial_exit": expected_exit,
        "rerun_exits": [2, 2],
        "report_sha256": original_sha256,
        "original_bytes_preserved": True,
    }


def run(root):
    lifecycle = check_runner_artifact_history(root)
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
    report_checks = []
    for nested in (False, True):
        for passed in (False, True):
            report_checks.append(
                check_cli_report_history(
                    root,
                    good if passed else root / "absent_zero" / "bundle",
                    name=("nested" if nested else "external")
                    + ("-success" if passed else "-failure"),
                    nested=nested,
                    expected_exit=0 if passed else 1,
                )
            )
    return {
        "status": "passed",
        "exit_status": 0,
        "mutations_rejected": ["compensating", "absent_zero", "present_null"],
        "cli_report_history": report_checks,
        "runner_artifact_history": lifecycle,
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
    try:
        args.artifact_dir.mkdir(parents=True, exist_ok=False)
    except OSError as exc:
        parser.error(f"Choose a fresh artifact directory: {exc}")
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

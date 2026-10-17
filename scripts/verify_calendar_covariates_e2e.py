#!/usr/bin/env python3
"""Retain source-to-Parquet covariate E2Es and verify their saved evidence."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/test_calendar_covariates_e2e.py"
RECEIPT = "receipt.json"


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def inventory(root: Path) -> dict:
    files = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError("Retained covariate evidence cannot contain symlinks")
        if path.is_file() and path != root / RECEIPT:
            files[str(path.relative_to(root))] = {
                "bytes": path.stat().st_size,
                "sha256": sha256(path),
            }
    return files


def cases(path: Path) -> list[dict]:
    return [
        {
            "name": case.attrib["name"],
            "passed": not any(
                case.find(tag) is not None for tag in ("failure", "error", "skipped")
            ),
        }
        for case in ET.parse(path).getroot().iter("testcase")
    ]


def verify(root: Path, trusted_digest: str) -> dict:
    path = root / RECEIPT
    if sha256(path) != trusted_digest:
        raise ValueError("Covariate E2E receipt differs from trusted digest")
    receipt = json.loads(path.read_text())
    if (
        receipt.get("schema") != "trinetx-calendar-covariates-e2e-v1"
        or receipt["status"] != "passed"
        or receipt["exit_status"] != 0
        or receipt["inventory"] != inventory(root)
        or receipt["source_before"] != receipt["source_after"]
        or receipt["cases"] != cases(root / "junit.xml")
        or len(receipt["cases"]) != 25
        or not all(case["passed"] for case in receipt["cases"])
        or receipt["fixture_sha256"] != sha256(root / "fixture.py")
        or receipt["runner_sha256"] != sha256(root / "runner.py")
    ):
        raise ValueError("Covariate E2E artifacts or results differ")
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifact_dir", type=Path)
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--receipt-sha256")
    parser.add_argument("--require-installed", action="store_true")
    args = parser.parse_args()
    if args.verify:
        if not args.receipt_sha256:
            parser.error("Verification requires a trusted receipt digest")
        verify(args.artifact_dir, args.receipt_sha256)
        print("Covariate E2E receipt, cases and artifact hashes verified")
        return 0

    import trinetx_preprocessing
    from trinetx_preprocessing.combined_preprocessing.builder import (
        require_safe_output_location,
    )
    from trinetx_preprocessing.encounters.compatibility import no_symlinks

    package = Path(trinetx_preprocessing.__file__).resolve().parent
    direct_url = importlib.metadata.distribution("trinetx-preprocessing").read_text(
        "direct_url.json"
    )
    editable = bool(
        direct_url and json.loads(direct_url).get("dir_info", {}).get("editable")
    )
    installed = package.is_relative_to(Path(sys.prefix).resolve()) and not editable
    if args.require_installed and (not installed or "PYTHONPATH" in os.environ):
        parser.error("Require a noneditable wheel with PYTHONPATH removed")
    output = no_symlinks(args.artifact_dir)
    require_safe_output_location(output, artifact_label="covariate E2E evidence")
    try:
        output.mkdir(mode=0o700, parents=True, exist_ok=False)
    except OSError as exc:
        parser.error(f"Choose a fresh artifact directory: {exc}")

    def sources() -> dict:
        return {
            str(path.relative_to(package)): sha256(path)
            for path in sorted(package.rglob("*.py"))
        }

    result = {
        "schema": "trinetx-calendar-covariates-e2e-v1",
        "status": "failed",
        "exit_status": 1,
        "scope": "Synthetic mapper qualification; not private or clinical acceptance",
        "source_before": sources(),
        "fixture_sha256": sha256(FIXTURE),
        "runner_sha256": sha256(Path(__file__)),
        "command": [sys.executable, *sys.argv],
        "python": sys.version,
        "platform": platform.platform(),
        "installed_noneditable": installed,
        "packages": {
            name: importlib.metadata.version(name)
            for name in ("duckdb", "numpy", "pandas", "pyarrow", "pytest")
        },
        "started_utc": datetime.now(timezone.utc).isoformat(),
    }
    try:
        shutil.copy2(__file__, output / "runner.py")
        shutil.copy2(FIXTURE, output / "fixture.py")
        command = [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            str(FIXTURE),
            "-o",
            "pythonpath=",
            "-o",
            "tmp_path_retention_policy=all",
            "--basetemp",
            str(output / "work"),
            "--junitxml",
            str(output / "junit.xml"),
        ]
        result["pytest_command"] = command
        with (output / "pytest.log").open("w") as log:
            run = subprocess.run(
                command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT
            )
        result["exit_status"] = run.returncode
        result["cases"] = cases(output / "junit.xml")
        if (
            run.returncode == 0
            and len(result["cases"]) == 25
            and all(case["passed"] for case in result["cases"])
        ):
            result["status"] = "passed"
    except Exception as exc:
        result.update(
            status="failed", exit_status=1, failure=f"{type(exc).__name__}: {exc}"
        )
    result["source_after"] = sources()
    if (
        result["source_before"] != result["source_after"]
        or result["fixture_sha256"] != sha256(FIXTURE)
        or result["runner_sha256"] != sha256(Path(__file__))
    ):
        result.update(status="failed", exit_status=1, failure="Package source changed")
    if result["status"] != "passed":
        result["exit_status"] = result["exit_status"] or 1
    result["finished_utc"] = datetime.now(timezone.utc).isoformat()
    # Pytest's convenience aliases point at the retained numbered directories.
    # They are not payload and are not portable through artifact archives.
    for path in (output / "work").glob("*current"):
        if path.is_symlink() and path.resolve().is_relative_to(output / "work"):
            path.unlink()
    try:
        result["inventory"] = inventory(output)
    except ValueError as exc:
        result.update(status="failed", exit_status=1, failure=str(exc), inventory={})
    path = output / RECEIPT
    path.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"status": result["status"], "receipt_sha256": sha256(path)}))
    return result["exit_status"]


if __name__ == "__main__":
    raise SystemExit(main())

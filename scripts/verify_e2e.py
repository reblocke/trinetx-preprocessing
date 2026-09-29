"""Run existing synthetic workflows and retain independently checkable evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NODES = (
    "tests/test_pipeline_run.py::test_run_pipeline_end_to_end",
    "tests/test_pipeline_run.py::test_run_pipeline_end_to_end_with_parquet_intermediates",
    "tests/test_pipeline_run.py::test_baseline_compare_profile_end_to_end_with_parquet_intermediates",
    "tests/test_combined_preprocessing.py::test_synthetic_example_is_rerunnable",
    "tests/test_combined_preprocessing.py::test_combined_build_exports_exact_historical_contract",
)
MANIFEST = "e2e_manifest.json"


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def file_record(path: Path, root: Path) -> dict:
    if path.is_symlink():
        if not path.resolve().is_relative_to(root.resolve()):
            raise ValueError(f"External symlink in evidence: {path}")
        return {"kind": "symlink", "target": str(path.readlink())}
    if not path.is_file():
        raise ValueError(f"Unsupported evidence entry: {path}")
    return {"kind": "file", "bytes": path.stat().st_size, "sha256": sha256(path)}


def inventory(root: Path) -> dict:
    return {
        p.relative_to(root).as_posix(): file_record(p, root)
        for p in sorted(root.rglob("*"))
        if p != root / MANIFEST and (p.is_symlink() or not p.is_dir())
    }


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def source_inventory() -> dict:
    paths = git(
        "ls-files",
        "-z",
        "--cached",
        "--others",
        "--exclude-standard",
        "--",
        "src",
        "tests",
        "config",
        "scripts",
        "pyproject.toml",
        "uv.lock",
        ".python-version",
        "README.md",
    ).split("\0")
    return {
        name: file_record(ROOT / name, ROOT)
        for name in sorted(set(paths))
        if name and (ROOT / name).exists()
    }


def cases(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    return [
        {
            "name": case.attrib["name"],
            "class": case.attrib.get("classname", ""),
            "passed": not any(
                case.find(tag) is not None for tag in ("failure", "error", "skipped")
            ),
        }
        for case in ET.parse(path).getroot().iter("testcase")
    ]


def successful_cases(results: list[dict]) -> bool:
    expected = sorted(
        (node.split("::")[0][:-3].replace("/", "."), node.split("::")[1])
        for node in NODES
    )
    return sorted(
        (case["class"], case["name"]) for case in results
    ) == expected and all(case["passed"] for case in results)


def workflow_products(root: Path) -> dict:
    work = root / "work"
    if not work.is_dir():
        return {}
    return {
        p.name: len(list(p.rglob("RFS_*_ENC_*_*.csv")))
        for p in sorted(work.iterdir())
        if p.is_dir() and not p.is_symlink()
    }


def products_retained(products: dict) -> bool:
    return len(products) == len(NODES) and all(n >= 36 for n in products.values())


def verify(root: Path, expected_hash: str | None = None) -> dict:
    if not (root / MANIFEST).exists() and (root / "e2e.json").is_file():
        path = root / "e2e.json"
        if expected_hash and sha256(path) != expected_hash:
            raise ValueError("Return E2E manifest differs from supplied hash")
        receipt = json.loads(path.read_text())
        if receipt.get("schema") != "trinetx-return-e2e-v1":
            raise ValueError("Unsupported return E2E evidence schema")
        files = {}
        for item in sorted(root.rglob("*")):
            if item.is_symlink():
                raise ValueError("Return E2E evidence cannot contain symlinks")
            if item.is_file() and item != path and item.suffix != ".key":
                files[str(item.relative_to(root))] = {
                    "bytes": item.stat().st_size,
                    "sha256": sha256(item),
                }
        if files != receipt.get("inventory"):
            raise ValueError("Return E2E inventory or hashes differ")
        if sha256(root / "runner.py") != receipt.get("script_sha256"):
            raise ValueError("Return E2E runner identity differs")
        if receipt.get("status") != "passed" or receipt.get("exit_status") != 0:
            raise ValueError("Return E2E run did not pass")
        return receipt
    manifest_path = root / MANIFEST
    if expected_hash and sha256(manifest_path) != expected_hash:
        raise ValueError("Manifest SHA-256 differs from the supplied hash")
    manifest = json.loads(manifest_path.read_text())
    if manifest["schema"] != "trinetx-synthetic-e2e-v1":
        raise ValueError("Unsupported E2E evidence schema")
    if inventory(root) != manifest["files"]:
        raise ValueError("Evidence inventory or hashes differ from the manifest")
    try:
        results = cases(root / "junit.xml")
    except (OSError, KeyError, ET.ParseError):
        results = []
    products = workflow_products(root)
    passed = (
        manifest["pytest_exit_code"] == 0
        and successful_cases(results)
        and manifest["source_before"] == manifest["source_after"]
        and products_retained(products)
        and not manifest["runner_errors"]
    )
    if (
        results != manifest["cases"]
        or products != manifest["workflow_products"]
        or passed != (manifest["status"] == "passed")
    ):
        raise ValueError("Receipt status disagrees with the retained evidence")
    return manifest


def run(output: Path) -> int:
    output = output.absolute()
    if any(p.is_symlink() for p in (output, *output.parents)):
        raise ValueError("Output and its ancestors must not be symlinks")
    output = output.resolve()
    if output.is_relative_to(ROOT):
        raise ValueError("Use a fresh evidence directory outside the repository")
    if output.exists():
        raise ValueError("Output already exists; choose a new evidence directory")
    before = source_inventory()
    git_head = git("rev-parse", "HEAD")
    output.mkdir(parents=True)
    for name in before:
        source = ROOT / name
        if source.is_symlink():
            raise ValueError(f"Source snapshot requires regular files: {name}")
        target = output / "source" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    errors = []
    if inventory(output / "source") != before:
        errors.append("Source snapshot differs from the pre-run source inventory")
    command = [
        sys.executable,
        "-m",
        "pytest",
        "-q",
        *NODES,
        "-o",
        "tmp_path_retention_policy=all",
        "--basetemp",
        str(output / "work"),
        "--junitxml",
        str(output / "junit.xml"),
    ]
    started = datetime.now(timezone.utc).isoformat()
    print(f"Running {len(NODES)} synthetic workflows; log: {output / 'pytest.log'}")
    sys.stdout.flush()
    with (output / "pytest.log").open("w") as log:
        try:
            result = subprocess.run(
                command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT
            )
            exit_code = result.returncode
        except OSError as exc:
            errors.append(f"Pytest launch: {exc}")
            log.write(str(exc) + "\n")
            exit_code = 127
    try:
        after = source_inventory()
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        after = {}
        errors.append(f"Post-run source inventory: {exc}")
    try:
        results = cases(output / "junit.xml")
    except (OSError, KeyError, ET.ParseError) as exc:
        results = []
        errors.append(f"JUnit readback: {exc}")
    packages = {}
    for name in ("pytest", "duckdb", "numpy", "pandas", "pyarrow", "PyYAML"):
        try:
            packages[name] = version(name)
        except PackageNotFoundError as exc:
            errors.append(f"Package metadata: {exc}")
    try:
        files = inventory(output)
    except (OSError, ValueError) as exc:
        files = {}
        errors.append(f"Artifact inventory: {exc}")
    products = workflow_products(output)
    passed = (
        exit_code == 0
        and successful_cases(results)
        and before == after
        and products_retained(products)
        and not errors
    )
    manifest = {
        "schema": "trinetx-synthetic-e2e-v1",
        "status": "passed" if passed else "failed",
        "scope": "Synthetic positive/negative workflow evidence; not accepted products",
        "git_head": git_head,
        "source_before": before,
        "source_after": after,
        "started_utc": started,
        "finished_utc": datetime.now(timezone.utc).isoformat(),
        "environment": {
            "python": sys.version,
            "platform": platform.platform(),
            "packages": packages,
        },
        "command": command,
        "cwd": str(ROOT),
        "repeat_command": [
            "uv",
            "run",
            "python",
            "scripts/verify_e2e.py",
            "--output-dir",
            "<new-external-directory>",
        ],
        "pytest_exit_code": exit_code,
        "cases": results,
        "workflow_products": products,
        "runner_errors": errors,
        "files": files,
    }
    (output / MANIFEST).write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    )
    verify(output)
    print(f"{manifest['status'].upper()}: {output / MANIFEST}")
    print(f"Manifest SHA-256: {sha256(output / MANIFEST)}")
    return 0 if passed else (exit_code or 1)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--output-dir", type=Path)
    group.add_argument("--verify", type=Path)
    parser.add_argument("--manifest-sha256", help="Previously recorded manifest hash")
    args = parser.parse_args()
    if args.manifest_sha256 and not args.verify:
        parser.error("--manifest-sha256 requires --verify")
    try:
        if args.verify:
            manifest = verify(args.verify, args.manifest_sha256)
            print(f"Evidence verified; recorded run status: {manifest['status']}")
            return 0 if manifest["status"] == "passed" else 1
        return run(args.output_dir)
    except (OSError, ValueError, KeyError, ET.ParseError) as exc:
        print(f"E2E evidence error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

"""One concise CLI for change planning, execution, status, and candidate reuse."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from ..combined_preprocessing.builder import require_safe_output_location
from ..filesystem import remove_tree_strict, write_text_atomic
from .policy import ROOT, git, make_plan, sha


def write(path: Path, value: object) -> None:
    write_text_atomic(path, json.dumps(value, indent=2, default=str) + "\n")


def decision_valid(decision: dict, plan: dict) -> bool:
    """A recorded human decision is bound to both compared revisions."""
    return (
        decision.get("base") == plan["base"]
        and decision.get("head") == plan["head"]
        and decision.get("status") == "approved"
        and all(
            isinstance(decision.get(k), str) and decision[k].strip()
            for k in ("approved_by", "decision_reference", "expected_drift")
        )
    )


def run(args: argparse.Namespace) -> int:
    plan = make_plan(args.base, args.head)
    if not plan["clean"] or git("rev-parse", "HEAD").decode().strip() != plan["head"]:
        raise ValueError("Commit the work and run verification at the requested head")
    decision = None
    if plan["gate"] == "scientific":
        if args.decision is None:
            raise ValueError("Scientific decision required; see verify-update plan")
        decision = json.loads(args.decision.read_text())
        if not decision_valid(decision, plan):
            raise ValueError(
                "Decision must approve these revisions and describe expected drift"
            )
    baseline = None
    if args.baseline_receipt:
        baseline = json.loads(args.baseline_receipt.read_text())
        if baseline.get("status") != "passed" or not baseline.get("private_full_data"):
            raise ValueError("Baseline must be an accepted private-data receipt")
        if baseline.get("plan", {}).get("head") != plan["base"]:
            raise ValueError(
                "Baseline receipt must certify the requested base revision"
            )
    if decision and baseline is None:
        raise ValueError("Scientific drift review requires --baseline-receipt")
    private = plan["gate"] != "static" or args.full_glp1
    reuse_builds = getattr(args, "reuse_build_receipt", None)
    if reuse_builds and getattr(args, "reuse_raw_receipt", None):
        raise ValueError("Choose one completed-build reuse receipt")
    if (getattr(args, "reuse_raw_receipt", None) or reuse_builds) and not private:
        raise ValueError("Reference reuse requires a private verification run")
    if private and not args.full_glp1 and baseline is None:
        raise ValueError(
            "Updates require --baseline-receipt; initial source parity uses --full-glp1"
        )
    if private and not all((args.database, args.raw_input, args.config)):
        raise ValueError(
            "Private parity requires --database, --raw-input, and --config"
        )
    if "canonical" in plan["products"] and not all(
        (args.preprocessing_config, args.compatibility_baseline)
    ):
        raise ValueError(
            "Materialization changes require --preprocessing-config and "
            "--compatibility-baseline"
        )
    root = args.receipt_dir.resolve()
    require_safe_output_location(root, artifact_label="verification receipts")
    # A unique owned root makes failure preservation and success cleanup unambiguous.
    root.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    receipt = {
        "schema_version": 1,
        "status": "running",
        "plan": plan,
        "started_at": datetime.now(UTC).isoformat(),
        "steps": [],
        "decision": decision,
        "private_full_data": private,
    }
    for name in ("config", "preprocessing_config", "compatibility_baseline"):
        value = getattr(args, name)
        if value:
            receipt[name + "_sha256"] = hashlib.sha256(value.read_bytes()).hexdigest()

    def stage(name, action):
        receipt["phase"] = name
        write(root / "status.json", receipt)
        print(json.dumps({"status": "running", "phase": name}), flush=True)
        at = time.monotonic()
        result = action()
        receipt["steps"].append(
            {"name": name, "seconds": round(time.monotonic() - at, 3), "result": result}
        )
        write(root / "status.json", receipt)
        return result

    def command(argv):
        proc = subprocess.run(argv, cwd=ROOT, capture_output=True, text=True)
        # Public test output only; never capture unrestricted row diagnostics here.
        if proc.returncode:
            write(
                root / "public_check_failure.json",
                {
                    "command": argv,
                    "exit_code": proc.returncode,
                    "output": (proc.stdout + proc.stderr)[-8000:],
                },
            )
            raise ValueError("Public checks failed; see public_check_failure.json")
        return {"exit_code": 0, "summary": proc.stdout.strip().splitlines()[-1:]}

    try:
        stage("public_tests", lambda: command([sys.executable, "-m", "pytest", "-q"]))
        stage(
            "lint",
            lambda: command(
                [
                    sys.executable,
                    "-m",
                    "ruff",
                    "check",
                    "src",
                    "scripts/run_glp1_source_acceptance.py",
                ]
            ),
        )
        if private:
            from ..combined_preprocessing.cohort_source import validate_cohort_source
            from ..config import load_config
            from ..glp1_eligibility.builder import build_glp1_eligibility
            from ..glp1_eligibility.parity import compare_glp1_reference_outputs

            if "canonical" in plan["products"]:
                from ..combined_preprocessing.builder import build_preprocessed

                config = load_config(args.preprocessing_config)
                expected = config.output_dir / config.combined.database_name
                if expected.resolve() != args.database.resolve():
                    raise ValueError("Configured build database must match --database")

                def build():
                    result = build_preprocessed(config, strict=True)
                    if result.database_path.resolve() != args.database.resolve():
                        raise ValueError("Build database must match --database")
                    return {"completed": True}

                stage("canonical_build", build)
                stage(
                    "compatibility36",
                    lambda: compatibility_receipt(
                        args.database,
                        config.output_dir,
                        args.compatibility_baseline,
                        allow_drift=decision is not None,
                    ),
                )
            contract = stage(
                "source_contract",
                lambda: contract_payload(validate_cohort_source(args.database)),
            )
            if not contract["valid"]:
                raise ValueError("Canonical source contract failed")
            # Path-free product identity; input audit hashes are checked by DB build.
            receipt["source_identity"] = {
                k: v for k, v in contract["metadata"].items() if k != "database"
            }
            outputs = root / ".verification-outputs"
            outputs.mkdir()
            raw_output = outputs / "raw"
            canonical_output = outputs / "canonical"
            producer_revisions = None
            reused_results = None
            previous = getattr(args, "reuse_raw_receipt", None)
            if reuse_builds is not None:
                from .reuse import reuse_completed_builds

                borrowed, reused_results, proof = reuse_completed_builds(
                    reuse_builds,
                    plan=plan,
                    source_identity=receipt["source_identity"],
                    database=args.database,
                    raw_input=args.raw_input,
                    config_path=args.config,
                )
                receipt["build_reuse"] = proof
                raw_output, canonical_output = borrowed["raw"], borrowed["canonical"]
                producer_revisions = tuple(
                    proof["outputs"][mode]["producer_revision"]
                    for mode in ("raw", "canonical")
                )
            elif previous is not None:
                from .reuse import reuse_raw_reference

                raw_output, raw_result, proof = reuse_raw_reference(
                    previous,
                    plan=plan,
                    source_identity=receipt["source_identity"],
                    database=args.database,
                    raw_input=args.raw_input,
                    config_path=args.config,
                )
                receipt["raw_reference_reuse"] = proof
                producer_revisions = (proof["producer_revision"], plan["head"])
            for mode in ("raw", "canonical"):
                if reused_results is not None:
                    stage("glp1_" + mode, lambda: reused_results[mode])
                    continue
                if mode == "raw" and previous is not None:
                    stage("glp1_raw", lambda: raw_result)
                    continue

                def build_glp(mode=mode):
                    result = build_glp1_eligibility(
                        input_root=args.raw_input if mode == "raw" else None,
                        database_path=args.database if mode == "canonical" else None,
                        output_dir=outputs / mode,
                        config_path=args.config,
                    )
                    return {
                        "run_id": result.run_id,
                        "counts": vars(result.counts),
                        "warnings": result.warning_count,
                    }

                stage("glp1_" + mode, build_glp)
            parity = stage(
                "glp1_parity",
                lambda: compare_glp1_reference_outputs(
                    raw_output,
                    canonical_output,
                    scratch_root=outputs,
                    progress=lambda event: write(
                        root / "comparison_progress.json",
                        {**event, "updated_at": datetime.now(UTC).isoformat()},
                    ),
                    **(
                        {"expected_producer_revisions": producer_revisions}
                        if producer_revisions
                        else {}
                    ),
                ).to_dict(),
            )
            if not parity["valid"]:
                raise ValueError("GLP-1 parity failed; private outputs preserved")
            from .metrics import drift_report, scientific_metrics

            receipt["scientific_metrics"] = stage(
                "scientific_summary",
                lambda: scientific_metrics(
                    canonical_output / "glp1_hypercapnia.duckdb"
                ),
            )
            if baseline:
                report = {
                    "base": plan["base"],
                    "head": plan["head"],
                    "baseline_sha256": sha(baseline),
                    "compatibility": [
                        step["result"]
                        for step in receipt["steps"]
                        if step["name"] == "compatibility36"
                    ],
                    "differences": drift_report(
                        baseline["scientific_metrics"], receipt["scientific_metrics"]
                    ),
                    "scope": "aggregate review accompanying exact source-mode parity",
                }
                write(root / "drift_report.json", report)
                receipt["drift_report_sha256"] = sha(report)
                if report["differences"] and not decision:
                    raise ValueError(
                        "Unexpected scientific drift requires a recorded decision"
                    )
            receipt["status"] = "review_required" if decision else "passed"
            if receipt["status"] == "passed":
                write(root / "parity_evidence.json", receipt)
                remove_tree_strict(
                    outputs, context="Successful owned verification outputs"
                )
        else:
            receipt["status"] = "passed"
        receipt["elapsed_seconds"] = round(time.monotonic() - started, 3)
        receipt["completed_at"] = datetime.now(UTC).isoformat()
        write(root / "status.json", receipt)
        if receipt["status"] == "passed":
            write(root / "acceptance_complete.json", receipt)
        print(
            json.dumps(
                {
                    "status": receipt["status"],
                    "scope": plan["gate"],
                    "private_full_data": private,
                    "receipt": str(root),
                }
            )
        )
        return 0 if receipt["status"] == "passed" else 2
    except Exception as exc:
        receipt["status"] = "failed"
        # Keep runtime error text private; no raw rows are printed to the caller.
        receipt["failure_type"] = type(exc).__name__
        write(root / "failure.json", {"error": str(exc)})
        write(root / "status.json", receipt)
        print(
            json.dumps(
                {
                    "status": "failed",
                    "phase": receipt.get("phase"),
                    "receipt": str(root),
                }
            )
        )
        return 1


def contract_payload(result) -> dict:
    return {
        "valid": result.valid,
        "errors": list(result.errors),
        "metadata": result.metadata.to_dict() if result.metadata else None,
        "required_elements": list(result.required_elements),
    }


def compatibility_receipt(
    database: Path, output: Path, baseline_path: Path, *, allow_drift: bool = False
) -> dict:
    """Scan the 36 exported projections once; avoid recursive source auditing."""
    from ..combined_preprocessing.cohort_source import validate_cohort_source
    from ..combined_preprocessing.evidence import capture_compatibility_evidence

    contract = validate_cohort_source(database)
    if not contract.valid:
        raise ValueError("Compatibility product contract failed")
    current = capture_compatibility_evidence(output)
    baseline = json.loads(baseline_path.read_text())
    previous = {t["key"]: t for t in baseline["tables"]}
    observed = {t["key"]: t for t in current["tables"]}
    if len(previous) != 36 or len(baseline["tables"]) != 36:
        raise ValueError("Baseline must have exactly 36 distinct projections")
    keys = ("normalized_sha256", "row_count", "columns")
    differences = sorted(
        k
        for k in previous.keys() | observed.keys()
        if k not in previous
        or k not in observed
        or any(previous[k][f] != observed[k][f] for f in keys)
    )
    if differences and not allow_drift:
        raise ValueError("Compatibility projections differ: " + ", ".join(differences))
    return {
        "valid": not differences,
        "scope": "compatibility36_content_parity",
        "differences": differences,
        "baseline_sha256": sha(baseline),
        "current": current,
    }


def accept_drift(root: Path, decision_path: Path) -> int:
    require_safe_output_location(root, artifact_label="drift acceptance")
    receipt = json.loads((root / "status.json").read_text())
    report = json.loads((root / "drift_report.json").read_text())
    decision = json.loads(decision_path.read_text())
    if receipt["status"] != "review_required":
        raise ValueError(
            "Only a completed run awaiting scientific review may be accepted"
        )
    if not decision_valid(decision, receipt["plan"]):
        raise ValueError("Scientific decision must approve the verified revisions")
    if decision.get("drift_report_sha256") != sha(report):
        raise ValueError("Scientific decision does not approve this exact drift report")
    if receipt.get("drift_report_sha256") != sha(report):
        raise ValueError("Drift report changed after verification")
    receipt.update(status="passed", scientific_acceptance=decision)
    write(root / "parity_evidence.json", receipt)
    outputs = root / ".verification-outputs"
    if outputs.exists():
        remove_tree_strict(
            outputs, context="Scientifically accepted verification outputs"
        )
    write(root / "status.json", receipt)
    write(root / "acceptance_complete.json", receipt)
    print(json.dumps({"status": "passed", "receipt": str(root)}))
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    for name in ("plan", "run"):
        p = sub.add_parser(name)
        p.add_argument("--base", required=True)
        p.add_argument("--head", default="HEAD")
        if name == "run":
            p.add_argument("--receipt-dir", type=Path, required=True)
            for option in (
                "database",
                "raw-input",
                "config",
                "preprocessing-config",
                "compatibility-baseline",
                "baseline-receipt",
                "reuse-raw-receipt",
                "reuse-build-receipt",
                "decision",
            ):
                p.add_argument("--" + option, type=Path)
            p.add_argument(
                "--full-glp1",
                action="store_true",
                help="Establish initial private parity even for static changes",
            )
    p = sub.add_parser("accept-drift")
    p.add_argument("--receipt-dir", type=Path, required=True)
    p.add_argument("--decision", type=Path, required=True)
    p = sub.add_parser("status")
    p.add_argument("--receipt-dir", type=Path, required=True)
    for name in ("check-candidate", "promote-candidate"):
        p = sub.add_parser(name)
        p.add_argument("--database", type=Path, required=True)
        p.add_argument("--preprocessing-config", type=Path, required=True)
        p.add_argument("--producer", required=True)
        if name == "promote-candidate":
            p.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.action == "plan":
            print(json.dumps(make_plan(args.base, args.head), indent=2))
            return 0
        if args.action == "run":
            return run(args)
        if args.action == "accept-drift":
            return accept_drift(args.receipt_dir, args.decision)
        if args.action == "status":
            receipt = json.loads((args.receipt_dir / "status.json").read_text())
            print(
                json.dumps(
                    {
                        k: receipt.get(k)
                        for k in ("status", "phase", "elapsed_seconds", "completed_at")
                    }
                )
            )
            return 0
        from ..config import load_config
        from .candidate import candidate_preflight, promote_candidate

        config = load_config(args.preprocessing_config)
        if args.action == "check-candidate":
            receipt = candidate_preflight(args.database, config, args.producer)
        else:
            require_safe_output_location(
                args.receipt.parent, artifact_label="promotion receipt"
            )
            if args.receipt.exists():
                raise ValueError("Promotion receipt already exists")
            receipt = promote_candidate(args.database, config, args.producer)
            write(args.receipt, receipt)
        print(json.dumps(receipt, indent=2))
        return 0
    except (ValueError, OSError, KeyError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}))
        return 1

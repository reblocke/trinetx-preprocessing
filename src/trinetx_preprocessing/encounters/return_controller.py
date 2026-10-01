"""One locked controller for an explicitly configured private return candidate."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import time
import uuid
from pathlib import Path

from ..combined_preprocessing.builder import require_safe_output_location
from ..filesystem import write_text_atomic
from .builder import sha256
from .compatibility import no_symlinks
from .return_acceptance import verify_accepted_return_bundle
from .return_evidence import PartitionCheckpoints, component_identities
from .return_execution import (
    ProgressEvents,
    build_returns_v2,
    set_execution_lock_descriptor,
    source_stage_identity,
)
from .return_prerequisites import prepare_prerequisites
from .return_release import compare_retained_reference, seal_return_product
from .return_source_stage import create_source_stage, verify_source_stage
from .return_validation_execution import validate_return_product


def execute(config_path: Path, *, resume=False):
    """The configuration supplies explicit paths, trust, frozen identities and pilot."""
    config_path = no_symlinks(config_path)
    config_hash = sha256(config_path)
    config = json.loads(config_path.read_text())
    if (
        config.get("controller_contract_version") != "1.0"
        or config.get("scope") != "private_candidate_acceptance"
    ):
        raise ValueError("Unsupported return execution configuration")
    from .return_resources import check_workers, resource_policy

    policy = resource_policy(config.get("resource_policy"))
    check_workers(policy, config.get("workers", 1))
    current = component_identities()
    if config.get("frozen_component_identities") != current:
        raise ValueError("Execution differs from the explicitly frozen candidate")
    pilot_path = no_symlinks(Path(config["resource_pilot_path"]))
    if sha256(pilot_path) != config["trusted_resource_pilot_sha256"]:
        raise ValueError("Resource pilot differs from trusted digest")
    pilot = json.loads(pilot_path.read_text())
    workers = config.get("workers", 1)
    partitions = config.get("partitions", 32)
    if (
        pilot.get("status") != "passed"
        or resource_policy(pilot.get("resource_policy")) != policy
        or any(
            pilot.get("component_identities", {}).get(role) != current[role]
            for role in (
                "producer",
                "parent_validator",
                "outcome_validator",
                "source_validator",
                "source_stage",
                "contract",
                "environment",
            )
        )
        or workers not in pilot.get("verified_workers", [])
        or pilot.get("partitions") != partitions
        or not pilot.get("forecast_total_seconds", 0) > 0
    ):
        raise ValueError("Resource pilot does not cover this candidate/configuration")
    database = no_symlinks(Path(config["database"]))
    parent = no_symlinks(Path(config["parent_bundle"]))
    external_receipt = config.get("reuse_prerequisite_receipt_path")
    external_digest = config.get("trusted_prerequisite_receipt_sha256")
    if (external_receipt is None) != (external_digest is None):
        raise ValueError(
            "Explicit prerequisite reuse requires receipt and trusted SHA-256"
        )
    reference = no_symlinks(Path(config["reference_bundle"]))
    run_root = no_symlinks(Path(config["run_root"]))
    work = no_symlinks(Path(config["work_root"]))
    for destination in (run_root, work):
        require_safe_output_location(
            destination, artifact_label="return candidate execution"
        )
        if any(
            destination.is_relative_to(p) or p.is_relative_to(destination)
            for p in (database.parent, parent, reference)
        ):
            raise ValueError("Candidate execution overlaps immutable inputs")
    if run_root.is_relative_to(work) or work.is_relative_to(run_root):
        raise ValueError("Candidate output and work roots must be separate")
    if run_root.exists() and not resume:
        raise FileExistsError("Candidate run exists; explicit resume required")
    if resume and not run_root.is_dir():
        raise FileNotFoundError("Candidate run to resume does not exist")
    run_root.mkdir(mode=0o700, parents=True, exist_ok=resume)
    evidence = run_root / "evidence"
    evidence.mkdir(mode=0o700, exist_ok=True)
    work.mkdir(mode=0o700, parents=True, exist_ok=True)
    copied_config = evidence / "run-config.json"
    if copied_config.exists():
        if sha256(copied_config) != config_hash:
            raise ValueError("Resume configuration differs from the frozen run")
    else:
        write_text_atomic(copied_config, config_path.read_text())
    phases = PartitionCheckpoints(
        work / "phase-checkpoints", key_path=evidence / "controller.key"
    )
    run_binding = {"config_sha256": config_hash}
    start = phases.authenticated_record("run-start", run_binding)
    if start is None:
        started = time.time()
        phases.complete(
            "run-start",
            run_binding,
            {"config": copied_config},
            {"pass": True, "started_at_unix": started},
        )
    else:
        started = start["result"]["started_at_unix"]
    events = ProgressEvents(evidence / "events.jsonl")
    attempt = uuid.uuid4().hex
    events.emit(
        "controller",
        "resume" if resume else "start",
        config_sha256=config_hash,
        attempt=attempt,
        resource_policy=policy,
    )
    try:
        accepted = phases.authenticated_record("product-acceptance", run_binding)
        if accepted is not None:
            previous = accepted["result"]
            artifacts = {
                "receipt": no_symlinks(Path(previous["receipt_path"])),
                "validation": no_symlinks(Path(previous["validation_report_path"])),
            }
            if any(not p.is_relative_to(evidence) for p in artifacts.values()):
                raise ValueError("Accepted evidence is outside this run")
            if not phases.reusable("product-acceptance", run_binding, artifacts):
                raise ValueError("Previously accepted evidence has changed")
            verify_accepted_return_bundle(
                run_root / "outcomes",
                variant="FULL_DATA",
                receipt_path=artifacts["receipt"],
                expected_receipt_sha256=previous["receipt_sha256"],
                validation_report_path=artifacts["validation"],
            )
            events.emit("controller", "accepted_product_reverified")
            return {k: v for k, v in previous.items() if k != "pass"}
        # Reuse prerequisite computation only through the separately held key,
        # then rehash all actual input bytes through prepare_prerequisites.
        prior = phases.authenticated_record("prerequisites", run_binding)
        reuse = {}
        if external_receipt is not None:
            reuse = {
                "reuse_receipt_path": no_symlinks(Path(external_receipt)),
                "expected_reuse_sha256": external_digest,
            }
        if prior is not None:
            previous = no_symlinks(Path(prior["result"]["receipt_path"]))
            if not previous.is_relative_to(evidence):
                raise ValueError("Prerequisite receipt is outside this run's evidence")
            if phases.reusable("prerequisites", run_binding, {"receipt": previous}):
                reuse = {
                    "reuse_receipt_path": previous,
                    "expected_reuse_sha256": prior["artifacts"]["receipt"]["sha256"],
                }
        events.emit("prerequisites", "start", reused=bool(reuse))
        inputs = prepare_prerequisites(
            database=database,
            parent_bundle=parent,
            receipt_path=evidence / f"prerequisites-{attempt}.json",
            work_dir=work / f"parent-validation-{attempt}",
            memory_limit_mib=policy["parent_memory_limit_mib"],
            **reuse,
        )
        if (
            inputs.receipt["inputs"]["source_database"]["sha256"]
            != config["expected_source_database_sha256"]
        ):
            raise ValueError("Canonical source bytes differ from the approved snapshot")
        phases.complete(
            "prerequisites",
            run_binding,
            {"receipt": inputs.receipt_path},
            {"pass": True, "receipt_path": str(inputs.receipt_path)},
        )
        events.emit("prerequisites", "complete", receipt_sha256=inputs.receipt_sha256)
        stage = run_root / "source-stage"
        stage_binding = source_stage_identity(inputs, partitions, policy)
        stage_files = {"manifest": stage / "manifest.json"}
        if phases.reusable("source-stage", stage_binding, stage_files):
            trusted_stage = sha256(stage / "manifest.json")
            verify_source_stage(
                stage, expected_manifest_sha256=trusted_stage, identity=stage_binding
            )
            events.emit("source_stage", "reused", manifest_sha256=trusted_stage)
        else:
            if stage.exists():
                # A complete but unauthenticated stage is retained for diagnosis.
                stage.rename(stage.with_name(f"source-stage-unaccepted-{attempt}"))
            create_source_stage(
                database=database,
                parent_bundle=parent,
                output_dir=stage,
                work_dir=work / f"source-stage-{attempt}",
                partitions=partitions,
                identity=stage_binding,
                memory_limit_mib=policy["stage_memory_limit_mib"],
                threads=policy["threads"],
                events=events,
            )
            phases.complete("source-stage", stage_binding, stage_files, {"pass": True})
            trusted_stage = sha256(stage / "manifest.json")
        bundle = run_root / "outcomes"
        if not bundle.exists():
            build_returns_v2(
                inputs=inputs,
                output_dir=bundle,
                work_dir=work / "producer",
                checkpoint_key_path=evidence / "producer.key",
                partitions=partitions,
                workers=workers,
                resource_limits=policy,
                source_stage=stage,
                expected_stage_sha256=trusted_stage,
                events=events,
                resume=(run_root / ".outcomes.return-staging").exists(),
            )
        # Recover safely even if publication completed just before controller
        # death: every produced partition must still have authenticated evidence.
        from .builder import VARIANTS
        from .return_acceptance import TABLES

        produced = json.loads((bundle / "progress.json").read_text())
        producer_checkpoints = PartitionCheckpoints(
            work / "producer" / "build-checkpoints", key_path=evidence / "producer.key"
        )
        for variant in VARIANTS:
            for bucket in range(partitions):
                artifacts = {
                    table: bundle / f"{variant.lower()}_{bucket:04d}_{table}.parquet"
                    for table in TABLES
                }
                if not producer_checkpoints.reusable(
                    f"{variant}:{bucket}", produced["binding"], artifacts
                ):
                    raise ValueError(
                        "Completed product lacks authenticated producer evidence"
                    )
        validation_path = evidence / f"validation-{attempt}.json"
        validate_return_product(
            bundle=bundle,
            inputs=inputs,
            work_dir=work / "validator",
            checkpoint_key_path=evidence / "validator.key",
            report_path=validation_path,
            workers=workers,
            resource_limits=policy,
            source_stage=stage,
            expected_stage_sha256=trusted_stage,
            events=events,
        )
        comparison_path = evidence / f"reference-{attempt}.json"
        compare_retained_reference(
            bundle=bundle,
            reference_bundle=reference,
            reference_receipt_path=Path(config["reference_receipt_path"]),
            expected_reference_receipt_sha256=config[
                "trusted_reference_receipt_sha256"
            ],
            reference_validation_report_path=Path(
                config["reference_validation_report_path"]
            ),
            work_dir=work / f"reference-{attempt}",
            report_path=comparison_path,
            memory_limit_mib=policy["global_memory_limit_mib"],
            threads=policy["threads"],
            events=events,
        )
        unchanged_path = evidence / f"unchanged-inputs-{attempt}.json"
        events.emit("unchanged_inputs", "start")
        inputs.prove_unchanged_bytes(unchanged_path)
        events.emit(
            "unchanged_inputs", "complete", receipt_sha256=sha256(unchanged_path)
        )
        baseline = json.loads(Path(config["reference_receipt_path"]).read_text())
        baseline_seconds = baseline["build_seconds"] + baseline["validate_seconds"]
        total = time.time() - started
        runtime = {
            "resource_policy": policy,
            "status": "passed" if 0 < total < baseline_seconds else "failed",
            "bundle_manifest_sha256": sha256(bundle / "manifest.json"),
            "candidate_total_seconds": total,
            "baseline_build_validate_seconds": baseline_seconds,
            "target_seconds": 18000,
            "target_gap_seconds": max(0, total - 18000),
            "preseal_only": True,
            "includes_cold_setup_and_recovery_downtime": external_receipt is None,
            "prerequisite_mode": (
                "external_verified_reuse"
                if external_receipt is not None
                else "cold_or_same_run_resume"
            ),
            "includes_same_run_recovery_downtime": True,
            "includes_prior_candidate_time": False,
            "reference_acceptance_sha256": config["trusted_reference_receipt_sha256"],
            "resource_pilot_sha256": config["trusted_resource_pilot_sha256"],
            "events_sha256_before_seal": sha256(events.path),
        }
        runtime_path = evidence / f"runtime-{attempt}.json"
        write_text_atomic(
            runtime_path, json.dumps(runtime, sort_keys=True, indent=2) + "\n"
        )
        if runtime["status"] != "passed":
            raise ValueError("Measured runtime improvement gate failed")
        receipt_path = evidence / f"acceptance-{attempt}.json"
        seal_return_product(
            bundle=bundle,
            inputs=inputs,
            validation_report_path=validation_path,
            comparison_report_path=comparison_path,
            receipt_path=receipt_path,
            runtime_report_path=runtime_path,
            expected_runtime_report_sha256=sha256(runtime_path),
            unchanged_inputs_report_path=unchanged_path,
            expected_unchanged_inputs_sha256=sha256(unchanged_path),
        )
        result = {
            "status": "upstream_product_accepted",
            "receipt_path": str(receipt_path),
            "receipt_sha256": sha256(receipt_path),
            "validation_report_path": str(validation_path),
            "elapsed_seconds": time.time() - started,
            "combined_release": "pending",
        }
        phases.complete(
            "product-acceptance",
            run_binding,
            {"receipt": receipt_path, "validation": validation_path},
            {"pass": True, **result},
        )
        events.emit(
            "controller",
            "upstream_product_accepted",
            receipt_sha256=sha256(receipt_path),
            total_seconds=time.time() - started,
            downstream_release_verification="pending",
        )
        return result
    except BaseException as exc:
        events.emit(
            "controller", "blocked", error_type=type(exc).__name__, error=str(exc)
        )
        write_text_atomic(
            evidence / f"blocked-{attempt}.json",
            json.dumps(
                {
                    "status": "BLOCKED",
                    "error": f"{type(exc).__name__}: {exc}",
                    "elapsed_seconds": time.time() - started,
                    "config_sha256": config_hash,
                },
                sort_keys=True,
                indent=2,
            )
            + "\n",
        )
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--lock-file", type=Path, required=True)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    lock_path = no_symlinks(args.lock_file)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("BLOCKED: another controller owns the execution lock")
            return 75
        os.set_inheritable(lock.fileno(), True)
        set_execution_lock_descriptor(lock.fileno())
        print(
            json.dumps(
                execute(args.config, resume=args.resume), sort_keys=True, indent=2
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

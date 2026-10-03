#!/usr/bin/env python3
"""Real synthetic source/parent validation, production, recovery and acceptance E2E.

Expected before the corresponding full execution checks: cold and trusted warm
prerequisites agree; altered trust fails. A deliberate interruption preserves a
completed partition and resume skips only that verified work. Direct and staged
products have exact schemas/rows for both variants. Independent validation reuses
signed checkpoints, while final global proofs always run. Receipts here are
explicitly synthetic and cannot certify private acceptance.
"""

from __future__ import annotations

import argparse
import json
import platform
import runpy
import shutil
import sys
from pathlib import Path

import duckdb

from trinetx_preprocessing.encounters.builder import VARIANTS, literal, sha256

ROOT = Path(__file__).resolve().parents[1]


def run(root, *, consumer=False):
    from trinetx_preprocessing.combined_preprocessing.database import (
        COMBINED_MANIFEST_FILENAME,
    )
    from trinetx_preprocessing.encounters.return_acceptance import (
        REQUIRED_GATES,
        TABLES,
        verify_accepted_return_bundle,
    )
    from trinetx_preprocessing.encounters.return_execution import (
        ProgressEvents,
        build_returns_v2,
        source_stage_identity,
    )
    from trinetx_preprocessing.encounters.return_prerequisites import (
        prepare_prerequisites,
    )
    from trinetx_preprocessing.encounters.return_source_stage import create_source_stage
    from trinetx_preprocessing.encounters.return_validation_execution import (
        validate_return_product,
    )
    from trinetx_preprocessing.encounters.return_validation_v2 import (
        _assert_equal_multiset,
    )

    root.mkdir(parents=True, exist_ok=False)
    canonical = root / "canonical"
    canonical.mkdir()
    source = runpy.run_path(str(ROOT / "tests/test_cohort_source.py"))[
        "_build_cohort_source_product"
    ](canonical)
    parent = root / "parent"
    runpy.run_path(str(ROOT / "tests/test_return_parent_validation.py"))["_bundle"](
        parent
    )
    # Supply actual retained day strings in the synthetic parent. The old
    # v1 fixture used placeholder numeric raw dates; v2 must reject those.
    import pyarrow as pa
    import pyarrow.parquet as pq

    from trinetx_preprocessing.encounters.compatibility import artifact_inventory
    from trinetx_preprocessing.encounters.return_parent_validation import (
        LEGACY_DATE_FIELDS,
    )

    for variant in VARIANTS:
        for table, raw_column in LEGACY_DATE_FIELDS.items():
            path = parent / f"encounter_features_{variant.lower()}_{table}.parquet"
            data = pq.read_table(path)
            raw = pa.array(
                [
                    value.strftime("%Y-%m-%d") if value is not None else None
                    for value in data["event_datetime"].to_pylist()
                ],
                type=pa.string(),
            )
            if raw_column in data.schema.names:
                data = data.set_column(
                    data.schema.get_field_index(raw_column), raw_column, raw
                )
            else:
                data = data.append_column(raw_column, raw)
            if "event_datetime_precision" in data.schema.names:
                data = data.set_column(
                    data.schema.get_field_index("event_datetime_precision"),
                    "event_datetime_precision",
                    pa.array(["date_only"] * len(data)),
                )
            pq.write_table(data, path)
    parent_manifest = json.loads((parent / "manifest.json").read_text())
    parent_manifest["outputs"] = {
        n: v for n, v in artifact_inventory(parent).items() if n != "manifest.json"
    }
    parent_manifest["source_manifest_sha256"] = sha256(
        source.parent / COMBINED_MANIFEST_FILENAME
    )
    (parent / "manifest.json").write_text(json.dumps(parent_manifest) + "\n")
    evidence = root / "evidence"
    evidence.mkdir()
    cold = prepare_prerequisites(
        database=source,
        parent_bundle=parent,
        receipt_path=evidence / "cold.json",
        work_dir=root / "parent-check",
        memory_limit_mib=8192,
        events=ProgressEvents(evidence / "parent-resource-events.jsonl"),
    )
    warm = prepare_prerequisites(
        database=source,
        parent_bundle=parent,
        receipt_path=evidence / "warm.json",
        work_dir=root / "unused-parent-check",
        reuse_receipt_path=cold.receipt_path,
        expected_reuse_sha256=cold.receipt_sha256,
    )
    assert not (root / "unused-parent-check").exists()
    parent_events = [
        json.loads(line)
        for line in (evidence / "parent-resource-events.jsonl").read_text().splitlines()
    ]
    parent_settings = [
        event for event in parent_events if event["event"] == "resource_settings"
    ]
    assert parent_settings[-1]["effective_memory_limit"] == "8.0 GiB"
    assert parent_settings[-1]["effective_threads"] == 1
    assert {
        event["variant"]
        for event in parent_events
        if event["event"] == "variant_checks_complete"
    } == {"FULL_DATA", "AFTER_EXCLUSION"}
    assert {
        event["variant"]
        for event in parent_events
        if event["event"] == "normalized_summary_bucket_complete"
    } == {"FULL_DATA", "AFTER_EXCLUSION"}
    from trinetx_preprocessing.encounters.return_parent_validation import (
        DAY_PRECISION_VALIDATION_VERSION,
        validate_bundle,
    )

    original_report = validate_bundle(
        bundle=parent,
        work_dir=root / "parent-unpartitioned-oracle",
        validation_contract_version=DAY_PRECISION_VALIDATION_VERSION,
    )
    assert cold.receipt["parent_report"] == original_report
    (evidence / "parent-unpartitioned-report.json").write_text(
        json.dumps(original_report, sort_keys=True, indent=2) + "\n"
    )
    # Independent semantic failures after refreshing artifact hashes: these must
    # reach the bounded summary proof rather than fail solely on byte identity.
    for label, suffix, column, value in (
        ("lab-value", "", "glp1_lab_a1c_latest", -999.0),
        ("bp-value", "", "glp1_bp_latest_sbp", -999.0),
        ("lab-unit", "_component_lab_evidence", "normalized_unit", "invalid"),
    ):
        altered = root / f"parent-normalized-negative-{label}"
        shutil.copytree(parent, altered)
        path = altered / f"encounter_features_full_data{suffix}.parquet"
        table = pq.read_table(path)
        index = table.schema.get_field_index(column)
        assert index >= 0 and len(table) > 0
        table = table.set_column(
            index,
            column,
            pa.array([value] * len(table), type=table.schema.field(index).type),
        )
        pq.write_table(table, path)
        changed_manifest = json.loads((altered / "manifest.json").read_text())
        changed_manifest["outputs"] = {
            n: v for n, v in artifact_inventory(altered).items() if n != "manifest.json"
        }
        (altered / "manifest.json").write_text(json.dumps(changed_manifest) + "\n")
        try:
            validate_bundle(
                bundle=altered,
                work_dir=root / f"parent-normalized-negative-work-{label}",
                memory_limit_mib=1024,
                distinct_count_partitions=4,
                validation_contract_version=DAY_PRECISION_VALIDATION_VERSION,
            )
        except ValueError as error:
            assert "normalized lab/vital summary reconciliation failed" in str(error)
            (evidence / f"parent-normalized-negative-{label}.txt").write_text(
                str(error) + "\n"
            )
        else:
            raise AssertionError(
                f"Bounded normalized summary accepted {label} mutation"
            )
    assert cold.receipt["inputs"] == warm.receipt["inputs"]
    try:
        prepare_prerequisites(
            database=source,
            parent_bundle=parent,
            receipt_path=evidence / "bad.json",
            work_dir=root / "bad-parent",
            reuse_receipt_path=cold.receipt_path,
            expected_reuse_sha256="0" * 64,
        )
    except ValueError:
        pass
    else:
        raise AssertionError("Wrong prerequisite trust was reused")
    stage = root / "source-stage"
    create_source_stage(
        database=source,
        parent_bundle=parent,
        output_dir=stage,
        work_dir=root / "source-stage-work",
        partitions=2,
        identity=source_stage_identity(warm, 2),
    )
    events = ProgressEvents(evidence / "events.jsonl")
    direct = root / "direct"
    build_returns_v2(
        inputs=warm,
        output_dir=direct,
        work_dir=root / "direct-work",
        checkpoint_key_path=evidence / "direct.key",
        partitions=2,
        events=events,
    )

    class Interrupted(ProgressEvents):
        def completed(self, *args, **kwargs):
            super().completed(*args, **kwargs)
            raise InterruptedError(
                "Deliberate E2E interruption after durable partition checkpoint"
            )

    staged = root / "staged"
    arguments = dict(
        inputs=warm,
        output_dir=staged,
        work_dir=root / "staged-work",
        checkpoint_key_path=evidence / "staged.key",
        partitions=2,
        source_stage=stage,
        expected_stage_sha256=sha256(stage / "manifest.json"),
    )
    try:
        build_returns_v2(
            **arguments, events=Interrupted(evidence / "interruption.jsonl")
        )
    except InterruptedError:
        pass
    else:
        raise AssertionError("Controlled interruption did not occur")
    assert not staged.exists()
    build_returns_v2(**arguments, events=events, resume=True, workers=2)
    with duckdb.connect() as db:
        for variant in VARIANTS:
            for table in TABLES:
                left = direct / f"{variant.lower()}_*_{table}.parquet"
                right = staged / f"{variant.lower()}_*_{table}.parquet"
                _assert_equal_multiset(
                    db,
                    f"SELECT * FROM read_parquet({literal(left)})",
                    f"SELECT * FROM read_parquet({literal(right)})",
                    table,
                )
    report = validate_return_product(
        bundle=staged,
        inputs=warm,
        work_dir=root / "validation-work",
        checkpoint_key_path=evidence / "validation.key",
        report_path=evidence / "validation.json",
        workers=2,
        source_stage=stage,
        expected_stage_sha256=sha256(stage / "manifest.json"),
        events=events,
    )
    again = validate_return_product(
        bundle=staged,
        inputs=warm,
        work_dir=root / "validation-work",
        checkpoint_key_path=evidence / "validation.key",
        report_path=evidence / "validation-reused.json",
        workers=1,
        source_stage=stage,
        expected_stage_sha256=sha256(stage / "manifest.json"),
        events=events,
    )
    assert report == again
    warm.check_unchanged(complete_bytes=True)
    receipt = {
        k: report[k]
        for k in (
            "schema_version",
            "return_contract_version",
            "bundle_manifest_sha256",
            "parent_manifest_sha256",
            "source_manifest_sha256",
            "source_database_sha256",
            "identities",
            "original_keys",
            "artifact_inventory_sha256",
        )
    }
    receipt.update(
        kind="return_outcomes_acceptance",
        status="accepted",
        acceptance_contract_version="1.0",
        validation_report_sha256=sha256(evidence / "validation.json"),
        evidence_scope="synthetic full workflow",
        gates={
            g: {"status": "pass", "evidence_sha256": sha256(evidence / "events.jsonl")}
            for g in REQUIRED_GATES
        },
    )
    receipt_path = evidence / "acceptance.json"
    receipt_path.write_text(json.dumps(receipt, sort_keys=True, indent=2) + "\n")
    for variant in VARIANTS:
        verify_accepted_return_bundle(
            staged,
            variant=variant,
            receipt_path=receipt_path,
            expected_receipt_sha256=sha256(receipt_path),
            validation_report_path=evidence / "validation.json",
        )
    from trinetx_preprocessing.encounters.return_release import (
        compare_retained_reference,
        seal_return_product,
    )

    direct_report_path = evidence / "direct-validation.json"
    validate_return_product(
        bundle=direct,
        inputs=warm,
        work_dir=root / "direct-validation-work",
        checkpoint_key_path=evidence / "direct-validation.key",
        report_path=direct_report_path,
        workers=1,
        events=events,
    )
    comparison_path = evidence / "exact-reference.json"
    compare_retained_reference(
        bundle=direct,
        reference_bundle=staged,
        reference_receipt_path=receipt_path,
        expected_reference_receipt_sha256=sha256(receipt_path),
        reference_validation_report_path=evidence / "validation.json",
        work_dir=root / "reference-work",
        report_path=comparison_path,
        events=events,
    )
    unchanged_path = evidence / "unchanged-inputs.json"
    warm.prove_unchanged_bytes(unchanged_path)
    # These durations are a labeled boundary fixture, not a performance result.
    runtime_path = evidence / "runtime-gate-fixture.json"
    runtime = {
        "status": "passed",
        "bundle_manifest_sha256": sha256(direct / "manifest.json"),
        "candidate_total_seconds": 1,
        "baseline_build_validate_seconds": 2,
        "evidence_scope": "synthetic gate fixture; no measured speedup claimed",
    }
    runtime_path.write_text(json.dumps(runtime) + "\n")
    accepted_path = evidence / "sealed-product.json"
    abandoned = accepted_path.with_name(accepted_path.name + ".pending")
    abandoned.write_text("deliberately incomplete historical draft\n")
    seal_return_product(
        bundle=direct,
        inputs=warm,
        validation_report_path=direct_report_path,
        comparison_report_path=comparison_path,
        receipt_path=accepted_path,
        runtime_report_path=runtime_path,
        expected_runtime_report_sha256=sha256(runtime_path),
        unchanged_inputs_report_path=unchanged_path,
        expected_unchanged_inputs_sha256=sha256(unchanged_path),
    )
    assert abandoned.read_text() == "deliberately incomplete historical draft\n"

    # Exercise the real CLI with explicitly synthetic pilot/timing evidence.
    # These fixtures establish wiring and recovery, never private performance.
    import os
    import subprocess

    from trinetx_preprocessing.encounters.return_evidence import component_identities

    policy = {
        "policy_version": "1.0",
        "stage_memory_limit_mib": 12288,
        "parent_memory_limit_mib": 8192,
        "global_memory_limit_mib": 12288,
        "worker_memory_limit_mib": 5120,
        "threads": 1,
        "max_workers": 2,
    }
    controller_reference = json.loads(accepted_path.read_text())
    controller_reference.update(build_seconds=1_000_000, validate_seconds=1_000_000)
    controller_reference_path = evidence / "controller-reference-fixture.json"
    controller_reference_path.write_text(json.dumps(controller_reference) + "\n")
    pilot = evidence / "controller-pilot-fixture.json"
    pilot.write_text(
        json.dumps(
            {
                "status": "passed",
                "component_identities": component_identities(),
                "verified_workers": [1, 2],
                "resource_policy": policy,
                "partitions": 2,
                "forecast_total_seconds": 60,
                "scope": "synthetic controller fixture; no private resource claim",
            }
        )
        + "\n"
    )
    config = evidence / "controller-config.json"
    config.write_text(
        json.dumps(
            {
                "controller_contract_version": "1.0",
                "scope": "private_candidate_acceptance",
                "frozen_component_identities": component_identities(),
                "resource_pilot_path": str(pilot.resolve()),
                "trusted_resource_pilot_sha256": sha256(pilot),
                "workers": 2,
                "resource_policy": policy,
                "partitions": 2,
                "database": str(source.resolve()),
                "parent_bundle": str(parent.resolve()),
                "reference_bundle": str(direct.resolve()),
                "run_root": str((root / "controller-run").resolve()),
                "work_root": str((root / "controller-work").resolve()),
                "expected_source_database_sha256": sha256(source),
                "reference_receipt_path": str(controller_reference_path.resolve()),
                "trusted_reference_receipt_sha256": sha256(controller_reference_path),
                "reference_validation_report_path": str(direct_report_path.resolve()),
                "reuse_prerequisite_receipt_path": str(cold.receipt_path.resolve()),
                "trusted_prerequisite_receipt_sha256": cold.receipt_sha256,
            }
        )
        + "\n"
    )
    command = [
        sys.executable,
        "-m",
        "trinetx_preprocessing.encounters.return_controller",
        "--config",
        str(config.resolve()),
        "--lock-file",
        str((root / "controller.lock").resolve()),
    ]
    environment = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    original_config = json.loads(config.read_text())
    # A pilot for a different or unrecorded profile must fail before input reads.
    from trinetx_preprocessing.encounters.return_controller import execute

    for stale_policy in (None, {**policy, "stage_memory_limit_mib": 3072}):
        stale = json.loads(pilot.read_text())
        stale["resource_policy"] = stale_policy
        stale_path = evidence / ("stale-policy-" + str(stale_policy is None) + ".json")
        stale_path.write_text(json.dumps(stale) + "\n")
        invalid_config = evidence / (
            "stale-config-" + str(stale_policy is None) + ".json"
        )
        invalid_config.write_text(
            json.dumps(
                {
                    **original_config,
                    "resource_pilot_path": str(stale_path),
                    "trusted_resource_pilot_sha256": sha256(stale_path),
                    "database": str(root / "absent-canonical"),
                }
            )
            + "\n"
        )
        try:
            execute(invalid_config)
        except ValueError as exc:
            assert "Resource pilot" in str(exc)
        else:
            raise AssertionError("Uncovered resource policy accepted")
    for invalid in (True, 0, -1, "12288", 12289):
        invalid_policy = {**policy, "stage_memory_limit_mib": invalid}
        bad_config = evidence / ("invalid-policy-" + str(invalid) + ".json")
        bad_config.write_text(
            json.dumps({**original_config, "resource_policy": invalid_policy}) + "\n"
        )
        try:
            execute(bad_config)
        except ValueError:
            pass
        else:
            raise AssertionError("Invalid operational policy accepted")
    changed = json.loads(cold.receipt_path.read_text())
    changed["dependencies"]["parent_validator"] = "changed-validator"
    changed_path = evidence / "changed-prerequisite-dependency.json"
    changed_path.write_text(json.dumps(changed) + "\n")
    for label, updates in (
        ("missing-trust", {"trusted_prerequisite_receipt_sha256": None}),
        ("wrong-trust", {"trusted_prerequisite_receipt_sha256": "0" * 64}),
        (
            "changed-dependency",
            {
                "reuse_prerequisite_receipt_path": str(changed_path.resolve()),
                "trusted_prerequisite_receipt_sha256": sha256(changed_path),
            },
        ),
    ):
        rejected_root = root / f"controller-rejected-{label}"
        rejected_config = {
            **original_config,
            **updates,
            "run_root": str(rejected_root.resolve()),
            "work_root": str((root / f"controller-rejected-work-{label}").resolve()),
        }
        config.write_text(json.dumps(rejected_config) + "\n")
        rejected = subprocess.run(
            command, env=environment, capture_output=True, text=True
        )
        (evidence / f"controller-rejected-{label}.log").write_text(
            rejected.stdout + rejected.stderr
        )
        assert rejected.returncode != 0
        assert not (rejected_root / "source-stage").exists()
        assert not (rejected_root / "outcomes").exists()
    config.write_text(json.dumps(original_config) + "\n")
    outcomes = []
    for attempt, extra in enumerate(([], ["--resume"])):
        process = subprocess.run(
            command + extra, env=environment, capture_output=True, text=True
        )
        (evidence / f"controller-{attempt}.log").write_text(
            process.stdout + process.stderr
        )
        assert process.returncode == 0, process.stderr
        outcomes.append(json.loads(process.stdout))
    assert outcomes[0]["receipt_sha256"] == outcomes[1]["receipt_sha256"]
    assert outcomes[0]["receipt_path"] == outcomes[1]["receipt_path"]
    reused_receipts = list(
        (root / "controller-run" / "evidence").glob("prerequisites-*.json")
    )
    assert len(reused_receipts) == 1
    assert (
        json.loads(reused_receipts[0].read_text())["reused_from_sha256"]
        == cold.receipt_sha256
    )
    runtime_receipts = list(
        (root / "controller-run" / "evidence").glob("runtime-*.json")
    )
    assert len(runtime_receipts) == 1
    reuse_runtime = json.loads(runtime_receipts[0].read_text())
    assert reuse_runtime["prerequisite_mode"] == "external_verified_reuse"
    assert reuse_runtime["includes_cold_setup_and_recovery_downtime"] is False
    assert reuse_runtime["includes_same_run_recovery_downtime"] is True
    assert reuse_runtime["includes_prior_candidate_time"] is False
    if consumer:
        from trinetx_preprocessing.encounters.return_acceptance import KEYS
        from trinetx_preprocessing.encounters.return_quality import build_quality_report
        from trinetx_preprocessing.encounters.return_reader import (
            join_return_summary,
            open_return_summary,
        )

        for variant in VARIANTS:
            with open_return_summary(
                direct,
                variant=variant,
                receipt_path=accepted_path,
                expected_receipt_sha256=sha256(accepted_path),
                validation_report_path=direct_report_path,
            ) as summary:
                frame = pq.read_table(
                    parent / f"encounter_features_{variant.lower()}.parquet"
                ).to_pandas()
                joined = join_return_summary(
                    frame,
                    summary,
                    parent_manifest_sha256=sha256(parent / "manifest.json"),
                    columns=[*KEYS, "outcome_inpatient_all_cause_30d_flag"],
                )
                assert (
                    len(joined) == 1
                    and joined["outcome_inpatient_all_cause_30d_flag"].isna().all()
                )
        quality = build_quality_report(
            direct,
            receipt_path=accepted_path,
            expected_receipt_sha256=sha256(accepted_path),
            validation_report_path=direct_report_path,
            output_dir=root / "installed-consumer-quality",
        )
        assert all(
            quality["variants"][v]["original_index_count"] == 1 for v in VARIANTS
        )
    records = [
        json.loads(line)
        for line in (evidence / "events.jsonl").read_text().splitlines()
    ]
    assert (
        len(
            [
                r
                for r in records
                if r["event"] == "partition_reused" and r["phase"] == "build"
            ]
        )
        == 1
    )
    assert (
        len(
            [
                r
                for r in records
                if r["event"] == "partition_reused" and r["phase"] == "validation"
            ]
        )
        == 4
    )
    settings = [
        json.loads(line)
        for line in (root / "controller-run/evidence/events.jsonl")
        .read_text()
        .splitlines()
        if json.loads(line).get("event") == "resource_settings"
    ]
    assert {x["phase"] for x in settings} >= {
        "source_stage",
        "build",
        "validation",
        "global_validation",
        "reference_comparison",
    }
    assert all(x["effective_threads"] == 1 for x in settings)
    assert all(
        x["requested_memory_limit_mib"]
        == (5120 if x["phase"] in ("build", "validation") else 12288)
        for x in settings
    )
    assert all(
        x["effective_memory_limit"]
        == ("5.0 GiB" if x["phase"] in ("build", "validation") else "12.0 GiB")
        for x in settings
    )
    return {
        "status": "passed",
        "real_source_and_parent_validation": True,
        "resumed_build_partitions": 1,
        "reused_validation_partitions": 4,
        "workers_exercised": [1, 2],
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("artifact_dir", type=Path)
    p.add_argument("--require-installed", action="store_true")
    p.add_argument("--consumer", action="store_true")
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
        result.update(run(args.artifact_dir, consumer=args.consumer))
        result["exit_status"] = 0
    except Exception as exc:
        import traceback

        traceback.print_exc()
        result.update(
            status="failed", error=f"{type(exc).__name__}: {exc}", exit_status=1
        )
    args.artifact_dir.mkdir(parents=True, exist_ok=True)
    (args.artifact_dir / "runner.py").write_bytes(Path(__file__).read_bytes())
    result["schema"] = "trinetx-return-e2e-v1"
    result["installed_noneditable"] = installed
    result["consumer_exercised"] = args.consumer
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

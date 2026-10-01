"""Materialized independent validation; clinical checks retain their own SQL."""

from __future__ import annotations

from . import return_validation_v2 as reference


def validate_partition_materialized(db) -> None:
    """Validate one explicit parent-key partition with reusable intermediates.

    Source staging supplies only verified raw values. Expected episodes,
    phenotypes and summaries are still derived by the independent validator.
    The direct reference validator remains available with its default views.
    """
    reference._check_partition_source(db, materialize=True)
    reference._check_partition_episodes(db, materialize=True)
    reference._check_partition_pairs(db)
    reference._check_partition_geometry(db)
    reference._check_partition_evidence(db, materialize=True)
    reference._check_partition_phenotypes(db, materialize=True)
    reference._check_summary_states(db, materialize=True)
    for days in (30, 90, 365):
        for kind in ("inpatient", "ed_only", "any_ed", "acute_union"):
            reference._check_summary_metric(db, kind=kind, days=days)


def _validate_one(job):
    import time
    from pathlib import Path

    import pyarrow.parquet as pq

    from .builder import literal
    from .return_acceptance import TABLES, frozen_table_schema
    from .return_execution import _connection
    from .return_source_stage import attach_source_partition

    started = time.monotonic()
    with _connection(
        Path(job["scratch"]),
        memory_limit_mib=job["resource_policy"]["worker_memory_limit_mib"],
        threads=job["resource_policy"]["threads"],
    ) as db:
        if job["stage"] is None:
            db.execute(f"ATTACH {literal(job['database'])} AS preprocessed (READ_ONLY)")
        else:
            attach_source_partition(
                db,
                Path(job["stage"]),
                bucket=job["bucket"],
                expected_manifest_sha256=job["stage_sha256"],
                identity=job["stage_identity"],
            )
        for table in TABLES:
            path = (
                Path(job["bundle"])
                / f"{job['variant'].lower()}_{job['bucket']:04d}_{table}.parquet"
            )
            if not pq.read_schema(path).equals(
                frozen_table_schema(table), check_metadata=False
            ):
                raise ValueError("Return artifact schema differs from frozen contract")
            db.execute(
                f"CREATE TEMP VIEW {table} AS SELECT * "
                f"FROM read_parquet({literal(path)})"
            )
        db.execute(
            "CREATE TEMP VIEW parent_index AS SELECT patient_id::VARCHAR patient_id,"
            "encounter_id::VARCHAR encounter_id,pat_enc_hash::VARCHAR index_event_id "
            f"FROM read_parquet({literal(job['parent_file'])}) "
            f"WHERE hash(patient_id::VARCHAR)%{job['partitions']}={job['bucket']}"
        )
        from .return_resources import configure_connection

        effective = configure_connection(
            db,
            memory_limit_mib=job["resource_policy"]["worker_memory_limit_mib"],
            threads=job["resource_policy"]["threads"],
        )
        validate_partition_materialized(db)
        rows = db.execute("SELECT count(*) FROM summary").fetchone()[0]
    return {
        "pass": True,
        "rows": rows,
        "seconds": time.monotonic() - started,
        "resources": effective,
    }


def validate_return_product(
    *,
    bundle,
    inputs,
    work_dir,
    checkpoint_key_path,
    report_path,
    workers=1,
    source_stage=None,
    expected_stage_sha256=None,
    events,
    resource_limits=None,
):
    """Independently validate all partitions and mandatory global product proofs."""
    import json
    import uuid

    from .return_resources import check_workers, resource_policy

    policy = resource_policy(resource_limits)
    check_workers(policy, workers)

    import pyarrow.parquet as pq

    from ..combined_preprocessing.builder import require_safe_output_location
    from ..filesystem import fsync_directory_strict, write_text_atomic
    from .builder import VARIANTS, literal, sha256
    from .compatibility import no_symlinks
    from .return_acceptance import (
        TABLES,
        artifact_inventory_digest,
        canonical_digest,
        frozen_table_schema,
        key_proof,
        summary_names,
        verify_return_output,
    )
    from .return_evidence import PartitionCheckpoints, component_identities
    from .return_execution import (
        _connection,
        _production_identities,
        run_partition_jobs,
        source_stage_identity,
    )
    from .return_source_stage import verify_source_stage
    from .returns_v2 import dictionary_entry

    bundle, work_dir, report_path = (
        no_symlinks(bundle),
        no_symlinks(work_dir),
        no_symlinks(report_path),
    )
    for path in (work_dir, report_path.parent):
        require_safe_output_location(path, artifact_label="return validation evidence")
        if any(
            path.is_relative_to(p) or p.is_relative_to(path)
            for p in (bundle, inputs.parent_bundle, inputs.database.parent)
        ):
            raise ValueError("Return validation work overlaps an input")
    if report_path.exists():
        raise FileExistsError("Historical validation reports cannot be overwritten")
    inputs.check_unchanged()
    manifest_path = bundle / "manifest.json"
    manifest_hash = sha256(manifest_path)
    manifest = json.loads(manifest_path.read_text())
    partitions = manifest.get("partitions")
    if (
        manifest.get("kind") != "return_outcomes"
        or manifest.get("status") != "complete"
        or manifest.get("schema_version") != "2.0"
        or manifest.get("return_contract_version") != "2.0"
        or manifest.get("execution_contract_version") != "1.0"
        or type(partitions) is not int
        or not 1 <= partitions <= 1024
        or manifest.get("variants") != list(VARIANTS)
        or manifest.get("horizons_days") != [30, 90, 365]
    ):
        raise ValueError("Unsupported return execution product")
    if manifest.get("identities") != _production_identities(inputs, partitions):
        raise ValueError("Return producer dependency identities differ")
    source_inputs = inputs.receipt["inputs"]
    for field, input_name in (
        ("parent_manifest_sha256", "parent/manifest.json"),
        ("source_manifest_sha256", "source_manifest"),
        ("source_database_sha256", "source_database"),
    ):
        if manifest.get(field) != source_inputs[input_name]["sha256"]:
            raise ValueError("Return product provenance differs from validated inputs")
    expected = {"data_dictionary.json", "progress.json"} | {
        f"{v.lower()}_{b:04d}_{t}.parquet"
        for v in VARIANTS
        for b in range(partitions)
        for t in TABLES
    }
    if set(manifest.get("outputs", {})) != expected or {
        p.name for p in bundle.iterdir() if not p.name.startswith("._")
    } != expected | {"manifest.json"}:
        raise ValueError("Return complete artifact inventory differs")
    for name in expected:
        verify_return_output(bundle, manifest, name)
    dictionary = json.loads((bundle / "data_dictionary.json").read_text())
    with _connection(
        work_dir / f"global-{uuid.uuid4().hex}",
        memory_limit_mib=policy["global_memory_limit_mib"],
        threads=policy["threads"],
        events=events,
        phase="global_validation",
    ) as db:
        for variant in VARIANTS:
            for bucket in range(partitions):
                for table in TABLES:
                    path = bundle / f"{variant.lower()}_{bucket:04d}_{table}.parquet"
                    if not pq.read_schema(path).equals(
                        frozen_table_schema(table), check_metadata=False
                    ):
                        raise ValueError("Return frozen schema differs")
                    declared = [
                        dictionary_entry(table, c, t)
                        for c, t, *_ in db.execute(
                            f"DESCRIBE SELECT * FROM read_parquet({literal(path)})"
                        ).fetchall()
                    ]
                    if dictionary.get(table) != declared:
                        raise ValueError("Return data dictionary differs")
        proofs = {}
        for variant in VARIANTS:
            paths = [bundle / n for n in summary_names(manifest, variant)]
            parent = (
                inputs.parent_bundle / f"encounter_features_{variant.lower()}.parquet"
            )
            expected_keys = key_proof(
                [parent], parent=True, work_dir=work_dir / f"keys-parent-{variant}"
            )
            actual_keys = key_proof(paths, work_dir=work_dir / f"keys-return-{variant}")
            if actual_keys != expected_keys:
                raise ValueError(
                    "Return original composite keys differ from accepted parent"
                )
            files = "[" + ",".join(literal(p) for p in paths) + "]"
            reference._assert_equal_multiset(
                db,
                "SELECT patient_id::VARCHAR,encounter_id::VARCHAR,"
                "pat_enc_hash::VARCHAR "
                f"FROM read_parquet({literal(parent)})",
                "SELECT patient_id,encounter_id,index_event_id "
                f"FROM read_parquet({files})",
                "global original parent key equality",
            )
            if db.execute(
                "SELECT count(*) FROM (SELECT pat_enc_hash FROM "
                f"read_parquet({literal(parent)}) GROUP BY 1 HAVING count(*)<>1)"
            ).fetchone()[0]:
                raise ValueError("Parent original index hash is not unique")
            proofs[variant] = expected_keys
    progress = json.loads((bundle / "progress.json").read_text())
    if set(progress.get("completed", {})) != {
        f"{v}:{b}" for v in VARIANTS for b in range(partitions)
    }:
        raise ValueError("Incomplete return producer partition evidence")
    for variant in VARIANTS:
        for bucket in range(partitions):
            expected_part = {
                t: manifest["outputs"][f"{variant.lower()}_{bucket:04d}_{t}.parquet"]
                for t in TABLES
            }
            if progress["completed"][f"{variant}:{bucket}"] != expected_part:
                raise ValueError("Return producer artifact receipt differs")
    stage_identity = source_stage_identity(inputs, partitions, policy)
    if (source_stage is None) != (expected_stage_sha256 is None):
        raise ValueError(
            "Validation stage requires an explicit trusted manifest digest"
        )
    if source_stage is not None:
        verify_source_stage(
            source_stage,
            expected_manifest_sha256=expected_stage_sha256,
            identity=stage_identity,
        )
    current = component_identities()
    identities = {
        **manifest["identities"],
        "parent_validator": current["parent_validator"],
        "outcome_validator": current["outcome_validator"],
        "validator_environment": current["environment"],
    }
    binding = {
        "resource_policy": policy,
        "manifest_sha256": manifest_hash,
        "identities": identities,
        "input_bytes_sha256": canonical_digest(inputs.receipt["inputs"]),
        "validation_source_stage_sha256": expected_stage_sha256,
    }
    checkpoints = PartitionCheckpoints(
        work_dir / "validation-checkpoints", key_path=checkpoint_key_path
    )
    jobs = []
    completed = 0
    for variant in VARIANTS:
        for bucket in range(partitions):
            key = f"{variant}:{bucket}"
            artifacts = {
                t: bundle / f"{variant.lower()}_{bucket:04d}_{t}.parquet"
                for t in TABLES
            }
            if checkpoints.reusable(key, binding, artifacts):
                completed += 1
                events.emit(
                    "validation", "partition_reused", variant=variant, bucket=bucket
                )
                continue
            jobs.append(
                {
                    "resource_policy": policy,
                    "variant": variant,
                    "bucket": bucket,
                    "partitions": partitions,
                    "database": str(inputs.database),
                    "stage": None if source_stage is None else str(source_stage),
                    "stage_sha256": expected_stage_sha256,
                    "stage_identity": stage_identity,
                    "parent_file": str(
                        inputs.parent_bundle
                        / f"encounter_features_{variant.lower()}.parquet"
                    ),
                    "bundle": str(bundle),
                    "scratch": str(
                        work_dir / f"validate-{variant}-{bucket}-{uuid.uuid4().hex}"
                    ),
                }
            )
    events.emit(
        "validation",
        "start",
        scheduled_partitions=len(jobs),
        reused_partitions=completed,
        workers=workers,
    )
    for index, (job, result) in enumerate(
        run_partition_jobs(_validate_one, jobs, workers)
    ):
        inputs.check_unchanged()
        artifacts = {
            t: bundle / f"{job['variant'].lower()}_{job['bucket']:04d}_{t}.parquet"
            for t in TABLES
        }
        checkpoints.complete(
            f"{job['variant']}:{job['bucket']}", binding, artifacts, result
        )
        completed += 1
        events.emit(
            "validation",
            "resource_settings",
            variant=job["variant"],
            bucket=job["bucket"],
            **result["resources"],
        )
        events.completed(
            "validation",
            job["variant"],
            job["bucket"],
            result["seconds"],
            len(jobs) - index - 1,
        )
    if completed != len(VARIANTS) * partitions:
        raise ValueError("Incomplete return validation partitions")
    for name in expected:
        verify_return_output(bundle, manifest, name)
    inputs.check_unchanged()
    if sha256(manifest_path) != manifest_hash or component_identities() != current:
        raise ValueError("Return manifest or validator dependencies changed")
    if source_stage is not None:
        verify_source_stage(
            source_stage,
            expected_manifest_sha256=expected_stage_sha256,
            identity=stage_identity,
        )
    report = {
        "pass": True,
        "validation_report_version": "1.0",
        "schema_version": "2.0",
        "return_contract_version": "2.0",
        "bundle_manifest_sha256": manifest_hash,
        "parent_manifest_sha256": manifest["parent_manifest_sha256"],
        "source_manifest_sha256": manifest["source_manifest_sha256"],
        "source_database_sha256": manifest["source_database_sha256"],
        "identities": identities,
        "original_keys": proofs,
        "artifact_inventory_sha256": artifact_inventory_digest(manifest["outputs"]),
        "prerequisite_receipt_sha256": inputs.receipt_sha256,
        "validation_source_stage_sha256": expected_stage_sha256,
    }
    write_text_atomic(report_path, json.dumps(report, sort_keys=True, indent=2) + "\n")
    fsync_directory_strict(report_path.parent)
    events.emit("validation", "complete", report_sha256=sha256(report_path))
    return report

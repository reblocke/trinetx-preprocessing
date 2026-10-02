"""Opt-in staged v2 execution with durable progress and reusable partition evidence."""

from __future__ import annotations

import json
import multiprocessing
import os
import shutil
import time
import uuid
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from contextlib import closing
from pathlib import Path

import duckdb
import pyarrow.parquet as pq

from ..combined_preprocessing.builder import require_safe_output_location
from ..filesystem import fsync_directory_strict, fsync_file_strict, write_text_atomic
from .builder import VARIANTS, code_identity, literal, sha256
from .compatibility import artifact_inventory, no_symlinks
from .return_acceptance import TABLES, canonical_digest, frozen_table_schema
from .return_evidence import PartitionCheckpoints, component_identities
from .return_prerequisites import VerifiedPrerequisites
from .return_source_stage import attach_source_partition, verify_source_stage
from .returns_v2 import build_partition_v2, dictionary_entry

_EXECUTION_LOCK_DESCRIPTOR = None


def set_execution_lock_descriptor(descriptor: int) -> None:
    """Retain the controller's open file description in spawned active workers."""
    global _EXECUTION_LOCK_DESCRIPTOR
    os.fstat(descriptor)
    _EXECUTION_LOCK_DESCRIPTOR = descriptor


def _run_locked_partition(worker, job, transferred, observation):
    descriptor = None if transferred is None else transferred.detach()
    passed = False
    events = None
    try:
        if observation is not None:
            path, started, phase = observation
            # Callbacks/subclasses remain in the controller. Only immutable
            # path/clock values cross the spawn boundary.
            events = ProgressEvents(Path(path))
            events.started = started
            events.emit(
                phase,
                "worker_start",
                pid=os.getpid(),
                parent_pid=os.getppid(),
                variant=job["variant"],
                bucket=job["bucket"],
            )
        result = worker(job)
        passed = True
        return os.getpid(), result
    finally:
        try:
            if events is not None:
                events.emit(
                    phase,
                    "worker_job_exit",
                    pid=os.getpid(),
                    passed=passed,
                    variant=job["variant"],
                    bucket=job["bucket"],
                )
        finally:
            if descriptor is not None:
                os.close(descriptor)


class ProgressEvents:
    """Durable phase/partition events; estimates cover measured comparable work."""

    def __init__(self, path: Path):
        self.path = no_symlinks(path)
        require_safe_output_location(
            self.path.parent, artifact_label="return progress events"
        )
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.started = time.monotonic()
        self.durations = {}

    def emit(self, phase, event, **values):
        record = {
            "event_contract_version": "1.0",
            "at_unix": time.time(),
            "elapsed_seconds": time.monotonic() - self.started,
            "phase": phase,
            "event": event,
            **values,
        }
        with self.path.open("a") as stream:
            stream.write(json.dumps(record, sort_keys=True) + "\n")
            stream.flush()
            os.fsync(stream.fileno())

    def completed(self, phase, variant, bucket, seconds, remaining):
        durations = self.durations.setdefault((phase, variant), [])
        durations.append(seconds)
        self.emit(
            phase,
            "partition_complete",
            variant=variant,
            bucket=bucket,
            seconds=seconds,
            remaining_partitions=remaining,
            estimated_remaining_partition_seconds=sum(durations)
            / len(durations)
            * remaining,
            estimate_scope=(
                "serial comparable partition work only; excludes unmeasured phases"
            ),
        )


def source_stage_identity(
    inputs: VerifiedPrerequisites, partitions: int, resource_limits=None
) -> dict:
    from .return_resources import resource_policy

    policy = resource_policy(resource_limits)
    identities = component_identities()
    return {
        "inputs_sha256": canonical_digest(inputs.receipt["inputs"]),
        "source_stage": identities["source_stage"],
        "environment": identities["environment"],
        "partitions": partitions,
        "stage_contract_version": "1.0",
        "resource_policy": policy,
    }


def _production_identities(inputs, partitions):
    current = component_identities()
    return {
        "producer": current["producer"],
        "source_stage": current["source_stage"],
        "contract": current["contract"],
        "environment": current["environment"],
        "configuration": canonical_digest(
            {"partitions": partitions, "return_contract_version": "2.0"}
        ),
        "catalog": inputs.receipt["dependencies"]["catalog"],
    }


def _connection(
    work_dir, *, memory_limit_mib=3072, threads=1, events=None, phase="resources"
):
    from .return_resources import check_settings, configure_connection

    check_settings(memory_limit_mib, threads)
    work_dir.mkdir(mode=0o700, parents=True, exist_ok=False)
    db = duckdb.connect()
    configure_connection(
        db,
        memory_limit_mib=memory_limit_mib,
        threads=threads,
        events=events,
        phase=phase,
    )
    db.execute("SET temp_directory=?", [str(work_dir)])
    return db


def _build_one(job):
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
        db.execute(
            "CREATE TEMP VIEW index_file AS SELECT * FROM read_parquet("
            + literal(job["index_file"])
            + ")"
        )
        from .return_resources import configure_connection

        effective = configure_connection(
            db,
            memory_limit_mib=job["resource_policy"]["worker_memory_limit_mib"],
            threads=job["resource_policy"]["threads"],
        )
        result = build_partition_v2(
            db,
            variant=job["variant"],
            bucket=job["bucket"],
            partitions=job["partitions"],
            output=Path(job["output"]),
        )
    for table in TABLES:
        path = (
            Path(job["output"])
            / f"{job['variant'].lower()}_{job['bucket']:04d}_{table}.parquet"
        )
        if not pq.read_schema(path).equals(
            frozen_table_schema(table), check_metadata=False
        ):
            raise ValueError("Produced return schema differs from frozen v2 contract")
        fsync_file_strict(path)
    return {
        "pass": True,
        "artifacts": result,
        "seconds": time.monotonic() - started,
        "resources": effective,
    }


def run_partition_jobs(worker, jobs, workers, *, events=None, phase=None):
    """Bound concurrency with a fresh spawned process for every partition.

    Joining each single-job executor before exposing its result prevents native
    allocations from accumulating across jobs, including the one-worker route.
    On errors or iterator closure, submitted jobs finish and all executors join;
    no replacement is scheduled and the original worker exception propagates.
    """
    if type(workers) is not int or workers not in (1, 2, 4):
        raise ValueError("Supported worker counts are 1, 2 and 4")
    if (events is None) != (phase is None):
        raise ValueError("Worker observations require both events and phase")
    from multiprocessing.reduction import DupFd

    pending = iter(jobs)
    active = {}
    observation = None if events is None else (str(events.path), events.started, phase)

    def submit_next():
        try:
            job = next(pending)
        except StopIteration:
            return False
        # Spawn prevents inheriting a live DuckDB connection across fork.
        pool = ProcessPoolExecutor(
            max_workers=1, mp_context=multiprocessing.get_context("spawn")
        )
        try:
            future = pool.submit(
                _run_locked_partition,
                worker,
                job,
                None
                if _EXECUTION_LOCK_DESCRIPTOR is None
                else DupFd(_EXECUTION_LOCK_DESCRIPTOR),
                observation,
            )
        except BaseException:
            pool.shutdown(wait=True)
            raise
        active[future] = job, pool
        return True

    try:
        for _ in range(workers):
            if not submit_next():
                break
        while active:
            done, _ = wait(active, return_when=FIRST_COMPLETED)
            completed = []
            # Inspect the complete ready batch before scheduling replacements.
            for future in done:
                job, pool = active.pop(future)
                try:
                    pid, result = future.result()
                finally:
                    pool.shutdown(wait=True)
                if events is not None:
                    events.emit(
                        phase,
                        "worker_reaped",
                        pid=pid,
                        variant=job["variant"],
                        bucket=job["bucket"],
                    )
                completed.append((job, result))
            yield from completed
            # A failure can become ready while the caller checkpoints a yielded
            # result. Observe it before filling any newly available slot.
            for future in active:
                if future.done() and future.exception() is not None:
                    future.result()
            for _ in completed:
                if not submit_next():
                    break
    finally:
        # Do not cancel a submitted DupFd transfer: drain it so the child closes
        # the inherited lock description. No new jobs are submitted here.
        for _, pool in active.values():
            pool.shutdown(wait=True)


def build_returns_v2(
    *,
    inputs: VerifiedPrerequisites,
    output_dir: Path,
    work_dir: Path,
    checkpoint_key_path: Path,
    partitions: int = 32,
    workers: int = 1,
    resume: bool = False,
    source_stage: Path | None = None,
    expected_stage_sha256: str | None = None,
    events: ProgressEvents,
    resource_limits=None,
) -> dict:
    """Build through verified prerequisites; preserve the direct reference route."""
    from .return_resources import check_workers, resource_policy

    policy = resource_policy(resource_limits)
    check_workers(policy, workers)
    if type(partitions) is not int or not 1 <= partitions <= 1024:
        raise ValueError("Invalid patient partition count")
    if (source_stage is None) != (expected_stage_sha256 is None):
        raise ValueError("Staged execution requires an explicit trusted stage digest")
    output_dir, work_dir = no_symlinks(output_dir), no_symlinks(work_dir)
    for path in (output_dir, work_dir):
        require_safe_output_location(path, artifact_label="return execution")
        if any(
            path.is_relative_to(p) or p.is_relative_to(path)
            for p in (inputs.database.parent, inputs.parent_bundle)
        ):
            raise ValueError("Return execution overlaps immutable inputs")
    if output_dir.is_relative_to(work_dir) or work_dir.is_relative_to(output_dir):
        raise ValueError("Return bundle and work must be separate")
    if output_dir.exists():
        raise FileExistsError("Completed return bundle cannot be overwritten")
    inputs.check_unchanged()
    production = _production_identities(inputs, partitions)
    stage_identity = source_stage_identity(inputs, partitions, policy)
    if source_stage is not None:
        verify_source_stage(
            source_stage,
            expected_manifest_sha256=expected_stage_sha256,
            identity=stage_identity,
        )
    binding = {
        "resource_policy": policy,
        "inputs_sha256": canonical_digest(inputs.receipt["inputs"]),
        "production": production,
        "partitions": partitions,
        "source_stage_manifest_sha256": expected_stage_sha256,
    }
    staging = output_dir.with_name(f".{output_dir.name}.return-staging")
    no_symlinks(staging)
    progress_path = staging / "progress.json"
    if staging.exists():
        if not resume:
            raise FileExistsError("Return staging exists; explicit resume required")
        progress = json.loads(no_symlinks(progress_path).read_text())
        if progress.get("binding") != binding:
            raise ValueError("Return build resume dependencies differ")
    else:
        if resume:
            raise FileNotFoundError("No return staging to resume")
        staging.mkdir(mode=0o700, parents=True)
        progress = {
            "execution_contract_version": "1.0",
            "binding": binding,
            "completed": {},
        }
        write_text_atomic(
            progress_path, json.dumps(progress, sort_keys=True, indent=2) + "\n"
        )
    checkpoints = PartitionCheckpoints(
        work_dir / "build-checkpoints", key_path=checkpoint_key_path
    )
    jobs = []
    for variant in VARIANTS:
        for bucket in range(partitions):
            key = f"{variant}:{bucket}"
            paths = {
                t: staging / f"{variant.lower()}_{bucket:04d}_{t}.parquet"
                for t in TABLES
            }
            if checkpoints.reusable(key, binding, paths):
                progress["completed"][key] = {
                    t: {"bytes": p.stat().st_size, "sha256": sha256(p)}
                    for t, p in paths.items()
                }
                events.emit("build", "partition_reused", variant=variant, bucket=bucket)
                continue
            existing = [p for p in paths.values() if p.exists()]
            if existing:
                archive = work_dir / "interrupted-parts" / uuid.uuid4().hex
                archive.mkdir(mode=0o700, parents=True)
                for p in existing:
                    shutil.move(str(no_symlinks(p)), str(archive / p.name))
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
                    "index_file": str(
                        inputs.parent_bundle
                        / f"encounter_features_{variant.lower()}.parquet"
                    ),
                    "output": str(staging),
                    "scratch": str(
                        work_dir / f"build-{variant}-{bucket}-{uuid.uuid4().hex}"
                    ),
                }
            )
    events.emit("build", "start", scheduled_partitions=len(jobs), workers=workers)
    with closing(
        run_partition_jobs(_build_one, jobs, workers, events=events, phase="build")
    ) as results:
        for index, (job, result) in enumerate(results):
            inputs.check_unchanged()
            key = f"{job['variant']}:{job['bucket']}"
            paths = {
                t: staging / f"{job['variant'].lower()}_{job['bucket']:04d}_{t}.parquet"
                for t in TABLES
            }
            checkpoints.complete(
                key, binding, paths, {"pass": True, "resources": result["resources"]}
            )
            events.emit(
                "build",
                "resource_settings",
                variant=job["variant"],
                bucket=job["bucket"],
                **result["resources"],
            )
            progress["completed"][key] = result["artifacts"]
            write_text_atomic(
                progress_path, json.dumps(progress, sort_keys=True, indent=2) + "\n"
            )
            fsync_directory_strict(staging)
            events.completed(
                "build",
                job["variant"],
                job["bucket"],
                result["seconds"],
                len(jobs) - index - 1,
            )
    if set(progress["completed"]) != {
        f"{v}:{b}" for v in VARIANTS for b in range(partitions)
    }:
        raise ValueError("Return build partition inventory is incomplete")
    write_text_atomic(
        progress_path, json.dumps(progress, sort_keys=True, indent=2) + "\n"
    )
    if _production_identities(inputs, partitions) != production:
        raise ValueError("Producer dependencies changed during execution")
    dictionary = {}
    with duckdb.connect() as db:
        for table in TABLES:
            path = staging / f"full_data_0000_{table}.parquet"
            dictionary[table] = [
                dictionary_entry(table, col, kind)
                for col, kind, *_ in db.execute(
                    f"DESCRIBE SELECT * FROM read_parquet({literal(path)})"
                ).fetchall()
            ]
    write_text_atomic(
        staging / "data_dictionary.json", json.dumps(dictionary, indent=2) + "\n"
    )
    manifest = {
        "kind": "return_outcomes",
        "status": "complete",
        "schema_version": "2.0",
        "return_contract_version": "2.0",
        "execution_contract_version": "1.0",
        "identities": production,
        "code_sha256": code_identity(),
        "parent_manifest_sha256": inputs.receipt["inputs"]["parent/manifest.json"][
            "sha256"
        ],
        "source_manifest_sha256": inputs.receipt["inputs"]["source_manifest"]["sha256"],
        "source_database_sha256": inputs.receipt["inputs"]["source_database"]["sha256"],
        "source_stage_manifest_sha256": expected_stage_sha256,
        "prerequisite_receipt_sha256": inputs.receipt_sha256,
        "partitions": partitions,
        "variants": list(VARIANTS),
        "horizons_days": [30, 90, 365],
        "outputs": artifact_inventory(staging),
        "limitations": [
            "Observed returns only; forward capture is not proven complete"
        ],
    }
    write_text_atomic(
        staging / "manifest.json", json.dumps(manifest, sort_keys=True, indent=2) + "\n"
    )
    fsync_directory_strict(staging)
    staging.replace(output_dir)
    fsync_directory_strict(output_dir.parent)
    events.emit(
        "build", "complete", manifest_sha256=sha256(output_dir / "manifest.json")
    )
    return manifest

#!/usr/bin/env python3
"""Retained synthetic native worker lifetime, failure and lock ownership E2E.

The failure modes were recorded in docs/WORKER_LIFETIME_RECOVERY.md before this
fixture or the scheduler repair. Native ps observations are independent of
scheduler bookkeeping. Deliberately retained, touched pages expose process reuse.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import importlib.metadata
import json
import os
import platform
import signal
import subprocess
import sys
import time
from pathlib import Path

RETAINED = []


def digest(path):
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024**2), b""):
            value.update(block)
    return value.hexdigest()


def write(path, value):
    with path.open("x") as stream:
        json.dump(value, stream, sort_keys=True, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def native(pid):
    result = subprocess.run(
        ["ps", "-p", str(pid), "-o", "pid=,ppid=,lstart=,rss=,comm="],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode not in (0, 1):
        raise RuntimeError("Native process observation failed: " + result.stderr)
    return result.stdout.strip()


def group_members(group):
    result = subprocess.run(
        ["ps", "-axo", "pid=,pgid=,state=,lstart=,comm="],
        capture_output=True,
        text=True,
        check=True,
    )
    members = {}
    for line in result.stdout.splitlines():
        fields = line.split(None, 8)
        if len(fields) == 9 and int(fields[1]) == group and "Z" not in fields[2]:
            members[int(fields[0])] = " ".join(fields[3:8])
    return members


def stop_fixture_members(group, captured):
    # A disappeared/empty group needs no signal. Reusing a bare group number
    # after its owner exits is not proof that the current members are ours.
    for sig in (signal.SIGTERM, signal.SIGKILL):
        active = group_members(group)
        if any(
            pid not in captured or captured[pid] != birth
            for pid, birth in active.items()
        ):
            raise RuntimeError("Synthetic cleanup found an uncaptured/reused identity")
        for pid in active:
            try:
                os.kill(pid, sig)
            except ProcessLookupError:
                pass
        deadline = time.monotonic() + 5
        while group_members(group):
            if time.monotonic() >= deadline:
                break
            time.sleep(0.05)
        else:
            return
    raise RuntimeError("Synthetic cleanup left captured members running")


def retaining_job(job):
    pages = bytearray(4 * 1024**2)
    pages[::4096] = b"x" * (len(pages) // 4096)
    RETAINED.append(pages)
    result = {
        "pass": True,
        "phase": job["phase"],
        "index": job["index"],
        "pid": os.getpid(),
        "native": native(os.getpid()),
        "retained_bytes": sum(map(len, RETAINED)),
    }
    write(Path(job["root"]) / f"{job['phase']}-{job['index']:04d}.json", result)
    return result


def failing_job(job):
    root = Path(job["root"])
    record = {"pid": os.getpid(), "native": native(os.getpid())}
    write(root / f"started-{job['index']}.json", record)
    if job["index"] == 0:
        if job["mode"] == "exception":
            raise ValueError("deliberate worker failure")
        os._exit(19)
    time.sleep(0.25)
    write(root / f"finished-{job['index']}.json", record)
    return {"pass": True, "pid": os.getpid()}


def held_job(job):
    root = Path(job["root"])
    write(
        root / "worker-started.json",
        {"pid": os.getpid(), "native": native(os.getpid())},
    )
    deadline = time.monotonic() + 20
    while not (root / "finish-worker").exists():
        if time.monotonic() > deadline:
            raise TimeoutError("Synthetic held worker deadline")
        time.sleep(0.05)
    return {"pass": True}


def lock_controller(root, workers):
    from trinetx_preprocessing.encounters.return_execution import (
        run_partition_jobs,
        set_execution_lock_descriptor,
    )

    with (root / "execution.lock").open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        set_execution_lock_descriptor(lock.fileno())
        list(run_partition_jobs(held_job, [{"root": str(root)}], workers))


def lock_case(root, workers):
    root.mkdir()
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        str(root),
        "--lock-controller",
        "--workers",
        str(workers),
    ]
    with (root / "controller.log").open("x") as log:
        process = subprocess.Popen(
            command, stdout=log, stderr=subprocess.STDOUT, start_new_session=True
        )
        captured = group_members(process.pid)
        try:
            deadline = time.monotonic() + 25
            while not (root / "worker-started.json").exists():
                if process.poll() is not None:
                    raise AssertionError("Controller exited before worker start")
                if time.monotonic() > deadline:
                    raise TimeoutError("Synthetic worker startup deadline")
                time.sleep(0.05)
            record = json.loads((root / "worker-started.json").read_text())
            captured.update(group_members(process.pid))
            process.terminate()
            process.wait(timeout=5)
            with (root / "execution.lock").open("r") as probe:
                try:
                    fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    pass
                else:
                    raise AssertionError("Controller death released active worker lock")
                (root / "finish-worker").write_text("finish\n")
                deadline = time.monotonic() + 15
                while True:
                    try:
                        fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        fcntl.flock(probe, fcntl.LOCK_UN)
                        break
                    except BlockingIOError:
                        if time.monotonic() > deadline:
                            raise TimeoutError("Exited worker retained the lock")
                        time.sleep(0.05)
            write(root / "result.json", {"pass": True, "workers": workers, **record})
        finally:
            if process.poll() is None:
                captured.update(group_members(process.pid))
            stop_fixture_members(process.pid, captured)
            process.wait(timeout=5)


def run(root):
    from trinetx_preprocessing.encounters.return_execution import run_partition_jobs

    results = {}
    for workers in (1, 2, 4):
        target = root / f"workers-{workers}"
        target.mkdir()
        phases = {}
        for phase in ("build", "validation"):
            jobs = [
                {"root": str(target), "phase": phase, "index": i} for i in range(64)
            ]
            observations = []
            for job, result in run_partition_jobs(retaining_job, jobs, workers):
                if (job["index"], job["phase"]) != (result["index"], result["phase"]):
                    raise AssertionError("Job/result mapping changed")
                observations.append(
                    {**result, "native_after_yield": native(result["pid"])}
                )
            write(target / f"{phase}-observations.json", observations)
            if sorted(r["index"] for r in observations) != list(range(64)):
                raise AssertionError(
                    "Synthetic complete sequence lost or duplicated jobs"
                )
            if any(not r["native"] or r["native_after_yield"] for r in observations):
                raise AssertionError("Worker still exists when its result is exposed")
            if len({r["pid"] for r in observations}) != 64:
                raise AssertionError("Native worker process was reused across jobs")
            if any(r["retained_bytes"] != 4 * 1024**2 for r in observations):
                raise AssertionError("Touched native pages carried over between jobs")
            phases[phase] = {"pass": True, "jobs": 64}
        if list(run_partition_jobs(retaining_job, [], workers)):
            raise AssertionError("Empty job sequence produced a result")
        odd = [{"root": str(target), "phase": "odd", "index": i} for i in range(5)]
        if sorted(
            j["index"] for j, _ in run_partition_jobs(retaining_job, odd, workers)
        ) != list(range(5)):
            raise AssertionError("Uneven sequence lost jobs")
        results[str(workers)] = phases
        lock_case(root / f"lock-{workers}", workers)

    for mode in ("exception", "abrupt_exit"):
        target = root / mode
        target.mkdir()
        jobs = [{"root": str(target), "index": i, "mode": mode} for i in range(9)]
        try:
            list(run_partition_jobs(failing_job, jobs, 2))
        except Exception as error:
            started = [json.loads(p.read_text()) for p in target.glob("started-*.json")]
            if not started or len(started) > 2:
                raise AssertionError(
                    "Worker failure scheduled replacement jobs"
                ) from error
            if any(native(r["pid"]) for r in started):
                raise AssertionError("Worker failure left a child alive") from error
            write(
                target / "result.json",
                {"pass": True, "error": repr(error), "started": started},
            )
        else:
            raise AssertionError("Worker failure did not propagate")

    target = root / "iterator-close"
    target.mkdir()
    jobs = [{"root": str(target), "phase": "close", "index": i} for i in range(9)]
    iterator = run_partition_jobs(retaining_job, jobs, 2)
    next(iterator)
    iterator.close()
    records = [json.loads(p.read_text()) for p in target.glob("close-*.json")]
    if len(records) != 2 or any(native(r["pid"]) for r in records):
        raise AssertionError(
            "Iterator closure scheduled replacements or leaked workers"
        )
    write(target / "result.json", {"pass": True, "completed_submitted_jobs": records})
    return {"pass": True, "synthetic_only": True, "workers": results}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifact_dir", type=Path)
    parser.add_argument("--lock-controller", action="store_true")
    parser.add_argument("--workers", type=int, choices=(1, 2, 4), default=2)
    parser.add_argument("--require-installed", action="store_true")
    args = parser.parse_args()
    if args.lock_controller:
        lock_controller(args.artifact_dir, args.workers)
        return 0
    from trinetx_preprocessing.combined_preprocessing.builder import (
        require_safe_output_location,
    )
    from trinetx_preprocessing.encounters import return_execution
    from trinetx_preprocessing.encounters.compatibility import no_symlinks

    root = no_symlinks(args.artifact_dir)
    require_safe_output_location(root, artifact_label="synthetic worker lifetime E2E")
    root.mkdir(mode=0o700, parents=True, exist_ok=False)
    result = {"pass": False}
    try:
        if args.require_installed:
            distribution = importlib.metadata.distribution("trinetx_preprocessing")
            direct = distribution.read_text("direct_url.json")
            if direct and json.loads(direct).get("dir_info", {}).get("editable"):
                raise AssertionError("Installed check selected editable package")
            if "site-packages" not in str(Path(return_execution.__file__).resolve()):
                raise AssertionError("Installed check selected checkout source")
        result = run(root)
        return 0
    except BaseException as error:
        result.update(error=f"{type(error).__name__}: {error}")
        raise
    finally:
        write(root / "result.json", result)
        (root / "runner.py").write_bytes(Path(__file__).read_bytes())
        write(
            root / "e2e.json",
            {
                "schema": "trinetx-return-e2e-v1",
                "command": sys.argv,
                "python": sys.version,
                "platform": platform.platform(),
                "packages": {
                    "trinetx-preprocessing": importlib.metadata.version(
                        "trinetx_preprocessing"
                    )
                },
                "script_sha256": digest(Path(__file__)),
                "execution_module_sha256": digest(Path(return_execution.__file__)),
                "status": "passed" if result["pass"] else "failed",
                "exit_status": 0 if result["pass"] else 1,
                "inventory": {
                    str(p.relative_to(root)): {
                        "bytes": p.stat().st_size,
                        "sha256": digest(p),
                    }
                    for p in sorted(root.rglob("*"))
                    if p.is_file()
                },
            },
        )


if __name__ == "__main__":
    raise SystemExit(main())

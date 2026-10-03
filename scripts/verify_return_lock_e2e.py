#!/usr/bin/env python3
"""Verify advisory-lock ownership survives controller death with an active worker."""

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


def held_job(job):
    root = Path(job["root"])
    (root / "worker-started").write_text(str(os.getpid()))
    deadline = time.monotonic() + 15
    while not (root / "finish-worker").exists():
        if time.monotonic() > deadline:
            raise TimeoutError("Lock fixture worker deadline")
        time.sleep(0.05)
    return {"pass": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifact_dir", type=Path)
    parser.add_argument("--controller", action="store_true")
    args = parser.parse_args()
    root = args.artifact_dir
    if args.controller:
        from trinetx_preprocessing.encounters.return_execution import (
            run_partition_jobs,
            set_execution_lock_descriptor,
        )

        with (root / "execution.lock").open("a+") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            set_execution_lock_descriptor(lock.fileno())
            list(run_partition_jobs(held_job, [{"root": str(root)}], 2))
        return 0
    root.mkdir(mode=0o700, parents=True, exist_ok=False)
    command = [sys.executable, str(Path(__file__).resolve()), str(root), "--controller"]
    with (root / "controller.log").open("w") as log:
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            text=True,
        )
        result = {"command": command, "controller_pid": process.pid, "pass": False}
        try:
            deadline = time.monotonic() + 20
            while not (root / "worker-started").exists():
                if process.poll() is not None:
                    raise AssertionError("Controller exited before worker")
                if time.monotonic() > deadline:
                    raise TimeoutError("Worker startup deadline")
                time.sleep(0.05)
            process.terminate()
            process.wait(timeout=5)
            with (root / "execution.lock").open("a+") as probe:
                try:
                    fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    result["second_owner_rejected_while_worker_active"] = True
                else:
                    raise AssertionError(
                        "Controller death released the active worker lock"
                    )
                (root / "finish-worker").write_text("finish\n")
                deadline = time.monotonic() + 10
                while True:
                    try:
                        fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        break
                    except BlockingIOError:
                        if time.monotonic() > deadline:
                            raise TimeoutError("Worker did not release lock")
                        time.sleep(0.05)
                result.update(pass_after_worker_exit=True, **{"pass": True})
        finally:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            if process.poll() is None:
                process.wait(timeout=5)
            try:
                stdout, _ = process.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                # Only this fixture's owned process group; orphaned Python
                # resource trackers may ignore SIGTERM and keep stdout open.
                os.killpg(process.pid, signal.SIGKILL)
                stdout, _ = process.communicate(timeout=5)
            log.write(stdout)
            log.flush()
            os.fsync(log.fileno())
            (root / "result.json").write_text(json.dumps(result, indent=2) + "\n")
            (root / "runner.py").write_bytes(Path(__file__).read_bytes())
            receipt = {
                "schema": "trinetx-return-e2e-v1",
                "command": sys.argv,
                "python": sys.version,
                "platform": platform.platform(),
                "packages": {
                    "trinetx-preprocessing": importlib.metadata.version(
                        "trinetx-preprocessing"
                    )
                },
                "script_sha256": hashlib.sha256(
                    Path(__file__).read_bytes()
                ).hexdigest(),
                "status": "passed" if result["pass"] else "failed",
                "exit_status": 0 if result["pass"] else 1,
                "inventory": {
                    p.name: {
                        "bytes": p.stat().st_size,
                        "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
                    }
                    for p in sorted(root.iterdir())
                    if p.is_file()
                },
            }
            (root / "e2e.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

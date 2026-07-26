"""Write aggregate status snapshots for a running combined preprocessing build."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path

from trinetx_preprocessing.combined_preprocessing.scratch import (
    COMBINED_BUILD_PREFIX,
)
from trinetx_preprocessing.config import load_config
from trinetx_preprocessing.filesystem import write_text_atomic
from trinetx_preprocessing.work_manifest import work_manifest_path

MONITOR_SCHEMA_VERSION = 2


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pid", type=int, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--log", type=Path)
    parser.add_argument(
        "--result",
        type=Path,
        help="Benchmark/result JSON whose terminal status determines build success.",
    )
    parser.add_argument("--interval-seconds", type=float, default=60.0)
    parser.add_argument("--footprint-interval-seconds", type=float, default=900.0)
    parser.add_argument("--once", action="store_true")
    arguments = parser.parse_args()
    if arguments.interval_seconds <= 0:
        parser.error("--interval-seconds must be positive")

    config = load_config(arguments.config)
    started = time.monotonic()
    last_footprint = float("-inf")
    footprints: dict[str, int | None] = {}
    trusted_result_pid: int | None = None
    while True:
        process = _process_status(arguments.pid)
        elapsed = time.monotonic() - started
        if elapsed - last_footprint >= arguments.footprint_interval_seconds:
            footprints = {
                "work": _directory_size(config.work_dir),
                "output": _directory_size(config.output_dir),
                "staging": sum(
                    _directory_size(path) or 0
                    for path in config.output_dir.parent.glob(
                        f"{COMBINED_BUILD_PREFIX}*"
                    )
                    if path.is_dir()
                ),
            }
            last_footprint = elapsed
        usage = shutil.disk_usage(config.output_dir.parent)
        payload = {
            "schema_version": MONITOR_SCHEMA_VERSION,
            "observed_at": datetime.now(UTC).isoformat(),
            "elapsed_seconds": round(elapsed, 3),
            "process": process,
            "work_manifest": _manifest_status(work_manifest_path(config)),
            "disk_free_bytes": usage.free,
            "footprint_bytes": footprints,
            "log": _file_status(arguments.log),
            "build_result": _result_status(arguments.result),
        }
        result_pid = payload["build_result"].get("pid")
        process_family = {
            arguments.pid,
            *(
                int(value)
                for value in process.get("worker_pids", [])
                if isinstance(value, int)
            ),
        }
        if (
            bool(process.get("running"))
            and isinstance(result_pid, int)
            and result_pid in process_family
        ):
            trusted_result_pid = result_pid
        payload["trusted_result_pid"] = trusted_result_pid
        write_text_atomic(
            arguments.out,
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
        )
        exit_code = _monitor_exit_code(
            once=arguments.once,
            process=process,
            build_result=payload["build_result"],
            trusted_result_pid=trusted_result_pid,
        )
        if exit_code is not None:
            return exit_code
        time.sleep(arguments.interval_seconds)


def _process_status(pid: int) -> dict[str, object]:
    completed = subprocess.run(
        ["ps", "-axo", "pid=,ppid=,etime=,rss=,%cpu=,state="],
        capture_output=True,
        text=True,
        check=False,
    )
    records: dict[int, tuple[int, str, int, float, str]] = {}
    for line in completed.stdout.splitlines():
        fields = line.split(None, 5)
        if len(fields) != 6:
            continue
        process_id, parent_id = int(fields[0]), int(fields[1])
        records[process_id] = (
            parent_id,
            fields[2],
            int(fields[3]),
            float(fields[4]),
            fields[5],
        )
    root = records.get(pid)
    if root is None:
        return {"pid": pid, "running": False, "exit_observed": False}
    descendants: set[int] = set()
    frontier = {pid}
    while frontier:
        children = {
            process_id
            for process_id, record in records.items()
            if record[0] in frontier and process_id not in descendants
        }
        descendants.update(children)
        frontier = children
    process_ids = {pid, *descendants}
    return {
        "pid": pid,
        "running": True,
        "exit_observed": False,
        "elapsed": root[1],
        "rss_bytes": sum(records[item][2] for item in process_ids) * 1024,
        "cpu_percent": round(sum(records[item][3] for item in process_ids), 1),
        "state": root[4],
        "worker_pids": sorted(descendants),
    }


def _manifest_status(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text())
    except (OSError, ValueError):
        return {"available": False, "path": str(path)}
    stages = payload.get("stages", {})
    return {
        "available": True,
        "path": str(path),
        "updated_at": payload.get("updated_at"),
        "stages": {
            name: record.get("status")
            for name, record in stages.items()
            if isinstance(record, dict)
        },
    }


def _directory_size(path: Path) -> int | None:
    if not path.exists():
        return 0
    completed = subprocess.run(
        ["du", "-sk", str(path)],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0 or not completed.stdout.strip():
        return None
    return int(completed.stdout.split()[0]) * 1024


def _file_status(path: Path | None) -> dict[str, object] | None:
    if path is None:
        return None
    try:
        stat = path.stat()
    except FileNotFoundError:
        return {"path": str(path), "exists": False}
    return {
        "path": str(path),
        "exists": True,
        "size_bytes": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
    }


def _result_status(path: Path | None) -> dict[str, object]:
    if path is None:
        return {"available": False, "path": None, "status": None}
    try:
        payload = json.loads(path.read_text())
    except FileNotFoundError:
        return {"available": False, "path": str(path), "status": None}
    except (OSError, json.JSONDecodeError) as exc:
        return {
            "available": False,
            "path": str(path),
            "status": None,
            "error": str(exc),
        }
    status = payload.get("status") if isinstance(payload, dict) else None
    result_pid = payload.get("pid") if isinstance(payload, dict) else None
    return {
        "available": isinstance(payload, dict),
        "path": str(path),
        "status": status,
        "pid": (
            result_pid
            if isinstance(result_pid, int) and not isinstance(result_pid, bool)
            else None
        ),
    }


def _monitor_exit_code(
    *,
    once: bool,
    process: dict[str, object],
    build_result: object,
    trusted_result_pid: int | None = None,
) -> int | None:
    """Return a terminal watcher code, or ``None`` while monitoring continues."""

    if once:
        return 0
    result_status = (
        build_result.get("status") if isinstance(build_result, dict) else None
    )
    result_pid = build_result.get("pid") if isinstance(build_result, dict) else None
    trusted_result = trusted_result_pid is not None and result_pid == trusted_result_pid
    if trusted_result and result_status == "failed":
        return 1
    if bool(process.get("running")):
        return None
    return 0 if trusted_result and result_status == "complete" else 1


if __name__ == "__main__":
    raise SystemExit(main())

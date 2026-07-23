"""Write aggregate status snapshots for a running combined preprocessing build."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path

from trinetx_preprocessing.config import load_config
from trinetx_preprocessing.filesystem import write_text_atomic
from trinetx_preprocessing.work_manifest import work_manifest_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pid", type=int, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--log", type=Path)
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
                        f".{config.output_dir.name}.combined-build-*"
                    )
                ),
            }
            last_footprint = elapsed
        usage = shutil.disk_usage(config.output_dir.parent)
        payload = {
            "schema_version": 1,
            "observed_at": datetime.now(UTC).isoformat(),
            "elapsed_seconds": round(elapsed, 3),
            "process": process,
            "work_manifest": _manifest_status(work_manifest_path(config)),
            "disk_free_bytes": usage.free,
            "footprint_bytes": footprints,
            "log": _file_status(arguments.log),
        }
        write_text_atomic(
            arguments.out,
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
        )
        if arguments.once or not process["running"]:
            return 0 if process["exit_observed"] else 1
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
        return {"pid": pid, "running": False, "exit_observed": True}
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


if __name__ == "__main__":
    raise SystemExit(main())

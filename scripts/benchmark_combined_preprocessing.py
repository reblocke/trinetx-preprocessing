"""Run and summarize one combined preprocessing build."""

from __future__ import annotations

import argparse
import json
import os
import resource
import subprocess
import sys
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

from trinetx_preprocessing.combined_preprocessing.builder import build_preprocessed
from trinetx_preprocessing.combined_preprocessing.evidence import write_evidence
from trinetx_preprocessing.config import load_config, validate_config

BENCHMARK_SCHEMA_VERSION = 2


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--replace", action="store_true")
    parser.add_argument("--rss-interval-seconds", type=float, default=1.0)
    args = parser.parse_args()
    if args.rss_interval_seconds <= 0:
        parser.error("--rss-interval-seconds must be positive")

    config = load_config(args.config)
    validate_config(config)
    started_at = datetime.now(UTC)
    started = time.perf_counter()
    phase_timings: dict[str, float] = {}
    process_id = os.getpid()
    write_evidence(
        args.out,
        {
            "schema_version": BENCHMARK_SCHEMA_VERSION,
            "status": "running",
            "pid": process_id,
            "started_at": started_at.isoformat(),
        },
    )
    sampler = _ProcessFamilyPeakSampler(
        process_id,
        interval_seconds=args.rss_interval_seconds,
    )
    try:
        with sampler:
            result = build_preprocessed(
                config,
                strict=args.strict,
                replace_existing=args.replace,
                timings=phase_timings,
            )
    except Exception as exc:
        payload = {
            "schema_version": BENCHMARK_SCHEMA_VERSION,
            "status": "failed",
            "pid": process_id,
            "started_at": started_at.isoformat(),
            "ended_at": datetime.now(UTC).isoformat(),
            "wall_seconds": round(time.perf_counter() - started, 3),
            "error_type": type(exc).__name__,
            "error": str(exc),
            **sampler.evidence(),
            "phase_timings_seconds": phase_timings,
        }
        write_evidence(args.out, payload)
        raise

    payload = {
        "schema_version": BENCHMARK_SCHEMA_VERSION,
        "status": "complete",
        "pid": process_id,
        "started_at": started_at.isoformat(),
        "ended_at": datetime.now(UTC).isoformat(),
        "wall_seconds": round(time.perf_counter() - started, 3),
        **sampler.evidence(),
        "run_id": result.run_id,
        "database_size_bytes": result.database_path.stat().st_size,
        "compatibility_file_count": len(result.compatibility_paths),
        "work_footprint_bytes": _directory_size(config.work_dir),
        "output_footprint_bytes": _directory_size(config.output_dir),
        "validation_counts": result.validation.counts,
        "validation_warnings": list(result.validation.warnings),
        "phase_timings_seconds": {
            key: round(value, 3) for key, value in phase_timings.items()
        },
    }
    write_evidence(args.out, payload)
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


def _directory_size(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def _resource_peak_rss_bytes() -> int:
    value = max(
        resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss,
    )
    return int(value if sys.platform == "darwin" else value * 1024)


def _process_family_rss_bytes(root_pid: int) -> int:
    completed = subprocess.run(
        ["ps", "-axo", "pid=,ppid=,rss="],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        return 0
    records: dict[int, tuple[int, int]] = {}
    for line in completed.stdout.splitlines():
        fields = line.split()
        if len(fields) != 3:
            continue
        try:
            process_id, parent_id, rss_kib = (int(value) for value in fields)
        except ValueError:
            continue
        records[process_id] = (parent_id, rss_kib)
    if root_pid not in records:
        return 0
    family = {root_pid}
    frontier = {root_pid}
    while frontier:
        children = {
            process_id
            for process_id, (parent_id, _) in records.items()
            if parent_id in frontier and process_id not in family
        }
        family.update(children)
        frontier = children
    return sum(records[process_id][1] for process_id in family) * 1024


class _ProcessFamilyPeakSampler:
    """Sample concurrent root-plus-descendant RSS for the benchmark lifetime."""

    def __init__(self, root_pid: int, *, interval_seconds: float) -> None:
        self.root_pid = root_pid
        self.interval_seconds = interval_seconds
        self.sampled_peak_rss_bytes = 0
        self.resource_peak_rss_bytes = 0
        self.sample_count = 0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def __enter__(self) -> "_ProcessFamilyPeakSampler":
        self._sample()
        self._thread = threading.Thread(
            target=self._run,
            name="combined-rss-sampler",
            daemon=True,
        )
        self._thread.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=max(self.interval_seconds * 2, 1.0))
        self._sample()
        self.resource_peak_rss_bytes = _resource_peak_rss_bytes()

    def evidence(self) -> dict[str, object]:
        peak_rss_bytes = max(
            self.sampled_peak_rss_bytes,
            self.resource_peak_rss_bytes,
        )
        return {
            "peak_rss_bytes": peak_rss_bytes,
            "peak_rss_mb": round(peak_rss_bytes / (1024 * 1024), 3),
            "peak_rss_method": (
                "max_of_sampled_concurrent_process_family_sum_and_resource_floor"
            ),
            "sampled_process_family_peak_rss_bytes": self.sampled_peak_rss_bytes,
            "resource_peak_rss_bytes": self.resource_peak_rss_bytes,
            "rss_sample_interval_seconds": self.interval_seconds,
            "rss_sample_count": self.sample_count,
        }

    def _run(self) -> None:
        while not self._stop.wait(self.interval_seconds):
            self._sample()

    def _sample(self) -> None:
        rss_bytes = _process_family_rss_bytes(self.root_pid)
        self.sampled_peak_rss_bytes = max(
            self.sampled_peak_rss_bytes,
            rss_bytes,
        )
        self.sample_count += 1


if __name__ == "__main__":
    raise SystemExit(main())

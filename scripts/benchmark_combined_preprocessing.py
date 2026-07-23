"""Run and summarize one combined preprocessing build."""

from __future__ import annotations

import argparse
import json
import resource
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from trinetx_preprocessing.combined_preprocessing.builder import build_preprocessed
from trinetx_preprocessing.combined_preprocessing.evidence import write_evidence
from trinetx_preprocessing.config import load_config, validate_config


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--replace", action="store_true")
    args = parser.parse_args()

    config = load_config(args.config)
    validate_config(config)
    started_at = datetime.now(UTC)
    started = time.perf_counter()
    phase_timings: dict[str, float] = {}
    try:
        result = build_preprocessed(
            config,
            strict=args.strict,
            replace_existing=args.replace,
            timings=phase_timings,
        )
    except Exception as exc:
        payload = {
            "schema_version": 1,
            "status": "failed",
            "started_at": started_at.isoformat(),
            "ended_at": datetime.now(UTC).isoformat(),
            "wall_seconds": round(time.perf_counter() - started, 3),
            "error_type": type(exc).__name__,
            "error": str(exc),
            "peak_rss_mb": _peak_rss_mb(),
            "phase_timings_seconds": phase_timings,
        }
        write_evidence(args.out, payload)
        raise

    payload = {
        "schema_version": 1,
        "status": "complete",
        "started_at": started_at.isoformat(),
        "ended_at": datetime.now(UTC).isoformat(),
        "wall_seconds": round(time.perf_counter() - started, 3),
        "peak_rss_mb": _peak_rss_mb(),
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


def _peak_rss_mb() -> float:
    value = max(
        resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss,
    )
    divisor = 1024 * 1024 if sys.platform == "darwin" else 1024
    return round(value / divisor, 3)


if __name__ == "__main__":
    raise SystemExit(main())

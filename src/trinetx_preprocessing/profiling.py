"""Profiling helpers for the preprocessing pipeline."""

from __future__ import annotations

import cProfile
import json
import logging
import pstats
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .config import Config


@dataclass
class StageTimer:
    """Context manager for timing pipeline stages."""

    name: str
    timings: dict[str, float] | None = None
    logger: logging.Logger | None = None
    time_fn: Callable[[], float] = time.perf_counter
    elapsed: float | None = None

    def __enter__(self) -> "StageTimer":
        self._start = self.time_fn()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        end = self.time_fn()
        self.elapsed = end - self._start
        if self.timings is not None:
            self.timings[self.name] = self.elapsed
        if self.logger is not None:
            self.logger.info("Stage %s completed in %.2fs", self.name, self.elapsed)


def run_profile(config: Config, out_dir: Path, *, strict: bool = False) -> list[Path]:
    """Run the pipeline under cProfile and write profiling artifacts."""

    logger = logging.getLogger(__name__)
    out_dir.mkdir(parents=True, exist_ok=True)

    timings: dict[str, float] = {}
    profiler = cProfile.Profile()
    started_at = datetime.now(timezone.utc)

    profiler.enable()
    try:
        from .pipeline.run import run_pipeline

        output_paths = run_pipeline(config, timings=timings, strict=strict)
    finally:
        profiler.disable()

    ended_at = datetime.now(timezone.utc)

    stats_path = out_dir / "profile.pstats"
    profiler.dump_stats(stats_path)
    _write_profile_report(profiler, out_dir / "profile.txt")
    provenance_path = write_provenance(
        out_dir,
        stage_timings=timings,
        started_at=started_at,
        ended_at=ended_at,
    )

    logger.info("Profile stats written to %s", stats_path)
    logger.info("Stage timings written to %s", provenance_path)
    return output_paths


def write_provenance(
    out_dir: Path,
    *,
    stage_timings: dict[str, float],
    started_at: datetime,
    ended_at: datetime,
) -> Path:
    """Write profiling provenance including stage timings."""

    normalized_timings = {
        name: round(seconds, 3) for name, seconds in sorted(stage_timings.items())
    }
    payload = {
        "started_at": started_at.isoformat(),
        "ended_at": ended_at.isoformat(),
        "total_seconds": round((ended_at - started_at).total_seconds(), 3),
        "stage_timings_seconds": normalized_timings,
    }
    out_path = out_dir / "provenance.json"
    out_path.write_text(json.dumps(payload, indent=2, sort_keys=True))
    return out_path


def _write_profile_report(profile: cProfile.Profile, path: Path) -> None:
    with path.open("w", encoding="utf-8") as handle:
        stats = pstats.Stats(profile, stream=handle)
        stats.sort_stats("cumulative")
        stats.print_stats(40)

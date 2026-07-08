"""Profiling helpers for the preprocessing pipeline."""

from __future__ import annotations

import cProfile
import hashlib
import json
import logging
import os
import pstats
import resource
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from . import __version__
from .config import Config
from .filesystem import write_text_atomic

GIT_CODE_STATE_PATHS = ("src", "pyproject.toml", "uv.lock")


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


def run_profile(
    config: Config,
    out_dir: Path,
    *,
    strict: bool = False,
    config_path: Path | None = None,
) -> list[Path]:
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
        config=config,
        output_paths=output_paths,
        stage_timings=timings,
        started_at=started_at,
        ended_at=ended_at,
        config_path=config_path,
        strict=strict,
    )

    logger.info("Profile stats written to %s", stats_path)
    logger.info("Stage timings written to %s", provenance_path)
    return output_paths


def write_provenance(
    out_dir: Path,
    *,
    config: Config,
    output_paths: list[Path],
    stage_timings: dict[str, float],
    started_at: datetime,
    ended_at: datetime,
    config_path: Path | None = None,
    strict: bool = False,
) -> Path:
    """Write profiling provenance including stage timings."""

    out_dir.mkdir(parents=True, exist_ok=True)
    normalized_timings = {
        name: round(seconds, 3) for name, seconds in sorted(stage_timings.items())
    }
    final_output_paths = _final_output_paths(output_paths, config.output_dir)
    payload = {
        "schema_version": 2,
        "started_at": started_at.isoformat(),
        "ended_at": ended_at.isoformat(),
        "total_seconds": round((ended_at - started_at).total_seconds(), 3),
        "package_version": __version__,
        "python_version": sys.version,
        "git_commit": _git_commit(),
        "git_dirty": _git_dirty(),
        "git_code_dirty": current_git_code_dirty(),
        "git_code_state_sha256": current_git_code_state_sha256(),
        "config_path": _resolved_path(config_path),
        "config_sha256": _file_sha256(config_path),
        "strict": strict,
        "stage_timings_seconds": normalized_timings,
        "generated_file_count": len(output_paths),
        "output_file_count": len(final_output_paths),
        "output_files": _output_file_inventory(final_output_paths),
        "disk_footprint_bytes": {
            "work_dir": _directory_size_bytes(config.work_dir),
            "output_dir": _directory_size_bytes(config.output_dir),
        },
        "peak_rss_mb": _peak_rss_mb(),
    }
    out_path = out_dir / "provenance.json"
    write_text_atomic(out_path, json.dumps(payload, indent=2, sort_keys=True))
    return out_path


def _final_output_paths(paths: list[Path], output_dir: Path) -> list[Path]:
    resolved_output_dir = output_dir.resolve(strict=False)
    return [
        path
        for path in paths
        if path.suffix.lower() == ".csv"
        and path.resolve(strict=False).is_relative_to(resolved_output_dir)
    ]


def _write_profile_report(profile: cProfile.Profile, path: Path) -> None:
    with path.open("w", encoding="utf-8") as handle:
        stats = pstats.Stats(profile, stream=handle)
        stats.sort_stats("cumulative")
        stats.print_stats(40)


def _directory_size_bytes(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def _output_file_inventory(paths: list[Path]) -> list[dict[str, object]]:
    inventory: list[dict[str, object]] = []
    for path in sorted(paths, key=lambda item: str(item)):
        exists = path.exists()
        path_stat = path.stat() if exists else None
        inventory.append(
            {
                "path": str(path.resolve(strict=False)),
                "exists": exists,
                "size_bytes": path_stat.st_size if path_stat is not None else None,
                "mtime_ns": path_stat.st_mtime_ns if path_stat is not None else None,
            }
        )
    return inventory


def _resolved_path(path: Path | None) -> str | None:
    if path is None:
        return None
    return str(path.resolve(strict=False))


def _file_sha256(path: Path | None) -> str | None:
    if path is None or not path.exists():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_commit() -> str | None:
    return _git_output("rev-parse", "HEAD")


def _git_dirty() -> bool | None:
    output = _git_output("status", "--porcelain", "--untracked-files=no")
    if output is None:
        return None
    return bool(output.strip())


def current_git_code_dirty() -> bool | None:
    """Return whether behavior-affecting code paths differ from HEAD."""

    output = _git_output(
        "status",
        "--porcelain",
        "--untracked-files=normal",
        "--",
        *GIT_CODE_STATE_PATHS,
    )
    if output is None:
        return None
    return bool(output.strip())


def current_git_code_state_sha256() -> str | None:
    """Hash current behavior-affecting code files without loading them at once."""

    repo_root = Path(__file__).resolve().parents[2]
    path_output = _git_output(
        "ls-files",
        "-z",
        "--cached",
        "--modified",
        "--deleted",
        "--others",
        "--exclude-standard",
        "--",
        *GIT_CODE_STATE_PATHS,
    )
    if path_output is None:
        return None

    digest = hashlib.sha256()
    relative_paths = sorted({path for path in path_output.split("\0") if path})
    for relative_path in relative_paths:
        path = repo_root / relative_path
        digest.update(b"path\0")
        digest.update(relative_path.encode("utf-8"))
        digest.update(b"\0")
        if path.is_symlink():
            digest.update(b"symlink\0")
            digest.update(os.readlink(path).encode("utf-8"))
            digest.update(b"\0")
        elif path.is_file():
            digest.update(b"file\0")
            with path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
            digest.update(b"\0")
        else:
            digest.update(b"missing\0")
    return digest.hexdigest()


def _git_output(*args: str) -> str | None:
    repo_root = Path(__file__).resolve().parents[2]
    try:
        completed = subprocess.run(
            ["git", "-C", str(repo_root), *args],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout.strip()


def _peak_rss_mb() -> float:
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if sys.platform == "darwin":
        bytes_used = rss
    else:
        bytes_used = rss * 1024
    return round(bytes_used / (1024 * 1024), 3)

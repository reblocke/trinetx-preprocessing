from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path
from types import ModuleType


def _load_script(name: str) -> ModuleType:
    path = Path(__file__).resolve().parents[1] / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"test_{name}", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


benchmark_script = _load_script("benchmark_combined_preprocessing")
monitor_script = _load_script("monitor_combined_preprocessing")


def test_monitor_requires_explicit_terminal_success() -> None:
    running = {"running": True}
    vanished = {"running": False}

    assert (
        monitor_script._monitor_exit_code(
            once=True,
            process=running,
            build_result={"status": None},
        )
        == 0
    )
    assert (
        monitor_script._monitor_exit_code(
            once=False,
            process=running,
            build_result={"status": "running", "pid": 42},
            trusted_result_pid=42,
        )
        is None
    )
    assert (
        monitor_script._monitor_exit_code(
            once=False,
            process=vanished,
            build_result={"status": "running", "pid": 42},
            trusted_result_pid=42,
        )
        == 1
    )
    assert (
        monitor_script._monitor_exit_code(
            once=False,
            process=running,
            build_result={"status": "failed", "pid": 42},
            trusted_result_pid=42,
        )
        == 1
    )
    assert (
        monitor_script._monitor_exit_code(
            once=False,
            process=vanished,
            build_result={"status": "complete", "pid": 42},
            trusted_result_pid=42,
        )
        == 0
    )
    assert (
        monitor_script._monitor_exit_code(
            once=False,
            process=vanished,
            build_result={"status": "complete", "pid": 99},
            trusted_result_pid=42,
        )
        == 1
    )


def test_benchmark_sums_concurrent_process_family_rss(
    monkeypatch,
) -> None:
    ps_output = "\n".join(
        [
            "100 1 100",
            "101 100 200",
            "102 101 300",
            "200 1 999",
        ]
    )

    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(args=args[0], returncode=0, stdout=ps_output)

    monkeypatch.setattr(benchmark_script.subprocess, "run", fake_run)

    assert benchmark_script._process_family_rss_bytes(100) == 600 * 1024


def test_benchmark_reports_sampled_family_and_resource_floor() -> None:
    sampler = benchmark_script._ProcessFamilyPeakSampler(
        100,
        interval_seconds=1.0,
    )
    sampler.sampled_peak_rss_bytes = 600
    sampler.resource_peak_rss_bytes = 500

    evidence = sampler.evidence()

    assert evidence["peak_rss_bytes"] == 600
    assert evidence["sampled_process_family_peak_rss_bytes"] == 600
    assert evidence["resource_peak_rss_bytes"] == 500
    assert "concurrent_process_family_sum" in evidence["peak_rss_method"]

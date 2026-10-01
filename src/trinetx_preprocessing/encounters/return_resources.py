"""Explicit operational limits; these never change scientific acceptance."""

from __future__ import annotations

DEFAULT_POLICY = {
    "policy_version": "1.0",
    "stage_memory_limit_mib": 3072,
    "parent_memory_limit_mib": 4096,
    "global_memory_limit_mib": 3072,
    "worker_memory_limit_mib": 3072,
    "threads": 1,
    "max_workers": 4,
}


def check_settings(memory_limit_mib, threads=1):
    if type(memory_limit_mib) is not int or memory_limit_mib < 1:
        raise ValueError("DuckDB memory limit must be a positive integer MiB")
    if type(threads) is not int or not 1 <= threads <= 2:
        raise ValueError("DuckDB thread count must be one or two")


def resource_policy(value=None):
    if value is None:
        return dict(DEFAULT_POLICY)
    if not isinstance(value, dict) or set(value) != set(DEFAULT_POLICY):
        raise ValueError("Resource policy needs the complete versioned field set")
    policy = dict(value)
    if policy["policy_version"] != "1.0":
        raise ValueError("Unsupported resource policy version")
    for name in ("stage", "parent", "global", "worker"):
        check_settings(policy[f"{name}_memory_limit_mib"], policy["threads"])
        if policy[f"{name}_memory_limit_mib"] > 12288:
            raise ValueError("Resource policy exceeds the selected 12 GiB budget")
    if type(policy["max_workers"]) is not int or policy["max_workers"] not in (1, 2, 4):
        raise ValueError("Unsupported resource-policy worker count")
    if policy["worker_memory_limit_mib"] * policy["max_workers"] > 12288:
        raise ValueError("Concurrent worker memory limits exceed the host budget")
    return policy


def check_workers(policy, workers):
    if (
        type(workers) is not int
        or workers not in (1, 2, 4)
        or workers > policy["max_workers"]
    ):
        raise ValueError("Worker count exceeds the selected resource policy")


def configure_connection(
    db, *, memory_limit_mib, threads=1, events=None, phase="resources"
):
    check_settings(memory_limit_mib, threads)
    db.execute(f"SET memory_limit='{memory_limit_mib}MiB'")
    db.execute(f"SET threads={threads}")
    effective = {
        "requested_memory_limit_mib": memory_limit_mib,
        "requested_threads": threads,
        "effective_memory_limit": db.execute(
            "SELECT current_setting('memory_limit')"
        ).fetchone()[0],
        "effective_threads": db.execute("SELECT current_setting('threads')").fetchone()[
            0
        ],
    }
    if events:
        events.emit(phase, "resource_settings", **effective)
    return effective

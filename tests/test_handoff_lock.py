"""The handoff lock must survive exec and prevent a second command from running."""

import subprocess
import sys
import time
from pathlib import Path

import pytest


@pytest.mark.skipif(
    sys.platform == "win32", reason="Mini launcher uses POSIX advisory locks"
)
def test_lock_survives_exec_rejects_duplicate_and_releases(tmp_path):
    tool = Path(__file__).resolve().parents[1] / "scripts" / "with_execution_lock.py"
    lock = tmp_path / "execution.lock"
    ready = tmp_path / "ready"
    duplicate = tmp_path / "duplicate"
    child = subprocess.Popen(
        [
            sys.executable,
            str(tool),
            str(lock),
            "--",
            sys.executable,
            "-c",
            "import pathlib,sys,time; "
            "pathlib.Path(sys.argv[1]).touch(); time.sleep(30)",
            str(ready),
        ]
    )
    try:
        deadline = time.monotonic() + 5
        while (
            not ready.exists() and time.monotonic() < deadline and child.poll() is None
        ):
            time.sleep(0.02)
        assert ready.exists(), "locked command did not start"
        second = subprocess.run(
            [
                sys.executable,
                str(tool),
                str(lock),
                "--",
                sys.executable,
                "-c",
                "import pathlib,sys; pathlib.Path(sys.argv[1]).touch()",
                str(duplicate),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        assert second.returncode == 75
        assert not duplicate.exists()
    finally:
        child.terminate()
        child.wait(timeout=5)
    released = subprocess.run(
        [sys.executable, str(tool), "--check", str(lock)], check=False
    )
    assert released.returncode == 0
    assert lock.exists(), "lock inode must remain stable between executions"


@pytest.mark.skipif(sys.platform == "win32", reason="Mini launcher uses POSIX shells")
def test_launcher_holds_controller_lock_through_shells(tmp_path):
    repo = Path(__file__).resolve().parents[1]
    wrapper = repo / "scripts" / "start_encounter_handoff.sh"
    (tmp_path / "LOCAL_PATHS.md").write_text("Synthetic operator paths only\n")
    (tmp_path / "start-on-mini.sh").write_text("#!/bin/bash\nexec /bin/sleep 30\n")
    first = subprocess.Popen(
        ["bash", str(wrapper), str(tmp_path)], stdout=subprocess.DEVNULL
    )
    try:
        deadline = time.monotonic() + 5
        while not (tmp_path / "NEXT_STEPS.md").exists() and time.monotonic() < deadline:
            assert first.poll() is None
            time.sleep(0.02)
        assert (tmp_path / "NEXT_STEPS.md").read_text() == (
            repo / "NEXT_STEPS.md"
        ).read_text()
        second = subprocess.run(
            ["bash", str(wrapper), str(tmp_path)], capture_output=True, check=False
        )
        assert second.returncode == 75
    finally:
        first.terminate()
        first.wait(timeout=5)

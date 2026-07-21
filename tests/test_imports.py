from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import trinetx_preprocessing

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"


def test_package_imports() -> None:
    assert trinetx_preprocessing.__version__


def test_module_help() -> None:
    env = os.environ.copy()
    pythonpath_entries = [str(SRC)]
    existing = env.get("PYTHONPATH")
    if existing:
        pythonpath_entries.append(existing)
    env["PYTHONPATH"] = os.pathsep.join(pythonpath_entries)

    result = subprocess.run(
        [sys.executable, "-m", "trinetx_preprocessing", "--help"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    output = (result.stdout or "") + (result.stderr or "")
    assert result.returncode == 0, output
    assert "TriNetX preprocessing" in output
    assert "validate-config" in output

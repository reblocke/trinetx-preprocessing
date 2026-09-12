from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "run_glp1_source_acceptance.py"


def _module():
    spec = importlib.util.spec_from_file_location("acceptance_launcher", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_dry_run_lists_all_private_acceptance_gates(tmp_path: Path, capsys) -> None:
    module = _module()
    result = module.main(
        [
            "--database", str(tmp_path / "canonical.duckdb"),
            "--compatibility-output", str(tmp_path / "compatibility"),
            "--raw-input", str(tmp_path / "raw"),
            "--raw-output", str(tmp_path / "raw-output"),
            "--canonical-output", str(tmp_path / "canonical-output"),
            "--config", str(tmp_path / "config.yml"),
            "--receipt-dir", str(tmp_path / "receipts"),
            "--dry-run",
        ]
    )
    output = capsys.readouterr().out
    assert result == 0
    assert "validate-preprocessed" in output
    assert "--raw-reference" in output
    assert "compare-reference-outputs" in output
    assert not (tmp_path / "receipts").exists()

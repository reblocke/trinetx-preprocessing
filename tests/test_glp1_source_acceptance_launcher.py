from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "run_glp1_source_acceptance.py"


def _module():
    spec = importlib.util.spec_from_file_location("acceptance_launcher", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_dry_run_lists_targeted_scientific_equivalence_gates(
    tmp_path: Path, capsys
) -> None:
    module = _module()
    result = module.main(
        [
            "--database", str(tmp_path / "canonical.duckdb"),
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
    assert "--raw-reference" in output
    assert "compare-reference-outputs" in output
    assert "validate-preprocessed" not in output
    assert "verify_combined_parity.py" not in output
    assert not (tmp_path / "receipts").exists()


def test_successful_run_writes_a_targeted_scope_receipt(
    tmp_path: Path, monkeypatch
) -> None:
    module = _module()

    def completed(*_args, **_kwargs):
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr(module.subprocess, "run", completed)
    receipt_dir = tmp_path / "receipts"
    result = module.main(
        [
            "--database", str(tmp_path / "canonical.duckdb"),
            "--raw-input", str(tmp_path / "raw"),
            "--raw-output", str(tmp_path / "raw-output"),
            "--canonical-output", str(tmp_path / "canonical-output"),
            "--config", str(tmp_path / "config.yml"),
            "--receipt-dir", str(receipt_dir),
        ]
    )

    assert result == 0
    receipt = json.loads((receipt_dir / "acceptance_complete.json").read_text())
    assert receipt["scope"] == "glp1_raw_vs_canonical_database_parity"
    assert receipt["out_of_scope"] == [
        "36-file compatibility certification",
        "all-source retained-record membership audit",
    ]
    assert len(list(receipt_dir.glob("*_receipt.json"))) == 3

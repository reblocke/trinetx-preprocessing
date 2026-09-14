"""Scientific routing and exact comparisons must fail closed on regressions."""

from __future__ import annotations

import json
from pathlib import Path

import duckdb
import pytest

from trinetx_preprocessing.glp1_eligibility.parity import _difference_counts
from trinetx_preprocessing.verification.cli import decision_valid
from trinetx_preprocessing.verification.policy import POLICY, classify, code_fingerprint


@pytest.mark.parametrize(
    ("path", "gate"),
    [
        ("README.md", "static"),
        ("src/trinetx_preprocessing/glp1_eligibility/parity.py", "static"),
        ("src/trinetx_preprocessing/glp1_eligibility/ingestion.py", "workflow"),
        (
            "src/trinetx_preprocessing/combined_preprocessing/glp1_adapter.py",
            "workflow",
        ),
        ("src/trinetx_preprocessing/pipeline/diagnosis_stage.py", "materialization"),
        ("uv.lock", "materialization"),
        ("config/concept_sets/diagnoses.csv", "scientific"),
        ("config/glp1_eligibility.yml", "scientific"),
        ("src/trinetx_preprocessing/glp1_eligibility/cohort.py", "scientific"),
        ("brand_new/unclassified.py", "materialization"),
    ],
)
def test_routes(path, gate):
    result = classify([path], json.loads(POLICY.read_text()))
    assert result["gate"] == gate


def test_shared_change_requires_all_products():
    result = classify(
        ["src/trinetx_preprocessing/pipeline/labs_stage.py"],
        json.loads(POLICY.read_text()),
    )
    assert set(result["products"]) == {"canonical", "compatibility36", "glp1"}


@pytest.mark.parametrize(
    "right,expected",
    [
        ("VALUES (1),(1),(NULL)", {"left_only": 0, "right_only": 0}),
        ("VALUES (1),(NULL)", {"left_only": 1, "right_only": 0}),
        ("VALUES (1),(1),(2)", {"left_only": 1, "right_only": 1}),
        ("VALUES (1),(1),(NULL),(NULL)", {"left_only": 0, "right_only": 1}),
    ],
)
def test_exact_multiset_difference(right, expected):
    with duckdb.connect() as con:
        assert _difference_counts(con, "VALUES (1),(1),(NULL)", right) == expected


def test_decision_requires_revision_binding_and_human_reference():
    plan = {"base": "a", "head": "b"}
    decision = {
        **plan,
        "status": "approved",
        "approved_by": "researcher",
        "decision_reference": "DECISIONS.md#example",
        "expected_drift": "Unit correction",
    }
    assert decision_valid(decision, plan)
    assert not decision_valid({**decision, "head": "old"}, plan)
    assert not decision_valid({**decision, "approved_by": ""}, plan)


def test_historical_fingerprint_is_not_a_commit_label(tmp_path: Path):
    import subprocess

    def git(*args):
        return subprocess.check_output(["git", "-C", str(tmp_path), *args])

    git("init", "-q")
    git("config", "user.email", "fixture@example.test")
    git("config", "user.name", "Fixture")
    (tmp_path / "src").mkdir()
    (tmp_path / "src/a.py").write_text("a=1\n")
    git("add", ".")
    git("commit", "-qm", "first")
    first = code_fingerprint("HEAD", root=tmp_path)
    (tmp_path / "README.md").write_text("Documentation\n")
    git("add", ".")
    git("commit", "-qm", "docs")
    assert code_fingerprint("HEAD", root=tmp_path) == first
    (tmp_path / "src/a.py").write_text("a=2\n")
    git("add", ".")
    git("commit", "-qm", "behavior")
    assert code_fingerprint("HEAD", root=tmp_path) != first


def test_aggregate_drift_preserves_missing_and_added_metrics():
    from trinetx_preprocessing.verification.metrics import drift_report

    assert drift_report({"a": 1, "b": None}, {"a": 2, "c": 0}) == {
        "a": {"before": 1, "after": 2},
        "b": {"before": None, "after": None},
        "c": {"before": None, "after": 0},
    }


def test_staged_candidate_rejects_changed_producer_and_promotes_with_receipt(
    tmp_path: Path, monkeypatch
):
    from test_combined_preprocessing import (
        _copy_glp1_fixture_for_combined,
        _write_combined_config,
    )

    from trinetx_preprocessing.combined_preprocessing import builder
    from trinetx_preprocessing.combined_preprocessing.cohort_source import (
        validate_cohort_source,
    )
    from trinetx_preprocessing.config import load_config
    from trinetx_preprocessing.verification import candidate

    data = _copy_glp1_fixture_for_combined(tmp_path)
    config = load_config(_write_combined_config(tmp_path, data_dir=data))
    original_publish = builder._publish_staged_product

    def stop_before_publish(*args, **kwargs):
        raise RuntimeError("test checkpoint preserved")

    monkeypatch.setattr(builder, "_publish_staged_product", stop_before_publish)
    with pytest.raises(RuntimeError, match="test checkpoint"):
        builder.build_preprocessed(config, strict=True)
    state_path = next(
        config.output_dir.parent.glob(".trinetx-combined-build-*.state.json")
    )
    state = json.loads(state_path.read_text())
    database = Path(state["staging_output"]) / config.combined.database_name
    digest = state["manifest"]["git_code_state_sha256"]
    monkeypatch.setattr(
        candidate, "git", lambda *a, **kw: b"" if a[0] == "status" else b"abc"
    )
    monkeypatch.setattr(candidate, "code_fingerprint", lambda *a, **kw: digest)
    result = candidate.candidate_preflight(database, config, "abc")
    assert result["valid"]
    monkeypatch.setattr(candidate, "code_fingerprint", lambda *a, **kw: "mismatch")
    with pytest.raises(ValueError, match="producer code hash"):
        candidate.candidate_preflight(database, config, "abc")
    monkeypatch.setattr(candidate, "code_fingerprint", lambda *a, **kw: digest)
    sidecar_path = database.parent / "trinetx_preprocessed_manifest.json"
    sidecar_bytes = sidecar_path.read_bytes()
    bad = json.loads(sidecar_bytes)
    bad["database"] = "/incorrect/path"
    sidecar_path.write_text(json.dumps(bad))
    with pytest.raises(ValueError, match="sidecar differs"):
        candidate.candidate_preflight(database, config, "abc")
    sidecar_path.write_bytes(sidecar_bytes)
    monkeypatch.setattr(builder, "_publish_staged_product", original_publish)
    result = candidate.promote_candidate(database, config, "abc")
    assert result["promoted"]
    assert validate_cohort_source(config.output_dir / database.name).valid
    assert not database.exists()


def test_scientific_acceptance_is_bound_to_report_and_never_accepts_failure(
    tmp_path: Path,
):
    from trinetx_preprocessing.verification.cli import accept_drift, write
    from trinetx_preprocessing.verification.policy import sha

    root = tmp_path / "receipts"
    root.mkdir()
    report = {
        "base": "a",
        "head": "b",
        "differences": {"eligible": {"before": 2, "after": 3}},
    }
    receipt = {
        "status": "review_required",
        "plan": {"base": "a", "head": "b"},
        "drift_report_sha256": sha(report),
    }
    write(root / "status.json", receipt)
    write(root / "drift_report.json", report)
    decision = {
        "base": "a",
        "head": "b",
        "status": "approved",
        "approved_by": "Fixture scientist",
        "decision_reference": "fixture decision",
        "expected_drift": "one case",
        "drift_report_sha256": "wrong",
    }
    path = tmp_path / "decision.json"
    write(path, decision)
    with pytest.raises(ValueError, match="exact drift report"):
        accept_drift(root, path)
    assert not (root / "acceptance_complete.json").exists()
    decision["drift_report_sha256"] = sha(report)
    write(path, decision)
    assert accept_drift(root, path) == 0
    receipt["status"] = "failed"
    write(root / "status.json", receipt)
    with pytest.raises(ValueError, match="awaiting scientific review"):
        accept_drift(root, path)


@pytest.fixture(scope="module")
def reference_output(tmp_path_factory):
    from trinetx_preprocessing.glp1_eligibility.builder import build_glp1_eligibility

    root = Path(__file__).resolve().parents[1]
    output = tmp_path_factory.mktemp("glp-parity-reference") / "output"
    build_glp1_eligibility(
        input_root=root / "tests/fixtures/glp1_synthetic",
        output_dir=output,
        config_path=root / "config/glp1_eligibility.yml",
    )
    return output


@pytest.mark.parametrize(
    "mutation", ["row", "duplicate", "null", "schema", "index", "parquet"]
)
def test_comparator_detects_scientific_and_serialization_changes(
    reference_output, tmp_path: Path, mutation
):
    import shutil

    from trinetx_preprocessing.glp1_eligibility.parity import (
        compare_glp1_reference_outputs,
    )

    target = tmp_path / "candidate"
    shutil.copytree(reference_output, target)
    database = target / "glp1_hypercapnia.duckdb"
    with duckdb.connect(str(database)) as con:
        if mutation == "row":
            con.execute(
                "UPDATE analysis_glp1_eligibility SET ind_fda_t2d=NOT ind_fda_t2d"
            )
        elif mutation == "duplicate":
            con.execute(
                "INSERT INTO analysis_glp1_eligibility "
                "SELECT * FROM analysis_glp1_eligibility LIMIT 1"
            )
        elif mutation == "null":
            con.execute("UPDATE analysis_glp1_eligibility SET ind_fda_t2d=NULL")
        elif mutation == "schema":
            con.execute(
                "ALTER TABLE analysis_glp1_eligibility ADD COLUMN drift INTEGER"
            )
        elif mutation == "index":
            con.execute("UPDATE analysis_glp1_eligibility SET index_event_id='wrong'")
        else:
            path = str(target / "analysis_glp1_eligibility.parquet").replace("'", "''")
            con.execute(
                f"COPY (SELECT * FROM analysis_glp1_eligibility LIMIT 1) TO '{path}' "
                "(FORMAT PARQUET)"
            )
    assert not compare_glp1_reference_outputs(reference_output, target).valid


def test_receipt_fingerprint_detects_reassignment_with_unchanged_totals():
    from trinetx_preprocessing.verification.metrics import table_fingerprint

    with duckdb.connect() as con:
        con.execute("CREATE TABLE results (id INTEGER, value INTEGER, run_id VARCHAR)")
        con.execute(
            "INSERT INTO results VALUES (1,10,'one'), (2,20,'one'), (3,NULL,'one')"
        )
        columns = [("id", "INTEGER"), ("value", "INTEGER"), ("run_id", "VARCHAR")]
        initial = table_fingerprint(con, "results", columns)
        con.execute("UPDATE results SET run_id='two'")
        assert table_fingerprint(con, "results", columns) == initial
        con.execute("UPDATE results SET value=30-value WHERE value IS NOT NULL")
        assert table_fingerprint(con, "results", columns) != initial


@pytest.mark.parametrize("parity_passes", [True, False])
def test_run_receipt_and_owned_cleanup(
    reference_output, tmp_path, monkeypatch, parity_passes
):
    import argparse
    import shutil
    from types import SimpleNamespace

    from trinetx_preprocessing.combined_preprocessing import cohort_source
    from trinetx_preprocessing.glp1_eligibility import builder, parity
    from trinetx_preprocessing.verification import cli

    monkeypatch.setattr(
        cli,
        "make_plan",
        lambda *a: {
            "clean": True,
            "head": "abc",
            "base": "def",
            "gate": "static",
            "products": [],
        },
    )
    monkeypatch.setattr(cli, "git", lambda *a: b"abc")
    monkeypatch.setattr(
        cli.subprocess,
        "run",
        lambda *a, **kw: SimpleNamespace(
            returncode=0, stdout="synthetic public check", stderr=""
        ),
    )
    monkeypatch.setattr(
        cohort_source,
        "validate_cohort_source",
        lambda *a: SimpleNamespace(
            valid=True,
            errors=(),
            required_elements=(),
            metadata=SimpleNamespace(to_dict=lambda: {"run_id": "fixture"}),
        ),
    )

    def build(**kwargs):
        shutil.copytree(reference_output, kwargs["output_dir"])
        return SimpleNamespace(
            run_id="fixture", counts=SimpleNamespace(rows=1), warning_count=0
        )

    monkeypatch.setattr(builder, "build_glp1_eligibility", build)
    if not parity_passes:
        monkeypatch.setattr(
            parity,
            "compare_glp1_reference_outputs",
            lambda *a: parity.ParityResult(False, ("fixture mismatch",), ()),
        )
    config = tmp_path / "config.yml"
    config.write_text("synthetic")
    raw = tmp_path / "raw"
    raw.mkdir()
    sentinel = raw / "preserve.txt"
    sentinel.write_text("immutable raw")
    args = argparse.Namespace(
        base="def",
        head="abc",
        decision=None,
        baseline_receipt=None,
        full_glp1=True,
        database=tmp_path / "canonical.duckdb",
        raw_input=raw,
        config=config,
        preprocessing_config=None,
        compatibility_baseline=None,
        receipt_dir=tmp_path / "receipt",
    )
    assert cli.run(args) == (0 if parity_passes else 1)
    receipt = json.loads((args.receipt_dir / "status.json").read_text())
    assert receipt["status"] == ("passed" if parity_passes else "failed")
    assert (args.receipt_dir / ".verification-outputs").exists() != parity_passes
    assert (args.receipt_dir / "acceptance_complete.json").exists() == parity_passes
    assert sentinel.read_text() == "immutable raw"

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from trinetx_preprocessing import cli as cli_module
from trinetx_preprocessing import filesystem
from trinetx_preprocessing.cli import _run_domain_probe_command
from trinetx_preprocessing.config import DomainInspection, load_config
from trinetx_preprocessing.pipeline import final_assembly
from trinetx_preprocessing.profiling import (
    current_git_code_dirty,
    current_git_code_state_sha256,
)
from trinetx_preprocessing.regression import TableHashEntry, write_hash_manifest
from trinetx_preprocessing.storage import write_work_table
from trinetx_preprocessing.work_manifest import (
    FINAL_ASSEMBLY_PREREQUISITES,
    initialize_work_manifest,
    mark_stage_complete,
)

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
FIXTURE_PATH = ROOT / "tests" / "fixtures" / "encounter" / "encounter0001.csv"
LAB_FIXTURE_PATH = ROOT / "tests" / "fixtures" / "labs" / "lab_results0001.csv"
PROFILE_CONFIG_CONTENT = b"data_dir: data\nwork_dir: work\noutput_dir: output\n"
PROFILE_CONFIG_SHA256 = hashlib.sha256(PROFILE_CONFIG_CONTENT).hexdigest()


def _build_env() -> dict[str, str]:
    env = os.environ.copy()
    pythonpath_entries = [str(SRC)]
    existing = env.get("PYTHONPATH")
    if existing:
        pythonpath_entries.append(existing)
    env["PYTHONPATH"] = os.pathsep.join(pythonpath_entries)
    return env


def _write_config(path: Path) -> None:
    content = (
        "data_dir: data\n"
        "work_dir: work\n"
        "output_dir: output\n"
        "domains:\n"
        "  encounter:\n"
        '    pattern: "Encounter/encounter*.csv"\n'
    )
    path.write_text(content)


def test_validate_inputs_accepts_minimal_medication_ingredient_schema(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data"
    medication_dir = data_dir / "Medications"
    medication_dir.mkdir(parents=True)
    ingredient = medication_dir / "medication_ingredient.csv"
    ingredient.write_text(
        "patient_id,code_system,code,start_date\nP1,RXNORM,1991302,2023-01-01\n"
    )
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        f'data_dir: "{data_dir}"\n'
        f'work_dir: "{tmp_path / "work"}"\n'
        f'output_dir: "{tmp_path / "output"}"\n'
        "domains:\n"
        "  meds:\n"
        '    pattern: "Medications/medication*.csv"\n'
    )

    cli_module.validate_input_headers(load_config(config_path))


def test_validate_inputs_rejects_incomplete_medication_ingredient_schema(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data"
    medication_dir = data_dir / "Medications"
    medication_dir.mkdir(parents=True)
    (medication_dir / "medication_ingredient.csv").write_text(
        "patient_id,code_system,code\nP1,RXNORM,1991302\n"
    )
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        f'data_dir: "{data_dir}"\n'
        f'work_dir: "{tmp_path / "work"}"\n'
        f'output_dir: "{tmp_path / "output"}"\n'
        "domains:\n"
        "  meds:\n"
        '    pattern: "Medications/medication*.csv"\n'
    )

    with pytest.raises(cli_module.ConfigError, match="start_date"):
        cli_module.validate_input_headers(load_config(config_path))


def test_run_uses_combined_builder_when_enabled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "data_dir: data\n"
        "work_dir: work\n"
        "output_dir: output\n"
        "combined:\n"
        "  enabled: true\n"
        "domains:\n"
        "  encounter:\n"
        '    pattern: "Encounter/encounter*.csv"\n'
    )
    calls = []

    def fake_build(config, *, strict=False, replace_existing=False):
        calls.append((config.combined.enabled, strict, replace_existing))
        return SimpleNamespace(
            database_path=tmp_path / "trinetx_preprocessed.duckdb",
            compatibility_paths=tuple(
                Path(f"output-{index}.csv") for index in range(36)
            ),
        )

    monkeypatch.setattr(cli_module, "validate_config", lambda config: None)
    monkeypatch.setattr(cli_module, "build_preprocessed", fake_build)
    monkeypatch.setattr(
        cli_module,
        "run_pipeline",
        lambda *args, **kwargs: pytest.fail("legacy pipeline entry point was used"),
    )

    result = cli_module.main(["run", "--config", str(config_path), "--strict"])

    assert result == 0
    assert calls == [(True, True, False)]


def test_build_preprocessed_cli_rejects_path_overlap_during_validation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = tmp_path / "data"
    shared_dir = tmp_path / "shared"
    shared_dir.mkdir()
    _write_encounter_csv(data_dir / "Encounter" / "encounter0001.csv")
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        f'data_dir: "{data_dir}"\n'
        f'work_dir: "{shared_dir}"\n'
        f'output_dir: "{shared_dir}"\n'
        "combined:\n"
        "  enabled: true\n"
        "domains:\n"
        "  encounter:\n"
        '    pattern: "Encounter/encounter*.csv"\n'
    )
    marker = shared_dir / "must-remain.txt"
    marker.write_text("unchanged")

    monkeypatch.setattr(
        cli_module,
        "_require_safe_combined_mutation_locations",
        lambda *args, **kwargs: pytest.fail(
            "mutation-location checks ran after invalid config validation"
        ),
    )
    monkeypatch.setattr(
        cli_module,
        "build_preprocessed",
        lambda *args, **kwargs: pytest.fail("combined builder was called"),
    )

    result = cli_module.main(["build-preprocessed", "--config", str(config_path)])

    assert result == 2
    assert marker.read_text() == "unchanged"


def test_export_legacy_cli_routes_atomic_replacement_flag(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = tmp_path / "product" / "trinetx_preprocessed.duckdb"
    output_dir = tmp_path / "compatibility"
    calls: list[tuple[Path, Path, bool]] = []

    def export(
        database_path: Path,
        destination: Path,
        *,
        replace_existing: bool,
    ) -> tuple[Path, ...]:
        calls.append((database_path, destination, replace_existing))
        return tuple(destination / f"output-{index}.csv" for index in range(36))

    monkeypatch.setattr(
        cli_module,
        "export_legacy_compatibility_outputs",
        export,
    )

    result = cli_module.main(
        [
            "export-legacy",
            "--database",
            str(database),
            "--output-dir",
            str(output_dir),
            "--replace",
        ]
    )

    assert result == 0
    assert calls == [(database, output_dir, True)]


@pytest.mark.parametrize(
    "failure",
    [
        FileExistsError("use --replace"),
        cli_module.CombinedLockError("another export holds the lock"),
    ],
)
def test_export_legacy_cli_reports_expected_lifecycle_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: Exception,
) -> None:
    def fail_export(*args, **kwargs):
        raise failure

    monkeypatch.setattr(
        cli_module,
        "export_legacy_compatibility_outputs",
        fail_export,
    )

    result = cli_module.main(
        [
            "export-legacy",
            "--database",
            str(tmp_path / "product.duckdb"),
            "--output-dir",
            str(tmp_path / "compatibility"),
        ]
    )

    assert result == 2


def test_validate_preprocessed_cli_guards_scratch_roots_before_validation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = tmp_path / "product" / "trinetx_preprocessed.duckdb"
    output_dir = tmp_path / "compatibility"
    calls: list[tuple[str, Path, str | None]] = []

    def record_guard(path: Path, *, artifact_label: str) -> None:
        calls.append(("guard", path, artifact_label))

    def record_compatibility_guard(path: Path, *, artifact_prefix: str) -> None:
        calls.append(("compatibility_guard", path, artifact_prefix))

    def validate(
        database_path: Path,
        *,
        compatibility_output_dir: Path | None,
    ) -> SimpleNamespace:
        calls.append(("validate", database_path, str(compatibility_output_dir)))
        return SimpleNamespace(valid=True, errors=(), warnings=(), counts={})

    monkeypatch.setattr(cli_module, "require_safe_output_location", record_guard)
    monkeypatch.setattr(
        cli_module,
        "require_safe_compatibility_hash_locations",
        record_compatibility_guard,
    )
    monkeypatch.setattr(cli_module, "validate_preprocessed_database", validate)

    result = cli_module.main(
        [
            "validate-preprocessed",
            "--database",
            str(database),
            "--output-dir",
            str(output_dir),
        ]
    )

    assert result == 0
    assert calls == [
        ("guard", database.parent, "validation database/spill directory"),
        (
            "compatibility_guard",
            output_dir,
            "validation compatibility",
        ),
        ("validate", database, str(output_dir)),
    ]


def test_validate_cohort_source_cli_accepts_repeated_elements_and_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    database = tmp_path / "product" / "trinetx_preprocessed.duckdb"
    calls: list[tuple[str, object]] = []

    def record_guard(path: Path, *, artifact_label: str) -> None:
        calls.append(("guard", (path, artifact_label)))

    def validate(database_path: Path, *, required_elements: list[str]):
        calls.append(("validate", (database_path, required_elements)))
        return SimpleNamespace(
            valid=True,
            errors=(),
            required_elements=tuple(required_elements),
            metadata=None,
        )

    monkeypatch.setattr(cli_module, "require_safe_output_location", record_guard)
    monkeypatch.setattr(cli_module, "validate_cohort_source", validate)

    result = cli_module.main(
        [
            "validate-cohort-source",
            "--database",
            str(database),
            "--require-element",
            "source.arterial_pco2",
            "--require-element",
            "source.traditional.lab.rfs_abg",
            "--json",
        ]
    )

    assert result == 0
    assert calls == [
        (
            "guard",
            (database.parent, "cohort-source database/spill directory"),
        ),
        (
            "validate",
            (
                database,
                ["source.arterial_pco2", "source.traditional.lab.rfs_abg"],
            ),
        ),
    ]
    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "errors": [],
        "metadata": None,
        "required_elements": [
            "source.arterial_pco2",
            "source.traditional.lab.rfs_abg",
        ],
        "valid": True,
    }


def test_validate_preprocessed_cli_rejects_repository_local_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        cli_module,
        "validate_preprocessed_database",
        lambda *args, **kwargs: pytest.fail("unsafe database reached validation"),
    )

    result = cli_module.main(
        [
            "validate-preprocessed",
            "--database",
            str(ROOT / "private-product" / "trinetx_preprocessed.duckdb"),
        ]
    )

    assert result == 2


def test_validate_preprocessed_cli_rejects_repository_local_compatibility_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        cli_module,
        "validate_preprocessed_database",
        lambda *args, **kwargs: pytest.fail("unsafe output reached validation"),
    )

    result = cli_module.main(
        [
            "validate-preprocessed",
            "--database",
            str(tmp_path / "product" / "trinetx_preprocessed.duckdb"),
            "--output-dir",
            str(ROOT / "private-compatibility"),
        ]
    )

    assert result == 2


def test_validate_preprocessed_cli_rejects_repository_local_hash_parent_symlink(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_dir = tmp_path / "compatibility"
    output_dir.mkdir()
    (output_dir / "AMBULATORY").symlink_to(ROOT, target_is_directory=True)
    monkeypatch.setattr(
        cli_module,
        "validate_preprocessed_database",
        lambda *args, **kwargs: pytest.fail("unsafe hash parent reached validation"),
    )

    result = cli_module.main(
        [
            "validate-preprocessed",
            "--database",
            str(tmp_path / "product" / "trinetx_preprocessed.duckdb"),
            "--output-dir",
            str(output_dir),
        ]
    )

    assert result == 2


COMBINED_MUTATING_ROUTES = (
    "run",
    "run-all",
    "build-preprocessed",
    "profile",
    "baseline",
    "compare",
    "run-encounter",
    "run-labs",
    "run-diagnosis",
    "run-meds",
    "run-procedure",
    "run-vitals",
    "run-rfs",
    "run-final-assembly",
)


@pytest.mark.parametrize("command", COMBINED_MUTATING_ROUTES)
def test_every_combined_mutating_route_guards_work_and_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    command: str,
) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        f'data_dir: "{tmp_path / "data"}"\n'
        f'work_dir: "{tmp_path / "work"}"\n'
        f'output_dir: "{tmp_path / "output"}"\n'
        "combined:\n"
        "  enabled: true\n"
        "domains:\n"
        "  encounter:\n"
        '    pattern: "Encounter/encounter*.csv"\n'
    )
    config = load_config(config_path)
    calls: list[tuple[Path, str]] = []

    def record_guard(path: Path, *, artifact_label: str) -> None:
        calls.append((path, artifact_label))

    monkeypatch.setattr(cli_module, "require_safe_output_location", record_guard)

    cli_module._require_safe_combined_mutation_locations(
        config,
        command=command,
    )

    assert set(COMBINED_MUTATING_ROUTES) == cli_module.COMBINED_MUTATING_COMMANDS
    assert calls == [
        (config.work_dir, "work directory"),
        (config.output_dir, "output directory"),
    ]


def _write_encounter_config(
    path: Path,
    data_dir: Path,
    work_dir: Path,
    output_dir: Path,
) -> None:
    content = (
        f'data_dir: "{data_dir}"\n'
        f'work_dir: "{work_dir}"\n'
        f'output_dir: "{output_dir}"\n'
        "domains:\n"
        "  encounter:\n"
        '    pattern: "Encounter/encounter*.csv"\n'
    )
    path.write_text(content)


def _write_encounter_csv(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "encounter_id,patient_id,start_date,end_date,type,"
        "start_date_derived_by_TriNetX,end_date_derived_by_TriNetX,"
        "derived_by_TriNetX,source_id\n"
    )


def _write_labs_config(
    path: Path,
    data_dir: Path,
    work_dir: Path,
    output_dir: Path,
) -> None:
    content = (
        f'data_dir: "{data_dir}"\n'
        f'work_dir: "{work_dir}"\n'
        f'output_dir: "{output_dir}"\n'
        "domains:\n"
        "  labs:\n"
        '    pattern: "Lab Results/lab_result*.csv"\n'
        "storage:\n"
        "  emit_normalized_domain_tables: true\n"
    )
    path.write_text(content)


def test_run_domain_probe_command_returns_none_on_timeout() -> None:
    result = _run_domain_probe_command(
        [sys.executable, "-c", "import time; time.sleep(10)"],
        timeout_seconds=0.1,
    )

    assert result.completed is None
    assert result.process_unreleased is False


def test_run_domain_probe_command_uses_file_output_and_polling_after_timeout(
    monkeypatch,
) -> None:
    class FakeProcess:
        pid = 999_999
        returncode = None

        def __init__(self) -> None:
            self.poll_calls = 0

        def communicate(self, timeout=None):
            raise AssertionError("timeout cleanup must not drain subprocess pipes")

        def wait(self, timeout=None):
            raise AssertionError("timeout cleanup must poll instead of waiting")

        def poll(self):
            self.poll_calls += 1
            return None

    fake_process = FakeProcess()
    popen_kwargs = {}

    def fake_popen(*args, **kwargs):
        popen_kwargs.update(kwargs)
        return fake_process

    monkeypatch.setattr(cli_module.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(cli_module.os, "killpg", lambda pid, sig: None)

    result = _run_domain_probe_command(["probe"], timeout_seconds=0.001)

    assert result.completed is None
    assert result.process_unreleased is True
    assert fake_process.poll_calls > 0
    assert popen_kwargs["stdout"] is not subprocess.PIPE
    assert popen_kwargs["stderr"] is not subprocess.PIPE


def test_timeout_inspection_skips_remaining_after_unreleased_probe(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        f'data_dir: "{tmp_path / "data"}"\n'
        f'work_dir: "{tmp_path / "work"}"\n'
        f'output_dir: "{tmp_path / "output"}"\n'
        "domains:\n"
        "  encounter:\n"
        '    pattern: "Encounter/encounter*.csv"\n'
        "  labs:\n"
        '    pattern: "Lab Results/lab_result*.csv"\n'
        "  meds:\n"
        '    pattern: "Medications/medication*.csv"\n'
    )
    (tmp_path / "data").mkdir()
    (tmp_path / "work").mkdir()
    (tmp_path / "output").mkdir()
    config = load_config(config_path)
    calls: list[str] = []

    def fake_inspect_one_domain_with_timeout(**kwargs):
        calls.append(kwargs["domain_name"])
        return cli_module._TimedDomainInspection(
            DomainInspection(
                name=kwargs["domain_name"],
                pattern=kwargs["pattern"],
                paths=(),
            ),
            timed_out=True,
            process_unreleased=True,
        )

    monkeypatch.setattr(
        cli_module,
        "_inspect_one_domain_with_timeout",
        fake_inspect_one_domain_with_timeout,
    )

    inspections, timed_out, probe_errors = (
        cli_module._inspect_domain_paths_with_timeouts(
            config,
            config_path=config_path,
            max_matches=1,
            selected_domains=None,
            timeout_seconds=1,
        )
    )

    assert calls == ["encounter"]
    assert [inspection.name for inspection in inspections] == [
        "encounter",
        "labs",
        "meds",
    ]
    assert timed_out == {"encounter"}
    assert sorted(probe_errors) == ["labs", "meds"]
    assert "did not release promptly" in probe_errors["labs"]
    assert inspections[0].search_dir == (tmp_path / "data" / "Encounter").resolve()
    assert inspections[0].search_dir_exists is None
    assert inspections[1].search_dir == (tmp_path / "data" / "Lab Results").resolve()
    assert inspections[1].search_dir_exists is None


def test_clean_scratch_dry_run_reports_known_artifacts(tmp_path: Path) -> None:
    root = tmp_path / "validation"
    work_dir = root / "refactor" / "work"
    work_dir.mkdir(parents=True)
    sqlite_scratch = work_dir / ".trinetx-demographics-test.sqlite"
    sqlite_scratch.write_text("scratch")
    hash_scratch = work_dir / ".trinetx-hash-test"
    hash_scratch.mkdir()
    (hash_scratch / "chunk-000001.csv").write_text("rows")
    normal_output = work_dir / "RFS_ABG.csv"
    normal_output.write_text("keep")
    unrelated_hidden = work_dir / ".other-hidden"
    unrelated_hidden.write_text("keep")
    report_path = tmp_path / "scratch_report.json"

    result = cli_module.main(
        [
            "clean-scratch",
            "--root",
            str(root),
            "--json-out",
            str(report_path),
        ]
    )

    assert result == 0
    payload = json.loads(report_path.read_text())
    assert payload["mode"] == "dry_run"
    assert payload["artifact_count"] == 2
    assert sorted(entry["relative_path"] for entry in payload["artifacts"]) == [
        "refactor/work/.trinetx-demographics-test.sqlite",
        "refactor/work/.trinetx-hash-test",
    ]
    assert sqlite_scratch.exists()
    assert hash_scratch.exists()
    assert normal_output.exists()
    assert unrelated_hidden.exists()


def test_clean_scratch_delete_removes_only_known_artifacts(tmp_path: Path) -> None:
    root = tmp_path / "validation"
    work_dir = root / "refactor" / "work"
    work_dir.mkdir(parents=True)
    sqlite_scratch = work_dir / ".trinetx-final-encounters-test.sqlite"
    sqlite_scratch.write_text("scratch")
    wal_scratch = work_dir / ".trinetx-final-encounters-test.sqlite-wal"
    wal_scratch.write_text("wal")
    hash_scratch = work_dir / ".trinetx-hash-test"
    hash_scratch.mkdir()
    (hash_scratch / "chunk-000001.csv").write_text("rows")
    normal_output = work_dir / "AMB_encounters.parquet"
    normal_output.write_text("keep")

    report_path = tmp_path / "scratch_delete_report.json"

    result = cli_module.main(
        [
            "clean-scratch",
            "--root",
            str(root),
            "--delete",
            "--json-out",
            str(report_path),
        ]
    )

    assert result == 0
    payload = json.loads(report_path.read_text())
    assert payload["deleted_count"] == 3
    assert not sqlite_scratch.exists()
    assert not wal_scratch.exists()
    assert not hash_scratch.exists()
    assert normal_output.exists()


def test_clean_scratch_recognizes_current_partition_stores(tmp_path: Path) -> None:
    root = tmp_path / "validation"
    work_dir = root / "refactor" / "work"
    work_dir.mkdir(parents=True)
    prefixes = [
        ".trinetx-final-cohorts-",
        ".trinetx-final-feature-sources-",
        ".trinetx-final-labs-",
        ".trinetx-final-prev-vitals-",
        ".trinetx-glp1-concept-ingest-",
        ".trinetx-glp1-observability-scan-",
        ".trinetx-glp1-terminology-qa-",
        ".trinetx-glp1-vital-ingest-",
        *cli_module.COMBINED_SCRATCH_PATH_PREFIXES,
        ".output.combined-build-",
        ".trinetx_preprocessed.duckdb.duckdb-tmp-",
        "._.trinetx-combined-build-",
        "._..trinetx-combined-publication-",
        "._.output.combined-build-",
        "._.trinetx-combined-lock-",
    ]
    scratch_names = [f"{prefix}test-{index}" for index, prefix in enumerate(prefixes)]
    for scratch_name in scratch_names:
        scratch = work_dir / scratch_name
        scratch.mkdir()
        (scratch / "bucket-000.parquet").write_text("rows")

    payload = cli_module.clean_scratch_artifacts(root, delete=False)

    expected_names = sorted(
        path.name
        for path in work_dir.iterdir()
        if cli_module._is_known_scratch_path(path)
    )
    assert set(scratch_names).issubset(expected_names)
    assert payload["artifact_count"] == len(expected_names)
    assert sorted(entry["relative_path"] for entry in payload["artifacts"]) == [
        f"refactor/work/{scratch_name}" for scratch_name in expected_names
    ]


def test_clean_scratch_preserves_persistent_lock_appledouble_sidecars(
    tmp_path: Path,
) -> None:
    root = tmp_path / "validation"
    work_dir = root / "refactor" / "work"
    work_dir.mkdir(parents=True)

    persistent_lock = work_dir / ".trinetx-combined-lock-persistent"
    persistent_lock.write_text("lock metadata\n")
    persistent_sidecar = work_dir / "._.trinetx-combined-lock-persistent"
    persistent_sidecar.write_bytes(b"AppleDouble")

    orphan_sidecar = work_dir / "._.trinetx-combined-lock-orphan"
    orphan_sidecar.write_bytes(b"AppleDouble")

    symlink_target = work_dir / "ordinary-file"
    symlink_target.write_text("keep\n")
    symlinked_lock = work_dir / ".trinetx-combined-lock-symlink"
    symlinked_lock.symlink_to(symlink_target)
    symlinked_lock_sidecar = work_dir / "._.trinetx-combined-lock-symlink"
    symlinked_lock_sidecar.write_bytes(b"AppleDouble")

    sidecar_lock = work_dir / ".trinetx-combined-lock-sidecar-symlink"
    sidecar_lock.write_text("lock metadata\n")
    symlinked_sidecar = work_dir / "._.trinetx-combined-lock-sidecar-symlink"
    # Non-APFS macOS test volumes can materialize this AppleDouble placeholder
    # when the paired lock is created. Replace that test-owned file with the
    # deliberately unsafe sidecar symlink exercised below.
    symlinked_sidecar.unlink(missing_ok=True)
    symlinked_sidecar.symlink_to(symlink_target)
    assert symlinked_sidecar.is_symlink()

    payload = cli_module.clean_scratch_artifacts(root, delete=True)

    assert payload["artifact_count"] == 3
    assert payload["deleted_count"] == 3
    assert persistent_lock.exists()
    assert persistent_sidecar.exists()
    assert not orphan_sidecar.exists()
    assert not symlinked_lock_sidecar.exists()
    assert not symlinked_sidecar.exists()
    assert symlinked_lock.is_symlink()
    assert sidecar_lock.exists()
    assert symlink_target.exists()


def test_clean_scratch_delete_tolerates_missing_nested_entries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "validation"
    work_dir = root / "refactor" / "work"
    work_dir.mkdir(parents=True)
    hash_scratch = work_dir / ".trinetx-hash-test"
    hash_scratch.mkdir()
    nested = hash_scratch / "chunk-000001.csv"
    nested.write_text("rows")
    original_rmtree = filesystem.shutil.rmtree

    def rmtree_with_missing_nested(path, *, onerror=None):
        nested.unlink()
        if onerror is not None:
            error = FileNotFoundError(nested)
            onerror(nested.unlink, str(nested), (FileNotFoundError, error, None))
        original_rmtree(path, onerror=onerror)

    monkeypatch.setattr(filesystem.shutil, "rmtree", rmtree_with_missing_nested)

    payload = cli_module.clean_scratch_artifacts(root, delete=True)

    assert payload["deleted_count"] == 1
    assert not hash_scratch.exists()


def test_clean_scratch_delete_propagates_directory_delete_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "validation"
    work_dir = root / "refactor" / "work"
    work_dir.mkdir(parents=True)
    hash_scratch = work_dir / ".trinetx-hash-test"
    hash_scratch.mkdir()
    (hash_scratch / "chunk-000001.csv").write_text("rows")

    def failing_rmtree(path, *, onerror=None):
        error = PermissionError("denied")
        if onerror is not None:
            onerror(path.rmdir, str(path), (PermissionError, error, None))
            return
        raise error

    monkeypatch.setattr(filesystem.shutil, "rmtree", failing_rmtree)

    with pytest.raises(PermissionError, match="denied"):
        cli_module.clean_scratch_artifacts(root, delete=True)

    assert hash_scratch.exists()


def test_clean_scratch_delete_raises_when_directory_remains(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "validation"
    work_dir = root / "refactor" / "work"
    work_dir.mkdir(parents=True)
    hash_scratch = work_dir / ".trinetx-hash-test"
    hash_scratch.mkdir()
    (hash_scratch / "chunk-000001.csv").write_text("rows")

    def noop_rmtree(path, *, onerror=None):
        return None

    monkeypatch.setattr(filesystem.shutil, "rmtree", noop_rmtree)

    with pytest.raises(OSError, match="Scratch directory was not deleted"):
        cli_module.clean_scratch_artifacts(root, delete=True)

    assert hash_scratch.exists()


def test_validate_config_cli(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    work_dir = tmp_path / "work"
    output_dir = tmp_path / "output"
    work_dir.mkdir()
    output_dir.mkdir()
    _write_encounter_csv(data_dir / "Encounter" / "encounter0001.csv")

    config_path = tmp_path / "config.yaml"
    _write_config(config_path)

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "trinetx_preprocessing",
            "validate-config",
            "--config",
            str(config_path),
        ],
        cwd=ROOT,
        env=_build_env(),
        capture_output=True,
        text=True,
        check=False,
    )

    output = (result.stdout or "") + (result.stderr or "")
    assert result.returncode == 0, output


def test_run_encounter_cli(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    work_dir = tmp_path / "work"
    output_dir = tmp_path / "output"
    data_dir.mkdir()
    work_dir.mkdir()
    output_dir.mkdir()

    encounter_dir = data_dir / "Encounter"
    encounter_dir.mkdir()
    shutil.copy(FIXTURE_PATH, encounter_dir / "encounter0001.csv")

    config_path = tmp_path / "config.yaml"
    _write_encounter_config(config_path, data_dir, work_dir, output_dir)

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "trinetx_preprocessing",
            "run-encounter",
            "--config",
            str(config_path),
        ],
        cwd=ROOT,
        env=_build_env(),
        capture_output=True,
        text=True,
        check=False,
    )

    output = (result.stdout or "") + (result.stderr or "")
    assert result.returncode == 0, output
    assert (work_dir / "AMB_encounters.csv").exists()
    assert (work_dir / "EMER_encounters.csv").exists()
    assert (work_dir / "INPAT_encounters.csv").exists()


def test_run_labs_cli(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    work_dir = tmp_path / "work"
    output_dir = tmp_path / "output"
    data_dir.mkdir()
    work_dir.mkdir()
    output_dir.mkdir()

    labs_dir = data_dir / "Lab Results"
    labs_dir.mkdir()
    shutil.copy(LAB_FIXTURE_PATH, labs_dir / "lab_results0001.csv")

    config_path = tmp_path / "config.yaml"
    _write_labs_config(config_path, data_dir, work_dir, output_dir)

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "trinetx_preprocessing",
            "run-labs",
            "--config",
            str(config_path),
        ],
        cwd=ROOT,
        env=_build_env(),
        capture_output=True,
        text=True,
        check=False,
    )

    output = (result.stdout or "") + (result.stderr or "")
    assert result.returncode == 0, output
    assert (work_dir / "lab_results_NEW_0001.csv").exists()


def test_run_final_assembly_cli_with_parquet_intermediates(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    work_dir = tmp_path / "work"
    output_dir = tmp_path / "output"
    patient_dir = data_dir / "Patient"
    patient_dir.mkdir(parents=True)
    work_dir.mkdir()
    output_dir.mkdir()
    pd.DataFrame(
        [
            {
                "patient_id": "P1",
                "sex": "F",
                "race": "White",
                "ethnicity": "Not Hispanic",
                "year_of_birth": 1980,
                "patient_regional_location": "US",
                "month_year_death": "",
            }
        ]
    ).to_csv(patient_dir / "patient.csv", index=False)
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        f'data_dir: "{data_dir}"\n'
        f'work_dir: "{work_dir}"\n'
        f'output_dir: "{output_dir}"\n'
        "domains:\n"
        "  patient:\n"
        '    pattern: "Patient/patient*.csv"\n'
        "storage:\n"
        '  intermediate_format: "parquet"\n'
        "  emit_legacy_csv_intermediates: false\n"
        "  parquet_row_group_size: 1\n"
        "data_screen:\n"
        "  source: legacy_files\n"
    )
    config = load_config(config_path)
    data_checks_dir = work_dir / "data_checks"
    data_checks_dir.mkdir()
    for filename in {"amb_enc_screen.csv", "inp_enc_screen.csv"}:
        pd.DataFrame(columns=["encounter_id"]).to_csv(
            data_checks_dir / filename,
            index=False,
        )
    initialize_work_manifest(config)
    for filename in final_assembly.SETTING_ENCOUNTER_FILES.values():
        write_work_table(
            config,
            filename,
            pd.DataFrame(columns=final_assembly.ENCOUNTER_COLUMNS),
        )
    for category in final_assembly.RFS_CATEGORIES:
        write_work_table(
            config,
            f"RFS_{category}.csv",
            pd.DataFrame(columns=final_assembly.RFS_EVENT_COLUMNS),
        )
    analysis_tables = {
        "analysis_lab_availability.csv": ["encounter_id"],
        "analysis_diagnosis_availability.csv": ["encounter_id"],
        "analysis_lab_features.csv": [
            "source_name",
            *final_assembly.LAB_COLUMNS,
        ],
        "analysis_rfs_labs.csv": ["category", *final_assembly.RFS_EVENT_COLUMNS],
        "analysis_rfs_diagnosis.csv": [
            "category",
            *final_assembly.RFS_EVENT_COLUMNS,
        ],
        "analysis_rfs_procedure.csv": [
            "category",
            *final_assembly.RFS_EVENT_COLUMNS,
        ],
        "analysis_rfs_vitals.csv": ["category", *final_assembly.RFS_EVENT_COLUMNS],
        "analysis_diagnosis_features.csv": [
            "source_name",
            *final_assembly.DIAGNOSIS_COLUMNS,
        ],
        "analysis_medication_features.csv": [
            "source_name",
            *final_assembly.MEDICATION_COLUMNS,
        ],
        "analysis_procedure_features.csv": [
            "source_name",
            *final_assembly.PROCEDURE_COLUMNS,
        ],
        "analysis_vital_features.csv": [
            "source_name",
            *final_assembly.VITALS_COLUMNS,
        ],
    }
    for logical_name, columns in analysis_tables.items():
        write_work_table(config, logical_name, pd.DataFrame(columns=columns))
    (work_dir / "rfs_rule_audit.json").write_text(
        json.dumps({"schema_version": 1, "ruleset": "corrected_v1"})
    )
    for stage in FINAL_ASSEMBLY_PREREQUISITES:
        if stage == "rfs":
            (work_dir / "rfs_stage_metrics.json").write_text(
                json.dumps({"schema_version": 1, "used_analysis_index": True})
            )
        mark_stage_complete(config, stage, [])

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "trinetx_preprocessing",
            "run-final-assembly",
            "--config",
            str(config_path),
            "--strict",
        ],
        cwd=ROOT,
        env=_build_env(),
        capture_output=True,
        text=True,
        check=False,
    )

    output = (result.stdout or "") + (result.stderr or "")
    assert result.returncode == 0, output
    assert (output_dir / "AMBULATORY" / "RFS_ABG_ENC_AMB_BEFORE.csv").exists()

    (work_dir / "encounter_conflicts.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "encounter_conflict_count": 1,
                "type_combinations": {"AMB+IMP": 1},
            }
        )
    )
    strict_resume = subprocess.run(
        [
            sys.executable,
            "-m",
            "trinetx_preprocessing",
            "run-final-assembly",
            "--config",
            str(config_path),
            "--strict",
        ],
        cwd=ROOT,
        env=_build_env(),
        capture_output=True,
        text=True,
        check=False,
    )

    strict_output = (strict_resume.stdout or "") + (strict_resume.stderr or "")
    assert strict_resume.returncode == 2
    assert "requires conflict-free encounter work" in strict_output


def test_inspect_inputs_cli_reports_missing_domains(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    work_dir = tmp_path / "work"
    output_dir = tmp_path / "output"
    work_dir.mkdir()
    output_dir.mkdir()
    _write_encounter_csv(data_dir / "Encounter" / "encounter0001.csv")
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        f'data_dir: "{data_dir}"\n'
        f'work_dir: "{work_dir}"\n'
        f'output_dir: "{output_dir}"\n'
        "domains:\n"
        "  encounter:\n"
        '    pattern: "Encounter/encounter*.csv"\n'
        "  labs:\n"
        '    pattern: "Lab Results/lab_result*.csv"\n'
    )

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "trinetx_preprocessing",
            "inspect-inputs",
            "--config",
            str(config_path),
        ],
        cwd=ROOT,
        env=_build_env(),
        capture_output=True,
        text=True,
        check=False,
    )

    output = (result.stdout or "") + (result.stderr or "")
    assert result.returncode == 2, output
    assert "Domain 'encounter' matched 1 file(s)" in output
    assert "Domain 'labs' matched 0 file(s)" in output
    assert "Missing input domains: labs" in output


def test_inspect_inputs_cli_allow_missing_returns_success(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    work_dir = tmp_path / "work"
    output_dir = tmp_path / "output"
    data_dir.mkdir()
    work_dir.mkdir()
    output_dir.mkdir()
    config_path = tmp_path / "config.yaml"
    _write_labs_config(config_path, data_dir, work_dir, output_dir)

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "trinetx_preprocessing",
            "inspect-inputs",
            "--config",
            str(config_path),
            "--allow-missing",
        ],
        cwd=ROOT,
        env=_build_env(),
        capture_output=True,
        text=True,
        check=False,
    )

    output = (result.stdout or "") + (result.stderr or "")
    assert result.returncode == 0, output
    assert "Domain 'labs' matched 0 file(s)" in output


def test_inspect_inputs_cli_json_reports_missing_domains(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    work_dir = tmp_path / "work"
    output_dir = tmp_path / "output"
    work_dir.mkdir()
    output_dir.mkdir()
    _write_encounter_csv(data_dir / "Encounter" / "encounter0001.csv")
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        f'data_dir: "{data_dir}"\n'
        f'work_dir: "{work_dir}"\n'
        f'output_dir: "{output_dir}"\n'
        "domains:\n"
        "  encounter:\n"
        '    pattern: "Encounter/encounter*.csv"\n'
        "  labs:\n"
        '    pattern: "Lab Results/lab_result*.csv"\n'
    )

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "trinetx_preprocessing",
            "inspect-inputs",
            "--config",
            str(config_path),
            "--json",
        ],
        cwd=ROOT,
        env=_build_env(),
        capture_output=True,
        text=True,
        check=False,
    )

    payload = json.loads(result.stdout)

    assert result.returncode == 2
    assert payload["schema_version"] == 1
    assert payload["config_path"] == str(config_path.resolve())
    assert (
        payload["config_sha256"] == hashlib.sha256(config_path.read_bytes()).hexdigest()
    )
    datetime.fromisoformat(payload["generated_at"])
    assert payload["all_present"] is False
    assert payload["space_ok"] is True
    assert payload["filesystems"][0]["label"] == "data_dir"
    assert payload["filesystems"][0]["free_bytes"] > 0
    assert payload["missing"] == ["labs"]
    assert payload["domains"][0]["name"] == "encounter"
    assert payload["domains"][0]["matched_count"] == 1
    assert payload["domains"][0]["search_dir"] == str(
        (data_dir / "Encounter").resolve()
    )
    assert payload["domains"][0]["search_dir_exists"] is True
    assert payload["domains"][1]["name"] == "labs"
    assert payload["domains"][1]["matched_count"] == 0
    assert payload["domains"][1]["search_dir"] == str(
        (data_dir / "Lab Results").resolve()
    )
    assert payload["domains"][1]["search_dir_exists"] is False


def test_inspect_inputs_cli_json_out_writes_status_file(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    work_dir = tmp_path / "work"
    output_dir = tmp_path / "output"
    status_path = tmp_path / "manifests" / "input_status.json"
    data_dir.mkdir()
    work_dir.mkdir()
    output_dir.mkdir()
    config_path = tmp_path / "config.yaml"
    _write_labs_config(config_path, data_dir, work_dir, output_dir)

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "trinetx_preprocessing",
            "inspect-inputs",
            "--config",
            str(config_path),
            "--allow-missing",
            "--json-out",
            str(status_path),
        ],
        cwd=ROOT,
        env=_build_env(),
        capture_output=True,
        text=True,
        check=False,
    )

    output = (result.stdout or "") + (result.stderr or "")
    payload = json.loads(status_path.read_text())

    assert result.returncode == 0, output
    assert result.stdout == ""
    assert payload["schema_version"] == 1
    assert payload["config_path"] == str(config_path.resolve())
    assert (
        payload["config_sha256"] == hashlib.sha256(config_path.read_bytes()).hexdigest()
    )
    assert payload["missing"] == ["labs"]


def test_inspect_inputs_cli_json_reports_truncated_match_counts(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data"
    work_dir = tmp_path / "work"
    output_dir = tmp_path / "output"
    work_dir.mkdir()
    output_dir.mkdir()
    _write_encounter_csv(data_dir / "Encounter" / "encounter0001.csv")
    _write_encounter_csv(data_dir / "Encounter" / "encounter0002.csv")
    config_path = tmp_path / "config.yaml"
    _write_encounter_config(config_path, data_dir, work_dir, output_dir)

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "trinetx_preprocessing",
            "inspect-inputs",
            "--config",
            str(config_path),
            "--json",
            "--max-matches",
            "1",
        ],
        cwd=ROOT,
        env=_build_env(),
        capture_output=True,
        text=True,
        check=False,
    )

    payload = json.loads(result.stdout)

    assert result.returncode == 0
    assert payload["max_matches"] == 1
    assert payload["domains"][0]["matched_count"] == 1
    assert payload["domains"][0]["matched_count_exact"] is False
    assert payload["domains"][0]["truncated"] is True


def test_inspect_inputs_cli_can_filter_domain_and_skip_space_check(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data"
    work_dir = tmp_path / "work"
    output_dir = tmp_path / "output"
    work_dir.mkdir()
    output_dir.mkdir()
    _write_encounter_csv(data_dir / "Encounter" / "encounter0001.csv")
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        f'data_dir: "{data_dir}"\n'
        f'work_dir: "{work_dir}"\n'
        f'output_dir: "{output_dir}"\n'
        "domains:\n"
        "  encounter:\n"
        '    pattern: "Encounter/encounter*.csv"\n'
        "  labs:\n"
        '    pattern: "Lab Results/lab_result*.csv"\n'
    )

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "trinetx_preprocessing",
            "inspect-inputs",
            "--config",
            str(config_path),
            "--json",
            "--domain",
            "encounter",
            "--skip-space-check",
        ],
        cwd=ROOT,
        env=_build_env(),
        capture_output=True,
        text=True,
        check=False,
    )

    payload = json.loads(result.stdout)

    assert result.returncode == 0
    assert payload["selected_domains"] == ["encounter"]
    assert payload["space_check_skipped"] is True
    assert payload["space_ok"] is None
    assert payload["filesystems"] == []
    assert [domain["name"] for domain in payload["domains"]] == ["encounter"]


def test_inspect_inputs_cli_domain_timeout_mode_aggregates_json(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data"
    work_dir = tmp_path / "work"
    output_dir = tmp_path / "output"
    work_dir.mkdir()
    output_dir.mkdir()
    _write_encounter_csv(data_dir / "Encounter" / "encounter0001.csv")
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        f'data_dir: "{data_dir}"\n'
        f'work_dir: "{work_dir}"\n'
        f'output_dir: "{output_dir}"\n'
        "domains:\n"
        "  encounter:\n"
        '    pattern: "Encounter/encounter*.csv"\n'
        "  labs:\n"
        '    pattern: "Lab Results/lab_result*.csv"\n'
    )

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "trinetx_preprocessing",
            "inspect-inputs",
            "--config",
            str(config_path),
            "--json",
            "--allow-missing",
            "--max-matches",
            "1",
            "--skip-space-check",
            "--domain-timeout-seconds",
            "5",
        ],
        cwd=ROOT,
        env=_build_env(),
        capture_output=True,
        text=True,
        check=False,
    )

    payload = json.loads(result.stdout)

    assert result.returncode == 0
    assert payload["domain_timeout_seconds"] == 5
    assert payload["timed_out"] == []
    assert payload["probe_errors"] == {}
    assert payload["missing"] == ["labs"]
    assert payload["domains"][0]["name"] == "encounter"
    assert payload["domains"][0]["paths"] == [
        str((data_dir / "Encounter" / "encounter0001.csv").resolve())
    ]
    assert payload["domains"][0]["path_sample_limit"] == 10
    assert payload["domains"][0]["paths_are_complete"] is True
    assert payload["domains"][0]["timed_out"] is False
    assert payload["domains"][1]["name"] == "labs"
    assert payload["domains"][1]["paths"] == []


def test_inspect_inputs_cli_limits_json_path_samples(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    work_dir = tmp_path / "work"
    output_dir = tmp_path / "output"
    work_dir.mkdir()
    output_dir.mkdir()
    for index in range(12):
        _write_encounter_csv(data_dir / "Encounter" / f"encounter{index:04}.csv")
    config_path = tmp_path / "config.yaml"
    _write_encounter_config(config_path, data_dir, work_dir, output_dir)

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "trinetx_preprocessing",
            "inspect-inputs",
            "--config",
            str(config_path),
            "--json",
            "--skip-space-check",
        ],
        cwd=ROOT,
        env=_build_env(),
        capture_output=True,
        text=True,
        check=False,
    )

    payload = json.loads(result.stdout)
    domain = payload["domains"][0]

    assert result.returncode == 0
    assert domain["matched_count"] == 12
    assert len(domain["paths"]) == 10
    assert domain["path_sample_limit"] == 10
    assert domain["paths_are_complete"] is False


def test_inspect_inputs_cli_domain_timeout_requires_bounded_scan(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data"
    work_dir = tmp_path / "work"
    output_dir = tmp_path / "output"
    work_dir.mkdir()
    output_dir.mkdir()
    _write_encounter_csv(data_dir / "Encounter" / "encounter0001.csv")
    config_path = tmp_path / "config.yaml"
    _write_encounter_config(config_path, data_dir, work_dir, output_dir)

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "trinetx_preprocessing",
            "inspect-inputs",
            "--config",
            str(config_path),
            "--json",
            "--skip-space-check",
            "--domain-timeout-seconds",
            "5",
        ],
        cwd=ROOT,
        env=_build_env(),
        capture_output=True,
        text=True,
        check=False,
    )

    output = (result.stdout or "") + (result.stderr or "")
    assert result.returncode == 2
    assert "domain-timeout-seconds requires max_matches" in output


def test_inspect_inputs_cli_min_free_gb_fails_low_space_gate(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    work_dir = tmp_path / "work"
    output_dir = tmp_path / "output"
    data_dir.mkdir()
    work_dir.mkdir()
    output_dir.mkdir()
    _write_encounter_csv(data_dir / "Encounter" / "encounter0001.csv")
    config_path = tmp_path / "config.yaml"
    _write_encounter_config(config_path, data_dir, work_dir, output_dir)

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "trinetx_preprocessing",
            "inspect-inputs",
            "--config",
            str(config_path),
            "--min-free-gb",
            "1000000000",
        ],
        cwd=ROOT,
        env=_build_env(),
        capture_output=True,
        text=True,
        check=False,
    )

    output = (result.stdout or "") + (result.stderr or "")
    assert result.returncode == 2, output
    assert "Filesystems below" in output


def test_scaffold_validation_cli_creates_external_layout(tmp_path: Path) -> None:
    data_dir = tmp_path / "TriNetX"
    validation_root = tmp_path / "validation"
    data_dir.mkdir()

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "trinetx_preprocessing",
            "scaffold-validation",
            "--data-dir",
            str(data_dir),
            "--validation-root",
            str(validation_root),
        ],
        cwd=ROOT,
        env=_build_env(),
        capture_output=True,
        text=True,
        check=False,
    )

    output = (result.stdout or "") + (result.stderr or "")
    config_path = validation_root / "config.yaml"

    assert result.returncode == 0, output
    assert config_path.exists()
    for relative in [
        "refactor/work",
        "refactor/output",
        "legacy/work",
        "legacy/output",
        "manifests",
        "profile",
        "logs",
        "uv-cache",
    ]:
        assert (validation_root / relative).is_dir()
    config_text = config_path.read_text()
    assert f'data_dir: "{data_dir}"' in config_text
    assert 'work_dir: "' in config_text
    assert "intermediate_format: parquet" in config_text
    assert "emit_legacy_csv_intermediates: false" in config_text
    assert 'pattern: "Lab Results/lab_result*.csv"' in config_text
    assert 'patterns:\n      - "Medications/medication[0-9]*.csv"' in config_text
    assert '      - "Medications/medication_ingredient*.csv"' in config_text

    second = subprocess.run(
        [
            sys.executable,
            "-m",
            "trinetx_preprocessing",
            "scaffold-validation",
            "--data-dir",
            str(data_dir),
            "--validation-root",
            str(validation_root),
        ],
        cwd=ROOT,
        env=_build_env(),
        capture_output=True,
        text=True,
        check=False,
    )

    assert second.returncode == 2
    assert "Config already exists" in ((second.stdout or "") + (second.stderr or ""))


def test_hash_outputs_cli(tmp_path: Path) -> None:
    work_dir = tmp_path / "legacy" / "work"
    output_dir = tmp_path / "legacy" / "output"
    out_dir = tmp_path / "hashes"
    work_dir.mkdir(parents=True)
    output_dir.mkdir(parents=True)
    pd.DataFrame({"patient_id": ["P1"], "encounter_id": ["E1"]}).to_csv(
        work_dir / "RFS_ABG.csv",
        index=False,
    )
    pd.DataFrame({"patient_id": ["P1"], "encounter_id": ["E1"]}).to_csv(
        output_dir / "RFS_ABG_ENC_AMB_AFTER.csv",
        index=False,
    )

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "trinetx_preprocessing",
            "hash-outputs",
            "--work-dir",
            str(work_dir),
            "--output-dir",
            str(output_dir),
            "--out",
            str(out_dir),
        ],
        cwd=ROOT,
        env=_build_env(),
        capture_output=True,
        text=True,
        check=False,
    )

    output = (result.stdout or "") + (result.stderr or "")
    assert result.returncode == 0, output
    raw_manifest = json.loads((out_dir / "hashes.json").read_text())
    assert raw_manifest["scope"] == "all"
    assert raw_manifest["work_dir"] == str(work_dir.resolve())
    assert raw_manifest["output_dir"] == str(output_dir.resolve())


def test_hash_outputs_cli_final_scope_without_work_dir(tmp_path: Path) -> None:
    output_dir = tmp_path / "legacy" / "output"
    out_dir = tmp_path / "hashes"
    output_dir.mkdir(parents=True)
    pd.DataFrame({"patient_id": ["P1"], "encounter_id": ["E1"]}).to_csv(
        output_dir / "RFS_ABG_ENC_AMB_AFTER.csv",
        index=False,
    )

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "trinetx_preprocessing",
            "hash-outputs",
            "--output-dir",
            str(output_dir),
            "--scope",
            "final",
            "--hash-chunk-rows",
            "1",
            "--out",
            str(out_dir),
        ],
        cwd=ROOT,
        env=_build_env(),
        capture_output=True,
        text=True,
        check=False,
    )

    output = (result.stdout or "") + (result.stderr or "")
    assert result.returncode == 0, output
    raw_manifest = json.loads((out_dir / "hashes.json").read_text())
    assert raw_manifest["scope"] == "final"
    assert raw_manifest["output_dir"] == str(output_dir.resolve())
    assert "work_dir" not in raw_manifest


def test_compare_manifests_cli(tmp_path: Path) -> None:
    baseline_dir = tmp_path / "baseline"
    current_dir = tmp_path / "current"
    write_hash_manifest(baseline_dir, {"output_dir/a.csv": "abc"})
    write_hash_manifest(current_dir, {"output_dir/a.csv": "abc"})

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "trinetx_preprocessing",
            "compare-manifests",
            "--baseline",
            str(baseline_dir),
            "--current",
            str(current_dir),
        ],
        cwd=ROOT,
        env=_build_env(),
        capture_output=True,
        text=True,
        check=False,
    )

    output = (result.stdout or "") + (result.stderr or "")
    assert result.returncode == 0, output


def test_compare_manifests_cli_detects_mismatch(tmp_path: Path) -> None:
    baseline_dir = tmp_path / "baseline"
    current_dir = tmp_path / "current"
    report_path = tmp_path / "reports" / "manifest_comparison.json"
    write_hash_manifest(baseline_dir, {"output_dir/a.csv": "abc"})
    write_hash_manifest(current_dir, {"output_dir/a.csv": "def"})

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "trinetx_preprocessing",
            "compare-manifests",
            "--baseline",
            str(baseline_dir),
            "--current",
            str(current_dir),
            "--report",
            str(report_path),
        ],
        cwd=ROOT,
        env=_build_env(),
        capture_output=True,
        text=True,
        check=False,
    )

    output = (result.stdout or "") + (result.stderr or "")
    report = json.loads(report_path.read_text())

    assert result.returncode == 1, output
    assert "Hash mismatch" in output
    assert report["schema_version"] == 1
    assert report["ok"] is False
    assert report["baseline_manifest_sha256"] == _manifest_sha256(baseline_dir)
    assert report["current_manifest_sha256"] == _manifest_sha256(current_dir)
    assert report["counts"]["hash_mismatched"] == 1
    assert report["hash_mismatched"] == [
        {
            "key": "output_dir/a.csv",
            "baseline_hash": "abc",
            "current_hash": "def",
        }
    ]


def _complete_profile_provenance_payload(tmp_path: Path) -> dict[str, object]:
    (tmp_path / "config.yaml").write_bytes(PROFILE_CONFIG_CONTENT)
    output_file = tmp_path / "output" / "a.csv"
    output_file.parent.mkdir(parents=True, exist_ok=True)
    if not output_file.exists():
        output_file.write_bytes(b"0123456789ab")
    output_stat = output_file.stat()
    return {
        "schema_version": 2,
        "generated_file_count": 2,
        "output_file_count": 1,
        "output_files": [
            {
                "path": str(output_file.resolve()),
                "exists": True,
                "size_bytes": output_stat.st_size,
                "mtime_ns": output_stat.st_mtime_ns,
            }
        ],
        "total_seconds": 12.3,
        "peak_rss_mb": 50.0,
        "disk_footprint_bytes": {"work_dir": 100, "output_dir": 20},
        "stage_timings_seconds": {"run": 12.1},
        "started_at": "2026-06-08T00:00:00+00:00",
        "ended_at": "2026-06-08T00:00:12+00:00",
        "package_version": "0.1.0",
        "python_version": "3.11.0",
        "git_commit": "a" * 40,
        "git_dirty": True,
        "git_code_dirty": current_git_code_dirty(),
        "git_code_state_sha256": current_git_code_state_sha256(),
        "config_path": str((tmp_path / "config.yaml").resolve()),
        "config_sha256": PROFILE_CONFIG_SHA256,
        "strict": True,
    }


def _complete_input_filesystems(
    tmp_path: Path,
    *,
    free_gb: float = 101.0,
) -> list[dict[str, object]]:
    free_bytes = int(free_gb * 1024**3)
    return [
        {
            "label": label,
            "path": str((tmp_path / label).resolve()),
            "checked_path": str(tmp_path.resolve()),
            "free_bytes": free_bytes,
            "free_gb": free_gb,
        }
        for label in ("data_dir", "work_dir", "output_dir")
    ]


def _table_entry_for_source(
    *,
    key: str,
    source_path: Path,
    hash_value: str = "abc",
    physical_format: str = "csv",
) -> TableHashEntry:
    source_stat = source_path.stat()
    return TableHashEntry(
        key=key,
        hash=hash_value,
        row_count=1,
        columns=("patient_id",),
        physical_format=physical_format,
        source_path=str(source_path.resolve()),
        source_size_bytes=source_stat.st_size,
        source_mtime_ns=source_stat.st_mtime_ns,
    )


def _profile_output_inventory_item(path: Path) -> dict[str, object]:
    path_stat = path.stat()
    return {
        "path": str(path.resolve()),
        "exists": True,
        "size_bytes": path_stat.st_size,
        "mtime_ns": path_stat.st_mtime_ns,
    }


def _write_legacy_manifest(path: Path, tmp_path: Path) -> Path:
    source_path = tmp_path / "legacy_output" / "a.csv"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_text("patient_id\n1\n")
    return write_hash_manifest(
        path,
        {
            "output_dir/a.csv": _table_entry_for_source(
                key="output_dir/a.csv",
                source_path=source_path,
            )
        },
        scope="final",
        output_dir=tmp_path / "legacy_output",
    )


def _write_work_scope_manifest(path: Path, tmp_path: Path) -> Path:
    source_path = tmp_path / "work" / "a.csv"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_text("patient_id\n1\n")
    return write_hash_manifest(
        path,
        {
            "work_dir/a.csv": _table_entry_for_source(
                key="work_dir/a.csv",
                source_path=source_path,
            )
        },
        scope="final",
        output_dir=tmp_path / "work",
    )


def _write_refactor_manifest(
    path: Path,
    tmp_path: Path,
    *,
    source_relative: str = "output/a.csv",
) -> Path:
    source_path = tmp_path / source_relative
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_text("patient_id\n1\n")
    return write_hash_manifest(
        path,
        {
            "output_dir/a.csv": _table_entry_for_source(
                key="output_dir/a.csv",
                source_path=source_path,
            )
        },
        scope="final",
        output_dir=tmp_path / "output",
    )


def _manifest_sha256(path: Path) -> str:
    manifest_path = path / "hashes.json" if path.is_dir() else path
    return hashlib.sha256(manifest_path.read_bytes()).hexdigest()


def _write_comparison_report(
    path: Path,
    baseline: Path,
    current: Path,
) -> None:
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "ok": True,
                "baseline": str(baseline.resolve()),
                "baseline_manifest_sha256": _manifest_sha256(baseline),
                "current": str(current.resolve()),
                "current_manifest_sha256": _manifest_sha256(current),
                "counts": {
                    "missing": 0,
                    "extra": 0,
                    "hash_mismatched": 0,
                    "row_count_mismatched": 0,
                    "columns_mismatched": 0,
                },
                "generated_at": "2026-06-08T00:00:00+00:00",
            }
        )
    )


def test_validation_status_cli_reports_ready_artifacts(tmp_path: Path) -> None:
    input_status = tmp_path / "input_status.json"
    markdown_path = tmp_path / "validation_status.md"
    config_path = str((tmp_path / "config.yaml").resolve())
    input_status.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "all_present": True,
                "space_ok": True,
                "space_check_skipped": False,
                "min_free_gb": 100.0,
                "filesystems": _complete_input_filesystems(tmp_path),
                "missing": [],
                "domains": [{"name": "encounter"}],
                "generated_at": "2026-06-08T00:00:00+00:00",
                "config_path": config_path,
                "config_sha256": PROFILE_CONFIG_SHA256,
            }
        )
    )
    legacy_manifest = tmp_path / "legacy_manifest"
    refactor_manifest = tmp_path / "refactor_manifest"
    _write_legacy_manifest(legacy_manifest, tmp_path)
    _write_refactor_manifest(refactor_manifest, tmp_path)
    comparison_report = tmp_path / "final_comparison.json"
    _write_comparison_report(comparison_report, legacy_manifest, refactor_manifest)
    profile_provenance = tmp_path / "profile" / "provenance.json"
    profile_provenance.parent.mkdir()
    profile_provenance.write_text(
        json.dumps(_complete_profile_provenance_payload(tmp_path))
    )

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "trinetx_preprocessing",
            "validation-status",
            "--input-status",
            str(input_status),
            "--legacy-manifest",
            str(legacy_manifest),
            "--refactor-manifest",
            str(refactor_manifest),
            "--comparison-report",
            str(comparison_report),
            "--profile-provenance",
            str(profile_provenance),
            "--required-root",
            str(tmp_path),
            "--required-root-min-free-gb",
            "0",
            "--json",
            "--markdown-out",
            str(markdown_path),
        ],
        cwd=ROOT,
        env=_build_env(),
        capture_output=True,
        text=True,
        check=False,
    )

    payload = json.loads(result.stdout)

    assert result.returncode == 0, result.stderr
    assert payload["ready"] is True
    assert payload["checks"]["input_status"]["schema_current"] is True
    assert payload["checks"]["legacy_manifest"]["table_count"] == 1
    assert payload["checks"]["legacy_manifest"]["manifest_schema_version"] == 2
    assert payload["checks"]["legacy_manifest"]["hash_algorithm"] == "sha256"
    assert payload["checks"]["legacy_manifest"]["manifest_scope"] == "final"
    assert payload["checks"]["legacy_manifest"]["manifest_output_dir"] == str(
        (tmp_path / "legacy_output").resolve()
    )
    assert payload["checks"]["legacy_manifest"]["header_complete"] is True
    assert (
        payload["checks"]["comparison_report"]["current_manifest_comparison_ok"] is True
    )
    assert payload["checks"]["comparison_report"]["comparison_ok_matches"] is True
    assert payload["checks"]["comparison_report"]["comparison_counts_match"] is True
    assert payload["checks"]["profile_provenance"]["output_file_count"] == 1
    assert payload["checks"]["artifact_consistency"]["config_path_matches"] is True
    assert payload["checks"]["artifact_consistency"]["config_sha256_matches"] is True
    assert (
        payload["checks"]["artifact_consistency"]["current_config_sha256"]
        == PROFILE_CONFIG_SHA256
    )
    assert (
        payload["checks"]["artifact_consistency"]["current_config_sha256_matches"]
        is True
    )
    assert payload["checks"]["artifact_consistency"]["blockers"] == []
    assert payload["checks"]["required_root"]["ok"] is True
    assert payload["checks"]["required_root"]["required_root"] == str(
        tmp_path.resolve()
    )
    assert payload["checks"]["required_root"]["space_ok"] is True
    assert payload["checks"]["required_root"]["min_free_gb"] == 0.0
    assert payload["checks"]["profile_refactor_outputs"]["ok"] is True
    markdown = markdown_path.read_text()
    assert "## Artifact Consistency" in markdown
    assert "- Config path match: yes" in markdown
    assert "- Config SHA-256 match: yes" in markdown
    assert "- Current config SHA-256 match: yes" in markdown
    assert "## Required Root" in markdown
    assert f"- Required root: {tmp_path.resolve()}" in markdown
    assert "- Root placement: pass" in markdown
    assert "- Minimum free GiB: 0.000" in markdown
    assert "- Free-space threshold: yes" in markdown


def test_validation_status_cli_rejects_artifacts_outside_required_root(
    tmp_path: Path,
) -> None:
    input_status = tmp_path / "input_status.json"
    config_path = str((tmp_path / "config.yaml").resolve())
    input_status.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "all_present": True,
                "space_ok": True,
                "space_check_skipped": False,
                "min_free_gb": 100.0,
                "filesystems": _complete_input_filesystems(tmp_path),
                "missing": [],
                "domains": [{"name": "encounter"}],
                "generated_at": "2026-06-08T00:00:00+00:00",
                "config_path": config_path,
                "config_sha256": PROFILE_CONFIG_SHA256,
            }
        )
    )
    legacy_manifest = tmp_path / "legacy_manifest"
    refactor_manifest = tmp_path / "refactor_manifest"
    _write_legacy_manifest(legacy_manifest, tmp_path)
    _write_refactor_manifest(refactor_manifest, tmp_path)
    comparison_report = tmp_path / "final_comparison.json"
    _write_comparison_report(comparison_report, legacy_manifest, refactor_manifest)
    profile_provenance = tmp_path / "profile" / "provenance.json"
    profile_provenance.parent.mkdir()
    profile_provenance.write_text(
        json.dumps(_complete_profile_provenance_payload(tmp_path))
    )
    required_root = tmp_path / "external"

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "trinetx_preprocessing",
            "validation-status",
            "--input-status",
            str(input_status),
            "--legacy-manifest",
            str(legacy_manifest),
            "--refactor-manifest",
            str(refactor_manifest),
            "--comparison-report",
            str(comparison_report),
            "--profile-provenance",
            str(profile_provenance),
            "--required-root",
            str(required_root),
            "--json",
        ],
        cwd=ROOT,
        env=_build_env(),
        capture_output=True,
        text=True,
        check=False,
    )

    payload = json.loads(result.stdout)
    root_check = payload["checks"]["required_root"]

    assert result.returncode == 1
    assert payload["ready"] is False
    assert root_check["ok"] is False
    assert root_check["required_root"] == str(required_root.resolve())
    assert root_check["blocker_count"] > 0
    assert "input_status_artifact must be under required root" in root_check["blockers"]


def test_required_root_check_rejects_low_free_space(tmp_path: Path) -> None:
    payload = cli_module._required_root_check(
        required_root=tmp_path,
        min_free_gb=10**12,
        input_status=None,
        legacy_manifest=None,
        refactor_manifest=None,
        comparison_report=None,
        profile_provenance=None,
        input_status_check={},
        profile_provenance_check={},
    )

    assert payload["ok"] is False
    assert payload["space_ok"] is False
    assert "required root free_gb below min_free_gb" in payload["blockers"]


def test_validation_status_cli_rejects_old_input_status_schema(
    tmp_path: Path,
) -> None:
    input_status = tmp_path / "input_status.json"
    config_path = str((tmp_path / "config.yaml").resolve())
    input_status.write_text(
        json.dumps(
            {
                "schema_version": 0,
                "all_present": True,
                "space_ok": True,
                "space_check_skipped": False,
                "min_free_gb": 100.0,
                "filesystems": _complete_input_filesystems(tmp_path),
                "missing": [],
                "timed_out": [],
                "probe_errors": {},
                "domains": [
                    {
                        "name": "encounter",
                        "matched_count": 1,
                        "matched_count_exact": True,
                        "timed_out": False,
                        "probe_error": None,
                    }
                ],
                "generated_at": "2026-06-08T00:00:00+00:00",
                "config_path": config_path,
                "config_sha256": PROFILE_CONFIG_SHA256,
            }
        )
    )
    legacy_manifest = tmp_path / "legacy_manifest"
    refactor_manifest = tmp_path / "refactor_manifest"
    _write_legacy_manifest(legacy_manifest, tmp_path)
    _write_refactor_manifest(refactor_manifest, tmp_path)
    comparison_report = tmp_path / "final_comparison.json"
    _write_comparison_report(comparison_report, legacy_manifest, refactor_manifest)
    profile_provenance = tmp_path / "profile" / "provenance.json"
    profile_provenance.parent.mkdir()
    profile_provenance.write_text(
        json.dumps(_complete_profile_provenance_payload(tmp_path))
    )

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "trinetx_preprocessing",
            "validation-status",
            "--input-status",
            str(input_status),
            "--legacy-manifest",
            str(legacy_manifest),
            "--refactor-manifest",
            str(refactor_manifest),
            "--comparison-report",
            str(comparison_report),
            "--profile-provenance",
            str(profile_provenance),
            "--json",
        ],
        cwd=ROOT,
        env=_build_env(),
        capture_output=True,
        text=True,
        check=False,
    )

    payload = json.loads(result.stdout)
    input_check = payload["checks"]["input_status"]

    assert result.returncode == 1
    assert payload["ready"] is False
    assert input_check["ok"] is False
    assert input_check["schema_version"] == 0
    assert input_check["expected_schema_version"] == 1
    assert input_check["schema_current"] is False
    assert input_check["message"] == "input status schema is stale or missing"


def test_validation_status_cli_rejects_manifest_without_row_and_column_metadata(
    tmp_path: Path,
) -> None:
    input_status = tmp_path / "input_status.json"
    config_path = str((tmp_path / "config.yaml").resolve())
    input_status.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "all_present": True,
                "space_ok": True,
                "space_check_skipped": False,
                "min_free_gb": 100.0,
                "filesystems": _complete_input_filesystems(tmp_path),
                "missing": [],
                "timed_out": [],
                "probe_errors": {},
                "domains": [
                    {
                        "name": "encounter",
                        "matched_count": 1,
                        "matched_count_exact": True,
                        "timed_out": False,
                        "probe_error": None,
                    }
                ],
                "generated_at": "2026-06-08T00:00:00+00:00",
                "config_path": config_path,
                "config_sha256": PROFILE_CONFIG_SHA256,
            }
        )
    )
    legacy_manifest = tmp_path / "legacy_manifest"
    refactor_manifest = tmp_path / "refactor_manifest"
    write_hash_manifest(
        legacy_manifest,
        {"output_dir/a.csv": "abc"},
        scope="final",
        output_dir=tmp_path / "legacy_output",
    )
    _write_refactor_manifest(refactor_manifest, tmp_path)
    comparison_report = tmp_path / "final_comparison.json"
    comparison_report.write_text(
        json.dumps(
            {
                "ok": True,
                "baseline": str(legacy_manifest.resolve()),
                "current": str(refactor_manifest.resolve()),
                "counts": {
                    "missing": 0,
                    "extra": 0,
                    "hash_mismatched": 0,
                    "row_count_mismatched": 0,
                    "columns_mismatched": 0,
                },
                "generated_at": "2026-06-08T00:00:00+00:00",
            }
        )
    )
    profile_provenance = tmp_path / "profile" / "provenance.json"
    profile_provenance.parent.mkdir()
    profile_provenance.write_text(
        json.dumps(_complete_profile_provenance_payload(tmp_path))
    )

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "trinetx_preprocessing",
            "validation-status",
            "--input-status",
            str(input_status),
            "--legacy-manifest",
            str(legacy_manifest),
            "--refactor-manifest",
            str(refactor_manifest),
            "--comparison-report",
            str(comparison_report),
            "--profile-provenance",
            str(profile_provenance),
            "--json",
        ],
        cwd=ROOT,
        env=_build_env(),
        capture_output=True,
        text=True,
        check=False,
    )

    payload = json.loads(result.stdout)
    legacy_check = payload["checks"]["legacy_manifest"]

    assert result.returncode == 1
    assert payload["ready"] is False
    assert legacy_check["ok"] is False
    assert legacy_check["metadata_complete"] is False
    assert legacy_check["message"] == "manifest metadata incomplete"
    assert legacy_check["metadata_blocker_count"] == 3
    assert legacy_check["metadata_blockers"] == [
        "output_dir/a.csv: row_count must be a nonnegative integer",
        "output_dir/a.csv: columns metadata missing",
        "output_dir/a.csv: physical_format must be csv",
    ]


def test_validation_status_cli_rejects_manifest_missing_scope_metadata(
    tmp_path: Path,
) -> None:
    input_status = tmp_path / "input_status.json"
    config_path = str((tmp_path / "config.yaml").resolve())
    input_status.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "all_present": True,
                "space_ok": True,
                "space_check_skipped": False,
                "min_free_gb": 100.0,
                "filesystems": _complete_input_filesystems(tmp_path),
                "missing": [],
                "timed_out": [],
                "probe_errors": {},
                "domains": [
                    {
                        "name": "encounter",
                        "matched_count": 1,
                        "matched_count_exact": True,
                        "timed_out": False,
                        "probe_error": None,
                    }
                ],
                "generated_at": "2026-06-08T00:00:00+00:00",
                "config_path": config_path,
                "config_sha256": PROFILE_CONFIG_SHA256,
            }
        )
    )
    source_path = tmp_path / "legacy_output" / "a.csv"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_text("patient_id\n1\n")
    legacy_manifest = tmp_path / "legacy_manifest"
    refactor_manifest = tmp_path / "refactor_manifest"
    write_hash_manifest(
        legacy_manifest,
        {
            "output_dir/a.csv": _table_entry_for_source(
                key="output_dir/a.csv",
                source_path=source_path,
            )
        },
    )
    _write_refactor_manifest(refactor_manifest, tmp_path)
    comparison_report = tmp_path / "final_comparison.json"
    _write_comparison_report(comparison_report, legacy_manifest, refactor_manifest)
    profile_provenance = tmp_path / "profile" / "provenance.json"
    profile_provenance.parent.mkdir()
    profile_provenance.write_text(
        json.dumps(_complete_profile_provenance_payload(tmp_path))
    )

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "trinetx_preprocessing",
            "validation-status",
            "--input-status",
            str(input_status),
            "--legacy-manifest",
            str(legacy_manifest),
            "--refactor-manifest",
            str(refactor_manifest),
            "--comparison-report",
            str(comparison_report),
            "--profile-provenance",
            str(profile_provenance),
            "--json",
        ],
        cwd=ROOT,
        env=_build_env(),
        capture_output=True,
        text=True,
        check=False,
    )

    payload = json.loads(result.stdout)
    legacy_check = payload["checks"]["legacy_manifest"]

    assert result.returncode == 1
    assert payload["ready"] is False
    assert legacy_check["ok"] is False
    assert legacy_check["header_complete"] is False
    assert legacy_check["manifest_scope"] is None
    assert legacy_check["manifest_output_dir"] is None
    assert legacy_check["message"] == "manifest header metadata incomplete"
    assert legacy_check["header_blockers"] == [
        "scope must be final",
        "output_dir must be present",
    ]


def test_validation_status_cli_rejects_manifest_with_wrong_hash_algorithm(
    tmp_path: Path,
) -> None:
    input_status = tmp_path / "input_status.json"
    config_path = str((tmp_path / "config.yaml").resolve())
    input_status.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "all_present": True,
                "space_ok": True,
                "space_check_skipped": False,
                "min_free_gb": 100.0,
                "filesystems": _complete_input_filesystems(tmp_path),
                "missing": [],
                "timed_out": [],
                "probe_errors": {},
                "domains": [
                    {
                        "name": "encounter",
                        "matched_count": 1,
                        "matched_count_exact": True,
                        "timed_out": False,
                        "probe_error": None,
                    }
                ],
                "generated_at": "2026-06-08T00:00:00+00:00",
                "config_path": config_path,
                "config_sha256": PROFILE_CONFIG_SHA256,
            }
        )
    )
    legacy_manifest = tmp_path / "legacy_manifest"
    refactor_manifest = tmp_path / "refactor_manifest"
    _write_legacy_manifest(legacy_manifest, tmp_path)
    legacy_manifest_json = json.loads((legacy_manifest / "hashes.json").read_text())
    legacy_manifest_json["hash_algorithm"] = "md5"
    (legacy_manifest / "hashes.json").write_text(json.dumps(legacy_manifest_json))
    _write_refactor_manifest(refactor_manifest, tmp_path)
    comparison_report = tmp_path / "final_comparison.json"
    _write_comparison_report(comparison_report, legacy_manifest, refactor_manifest)
    profile_provenance = tmp_path / "profile" / "provenance.json"
    profile_provenance.parent.mkdir()
    profile_provenance.write_text(
        json.dumps(_complete_profile_provenance_payload(tmp_path))
    )

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "trinetx_preprocessing",
            "validation-status",
            "--input-status",
            str(input_status),
            "--legacy-manifest",
            str(legacy_manifest),
            "--refactor-manifest",
            str(refactor_manifest),
            "--comparison-report",
            str(comparison_report),
            "--profile-provenance",
            str(profile_provenance),
            "--json",
        ],
        cwd=ROOT,
        env=_build_env(),
        capture_output=True,
        text=True,
        check=False,
    )

    payload = json.loads(result.stdout)
    legacy_check = payload["checks"]["legacy_manifest"]

    assert result.returncode == 1
    assert payload["ready"] is False
    assert legacy_check["ok"] is False
    assert legacy_check["message"] == "manifest header metadata incomplete"
    assert legacy_check["manifest_schema_version"] == 2
    assert legacy_check["hash_algorithm"] == "md5"
    assert legacy_check["header_complete"] is False
    assert legacy_check["header_blockers"] == ["hash_algorithm must be sha256"]


def test_validation_status_cli_rejects_final_manifest_with_parquet_table(
    tmp_path: Path,
) -> None:
    input_status = tmp_path / "input_status.json"
    config_path = str((tmp_path / "config.yaml").resolve())
    input_status.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "all_present": True,
                "space_ok": True,
                "space_check_skipped": False,
                "min_free_gb": 100.0,
                "filesystems": _complete_input_filesystems(tmp_path),
                "missing": [],
                "timed_out": [],
                "probe_errors": {},
                "domains": [
                    {
                        "name": "encounter",
                        "matched_count": 1,
                        "matched_count_exact": True,
                        "timed_out": False,
                        "probe_error": None,
                    }
                ],
                "generated_at": "2026-06-08T00:00:00+00:00",
                "config_path": config_path,
                "config_sha256": PROFILE_CONFIG_SHA256,
            }
        )
    )
    legacy_manifest = tmp_path / "legacy_manifest"
    refactor_manifest = tmp_path / "refactor_manifest"
    source_path = tmp_path / "legacy_output" / "a.parquet"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_bytes(b"not-real-parquet")
    write_hash_manifest(
        legacy_manifest,
        {
            "output_dir/a.parquet": _table_entry_for_source(
                key="output_dir/a.parquet",
                physical_format="parquet",
                source_path=source_path,
            )
        },
        scope="final",
        output_dir=tmp_path / "legacy_output",
    )
    _write_refactor_manifest(refactor_manifest, tmp_path)
    comparison_report = tmp_path / "final_comparison.json"
    _write_comparison_report(comparison_report, legacy_manifest, refactor_manifest)
    profile_provenance = tmp_path / "profile" / "provenance.json"
    profile_provenance.parent.mkdir()
    profile_provenance.write_text(
        json.dumps(_complete_profile_provenance_payload(tmp_path))
    )

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "trinetx_preprocessing",
            "validation-status",
            "--input-status",
            str(input_status),
            "--legacy-manifest",
            str(legacy_manifest),
            "--refactor-manifest",
            str(refactor_manifest),
            "--comparison-report",
            str(comparison_report),
            "--profile-provenance",
            str(profile_provenance),
            "--json",
        ],
        cwd=ROOT,
        env=_build_env(),
        capture_output=True,
        text=True,
        check=False,
    )

    payload = json.loads(result.stdout)
    legacy_check = payload["checks"]["legacy_manifest"]

    assert result.returncode == 1
    assert payload["ready"] is False
    assert legacy_check["ok"] is False
    assert legacy_check["metadata_complete"] is False
    assert legacy_check["message"] == "manifest metadata incomplete"
    assert legacy_check["metadata_blockers"] == [
        "output_dir/a.parquet: final output key must end with .csv",
        "output_dir/a.parquet: physical_format must be csv",
    ]


def test_validation_status_cli_rejects_manifest_with_non_csv_source_path(
    tmp_path: Path,
) -> None:
    input_status = tmp_path / "input_status.json"
    config_path = str((tmp_path / "config.yaml").resolve())
    input_status.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "all_present": True,
                "space_ok": True,
                "space_check_skipped": False,
                "min_free_gb": 100.0,
                "filesystems": _complete_input_filesystems(tmp_path),
                "missing": [],
                "timed_out": [],
                "probe_errors": {},
                "domains": [
                    {
                        "name": "encounter",
                        "matched_count": 1,
                        "matched_count_exact": True,
                        "timed_out": False,
                        "probe_error": None,
                    }
                ],
                "generated_at": "2026-06-08T00:00:00+00:00",
                "config_path": config_path,
                "config_sha256": PROFILE_CONFIG_SHA256,
            }
        )
    )
    legacy_manifest = tmp_path / "legacy_manifest"
    refactor_manifest = tmp_path / "refactor_manifest"
    source_path = tmp_path / "legacy_output" / "a.txt"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_text("patient_id\n1\n")
    write_hash_manifest(
        legacy_manifest,
        {
            "output_dir/a.csv": _table_entry_for_source(
                key="output_dir/a.csv",
                source_path=source_path,
            )
        },
        scope="final",
        output_dir=tmp_path / "legacy_output",
    )
    _write_refactor_manifest(refactor_manifest, tmp_path)
    comparison_report = tmp_path / "final_comparison.json"
    _write_comparison_report(comparison_report, legacy_manifest, refactor_manifest)
    profile_provenance = tmp_path / "profile" / "provenance.json"
    profile_provenance.parent.mkdir()
    profile_provenance.write_text(
        json.dumps(_complete_profile_provenance_payload(tmp_path))
    )

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "trinetx_preprocessing",
            "validation-status",
            "--input-status",
            str(input_status),
            "--legacy-manifest",
            str(legacy_manifest),
            "--refactor-manifest",
            str(refactor_manifest),
            "--comparison-report",
            str(comparison_report),
            "--profile-provenance",
            str(profile_provenance),
            "--json",
        ],
        cwd=ROOT,
        env=_build_env(),
        capture_output=True,
        text=True,
        check=False,
    )

    payload = json.loads(result.stdout)
    legacy_check = payload["checks"]["legacy_manifest"]

    assert result.returncode == 1
    assert payload["ready"] is False
    assert legacy_check["ok"] is False
    assert legacy_check["source_paths_available"] is False
    assert legacy_check["message"] == "manifest source files unavailable or mismatched"
    assert legacy_check["source_path_blockers"] == [
        "output_dir/a.csv: source_path must be a CSV file",
        "output_dir/a.csv: source_path filename must match manifest key",
    ]


def test_validation_status_cli_rejects_manifest_with_mismatched_source_filename(
    tmp_path: Path,
) -> None:
    input_status = tmp_path / "input_status.json"
    config_path = str((tmp_path / "config.yaml").resolve())
    input_status.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "all_present": True,
                "space_ok": True,
                "space_check_skipped": False,
                "min_free_gb": 100.0,
                "filesystems": _complete_input_filesystems(tmp_path),
                "missing": [],
                "timed_out": [],
                "probe_errors": {},
                "domains": [
                    {
                        "name": "encounter",
                        "matched_count": 1,
                        "matched_count_exact": True,
                        "timed_out": False,
                        "probe_error": None,
                    }
                ],
                "generated_at": "2026-06-08T00:00:00+00:00",
                "config_path": config_path,
                "config_sha256": PROFILE_CONFIG_SHA256,
            }
        )
    )
    legacy_manifest = tmp_path / "legacy_manifest"
    refactor_manifest = tmp_path / "refactor_manifest"
    source_path = tmp_path / "legacy_output" / "b.csv"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_text("patient_id\n1\n")
    write_hash_manifest(
        legacy_manifest,
        {
            "output_dir/a.csv": _table_entry_for_source(
                key="output_dir/a.csv",
                source_path=source_path,
            )
        },
        scope="final",
        output_dir=tmp_path / "legacy_output",
    )
    _write_refactor_manifest(refactor_manifest, tmp_path)
    comparison_report = tmp_path / "final_comparison.json"
    _write_comparison_report(comparison_report, legacy_manifest, refactor_manifest)
    profile_provenance = tmp_path / "profile" / "provenance.json"
    profile_provenance.parent.mkdir()
    profile_provenance.write_text(
        json.dumps(_complete_profile_provenance_payload(tmp_path))
    )

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "trinetx_preprocessing",
            "validation-status",
            "--input-status",
            str(input_status),
            "--legacy-manifest",
            str(legacy_manifest),
            "--refactor-manifest",
            str(refactor_manifest),
            "--comparison-report",
            str(comparison_report),
            "--profile-provenance",
            str(profile_provenance),
            "--json",
        ],
        cwd=ROOT,
        env=_build_env(),
        capture_output=True,
        text=True,
        check=False,
    )

    payload = json.loads(result.stdout)
    legacy_check = payload["checks"]["legacy_manifest"]

    assert result.returncode == 1
    assert payload["ready"] is False
    assert legacy_check["ok"] is False
    assert legacy_check["source_paths_available"] is False
    assert legacy_check["message"] == "manifest source files unavailable or mismatched"
    assert legacy_check["source_path_blockers"] == [
        "output_dir/a.csv: source_path filename must match manifest key"
    ]


def test_validation_status_cli_rejects_manifest_with_missing_source_file(
    tmp_path: Path,
) -> None:
    input_status = tmp_path / "input_status.json"
    config_path = str((tmp_path / "config.yaml").resolve())
    input_status.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "all_present": True,
                "space_ok": True,
                "space_check_skipped": False,
                "min_free_gb": 100.0,
                "filesystems": _complete_input_filesystems(tmp_path),
                "missing": [],
                "timed_out": [],
                "probe_errors": {},
                "domains": [
                    {
                        "name": "encounter",
                        "matched_count": 1,
                        "matched_count_exact": True,
                        "timed_out": False,
                        "probe_error": None,
                    }
                ],
                "generated_at": "2026-06-08T00:00:00+00:00",
                "config_path": config_path,
                "config_sha256": PROFILE_CONFIG_SHA256,
            }
        )
    )
    legacy_manifest = tmp_path / "legacy_manifest"
    refactor_manifest = tmp_path / "refactor_manifest"
    _write_legacy_manifest(legacy_manifest, tmp_path)
    (tmp_path / "legacy_output" / "a.csv").unlink()
    _write_refactor_manifest(refactor_manifest, tmp_path)
    comparison_report = tmp_path / "final_comparison.json"
    _write_comparison_report(comparison_report, legacy_manifest, refactor_manifest)
    profile_provenance = tmp_path / "profile" / "provenance.json"
    profile_provenance.parent.mkdir()
    profile_provenance.write_text(
        json.dumps(_complete_profile_provenance_payload(tmp_path))
    )

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "trinetx_preprocessing",
            "validation-status",
            "--input-status",
            str(input_status),
            "--legacy-manifest",
            str(legacy_manifest),
            "--refactor-manifest",
            str(refactor_manifest),
            "--comparison-report",
            str(comparison_report),
            "--profile-provenance",
            str(profile_provenance),
            "--json",
        ],
        cwd=ROOT,
        env=_build_env(),
        capture_output=True,
        text=True,
        check=False,
    )

    payload = json.loads(result.stdout)
    legacy_check = payload["checks"]["legacy_manifest"]

    assert result.returncode == 1
    assert payload["ready"] is False
    assert legacy_check["ok"] is False
    assert legacy_check["metadata_complete"] is True
    assert legacy_check["final_scope"] is True
    assert legacy_check["source_paths_available"] is False
    assert legacy_check["message"] == "manifest source files unavailable or mismatched"
    assert legacy_check["source_path_blocker_count"] == 1
    assert legacy_check["source_path_blockers"] == [
        "output_dir/a.csv: source_path file does not exist"
    ]


def test_validation_status_cli_rejects_manifest_with_stale_source_file_stats(
    tmp_path: Path,
) -> None:
    input_status = tmp_path / "input_status.json"
    config_path = str((tmp_path / "config.yaml").resolve())
    input_status.write_text(
        json.dumps(
            {
                "all_present": True,
                "space_ok": True,
                "space_check_skipped": False,
                "min_free_gb": 100.0,
                "filesystems": _complete_input_filesystems(tmp_path),
                "missing": [],
                "timed_out": [],
                "probe_errors": {},
                "domains": [
                    {
                        "name": "encounter",
                        "matched_count": 1,
                        "matched_count_exact": True,
                        "timed_out": False,
                        "probe_error": None,
                    }
                ],
                "generated_at": "2026-06-08T00:00:00+00:00",
                "config_path": config_path,
                "config_sha256": PROFILE_CONFIG_SHA256,
            }
        )
    )
    legacy_manifest = tmp_path / "legacy_manifest"
    refactor_manifest = tmp_path / "refactor_manifest"
    _write_legacy_manifest(legacy_manifest, tmp_path)
    (tmp_path / "legacy_output" / "a.csv").write_text("patient_id\n1\n2\n")
    _write_refactor_manifest(refactor_manifest, tmp_path)
    comparison_report = tmp_path / "final_comparison.json"
    _write_comparison_report(comparison_report, legacy_manifest, refactor_manifest)
    profile_provenance = tmp_path / "profile" / "provenance.json"
    profile_provenance.parent.mkdir()
    profile_provenance.write_text(
        json.dumps(_complete_profile_provenance_payload(tmp_path))
    )

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "trinetx_preprocessing",
            "validation-status",
            "--input-status",
            str(input_status),
            "--legacy-manifest",
            str(legacy_manifest),
            "--refactor-manifest",
            str(refactor_manifest),
            "--comparison-report",
            str(comparison_report),
            "--profile-provenance",
            str(profile_provenance),
            "--json",
        ],
        cwd=ROOT,
        env=_build_env(),
        capture_output=True,
        text=True,
        check=False,
    )

    payload = json.loads(result.stdout)
    legacy_check = payload["checks"]["legacy_manifest"]

    assert result.returncode == 1
    assert payload["ready"] is False
    assert legacy_check["ok"] is False
    assert legacy_check["source_paths_available"] is False
    assert legacy_check["message"] == "manifest source files unavailable or mismatched"
    assert (
        "output_dir/a.csv: source_size_bytes does not match current file size"
        in legacy_check["source_path_blockers"]
    )


def test_validation_status_cli_rejects_non_final_scope_manifest(
    tmp_path: Path,
) -> None:
    input_status = tmp_path / "input_status.json"
    markdown_path = tmp_path / "validation_status.md"
    config_path = str((tmp_path / "config.yaml").resolve())
    input_status.write_text(
        json.dumps(
            {
                "all_present": True,
                "space_ok": True,
                "space_check_skipped": False,
                "min_free_gb": 100.0,
                "filesystems": _complete_input_filesystems(tmp_path),
                "missing": [],
                "timed_out": [],
                "probe_errors": {},
                "domains": [
                    {
                        "name": "encounter",
                        "matched_count": 1,
                        "matched_count_exact": True,
                        "timed_out": False,
                        "probe_error": None,
                    }
                ],
                "generated_at": "2026-06-08T00:00:00+00:00",
                "config_path": config_path,
                "config_sha256": PROFILE_CONFIG_SHA256,
            }
        )
    )
    legacy_manifest = tmp_path / "legacy_manifest"
    refactor_manifest = tmp_path / "refactor_manifest"
    _write_work_scope_manifest(legacy_manifest, tmp_path)
    _write_refactor_manifest(refactor_manifest, tmp_path)
    comparison_report = tmp_path / "final_comparison.json"
    comparison_report.write_text(
        json.dumps(
            {
                "ok": True,
                "baseline": str(legacy_manifest.resolve()),
                "current": str(refactor_manifest.resolve()),
                "counts": {
                    "missing": 0,
                    "extra": 0,
                    "hash_mismatched": 0,
                    "row_count_mismatched": 0,
                    "columns_mismatched": 0,
                },
                "generated_at": "2026-06-08T00:00:00+00:00",
            }
        )
    )
    profile_provenance = tmp_path / "profile" / "provenance.json"
    profile_provenance.parent.mkdir()
    profile_provenance.write_text(
        json.dumps(_complete_profile_provenance_payload(tmp_path))
    )

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "trinetx_preprocessing",
            "validation-status",
            "--input-status",
            str(input_status),
            "--legacy-manifest",
            str(legacy_manifest),
            "--refactor-manifest",
            str(refactor_manifest),
            "--comparison-report",
            str(comparison_report),
            "--profile-provenance",
            str(profile_provenance),
            "--markdown-out",
            str(markdown_path),
            "--json",
        ],
        cwd=ROOT,
        env=_build_env(),
        capture_output=True,
        text=True,
        check=False,
    )

    payload = json.loads(result.stdout)
    legacy_check = payload["checks"]["legacy_manifest"]

    assert result.returncode == 1
    assert payload["ready"] is False
    assert legacy_check["ok"] is False
    assert legacy_check["metadata_complete"] is True
    assert legacy_check["final_scope"] is False
    assert legacy_check["message"] == "manifest includes non-final output keys"
    assert legacy_check["final_scope_blocker_count"] == 1
    assert legacy_check["final_scope_blockers"] == [
        "work_dir/a.csv: key must be under output_dir/"
    ]
    assert legacy_check["non_final_key_count"] == 1
    assert legacy_check["non_final_keys"] == ["work_dir/a.csv"]
    markdown = markdown_path.read_text()
    assert (
        "| `legacy_manifest` | work_dir/a.csv: key must be under output_dir/ |"
        in markdown
    )


def test_validation_status_cli_rejects_capped_input_status(
    tmp_path: Path,
) -> None:
    input_status = tmp_path / "input_status.json"
    config_path = str((tmp_path / "config.yaml").resolve())
    input_status.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "all_present": True,
                "space_ok": True,
                "space_check_skipped": False,
                "min_free_gb": 100.0,
                "filesystems": _complete_input_filesystems(tmp_path),
                "max_matches": 1,
                "domain_timeout_seconds": None,
                "missing": [],
                "timed_out": [],
                "probe_errors": {},
                "domains": [
                    {
                        "name": "encounter",
                        "matched_count": 1,
                        "matched_count_exact": False,
                        "timed_out": False,
                        "probe_error": None,
                    }
                ],
                "generated_at": "2026-06-08T00:00:00+00:00",
                "config_path": config_path,
                "config_sha256": PROFILE_CONFIG_SHA256,
            }
        )
    )
    legacy_manifest = tmp_path / "legacy_manifest"
    refactor_manifest = tmp_path / "refactor_manifest"
    _write_legacy_manifest(legacy_manifest, tmp_path)
    _write_refactor_manifest(refactor_manifest, tmp_path)
    comparison_report = tmp_path / "final_comparison.json"
    comparison_report.write_text(
        json.dumps(
            {
                "ok": True,
                "baseline": str(legacy_manifest.resolve()),
                "current": str(refactor_manifest.resolve()),
                "counts": {
                    "missing": 0,
                    "extra": 0,
                    "hash_mismatched": 0,
                    "row_count_mismatched": 0,
                    "columns_mismatched": 0,
                },
                "generated_at": "2026-06-08T00:00:00+00:00",
            }
        )
    )
    profile_provenance = tmp_path / "profile" / "provenance.json"
    profile_provenance.parent.mkdir()
    profile_provenance.write_text(
        json.dumps(_complete_profile_provenance_payload(tmp_path))
    )

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "trinetx_preprocessing",
            "validation-status",
            "--input-status",
            str(input_status),
            "--legacy-manifest",
            str(legacy_manifest),
            "--refactor-manifest",
            str(refactor_manifest),
            "--comparison-report",
            str(comparison_report),
            "--profile-provenance",
            str(profile_provenance),
            "--json",
        ],
        cwd=ROOT,
        env=_build_env(),
        capture_output=True,
        text=True,
        check=False,
    )

    payload = json.loads(result.stdout)

    assert result.returncode == 1
    assert payload["ready"] is False
    assert payload["checks"]["input_status"]["ok"] is False
    assert payload["checks"]["input_status"]["exact_input_status"] is False
    assert (
        payload["checks"]["input_status"]["message"]
        == "input status is capped or timeout-based"
    )
    assert (
        "input status was capped with max_matches"
        in payload["checks"]["input_status"]["blockers"]
    )
    assert (
        "input domain counts are capped: encounter"
        in payload["checks"]["input_status"]["blockers"]
    )


def test_validation_status_cli_rejects_missing_free_space_threshold(
    tmp_path: Path,
) -> None:
    input_status = tmp_path / "input_status.json"
    config_path = str((tmp_path / "config.yaml").resolve())
    input_status.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "all_present": True,
                "space_ok": True,
                "space_check_skipped": False,
                "missing": [],
                "timed_out": [],
                "probe_errors": {},
                "domains": [
                    {
                        "name": "encounter",
                        "matched_count": 1,
                        "matched_count_exact": True,
                        "timed_out": False,
                        "probe_error": None,
                    }
                ],
                "generated_at": "2026-06-08T00:00:00+00:00",
                "config_path": config_path,
                "config_sha256": PROFILE_CONFIG_SHA256,
            }
        )
    )
    legacy_manifest = tmp_path / "legacy_manifest"
    refactor_manifest = tmp_path / "refactor_manifest"
    _write_legacy_manifest(legacy_manifest, tmp_path)
    _write_refactor_manifest(refactor_manifest, tmp_path)
    comparison_report = tmp_path / "final_comparison.json"
    comparison_report.write_text(
        json.dumps(
            {
                "ok": True,
                "baseline": str(legacy_manifest.resolve()),
                "current": str(refactor_manifest.resolve()),
                "counts": {
                    "missing": 0,
                    "extra": 0,
                    "hash_mismatched": 0,
                    "row_count_mismatched": 0,
                    "columns_mismatched": 0,
                },
                "generated_at": "2026-06-08T00:00:00+00:00",
            }
        )
    )
    profile_provenance = tmp_path / "profile" / "provenance.json"
    profile_provenance.parent.mkdir()
    profile_provenance.write_text(
        json.dumps(_complete_profile_provenance_payload(tmp_path))
    )

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "trinetx_preprocessing",
            "validation-status",
            "--input-status",
            str(input_status),
            "--legacy-manifest",
            str(legacy_manifest),
            "--refactor-manifest",
            str(refactor_manifest),
            "--comparison-report",
            str(comparison_report),
            "--profile-provenance",
            str(profile_provenance),
            "--json",
        ],
        cwd=ROOT,
        env=_build_env(),
        capture_output=True,
        text=True,
        check=False,
    )

    payload = json.loads(result.stdout)
    input_check = payload["checks"]["input_status"]

    assert result.returncode == 1
    assert payload["ready"] is False
    assert input_check["ok"] is False
    assert input_check["space_evidence_ok"] is False
    assert input_check["message"] == "free-space evidence missing or below threshold"
    assert "min_free_gb must be at least 100" in input_check["space_evidence_blockers"]
    assert "filesystems must be a list" in input_check["space_evidence_blockers"]


def test_validation_status_cli_rejects_incomplete_profile_provenance(
    tmp_path: Path,
) -> None:
    input_status = tmp_path / "input_status.json"
    config_path = str((tmp_path / "config.yaml").resolve())
    input_status.write_text(
        json.dumps(
            {
                "all_present": True,
                "space_ok": True,
                "space_check_skipped": False,
                "min_free_gb": 100.0,
                "filesystems": _complete_input_filesystems(tmp_path),
                "missing": [],
                "timed_out": [],
                "probe_errors": {},
                "domains": [
                    {
                        "name": "encounter",
                        "matched_count": 1,
                        "matched_count_exact": True,
                        "timed_out": False,
                        "probe_error": None,
                    }
                ],
                "generated_at": "2026-06-08T00:00:00+00:00",
                "config_path": config_path,
                "config_sha256": PROFILE_CONFIG_SHA256,
            }
        )
    )
    legacy_manifest = tmp_path / "legacy_manifest"
    refactor_manifest = tmp_path / "refactor_manifest"
    _write_legacy_manifest(legacy_manifest, tmp_path)
    _write_refactor_manifest(refactor_manifest, tmp_path)
    comparison_report = tmp_path / "final_comparison.json"
    comparison_report.write_text(
        json.dumps(
            {
                "ok": True,
                "baseline": str(legacy_manifest.resolve()),
                "current": str(refactor_manifest.resolve()),
                "counts": {
                    "missing": 0,
                    "extra": 0,
                    "hash_mismatched": 0,
                    "row_count_mismatched": 0,
                    "columns_mismatched": 0,
                },
                "generated_at": "2026-06-08T00:00:00+00:00",
            }
        )
    )
    profile_provenance = tmp_path / "profile" / "provenance.json"
    profile_provenance.parent.mkdir()
    profile_payload = _complete_profile_provenance_payload(tmp_path)
    profile_payload["disk_footprint_bytes"] = {"work_dir": 100}
    profile_payload["generated_file_count"] = 0
    profile_payload["output_files"] = []
    profile_payload.pop("config_sha256")
    profile_payload.pop("stage_timings_seconds")
    profile_provenance.write_text(json.dumps(profile_payload))

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "trinetx_preprocessing",
            "validation-status",
            "--input-status",
            str(input_status),
            "--legacy-manifest",
            str(legacy_manifest),
            "--refactor-manifest",
            str(refactor_manifest),
            "--comparison-report",
            str(comparison_report),
            "--profile-provenance",
            str(profile_provenance),
            "--json",
        ],
        cwd=ROOT,
        env=_build_env(),
        capture_output=True,
        text=True,
        check=False,
    )

    payload = json.loads(result.stdout)
    profile_check = payload["checks"]["profile_provenance"]

    assert result.returncode == 1
    assert payload["ready"] is False
    assert profile_check["ok"] is False
    assert (
        "disk_footprint_bytes.output_dir must be a nonnegative integer"
        in profile_check["blockers"]
    )
    assert "stage_timings_seconds must be a mapping" in profile_check["blockers"]
    assert "config_sha256 must be a SHA-256 hex digest" in profile_check["blockers"]
    assert (
        "generated_file_count must be a positive integer" in profile_check["blockers"]
    )
    assert (
        "output_files length must match output_file_count" in profile_check["blockers"]
    )


def test_validation_status_cli_rejects_non_strict_profile_provenance(
    tmp_path: Path,
) -> None:
    input_status = tmp_path / "input_status.json"
    config_path = str((tmp_path / "config.yaml").resolve())
    input_status.write_text(
        json.dumps(
            {
                "all_present": True,
                "space_ok": True,
                "space_check_skipped": False,
                "min_free_gb": 100.0,
                "filesystems": _complete_input_filesystems(tmp_path),
                "missing": [],
                "timed_out": [],
                "probe_errors": {},
                "domains": [
                    {
                        "name": "encounter",
                        "matched_count": 1,
                        "matched_count_exact": True,
                        "timed_out": False,
                        "probe_error": None,
                    }
                ],
                "generated_at": "2026-06-08T00:00:00+00:00",
                "config_path": config_path,
                "config_sha256": PROFILE_CONFIG_SHA256,
            }
        )
    )
    legacy_manifest = tmp_path / "legacy_manifest"
    refactor_manifest = tmp_path / "refactor_manifest"
    _write_legacy_manifest(legacy_manifest, tmp_path)
    _write_refactor_manifest(refactor_manifest, tmp_path)
    comparison_report = tmp_path / "final_comparison.json"
    comparison_report.write_text(
        json.dumps(
            {
                "ok": True,
                "baseline": str(legacy_manifest.resolve()),
                "current": str(refactor_manifest.resolve()),
                "counts": {
                    "missing": 0,
                    "extra": 0,
                    "hash_mismatched": 0,
                    "row_count_mismatched": 0,
                    "columns_mismatched": 0,
                },
                "generated_at": "2026-06-08T00:00:00+00:00",
            }
        )
    )
    profile_provenance = tmp_path / "profile" / "provenance.json"
    profile_provenance.parent.mkdir()
    profile_payload = _complete_profile_provenance_payload(tmp_path)
    profile_payload["strict"] = False
    profile_provenance.write_text(json.dumps(profile_payload))

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "trinetx_preprocessing",
            "validation-status",
            "--input-status",
            str(input_status),
            "--legacy-manifest",
            str(legacy_manifest),
            "--refactor-manifest",
            str(refactor_manifest),
            "--comparison-report",
            str(comparison_report),
            "--profile-provenance",
            str(profile_provenance),
            "--json",
        ],
        cwd=ROOT,
        env=_build_env(),
        capture_output=True,
        text=True,
        check=False,
    )

    payload = json.loads(result.stdout)
    profile_check = payload["checks"]["profile_provenance"]

    assert result.returncode == 1
    assert payload["ready"] is False
    assert profile_check["ok"] is False
    assert "strict must be true" in profile_check["blockers"]
    assert profile_check["strict"] is False


def test_validation_status_cli_rejects_old_profile_provenance_schema(
    tmp_path: Path,
) -> None:
    input_status = tmp_path / "input_status.json"
    config_path = str((tmp_path / "config.yaml").resolve())
    input_status.write_text(
        json.dumps(
            {
                "all_present": True,
                "space_ok": True,
                "space_check_skipped": False,
                "min_free_gb": 100.0,
                "filesystems": _complete_input_filesystems(tmp_path),
                "missing": [],
                "timed_out": [],
                "probe_errors": {},
                "domains": [
                    {
                        "name": "encounter",
                        "matched_count": 1,
                        "matched_count_exact": True,
                        "timed_out": False,
                        "probe_error": None,
                    }
                ],
                "generated_at": "2026-06-08T00:00:00+00:00",
                "config_path": config_path,
                "config_sha256": PROFILE_CONFIG_SHA256,
            }
        )
    )
    legacy_manifest = tmp_path / "legacy_manifest"
    refactor_manifest = tmp_path / "refactor_manifest"
    _write_legacy_manifest(legacy_manifest, tmp_path)
    _write_refactor_manifest(refactor_manifest, tmp_path)
    comparison_report = tmp_path / "final_comparison.json"
    _write_comparison_report(comparison_report, legacy_manifest, refactor_manifest)
    profile_provenance = tmp_path / "profile" / "provenance.json"
    profile_provenance.parent.mkdir()
    profile_payload = _complete_profile_provenance_payload(tmp_path)
    profile_payload["schema_version"] = 1
    profile_provenance.write_text(json.dumps(profile_payload))

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "trinetx_preprocessing",
            "validation-status",
            "--input-status",
            str(input_status),
            "--legacy-manifest",
            str(legacy_manifest),
            "--refactor-manifest",
            str(refactor_manifest),
            "--comparison-report",
            str(comparison_report),
            "--profile-provenance",
            str(profile_provenance),
            "--json",
        ],
        cwd=ROOT,
        env=_build_env(),
        capture_output=True,
        text=True,
        check=False,
    )

    payload = json.loads(result.stdout)
    profile_check = payload["checks"]["profile_provenance"]

    assert result.returncode == 1
    assert payload["ready"] is False
    assert profile_check["ok"] is False
    assert profile_check["schema_version"] == 1
    assert "schema_version must be 2" in profile_check["blockers"]


def test_validation_status_cli_rejects_stale_profile_code_state(
    tmp_path: Path,
) -> None:
    input_status = tmp_path / "input_status.json"
    markdown_path = tmp_path / "validation_status.md"
    config_path = str((tmp_path / "config.yaml").resolve())
    input_status.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "all_present": True,
                "space_ok": True,
                "space_check_skipped": False,
                "min_free_gb": 100.0,
                "filesystems": _complete_input_filesystems(tmp_path),
                "missing": [],
                "timed_out": [],
                "probe_errors": {},
                "domains": [
                    {
                        "name": "encounter",
                        "matched_count": 1,
                        "matched_count_exact": True,
                        "timed_out": False,
                        "probe_error": None,
                    }
                ],
                "generated_at": "2026-06-08T00:00:00+00:00",
                "config_path": config_path,
                "config_sha256": PROFILE_CONFIG_SHA256,
            }
        )
    )
    legacy_manifest = tmp_path / "legacy_manifest"
    refactor_manifest = tmp_path / "refactor_manifest"
    _write_legacy_manifest(legacy_manifest, tmp_path)
    _write_refactor_manifest(refactor_manifest, tmp_path)
    comparison_report = tmp_path / "final_comparison.json"
    _write_comparison_report(comparison_report, legacy_manifest, refactor_manifest)
    profile_provenance = tmp_path / "profile" / "provenance.json"
    profile_provenance.parent.mkdir()
    profile_payload = _complete_profile_provenance_payload(tmp_path)
    profile_payload["git_code_state_sha256"] = "0" * 64
    profile_provenance.write_text(json.dumps(profile_payload))

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "trinetx_preprocessing",
            "validation-status",
            "--input-status",
            str(input_status),
            "--legacy-manifest",
            str(legacy_manifest),
            "--refactor-manifest",
            str(refactor_manifest),
            "--comparison-report",
            str(comparison_report),
            "--profile-provenance",
            str(profile_provenance),
            "--json",
            "--markdown-out",
            str(markdown_path),
        ],
        cwd=ROOT,
        env=_build_env(),
        capture_output=True,
        text=True,
        check=False,
    )

    payload = json.loads(result.stdout)
    profile_check = payload["checks"]["profile_provenance"]
    markdown = markdown_path.read_text()

    assert result.returncode == 1
    assert payload["ready"] is False
    assert profile_check["ok"] is False
    assert profile_check["current_git_code_state_sha256_matches"] is False
    assert (
        "git_code_state_sha256 must match current code state"
        in profile_check["blockers"]
    )
    assert "## Gate Blockers" in markdown
    assert (
        "| `profile_provenance` | git_code_state_sha256 must match current code state |"
        in markdown
    )


def test_validation_status_cli_rejects_old_comparison_report_schema(
    tmp_path: Path,
) -> None:
    input_status = tmp_path / "input_status.json"
    config_path = str((tmp_path / "config.yaml").resolve())
    input_status.write_text(
        json.dumps(
            {
                "all_present": True,
                "space_ok": True,
                "space_check_skipped": False,
                "min_free_gb": 100.0,
                "filesystems": _complete_input_filesystems(tmp_path),
                "missing": [],
                "timed_out": [],
                "probe_errors": {},
                "domains": [
                    {
                        "name": "encounter",
                        "matched_count": 1,
                        "matched_count_exact": True,
                        "timed_out": False,
                        "probe_error": None,
                    }
                ],
                "generated_at": "2026-06-08T00:00:00+00:00",
                "config_path": config_path,
                "config_sha256": PROFILE_CONFIG_SHA256,
            }
        )
    )
    legacy_manifest = tmp_path / "legacy_manifest"
    refactor_manifest = tmp_path / "refactor_manifest"
    _write_legacy_manifest(legacy_manifest, tmp_path)
    _write_refactor_manifest(refactor_manifest, tmp_path)
    comparison_report = tmp_path / "final_comparison.json"
    _write_comparison_report(comparison_report, legacy_manifest, refactor_manifest)
    report_payload = json.loads(comparison_report.read_text())
    report_payload["schema_version"] = 0
    comparison_report.write_text(json.dumps(report_payload))
    profile_provenance = tmp_path / "profile" / "provenance.json"
    profile_provenance.parent.mkdir()
    profile_provenance.write_text(
        json.dumps(_complete_profile_provenance_payload(tmp_path))
    )

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "trinetx_preprocessing",
            "validation-status",
            "--input-status",
            str(input_status),
            "--legacy-manifest",
            str(legacy_manifest),
            "--refactor-manifest",
            str(refactor_manifest),
            "--comparison-report",
            str(comparison_report),
            "--profile-provenance",
            str(profile_provenance),
            "--json",
        ],
        cwd=ROOT,
        env=_build_env(),
        capture_output=True,
        text=True,
        check=False,
    )

    payload = json.loads(result.stdout)
    comparison_check = payload["checks"]["comparison_report"]

    assert result.returncode == 1
    assert payload["ready"] is False
    assert comparison_check["ok"] is False
    assert comparison_check["schema_version"] == 0
    assert comparison_check["schema_current"] is False
    assert (
        comparison_check["message"]
        == "manifest comparison report schema is stale or missing"
    )
    assert "schema_version must be 1" in comparison_check["blockers"]


def test_validation_status_cli_rejects_stale_comparison_report(
    tmp_path: Path,
) -> None:
    input_status = tmp_path / "input_status.json"
    config_path = str((tmp_path / "config.yaml").resolve())
    input_status.write_text(
        json.dumps(
            {
                "all_present": True,
                "space_ok": True,
                "space_check_skipped": False,
                "min_free_gb": 100.0,
                "filesystems": _complete_input_filesystems(tmp_path),
                "missing": [],
                "timed_out": [],
                "probe_errors": {},
                "domains": [
                    {
                        "name": "encounter",
                        "matched_count": 1,
                        "matched_count_exact": True,
                        "timed_out": False,
                        "probe_error": None,
                    }
                ],
                "generated_at": "2026-06-08T00:00:00+00:00",
                "config_path": config_path,
                "config_sha256": PROFILE_CONFIG_SHA256,
            }
        )
    )
    legacy_manifest = tmp_path / "legacy_manifest"
    refactor_manifest = tmp_path / "refactor_manifest"
    _write_legacy_manifest(legacy_manifest, tmp_path)
    _write_refactor_manifest(refactor_manifest, tmp_path)
    comparison_report = tmp_path / "final_comparison.json"
    comparison_report.write_text(
        json.dumps(
            {
                "ok": True,
                "baseline": str((tmp_path / "other_legacy").resolve()),
                "current": str((tmp_path / "other_refactor").resolve()),
                "counts": {
                    "missing": 0,
                    "extra": 0,
                    "hash_mismatched": 0,
                    "row_count_mismatched": 0,
                    "columns_mismatched": 0,
                },
                "generated_at": "2026-06-08T00:00:00+00:00",
            }
        )
    )
    profile_provenance = tmp_path / "profile" / "provenance.json"
    profile_provenance.parent.mkdir()
    profile_provenance.write_text(
        json.dumps(_complete_profile_provenance_payload(tmp_path))
    )

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "trinetx_preprocessing",
            "validation-status",
            "--input-status",
            str(input_status),
            "--legacy-manifest",
            str(legacy_manifest),
            "--refactor-manifest",
            str(refactor_manifest),
            "--comparison-report",
            str(comparison_report),
            "--profile-provenance",
            str(profile_provenance),
            "--json",
        ],
        cwd=ROOT,
        env=_build_env(),
        capture_output=True,
        text=True,
        check=False,
    )

    payload = json.loads(result.stdout)
    comparison_check = payload["checks"]["comparison_report"]

    assert result.returncode == 1
    assert payload["ready"] is False
    assert comparison_check["ok"] is False
    assert comparison_check["baseline_matches"] is False
    assert comparison_check["current_matches"] is False
    assert (
        comparison_check["message"]
        == "manifest comparison report does not match requested manifests"
    )
    assert (
        "comparison report baseline does not match legacy manifest"
        in comparison_check["blockers"]
    )
    assert (
        "comparison report current does not match refactor manifest"
        in comparison_check["blockers"]
    )


def test_validation_status_cli_rejects_stale_comparison_report_contents(
    tmp_path: Path,
) -> None:
    input_status = tmp_path / "input_status.json"
    config_path = str((tmp_path / "config.yaml").resolve())
    input_status.write_text(
        json.dumps(
            {
                "all_present": True,
                "space_ok": True,
                "space_check_skipped": False,
                "min_free_gb": 100.0,
                "filesystems": _complete_input_filesystems(tmp_path),
                "missing": [],
                "timed_out": [],
                "probe_errors": {},
                "domains": [
                    {
                        "name": "encounter",
                        "matched_count": 1,
                        "matched_count_exact": True,
                        "timed_out": False,
                        "probe_error": None,
                    }
                ],
                "generated_at": "2026-06-08T00:00:00+00:00",
                "config_path": config_path,
                "config_sha256": PROFILE_CONFIG_SHA256,
            }
        )
    )
    legacy_manifest = tmp_path / "legacy_manifest"
    refactor_manifest = tmp_path / "refactor_manifest"
    _write_legacy_manifest(legacy_manifest, tmp_path)
    _write_refactor_manifest(refactor_manifest, tmp_path)
    comparison_report = tmp_path / "final_comparison.json"
    _write_comparison_report(comparison_report, legacy_manifest, refactor_manifest)
    write_hash_manifest(
        refactor_manifest,
        {
            "output_dir/a.csv": _table_entry_for_source(
                key="output_dir/a.csv",
                hash_value="def",
                source_path=tmp_path / "output" / "a.csv",
            )
        },
        scope="final",
        output_dir=tmp_path / "output",
    )
    profile_provenance = tmp_path / "profile" / "provenance.json"
    profile_provenance.parent.mkdir()
    profile_provenance.write_text(
        json.dumps(_complete_profile_provenance_payload(tmp_path))
    )

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "trinetx_preprocessing",
            "validation-status",
            "--input-status",
            str(input_status),
            "--legacy-manifest",
            str(legacy_manifest),
            "--refactor-manifest",
            str(refactor_manifest),
            "--comparison-report",
            str(comparison_report),
            "--profile-provenance",
            str(profile_provenance),
            "--json",
        ],
        cwd=ROOT,
        env=_build_env(),
        capture_output=True,
        text=True,
        check=False,
    )

    payload = json.loads(result.stdout)
    comparison_check = payload["checks"]["comparison_report"]

    assert result.returncode == 1
    assert payload["ready"] is False
    assert comparison_check["ok"] is False
    assert comparison_check["baseline_manifest_sha256_matches"] is True
    assert comparison_check["current_manifest_sha256_matches"] is False
    assert (
        comparison_check["message"]
        == "manifest comparison report does not match current manifest contents"
    )
    assert (
        "comparison report current manifest contents are stale"
        in comparison_check["blockers"]
    )


def test_validation_status_cli_recomputes_manifest_comparison(
    tmp_path: Path,
) -> None:
    input_status = tmp_path / "input_status.json"
    config_path = str((tmp_path / "config.yaml").resolve())
    input_status.write_text(
        json.dumps(
            {
                "all_present": True,
                "space_ok": True,
                "space_check_skipped": False,
                "min_free_gb": 100.0,
                "filesystems": _complete_input_filesystems(tmp_path),
                "missing": [],
                "timed_out": [],
                "probe_errors": {},
                "domains": [
                    {
                        "name": "encounter",
                        "matched_count": 1,
                        "matched_count_exact": True,
                        "timed_out": False,
                        "probe_error": None,
                    }
                ],
                "generated_at": "2026-06-08T00:00:00+00:00",
                "config_path": config_path,
                "config_sha256": PROFILE_CONFIG_SHA256,
            }
        )
    )
    legacy_manifest = tmp_path / "legacy_manifest"
    refactor_manifest = tmp_path / "refactor_manifest"
    _write_legacy_manifest(legacy_manifest, tmp_path)
    source_path = tmp_path / "output" / "a.csv"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_text("patient_id\n1\n")
    write_hash_manifest(
        refactor_manifest,
        {
            "output_dir/a.csv": _table_entry_for_source(
                key="output_dir/a.csv",
                hash_value="def",
                source_path=source_path,
            )
        },
        scope="final",
        output_dir=tmp_path / "output",
    )
    comparison_report = tmp_path / "final_comparison.json"
    _write_comparison_report(comparison_report, legacy_manifest, refactor_manifest)
    profile_provenance = tmp_path / "profile" / "provenance.json"
    profile_provenance.parent.mkdir()
    profile_provenance.write_text(
        json.dumps(_complete_profile_provenance_payload(tmp_path))
    )

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "trinetx_preprocessing",
            "validation-status",
            "--input-status",
            str(input_status),
            "--legacy-manifest",
            str(legacy_manifest),
            "--refactor-manifest",
            str(refactor_manifest),
            "--comparison-report",
            str(comparison_report),
            "--profile-provenance",
            str(profile_provenance),
            "--json",
        ],
        cwd=ROOT,
        env=_build_env(),
        capture_output=True,
        text=True,
        check=False,
    )

    payload = json.loads(result.stdout)
    comparison_check = payload["checks"]["comparison_report"]

    assert result.returncode == 1
    assert payload["ready"] is False
    assert comparison_check["ok"] is False
    assert comparison_check["current_manifest_comparison_ok"] is False
    assert comparison_check["comparison_ok_matches"] is False
    assert comparison_check["comparison_counts_match"] is False
    assert comparison_check["computed_counts"]["hash_mismatched"] == 1
    assert comparison_check["message"] == "current manifests do not match"
    assert "current manifests do not match" in comparison_check["blockers"]
    assert (
        "comparison report ok flag does not match current manifests"
        in comparison_check["blockers"]
    )
    assert (
        "comparison report counts do not match current manifests"
        in comparison_check["blockers"]
    )


def test_validation_status_cli_rejects_refactor_outputs_absent_from_profile(
    tmp_path: Path,
) -> None:
    input_status = tmp_path / "input_status.json"
    input_status.write_text(
        json.dumps(
            {
                "all_present": True,
                "space_ok": True,
                "space_check_skipped": False,
                "min_free_gb": 100.0,
                "filesystems": _complete_input_filesystems(tmp_path),
                "missing": [],
                "timed_out": [],
                "probe_errors": {},
                "domains": [
                    {
                        "name": "encounter",
                        "matched_count": 1,
                        "matched_count_exact": True,
                        "timed_out": False,
                        "probe_error": None,
                    }
                ],
                "generated_at": "2026-06-08T00:00:00+00:00",
                "config_path": str((tmp_path / "config.yaml").resolve()),
                "config_sha256": PROFILE_CONFIG_SHA256,
            }
        )
    )
    legacy_manifest = tmp_path / "legacy_manifest"
    refactor_manifest = tmp_path / "refactor_manifest"
    _write_legacy_manifest(legacy_manifest, tmp_path)
    _write_refactor_manifest(
        refactor_manifest,
        tmp_path,
        source_relative="other_output/a.csv",
    )
    comparison_report = tmp_path / "final_comparison.json"
    comparison_report.write_text(
        json.dumps(
            {
                "ok": True,
                "baseline": str(legacy_manifest.resolve()),
                "current": str(refactor_manifest.resolve()),
                "counts": {
                    "missing": 0,
                    "extra": 0,
                    "hash_mismatched": 0,
                    "row_count_mismatched": 0,
                    "columns_mismatched": 0,
                },
                "generated_at": "2026-06-08T00:00:00+00:00",
            }
        )
    )
    profile_provenance = tmp_path / "profile" / "provenance.json"
    profile_provenance.parent.mkdir()
    profile_provenance.write_text(
        json.dumps(_complete_profile_provenance_payload(tmp_path))
    )

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "trinetx_preprocessing",
            "validation-status",
            "--input-status",
            str(input_status),
            "--legacy-manifest",
            str(legacy_manifest),
            "--refactor-manifest",
            str(refactor_manifest),
            "--comparison-report",
            str(comparison_report),
            "--profile-provenance",
            str(profile_provenance),
            "--json",
        ],
        cwd=ROOT,
        env=_build_env(),
        capture_output=True,
        text=True,
        check=False,
    )

    payload = json.loads(result.stdout)
    output_check = payload["checks"]["profile_refactor_outputs"]

    assert result.returncode == 1
    assert payload["ready"] is False
    assert output_check["ok"] is False
    assert (
        "refactor manifest source paths absent from profile output inventory"
        in output_check["blockers"]
    )
    assert output_check["missing_from_profile"] == [
        str((tmp_path / "other_output" / "a.csv").resolve())
    ]


def test_validation_status_cli_rejects_profile_outputs_absent_from_manifest(
    tmp_path: Path,
) -> None:
    input_status = tmp_path / "input_status.json"
    input_status.write_text(
        json.dumps(
            {
                "all_present": True,
                "space_ok": True,
                "space_check_skipped": False,
                "min_free_gb": 100.0,
                "filesystems": _complete_input_filesystems(tmp_path),
                "missing": [],
                "timed_out": [],
                "probe_errors": {},
                "domains": [
                    {
                        "name": "encounter",
                        "matched_count": 1,
                        "matched_count_exact": True,
                        "timed_out": False,
                        "probe_error": None,
                    }
                ],
                "generated_at": "2026-06-08T00:00:00+00:00",
                "config_path": str((tmp_path / "config.yaml").resolve()),
                "config_sha256": PROFILE_CONFIG_SHA256,
            }
        )
    )
    legacy_manifest = tmp_path / "legacy_manifest"
    refactor_manifest = tmp_path / "refactor_manifest"
    _write_legacy_manifest(legacy_manifest, tmp_path)
    _write_refactor_manifest(refactor_manifest, tmp_path)
    comparison_report = tmp_path / "final_comparison.json"
    _write_comparison_report(comparison_report, legacy_manifest, refactor_manifest)
    profile_provenance = tmp_path / "profile" / "provenance.json"
    profile_provenance.parent.mkdir()
    profile_payload = _complete_profile_provenance_payload(tmp_path)
    (tmp_path / "output" / "b.csv").write_bytes(b"0123456789ab")
    profile_payload["output_file_count"] = 2
    profile_payload["output_files"] = [
        _profile_output_inventory_item(tmp_path / "output" / "a.csv"),
        _profile_output_inventory_item(tmp_path / "output" / "b.csv"),
    ]
    profile_provenance.write_text(json.dumps(profile_payload))

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "trinetx_preprocessing",
            "validation-status",
            "--input-status",
            str(input_status),
            "--legacy-manifest",
            str(legacy_manifest),
            "--refactor-manifest",
            str(refactor_manifest),
            "--comparison-report",
            str(comparison_report),
            "--profile-provenance",
            str(profile_provenance),
            "--json",
        ],
        cwd=ROOT,
        env=_build_env(),
        capture_output=True,
        text=True,
        check=False,
    )

    payload = json.loads(result.stdout)
    output_check = payload["checks"]["profile_refactor_outputs"]

    assert result.returncode == 1
    assert payload["ready"] is False
    assert output_check["ok"] is False
    assert (
        "profile output inventory paths absent from refactor manifest"
        in output_check["blockers"]
    )
    assert output_check["missing_from_manifest"] == [
        str((tmp_path / "output" / "b.csv").resolve())
    ]


def test_validation_status_cli_rejects_refactor_outputs_outside_configured_output_dir(
    tmp_path: Path,
) -> None:
    input_status = tmp_path / "input_status.json"
    input_status.write_text(
        json.dumps(
            {
                "all_present": True,
                "space_ok": True,
                "space_check_skipped": False,
                "min_free_gb": 100.0,
                "filesystems": _complete_input_filesystems(tmp_path),
                "missing": [],
                "timed_out": [],
                "probe_errors": {},
                "domains": [
                    {
                        "name": "encounter",
                        "matched_count": 1,
                        "matched_count_exact": True,
                        "timed_out": False,
                        "probe_error": None,
                    }
                ],
                "generated_at": "2026-06-08T00:00:00+00:00",
                "config_path": str((tmp_path / "config.yaml").resolve()),
                "config_sha256": PROFILE_CONFIG_SHA256,
            }
        )
    )
    legacy_manifest = tmp_path / "legacy_manifest"
    refactor_manifest = tmp_path / "refactor_manifest"
    _write_legacy_manifest(legacy_manifest, tmp_path)
    _write_refactor_manifest(
        refactor_manifest,
        tmp_path,
        source_relative="other_output/a.csv",
    )
    comparison_report = tmp_path / "final_comparison.json"
    _write_comparison_report(comparison_report, legacy_manifest, refactor_manifest)
    profile_provenance = tmp_path / "profile" / "provenance.json"
    profile_provenance.parent.mkdir()
    profile_payload = _complete_profile_provenance_payload(tmp_path)
    profile_payload["output_files"] = [
        _profile_output_inventory_item(tmp_path / "other_output" / "a.csv")
    ]
    profile_provenance.write_text(json.dumps(profile_payload))

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "trinetx_preprocessing",
            "validation-status",
            "--input-status",
            str(input_status),
            "--legacy-manifest",
            str(legacy_manifest),
            "--refactor-manifest",
            str(refactor_manifest),
            "--comparison-report",
            str(comparison_report),
            "--profile-provenance",
            str(profile_provenance),
            "--json",
        ],
        cwd=ROOT,
        env=_build_env(),
        capture_output=True,
        text=True,
        check=False,
    )

    payload = json.loads(result.stdout)
    output_check = payload["checks"]["profile_refactor_outputs"]
    outside_path = str((tmp_path / "other_output" / "a.csv").resolve())

    assert result.returncode == 1
    assert payload["ready"] is False
    assert output_check["ok"] is False
    assert output_check["configured_output_dir"] == str((tmp_path / "output").resolve())
    assert (
        "refactor manifest source paths outside configured output_dir"
        in output_check["blockers"]
    )
    assert (
        "profile output inventory paths outside configured output_dir"
        in output_check["blockers"]
    )
    assert output_check["manifest_paths_outside_output_dir"] == [outside_path]
    assert output_check["profile_paths_outside_output_dir"] == [outside_path]


def test_validation_status_cli_rejects_refactor_manifest_key_source_mismatch(
    tmp_path: Path,
) -> None:
    input_status = tmp_path / "input_status.json"
    input_status.write_text(
        json.dumps(
            {
                "all_present": True,
                "space_ok": True,
                "space_check_skipped": False,
                "min_free_gb": 100.0,
                "filesystems": _complete_input_filesystems(tmp_path),
                "missing": [],
                "timed_out": [],
                "probe_errors": {},
                "domains": [
                    {
                        "name": "encounter",
                        "matched_count": 1,
                        "matched_count_exact": True,
                        "timed_out": False,
                        "probe_error": None,
                    }
                ],
                "generated_at": "2026-06-08T00:00:00+00:00",
                "config_path": str((tmp_path / "config.yaml").resolve()),
                "config_sha256": PROFILE_CONFIG_SHA256,
            }
        )
    )
    nested_source = tmp_path / "output" / "nested" / "a.csv"
    nested_source.parent.mkdir(parents=True, exist_ok=True)
    nested_source.write_text("patient_id\n1\n")
    legacy_manifest = tmp_path / "legacy_manifest"
    refactor_manifest = tmp_path / "refactor_manifest"
    _write_legacy_manifest(legacy_manifest, tmp_path)
    write_hash_manifest(
        refactor_manifest,
        {
            "output_dir/a.csv": _table_entry_for_source(
                key="output_dir/a.csv",
                source_path=nested_source,
            )
        },
        scope="final",
        output_dir=tmp_path / "output",
    )
    comparison_report = tmp_path / "final_comparison.json"
    _write_comparison_report(comparison_report, legacy_manifest, refactor_manifest)
    profile_provenance = tmp_path / "profile" / "provenance.json"
    profile_provenance.parent.mkdir()
    profile_payload = _complete_profile_provenance_payload(tmp_path)
    profile_payload["output_files"] = [_profile_output_inventory_item(nested_source)]
    profile_provenance.write_text(json.dumps(profile_payload))

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "trinetx_preprocessing",
            "validation-status",
            "--input-status",
            str(input_status),
            "--legacy-manifest",
            str(legacy_manifest),
            "--refactor-manifest",
            str(refactor_manifest),
            "--comparison-report",
            str(comparison_report),
            "--profile-provenance",
            str(profile_provenance),
            "--json",
        ],
        cwd=ROOT,
        env=_build_env(),
        capture_output=True,
        text=True,
        check=False,
    )

    payload = json.loads(result.stdout)
    output_check = payload["checks"]["profile_refactor_outputs"]

    assert result.returncode == 1
    assert payload["ready"] is False
    assert output_check["ok"] is False
    assert (
        "refactor manifest keys do not match configured source paths"
        in output_check["blockers"]
    )
    assert output_check["manifest_key_source_mismatches"] == [
        {
            "key": "output_dir/a.csv",
            "expected_key": "output_dir/nested/a.csv",
            "source_path": str(nested_source.resolve()),
        }
    ]


def test_validation_status_cli_rejects_stale_profile_output_inventory(
    tmp_path: Path,
) -> None:
    input_status = tmp_path / "input_status.json"
    input_status.write_text(
        json.dumps(
            {
                "all_present": True,
                "space_ok": True,
                "space_check_skipped": False,
                "min_free_gb": 100.0,
                "filesystems": _complete_input_filesystems(tmp_path),
                "missing": [],
                "timed_out": [],
                "probe_errors": {},
                "domains": [
                    {
                        "name": "encounter",
                        "matched_count": 1,
                        "matched_count_exact": True,
                        "timed_out": False,
                        "probe_error": None,
                    }
                ],
                "generated_at": "2026-06-08T00:00:00+00:00",
                "config_path": str((tmp_path / "config.yaml").resolve()),
                "config_sha256": PROFILE_CONFIG_SHA256,
            }
        )
    )
    legacy_manifest = tmp_path / "legacy_manifest"
    refactor_manifest = tmp_path / "refactor_manifest"
    _write_legacy_manifest(legacy_manifest, tmp_path)
    _write_refactor_manifest(refactor_manifest, tmp_path)
    comparison_report = tmp_path / "final_comparison.json"
    _write_comparison_report(comparison_report, legacy_manifest, refactor_manifest)
    profile_provenance = tmp_path / "profile" / "provenance.json"
    profile_provenance.parent.mkdir()
    profile_payload = _complete_profile_provenance_payload(tmp_path)
    profile_payload["output_files"][0]["size_bytes"] = 99
    profile_provenance.write_text(json.dumps(profile_payload))

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "trinetx_preprocessing",
            "validation-status",
            "--input-status",
            str(input_status),
            "--legacy-manifest",
            str(legacy_manifest),
            "--refactor-manifest",
            str(refactor_manifest),
            "--comparison-report",
            str(comparison_report),
            "--profile-provenance",
            str(profile_provenance),
            "--json",
        ],
        cwd=ROOT,
        env=_build_env(),
        capture_output=True,
        text=True,
        check=False,
    )

    payload = json.loads(result.stdout)
    profile_check = payload["checks"]["profile_provenance"]

    assert result.returncode == 1
    assert payload["ready"] is False
    assert profile_check["ok"] is False
    assert (
        "output_files[0].size_bytes does not match current file size"
        in profile_check["blockers"]
    )


def test_validation_status_cli_rejects_invalid_profile_output_file_metadata(
    tmp_path: Path,
) -> None:
    input_status = tmp_path / "input_status.json"
    input_status.write_text(
        json.dumps(
            {
                "all_present": True,
                "space_ok": True,
                "space_check_skipped": False,
                "min_free_gb": 100.0,
                "filesystems": _complete_input_filesystems(tmp_path),
                "missing": [],
                "timed_out": [],
                "probe_errors": {},
                "domains": [
                    {
                        "name": "encounter",
                        "matched_count": 1,
                        "matched_count_exact": True,
                        "timed_out": False,
                        "probe_error": None,
                    }
                ],
                "generated_at": "2026-06-08T00:00:00+00:00",
                "config_path": str((tmp_path / "config.yaml").resolve()),
                "config_sha256": PROFILE_CONFIG_SHA256,
            }
        )
    )
    legacy_manifest = tmp_path / "legacy_manifest"
    refactor_manifest = tmp_path / "refactor_manifest"
    _write_legacy_manifest(legacy_manifest, tmp_path)
    _write_refactor_manifest(refactor_manifest, tmp_path)
    comparison_report = tmp_path / "final_comparison.json"
    _write_comparison_report(comparison_report, legacy_manifest, refactor_manifest)
    non_csv_path = tmp_path / "output" / "a.parquet"
    non_csv_path.write_bytes(b"not parquet\n")
    directory_path = tmp_path / "output" / "directory.csv"
    directory_path.mkdir()
    profile_provenance = tmp_path / "profile" / "provenance.json"
    profile_provenance.parent.mkdir()
    profile_payload = _complete_profile_provenance_payload(tmp_path)
    profile_payload["generated_file_count"] = 2
    profile_payload["output_file_count"] = 2
    profile_payload["output_files"] = [
        _profile_output_inventory_item(non_csv_path),
        _profile_output_inventory_item(directory_path),
    ]
    profile_provenance.write_text(json.dumps(profile_payload))

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "trinetx_preprocessing",
            "validation-status",
            "--input-status",
            str(input_status),
            "--legacy-manifest",
            str(legacy_manifest),
            "--refactor-manifest",
            str(refactor_manifest),
            "--comparison-report",
            str(comparison_report),
            "--profile-provenance",
            str(profile_provenance),
            "--json",
        ],
        cwd=ROOT,
        env=_build_env(),
        capture_output=True,
        text=True,
        check=False,
    )

    payload = json.loads(result.stdout)
    profile_check = payload["checks"]["profile_provenance"]

    assert result.returncode == 1
    assert payload["ready"] is False
    assert profile_check["ok"] is False
    assert "output_files[0].path must be a CSV file" in profile_check["blockers"]
    assert "output_files[1].path must be a file" in profile_check["blockers"]


def test_validation_status_cli_rejects_stale_profile_output_mtime(
    tmp_path: Path,
) -> None:
    input_status = tmp_path / "input_status.json"
    input_status.write_text(
        json.dumps(
            {
                "all_present": True,
                "space_ok": True,
                "space_check_skipped": False,
                "min_free_gb": 100.0,
                "filesystems": _complete_input_filesystems(tmp_path),
                "missing": [],
                "timed_out": [],
                "probe_errors": {},
                "domains": [
                    {
                        "name": "encounter",
                        "matched_count": 1,
                        "matched_count_exact": True,
                        "timed_out": False,
                        "probe_error": None,
                    }
                ],
                "generated_at": "2026-06-08T00:00:00+00:00",
                "config_path": str((tmp_path / "config.yaml").resolve()),
                "config_sha256": PROFILE_CONFIG_SHA256,
            }
        )
    )
    legacy_manifest = tmp_path / "legacy_manifest"
    refactor_manifest = tmp_path / "refactor_manifest"
    _write_legacy_manifest(legacy_manifest, tmp_path)
    _write_refactor_manifest(refactor_manifest, tmp_path)
    comparison_report = tmp_path / "final_comparison.json"
    _write_comparison_report(comparison_report, legacy_manifest, refactor_manifest)
    profile_provenance = tmp_path / "profile" / "provenance.json"
    profile_provenance.parent.mkdir()
    profile_payload = _complete_profile_provenance_payload(tmp_path)
    profile_payload["output_files"][0]["mtime_ns"] -= 1
    profile_provenance.write_text(json.dumps(profile_payload))

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "trinetx_preprocessing",
            "validation-status",
            "--input-status",
            str(input_status),
            "--legacy-manifest",
            str(legacy_manifest),
            "--refactor-manifest",
            str(refactor_manifest),
            "--comparison-report",
            str(comparison_report),
            "--profile-provenance",
            str(profile_provenance),
            "--json",
        ],
        cwd=ROOT,
        env=_build_env(),
        capture_output=True,
        text=True,
        check=False,
    )

    payload = json.loads(result.stdout)
    profile_check = payload["checks"]["profile_provenance"]

    assert result.returncode == 1
    assert payload["ready"] is False
    assert profile_check["ok"] is False
    assert (
        "output_files[0].mtime_ns does not match current file mtime"
        in profile_check["blockers"]
    )


def test_validation_status_cli_rejects_mismatched_config_identity(
    tmp_path: Path,
) -> None:
    input_status = tmp_path / "input_status.json"
    markdown_path = tmp_path / "validation_status.md"
    input_status.write_text(
        json.dumps(
            {
                "all_present": True,
                "space_ok": True,
                "space_check_skipped": False,
                "min_free_gb": 100.0,
                "filesystems": _complete_input_filesystems(tmp_path),
                "missing": [],
                "timed_out": [],
                "probe_errors": {},
                "domains": [
                    {
                        "name": "encounter",
                        "matched_count": 1,
                        "matched_count_exact": True,
                        "timed_out": False,
                        "probe_error": None,
                    }
                ],
                "generated_at": "2026-06-08T00:00:00+00:00",
                "config_path": str((tmp_path / "config.yaml").resolve()),
                "config_sha256": PROFILE_CONFIG_SHA256,
            }
        )
    )
    legacy_manifest = tmp_path / "legacy_manifest"
    refactor_manifest = tmp_path / "refactor_manifest"
    _write_legacy_manifest(legacy_manifest, tmp_path)
    _write_refactor_manifest(refactor_manifest, tmp_path)
    comparison_report = tmp_path / "final_comparison.json"
    comparison_report.write_text(
        json.dumps(
            {
                "ok": True,
                "baseline": str(legacy_manifest.resolve()),
                "current": str(refactor_manifest.resolve()),
                "counts": {
                    "missing": 0,
                    "extra": 0,
                    "hash_mismatched": 0,
                    "row_count_mismatched": 0,
                    "columns_mismatched": 0,
                },
                "generated_at": "2026-06-08T00:00:00+00:00",
            }
        )
    )
    profile_provenance = tmp_path / "profile" / "provenance.json"
    profile_provenance.parent.mkdir()
    profile_payload = _complete_profile_provenance_payload(tmp_path)
    profile_payload["config_path"] = str((tmp_path / "other_config.yaml").resolve())
    profile_provenance.write_text(json.dumps(profile_payload))

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "trinetx_preprocessing",
            "validation-status",
            "--input-status",
            str(input_status),
            "--legacy-manifest",
            str(legacy_manifest),
            "--refactor-manifest",
            str(refactor_manifest),
            "--comparison-report",
            str(comparison_report),
            "--profile-provenance",
            str(profile_provenance),
            "--json",
            "--markdown-out",
            str(markdown_path),
        ],
        cwd=ROOT,
        env=_build_env(),
        capture_output=True,
        text=True,
        check=False,
    )

    payload = json.loads(result.stdout)
    consistency_check = payload["checks"]["artifact_consistency"]
    markdown = markdown_path.read_text()

    assert result.returncode == 1
    assert payload["ready"] is False
    assert consistency_check["ok"] is False
    assert consistency_check["config_path_matches"] is False
    assert consistency_check["config_sha256_matches"] is True
    assert consistency_check["input_config_path"] == str(
        (tmp_path / "config.yaml").resolve()
    )
    assert consistency_check["profile_config_path"] == str(
        (tmp_path / "other_config.yaml").resolve()
    )
    assert "input and profile config paths differ" in consistency_check["blockers"]
    assert (
        "| `artifact_consistency` | input and profile config paths differ |" in markdown
    )


def test_validation_status_cli_rejects_mismatched_config_hash(
    tmp_path: Path,
) -> None:
    input_status = tmp_path / "input_status.json"
    input_status.write_text(
        json.dumps(
            {
                "all_present": True,
                "space_ok": True,
                "space_check_skipped": False,
                "min_free_gb": 100.0,
                "filesystems": _complete_input_filesystems(tmp_path),
                "missing": [],
                "timed_out": [],
                "probe_errors": {},
                "domains": [
                    {
                        "name": "encounter",
                        "matched_count": 1,
                        "matched_count_exact": True,
                        "timed_out": False,
                        "probe_error": None,
                    }
                ],
                "generated_at": "2026-06-08T00:00:00+00:00",
                "config_path": str((tmp_path / "config.yaml").resolve()),
                "config_sha256": "c" * 64,
            }
        )
    )
    legacy_manifest = tmp_path / "legacy_manifest"
    refactor_manifest = tmp_path / "refactor_manifest"
    _write_legacy_manifest(legacy_manifest, tmp_path)
    _write_refactor_manifest(refactor_manifest, tmp_path)
    comparison_report = tmp_path / "final_comparison.json"
    comparison_report.write_text(
        json.dumps(
            {
                "ok": True,
                "baseline": str(legacy_manifest.resolve()),
                "current": str(refactor_manifest.resolve()),
                "counts": {
                    "missing": 0,
                    "extra": 0,
                    "hash_mismatched": 0,
                    "row_count_mismatched": 0,
                    "columns_mismatched": 0,
                },
                "generated_at": "2026-06-08T00:00:00+00:00",
            }
        )
    )
    profile_provenance = tmp_path / "profile" / "provenance.json"
    profile_provenance.parent.mkdir()
    profile_provenance.write_text(
        json.dumps(_complete_profile_provenance_payload(tmp_path))
    )

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "trinetx_preprocessing",
            "validation-status",
            "--input-status",
            str(input_status),
            "--legacy-manifest",
            str(legacy_manifest),
            "--refactor-manifest",
            str(refactor_manifest),
            "--comparison-report",
            str(comparison_report),
            "--profile-provenance",
            str(profile_provenance),
            "--json",
        ],
        cwd=ROOT,
        env=_build_env(),
        capture_output=True,
        text=True,
        check=False,
    )

    payload = json.loads(result.stdout)
    consistency_check = payload["checks"]["artifact_consistency"]

    assert result.returncode == 1
    assert payload["ready"] is False
    assert consistency_check["ok"] is False
    assert consistency_check["config_path_matches"] is True
    assert consistency_check["config_sha256_matches"] is False
    assert consistency_check["input_config_sha256"] == "c" * 64
    assert consistency_check["profile_config_sha256"] == PROFILE_CONFIG_SHA256


def test_validation_status_cli_rejects_stale_config_file_contents(
    tmp_path: Path,
) -> None:
    input_status = tmp_path / "input_status.json"
    config_path = tmp_path / "config.yaml"
    input_status.write_text(
        json.dumps(
            {
                "all_present": True,
                "space_ok": True,
                "space_check_skipped": False,
                "min_free_gb": 100.0,
                "filesystems": _complete_input_filesystems(tmp_path),
                "missing": [],
                "timed_out": [],
                "probe_errors": {},
                "domains": [
                    {
                        "name": "encounter",
                        "matched_count": 1,
                        "matched_count_exact": True,
                        "timed_out": False,
                        "probe_error": None,
                    }
                ],
                "generated_at": "2026-06-08T00:00:00+00:00",
                "config_path": str(config_path.resolve()),
                "config_sha256": PROFILE_CONFIG_SHA256,
            }
        )
    )
    legacy_manifest = tmp_path / "legacy_manifest"
    refactor_manifest = tmp_path / "refactor_manifest"
    _write_legacy_manifest(legacy_manifest, tmp_path)
    _write_refactor_manifest(refactor_manifest, tmp_path)
    comparison_report = tmp_path / "final_comparison.json"
    _write_comparison_report(comparison_report, legacy_manifest, refactor_manifest)
    profile_provenance = tmp_path / "profile" / "provenance.json"
    profile_provenance.parent.mkdir()
    profile_provenance.write_text(
        json.dumps(_complete_profile_provenance_payload(tmp_path))
    )
    config_path.write_text("data_dir: changed\nwork_dir: work\noutput_dir: output\n")

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "trinetx_preprocessing",
            "validation-status",
            "--input-status",
            str(input_status),
            "--legacy-manifest",
            str(legacy_manifest),
            "--refactor-manifest",
            str(refactor_manifest),
            "--comparison-report",
            str(comparison_report),
            "--profile-provenance",
            str(profile_provenance),
            "--json",
        ],
        cwd=ROOT,
        env=_build_env(),
        capture_output=True,
        text=True,
        check=False,
    )

    payload = json.loads(result.stdout)
    consistency_check = payload["checks"]["artifact_consistency"]

    assert result.returncode == 1
    assert payload["ready"] is False
    assert consistency_check["ok"] is False
    assert consistency_check["config_path_matches"] is True
    assert consistency_check["config_sha256_matches"] is True
    assert (
        consistency_check["current_config_sha256"]
        == hashlib.sha256(config_path.read_bytes()).hexdigest()
    )
    assert consistency_check["current_config_sha256_matches"] is False


def test_validation_status_cli_reports_incomplete_artifacts(tmp_path: Path) -> None:
    status_path = tmp_path / "validation_status.json"
    markdown_path = tmp_path / "validation_status.md"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "trinetx_preprocessing",
            "validation-status",
            "--input-status",
            str(tmp_path / "missing_input_status.json"),
            "--json-out",
            str(status_path),
            "--markdown-out",
            str(markdown_path),
        ],
        cwd=ROOT,
        env=_build_env(),
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert result.stdout == ""
    assert json.loads(status_path.read_text())["ready"] is False
    markdown = markdown_path.read_text()
    assert "# TriNetX Refactor Validation Status" in markdown
    assert "| `input_status` | fail | artifact missing |" in markdown
    assert "## Gate Blockers" in markdown
    assert "| `input_status` | artifact missing |" in markdown
    assert "| `legacy_manifest` | artifact path not provided |" in markdown
    assert "| `profile_provenance` | artifact path not provided |" in markdown

    allowed = subprocess.run(
        [
            sys.executable,
            "-m",
            "trinetx_preprocessing",
            "validation-status",
            "--input-status",
            str(tmp_path / "missing_input_status.json"),
            "--allow-incomplete",
        ],
        cwd=ROOT,
        env=_build_env(),
        capture_output=True,
        text=True,
        check=False,
    )

    assert allowed.returncode == 0


def test_validation_status_cli_reports_timed_out_inputs(tmp_path: Path) -> None:
    input_status = tmp_path / "input_status.json"
    status_path = tmp_path / "validation_status.json"
    markdown_path = tmp_path / "validation_status.md"
    input_status.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "all_present": False,
                "space_ok": None,
                "space_check_skipped": True,
                "missing": ["labs"],
                "timed_out": ["labs"],
                "probe_errors": {"labs": "metadata probe timed out"},
                "domains": [
                    {
                        "name": "labs",
                        "matched_count": 0,
                        "matched_count_exact": True,
                        "timed_out": True,
                        "search_dir": "/external/TriNetX/Lab Results",
                        "search_dir_exists": None,
                        "first_path": None,
                        "probe_error": "metadata probe timed out",
                    }
                ],
                "generated_at": "2026-06-08T00:00:00+00:00",
            }
        )
    )

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "trinetx_preprocessing",
            "validation-status",
            "--input-status",
            str(input_status),
            "--json-out",
            str(status_path),
            "--markdown-out",
            str(markdown_path),
            "--allow-incomplete",
        ],
        cwd=ROOT,
        env=_build_env(),
        capture_output=True,
        text=True,
        check=False,
    )

    payload = json.loads(status_path.read_text())
    markdown = markdown_path.read_text()

    assert result.returncode == 0
    assert payload["checks"]["input_status"]["blockers"] == [
        "missing input domains: labs",
        "input free-space check did not pass",
        "input domain probes timed out: labs",
        "input domain probe errors: labs",
        "input domain details timed out: labs",
        "input domain details have probe errors: labs",
    ]
    assert payload["checks"]["input_status"]["timed_out"] == ["labs"]
    assert payload["checks"]["input_status"]["domains"] == [
        {
            "name": "labs",
            "matched_count": 0,
            "matched_count_exact": True,
            "timed_out": True,
            "search_dir": "/external/TriNetX/Lab Results",
            "search_dir_exists": None,
            "first_path": None,
            "probe_error": "metadata probe timed out",
        }
    ]
    assert "## Input Status Mode" in markdown
    assert "| `input_status` | missing input domains: labs |" in markdown
    assert "| `input_status` | input domain probes timed out: labs |" in markdown
    assert "| `input_status` | input domain probe errors: labs |" in markdown
    assert "- Exact input status: no" in markdown
    assert "- Space check skipped: yes" in markdown
    assert "## Timed-Out Input Domains" in markdown
    assert "## Input Probe Errors" in markdown
    assert "## Input Domain Status" in markdown
    assert "| `labs` | 0 | yes | unknown |  | metadata probe timed out |" in markdown
    assert "- `labs`: metadata probe timed out" in markdown
    assert "- `labs`" in markdown

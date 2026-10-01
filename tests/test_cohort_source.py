from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path

import duckdb
import pandas as pd
import pytest

from trinetx_preprocessing import cli as preprocessing_cli
from trinetx_preprocessing.combined_preprocessing import (
    cohort_source as cohort_source_module,
)
from trinetx_preprocessing.combined_preprocessing import (
    cohort_source_population_audit as population_audit_module,
)
from trinetx_preprocessing.combined_preprocessing import (
    cohort_source_scope_audit as scope_audit_module,
)
from trinetx_preprocessing.combined_preprocessing.builder import build_preprocessed
from trinetx_preprocessing.combined_preprocessing.cohort_source import (
    CohortSourceValidationError,
    open_cohort_source,
    validate_cohort_source,
)
from trinetx_preprocessing.combined_preprocessing.cohort_source_acceptance import (
    open_accepted_cohort_source,
    verify_accepted_cohort_source,
)
from trinetx_preprocessing.combined_preprocessing.database import (
    COMBINED_MANIFEST_FILENAME,
)
from trinetx_preprocessing.config import load_config

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
_REQUIRED_ELEMENTS = (
    "source.arterial_pco2",
    "source.traditional.lab.rfs_abg",
)


def _build_cohort_source_product(tmp_path: Path) -> Path:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "\n".join(
            [
                f'data_dir: "{REPOSITORY_ROOT / "tests/fixtures/example_data"}"',
                f'work_dir: "{tmp_path / "work"}"',
                f'output_dir: "{tmp_path / "output"}"',
                "chunking:",
                "  enabled: true",
                "  lines_per_chunk: 2",
                "storage:",
                "  intermediate_format: parquet",
                "  emit_legacy_csv_intermediates: false",
                "  parquet_row_group_size: 10",
                "  analysis_bucket_count: 2",
                "combined:",
                "  enabled: true",
                "  database_name: trinetx_preprocessed.duckdb",
                f'  concept_sets_dir: "{REPOSITORY_ROOT / "config/concept_sets"}"',
                "domains:",
                "  encounter:",
                '    pattern: "Encounter/encounter*.csv"',
                "  diagnosis:",
                '    pattern: "Diagnosis/diagnosis*.csv"',
                "  labs:",
                '    pattern: "Lab Results/lab_result*.csv"',
                "  meds:",
                '    pattern: "Medications/medication*.csv"',
                "  procedure:",
                '    pattern: "Procedure/procedure*.csv"',
                "  vitals:",
                '    pattern: "Vital Signs/vital*_signs*.csv"',
                "  patient:",
                '    pattern: "Patient/patient*.csv"',
                "rfs:",
                "  enabled: true",
                "",
            ]
        )
    )
    return build_preprocessed(load_config(config_path), strict=True).database_path


def test_cohort_source_validates_and_opens_read_only(tmp_path: Path) -> None:
    database_path = _build_cohort_source_product(tmp_path)
    spill_root = tmp_path / "spill"
    spill_root.mkdir()

    result = validate_cohort_source(
        database_path,
        required_elements=_REQUIRED_ELEMENTS,
        spill_root=spill_root,
    )

    assert result.valid, result.errors
    assert result.metadata is not None
    assert result.metadata.cohort_source_catalog_sha256
    assert result.metadata.glp1_catalog_sha256
    assert result.metadata.cohort_source_catalog_sha256 != (
        result.metadata.glp1_catalog_sha256
    )
    assert not list(spill_root.iterdir())

    with open_cohort_source(
        database_path,
        required_elements=_REQUIRED_ELEMENTS,
        spill_root=spill_root,
    ) as source:
        assert source.metadata == result.metadata
        assert (
            source.connection.execute(
                "SELECT count(*) FROM source_encounter"
            ).fetchone()
            is not None
        )
        with pytest.raises(duckdb.Error):
            source.connection.execute("CREATE TABLE should_not_be_written (id INTEGER)")
        population_audit = population_audit_module.audit_candidate_population(
            source.connection,
            pd.DataFrame(
                {"patient_id": ["synthetic-absent"], "encounter_id": ["index"]}
            ),
        )
        assert population_audit.patient_absent == 1
        source.connection.register(
            "historical_scope_patients",
            pd.DataFrame({"patient_id": ["synthetic-absent"]}),
        )
        try:
            scope_audit = scope_audit_module.audit_candidate_source_scope(
                source.connection,
                historical_patient_relation="historical_scope_patients",
            )
        finally:
            source.connection.unregister("historical_scope_patients")
        assert scope_audit.historical_patients == 1
        assert scope_audit.source_patient_missing == 1

    assert not list(spill_root.iterdir())


def test_capability_cli_reads_validated_source_and_emits_only_aggregate_counts(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    database_path = _build_cohort_source_product(tmp_path)
    spill_root = tmp_path / "capability-spill"
    spill_root.mkdir()

    assert (
        preprocessing_cli.main(
            [
                "audit-cohort-source-capabilities",
                "--database",
                str(database_path),
                "--spill-root",
                str(spill_root),
            ]
        )
        == 0
    )
    output = capsys.readouterr().out
    payload = json.loads(output)
    assert payload["kind"] == "candidate_source_capability_audit"
    assert payload["source_accepted"] is False
    assert payload["abstract_report_ready"] is False
    assert payload["counts"]["encounter_starts"]["source_rows"] == 0
    assert payload["counts"]["arterial_pco2_candidates"]["source_rows"] == 0
    assert payload["counts"]["arterial_ph_candidates"]["source_rows"] == 0
    assert {item["domain"] for item in payload["counts"]["raw_headers"]} == {
        "encounter",
        "labs",
        "meds",
    }
    assert str(tmp_path) not in output
    assert "patient_id" not in output
    assert "encounter_id" not in output
    assert not list(spill_root.iterdir())


def test_cohort_source_rejects_tampered_or_incomplete_products(
    tmp_path: Path,
) -> None:
    database_path = _build_cohort_source_product(tmp_path)
    sidecar_path = database_path.parent / COMBINED_MANIFEST_FILENAME
    original_sidecar = sidecar_path.read_text()

    sidecar_path.unlink()
    missing_sidecar = validate_cohort_source(database_path)
    assert not missing_sidecar.valid
    assert any(
        "Missing cohort-source product sidecar" in error
        for error in missing_sidecar.errors
    )
    sidecar_path.write_text(original_sidecar)

    wrong_catalog = validate_cohort_source(
        database_path,
        expected_catalog_sha256="0" * 64,
    )
    assert not wrong_catalog.valid
    assert "Cohort-source catalog digest does not match the requested value." in (
        wrong_catalog.errors
    )

    unknown_element = validate_cohort_source(
        database_path,
        required_elements=("source.not_in_catalog",),
    )
    assert not unknown_element.valid
    assert any(
        "missing required element IDs" in error for error in unknown_element.errors
    )

    sidecar = json.loads(original_sidecar)
    sidecar["cohort_source_schema_sha256"] = "0" * 64
    sidecar_path.write_text(json.dumps(sidecar))
    mismatched_sidecar = validate_cohort_source(database_path)
    assert not mismatched_sidecar.valid
    assert any("sidecar disagrees" in error for error in mismatched_sidecar.errors)
    sidecar_path.write_text(original_sidecar)

    connection = duckdb.connect(str(database_path))
    try:
        connection.execute("UPDATE preprocessing_manifest SET status = 'building'")
        connection.execute("CHECKPOINT")
    finally:
        connection.close()
    incomplete = validate_cohort_source(database_path)
    assert not incomplete.valid
    assert any(
        "mismatches the contract for: status" in error for error in incomplete.errors
    )


def test_cohort_source_rejects_schema_and_required_table_loss(tmp_path: Path) -> None:
    database_path = _build_cohort_source_product(tmp_path)
    connection = duckdb.connect(str(database_path))
    try:
        connection.execute(
            "ALTER TABLE source_patient RENAME COLUMN source_id TO source_id_tampered"
        )
        connection.execute("CHECKPOINT")
    finally:
        connection.close()
    mismatched_schema = validate_cohort_source(database_path)
    assert not mismatched_schema.valid
    assert "Cohort-source table schema mismatch: source_patient" in (
        mismatched_schema.errors
    )

    connection = duckdb.connect(str(database_path))
    try:
        connection.execute(
            "ALTER TABLE source_patient RENAME COLUMN source_id_tampered TO source_id"
        )
        connection.execute("DROP TABLE source_encounter")
        connection.execute("CHECKPOINT")
    finally:
        connection.close()
    missing_table = validate_cohort_source(database_path)
    assert not missing_table.valid
    assert "source_encounter" in " ".join(missing_table.errors)
    with pytest.raises(CohortSourceValidationError, match="Invalid cohort source"):
        with open_cohort_source(database_path):
            pass


def test_cohort_source_guards_default_and_explicit_spill_locations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = _build_cohort_source_product(tmp_path)
    spill_root = tmp_path / "spill"
    spill_root.mkdir()
    calls: list[tuple[Path, str]] = []

    def record_guard(path: Path, *, artifact_label: str) -> None:
        calls.append((path, artifact_label))

    monkeypatch.setattr(
        cohort_source_module,
        "require_safe_output_location",
        record_guard,
    )

    result = validate_cohort_source(database_path, spill_root=spill_root)

    assert result.valid, result.errors
    assert calls == [
        (database_path.parent, "cohort-source database/spill directory"),
        (spill_root, "cohort-source spill directory"),
    ]


def test_cohort_source_returns_unsafe_spill_location_as_invalid_product(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = _build_cohort_source_product(tmp_path)

    def reject_guard(path: Path, *, artifact_label: str) -> None:
        raise ValueError(f"unsafe {artifact_label}: {path}")

    monkeypatch.setattr(
        cohort_source_module,
        "require_safe_output_location",
        reject_guard,
    )

    result = validate_cohort_source(database_path)

    assert not result.valid
    assert result.errors == (
        f"unsafe cohort-source database/spill directory: {database_path.parent}",
    )


def test_trusted_population_receipt_binds_exact_source_and_passed_gates(
    tmp_path: Path,
) -> None:
    database_path = _build_cohort_source_product(tmp_path)
    result = validate_cohort_source(database_path, required_elements=_REQUIRED_ELEMENTS)
    assert result.valid and result.metadata is not None
    metadata = result.metadata.to_dict()
    metadata.pop("database")
    metadata.pop("database_size_bytes")
    sidecar_path = database_path.parent / COMBINED_MANIFEST_FILENAME
    receipt = {
        "acceptance_contract_version": "1.0",
        "status": "accepted",
        "kind": "canonical_cohort_source",
        "purpose": "glp1_abstract_population",
        "database_sha256": sha256(database_path.read_bytes()).hexdigest(),
        "database_size_bytes": database_path.stat().st_size,
        "sidecar_sha256": sha256(sidecar_path.read_bytes()).hexdigest(),
        "required_elements": list(_REQUIRED_ELEMENTS),
        "metadata": metadata,
        "gates": {
            name: {"pass": True, "evidence_sha256": sha256(name.encode()).hexdigest()}
            for name in (
                "source_provenance",
                "source_scope",
                "historical_index_coverage",
            )
        },
    }
    receipt_path = tmp_path / "accepted-source.json"
    receipt_path.write_text(json.dumps(receipt, sort_keys=True))
    trusted_digest = sha256(receipt_path.read_bytes()).hexdigest()
    options = {"receipt_path": receipt_path, "expected_receipt_sha256": trusted_digest}

    verified = verify_accepted_cohort_source(database_path, **options)
    assert verified == result.metadata
    with open_accepted_cohort_source(database_path, **options) as source:
        assert source.metadata == verified
        assert (
            source.connection.execute(
                "SELECT count(*) FROM source_encounter"
            ).fetchone()
            is not None
        )

    with pytest.raises(ValueError, match="trusted expectation"):
        verify_accepted_cohort_source(
            database_path,
            **{**options, "expected_receipt_sha256": "0" * 64},
        )
    receipt["gates"]["historical_index_coverage"]["pass"] = False
    receipt_path.write_text(json.dumps(receipt, sort_keys=True))
    with pytest.raises(ValueError, match="passing required population gates"):
        verify_accepted_cohort_source(
            database_path,
            **{
                **options,
                "expected_receipt_sha256": sha256(
                    receipt_path.read_bytes()
                ).hexdigest(),
            },
        )
    receipt["gates"]["historical_index_coverage"]["pass"] = True
    receipt_path.write_text(json.dumps(receipt, sort_keys=True))
    with duckdb.connect(str(database_path)) as connection:
        connection.execute("UPDATE preprocessing_manifest SET status = 'building'")
        connection.execute("CHECKPOINT")
    with pytest.raises(ValueError, match="differs from trusted receipt"):
        verify_accepted_cohort_source(
            database_path,
            **{
                **options,
                "expected_receipt_sha256": sha256(
                    receipt_path.read_bytes()
                ).hexdigest(),
            },
        )

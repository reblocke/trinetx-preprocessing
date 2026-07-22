"""Versioned provenance for resumable pipeline work tables."""

from __future__ import annotations

import csv
import hashlib
import json
import platform
from dataclasses import asdict
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any, Iterable

from . import __version__
from .config import Config, collect_domain_paths
from .profiling import current_git_code_state_sha256

WORK_MANIFEST_FILENAME = "pipeline_work_manifest.json"
WORK_MANIFEST_SCHEMA_VERSION = 5
INTERMEDIATE_SCHEMA_VERSION = 8
LEGACY_DATA_SCREEN_FILENAMES = (
    "amb_enc_screen.csv",
    "inp_enc_screen.csv",
)
DOMAIN_STAGES = (
    "labs",
    "encounter",
    "diagnosis",
    "medications",
    "procedure",
    "vitals",
)
FINAL_ASSEMBLY_PREREQUISITES = (*DOMAIN_STAGES, "rfs")
STAGE_ORDER = (*DOMAIN_STAGES, "rfs", "final_assembly")
STAGE_INTERNAL_ARTIFACTS = {
    "labs": (
        "analysis_lab_features.csv",
        "analysis_lab_availability.csv",
        "analysis_rfs_labs.csv",
        "rfs_rule_audit.json",
    ),
    "diagnosis": (
        "analysis_diagnosis_features.csv",
        "analysis_diagnosis_availability.csv",
        "analysis_rfs_diagnosis.csv",
    ),
    "medications": ("analysis_medication_features.csv",),
    "procedure": (
        "analysis_procedure_features.csv",
        "analysis_rfs_procedure.csv",
    ),
    "vitals": (
        "analysis_vital_features.csv",
        "analysis_rfs_vitals.csv",
    ),
    "rfs": ("rfs_stage_metrics.json",),
    "final_assembly": ("final_assembly_metrics.json",),
}


class StaleWorkError(RuntimeError):
    """Raised when work tables cannot be proven current."""


def initialize_work_manifest(config: Config) -> Path:
    """Create or validate the work manifest before writing intermediates."""

    config.work_dir.mkdir(parents=True, exist_ok=True)
    path = work_manifest_path(config)
    expected = _identity(config)
    if path.exists():
        manifest = _read_manifest(path)
        _require_identity(manifest, expected)
        return path

    managed_top_level_names = {WORK_MANIFEST_FILENAME}
    if config.data_screen.source == "legacy_files":
        managed_top_level_names.add("data_checks")
    unmanaged = [
        item
        for item in config.work_dir.iterdir()
        if item.name not in managed_top_level_names and not item.name.startswith(".")
    ]
    if unmanaged:
        raise StaleWorkError(
            "Work directory contains unmanaged artifacts; clean it before starting "
            f"the corrected pipeline: {config.work_dir}"
        )

    now = _timestamp()
    manifest = {
        **expected,
        "created_at": now,
        "updated_at": now,
        "stages": {},
    }
    _write_manifest(path, manifest)
    return path


def mark_stage_complete(
    config: Config,
    stage: str,
    output_paths: Iterable[Path],
    *,
    physical_output_dir: Path | None = None,
) -> None:
    """Atomically record a completed stage and its generated file metadata."""

    path = initialize_work_manifest(config)
    manifest = _read_manifest(path)
    artifacts = _stage_artifact_paths(config, stage, output_paths)
    missing_artifacts = [path for path in artifacts if not path.exists()]
    if missing_artifacts:
        raise StaleWorkError(
            f"Stage {stage} did not produce required artifacts: "
            + ", ".join(str(path) for path in missing_artifacts)
        )

    outputs = []
    known_row_counts = _known_row_counts(
        config,
        stage,
        output_dir=physical_output_dir,
    )
    for output_path in artifacts:
        candidate = Path(output_path)
        candidate_stat = candidate.stat()
        outputs.append(
            {
                "path": _display_path(
                    candidate,
                    config,
                    physical_output_dir=physical_output_dir,
                ),
                "size_bytes": candidate_stat.st_size,
                "mtime_ns": candidate_stat.st_mtime_ns,
                "row_count": _row_count(
                    candidate,
                    known_row_count=known_row_counts.get(candidate.resolve()),
                ),
            }
        )
    manifest["stages"][stage] = {
        "status": "complete",
        "completed_at": _timestamp(),
        "outputs": outputs,
    }
    manifest["updated_at"] = _timestamp()
    _write_manifest(path, manifest)


def mark_stage_started(config: Config, stage: str) -> None:
    """Mark a stage running and invalidate it plus every downstream stage."""

    if stage not in STAGE_ORDER:
        raise ValueError(f"Unknown pipeline stage: {stage}")
    path = initialize_work_manifest(config)
    manifest = _read_manifest(path)
    stage_index = STAGE_ORDER.index(stage)
    for invalidated in STAGE_ORDER[stage_index:]:
        manifest["stages"].pop(invalidated, None)
    manifest["stages"][stage] = {
        "status": "running",
        "started_at": _timestamp(),
        "outputs": [],
    }
    manifest["updated_at"] = _timestamp()
    _write_manifest(path, manifest)


def refresh_stage_output_metadata(
    config: Config,
    stage: str,
    *,
    physical_output_dir: Path | None = None,
) -> None:
    """Refresh fingerprints after a staged artifact is regenerated in place."""

    path = work_manifest_path(config)
    manifest = _read_manifest(path)
    stage_record = manifest["stages"].get(stage)
    if not isinstance(stage_record, dict) or stage_record.get("status") != "complete":
        raise StaleWorkError(f"Cannot refresh incomplete stage: {stage}")
    known_row_counts = _known_row_counts(
        config,
        stage,
        output_dir=physical_output_dir,
    )
    for output in stage_record.get("outputs", []):
        display_path = str(output.get("path", ""))
        logical_path = Path(display_path)
        if logical_path.parts and logical_path.parts[0] == "output":
            root = physical_output_dir or config.output_dir
            candidate = root / Path(*logical_path.parts[1:])
        else:
            candidate = _manifest_output_path(display_path, config)
        if not candidate.exists():
            raise StaleWorkError(
                f"Cannot refresh missing {stage} artifact: {candidate}"
            )
        candidate_stat = candidate.stat()
        output["size_bytes"] = candidate_stat.st_size
        output["mtime_ns"] = candidate_stat.st_mtime_ns
        output["row_count"] = _row_count(
            candidate,
            known_row_count=known_row_counts.get(candidate.resolve()),
        )
    manifest["updated_at"] = _timestamp()
    _write_manifest(path, manifest)


def require_current_work(
    config: Config,
    *,
    required_stages: Iterable[str],
) -> dict[str, Any]:
    """Validate identity and required stage completion for a resume command."""

    path = work_manifest_path(config)
    if not path.exists():
        raise StaleWorkError(
            f"Missing {WORK_MANIFEST_FILENAME}; rerun prerequisite stages."
        )
    manifest = _read_manifest(path)
    _require_identity(manifest, _identity(config))
    missing = [
        stage
        for stage in required_stages
        if manifest["stages"].get(stage, {}).get("status") != "complete"
    ]
    if missing:
        raise StaleWorkError(
            "Work manifest is missing completed stages: " + ", ".join(missing)
        )
    for stage in required_stages:
        _require_stage_outputs_current(config, stage, manifest["stages"][stage])
    return manifest


def require_strict_encounter_work(config: Config) -> None:
    """Reject strict resumes from deterministically conflict-resolved encounters."""

    path = config.work_dir / "encounter_conflicts.json"
    if not path.exists():
        return
    try:
        payload = json.loads(path.read_text())
        conflict_count = int(payload["encounter_conflict_count"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise StaleWorkError(
            f"Strict resume cannot validate encounter conflict report: {path}"
        ) from exc
    if conflict_count:
        raise StaleWorkError(
            "Strict resume requires conflict-free encounter work; "
            f"found {conflict_count} deterministically resolved conflict(s)."
        )


def work_manifest_path(config: Config) -> Path:
    """Return the configured work-manifest path."""

    return config.work_dir / WORK_MANIFEST_FILENAME


def _identity(config: Config) -> dict[str, Any]:
    combined_catalog_sha256 = None
    if config.combined.enabled:
        from .combined_preprocessing.elements import load_combined_catalog

        combined_catalog_sha256 = load_combined_catalog(config).sha256
    config_payload = {
        "data_dir": str(config.data_dir),
        "work_dir": str(config.work_dir),
        "output_dir": str(config.output_dir),
        "domains": {
            name: list(domain.pattern_list)
            for name, domain in sorted(config.domains.items())
        },
        "chunking": asdict(config.chunking),
        "rfs": asdict(config.rfs),
        "guardrails": asdict(config.guardrails),
        "storage": asdict(config.storage),
        "cohort": asdict(config.cohort),
        "data_screen": asdict(config.data_screen),
        "combined": {
            "enabled": config.combined.enabled,
            "database_name": config.combined.database_name,
            "schema_version": config.combined.schema_version,
            "concept_sets_dir": (
                str(config.combined.concept_sets_dir)
                if config.combined.concept_sets_dir is not None
                else None
            ),
        },
    }
    encoded = json.dumps(config_payload, sort_keys=True, separators=(",", ":"))
    code_state_sha256 = current_git_code_state_sha256()
    if code_state_sha256 is None:
        raise StaleWorkError("Cannot fingerprint the current pipeline code state.")
    return {
        "schema_version": WORK_MANIFEST_SCHEMA_VERSION,
        "intermediate_schema_version": INTERMEDIATE_SCHEMA_VERSION,
        "package_version": __version__,
        "git_code_state_sha256": code_state_sha256,
        "runtime_versions": _runtime_versions(),
        "ruleset": config.rfs.ruleset,
        "combined_element_catalog_sha256": combined_catalog_sha256,
        "config_hash": hashlib.sha256(encoded.encode("utf-8")).hexdigest(),
        "inputs": _input_fingerprints(config),
    }


def _input_fingerprints(config: Config) -> list[dict[str, Any]]:
    paths_by_domain = collect_domain_paths(config)
    fingerprints: list[dict[str, Any]] = []
    for domain, paths in sorted(paths_by_domain.items()):
        for path in paths:
            fingerprints.append(_input_fingerprint(domain=domain, path=path))
    if config.data_screen.source == "legacy_files":
        for path in _legacy_data_screen_paths(config):
            fingerprints.append(_input_fingerprint(domain="data_screen", path=path))
    return fingerprints


def _legacy_data_screen_paths(config: Config) -> tuple[Path, ...]:
    data_checks_dir = config.work_dir / "data_checks"
    paths = tuple(data_checks_dir / name for name in LEGACY_DATA_SCREEN_FILENAMES)
    missing = [path for path in paths if not path.is_file()]
    if missing:
        raise StaleWorkError(
            "Legacy data screening requires current input files: "
            + ", ".join(str(path) for path in missing)
        )
    return paths


def _input_fingerprint(
    *,
    domain: str,
    path: Path,
) -> dict[str, Any]:
    stat = path.stat()
    with path.open("r", encoding="utf-8-sig", errors="replace") as handle:
        header = handle.readline().rstrip("\r\n")
    return {
        "domain": domain,
        "path": str(path),
        "size_bytes": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "header": header,
    }


def _require_identity(
    manifest: dict[str, Any],
    expected: dict[str, Any],
) -> None:
    keys = (
        "schema_version",
        "intermediate_schema_version",
        "package_version",
        "git_code_state_sha256",
        "runtime_versions",
        "ruleset",
        "combined_element_catalog_sha256",
        "config_hash",
        "inputs",
    )
    mismatched = [key for key in keys if manifest.get(key) != expected.get(key)]
    if mismatched:
        raise StaleWorkError("Work manifest is stale for: " + ", ".join(mismatched))


def _read_manifest(path: Path) -> dict[str, Any]:
    try:
        manifest = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise StaleWorkError(f"Cannot read work manifest {path}: {exc}") from exc
    if not isinstance(manifest, dict) or not isinstance(manifest.get("stages"), dict):
        raise StaleWorkError(f"Invalid work manifest structure: {path}")
    return manifest


def _write_manifest(path: Path, manifest: dict[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)


def _stage_artifact_paths(
    config: Config,
    stage: str,
    output_paths: Iterable[Path],
) -> list[Path]:
    from .storage import resolve_work_table

    artifacts = [Path(path) for path in output_paths]
    for logical_name in STAGE_INTERNAL_ARTIFACTS.get(stage, ()):
        if logical_name.endswith(".json"):
            artifacts.append(config.work_dir / logical_name)
        else:
            artifacts.append(resolve_work_table(config, logical_name))
    return list(dict.fromkeys(artifacts))


def _require_stage_outputs_current(
    config: Config,
    stage: str,
    stage_record: dict[str, Any],
) -> None:
    for output in stage_record.get("outputs", []):
        path = _manifest_output_path(str(output.get("path", "")), config)
        if not path.exists():
            raise StaleWorkError(f"Completed {stage} artifact is missing: {path}")
        path_stat = path.stat()
        if (
            output.get("size_bytes") != path_stat.st_size
            or output.get("mtime_ns") != path_stat.st_mtime_ns
        ):
            raise StaleWorkError(f"Completed {stage} artifact changed: {path}")


def _manifest_output_path(display_path: str, config: Config) -> Path:
    path = Path(display_path)
    if path.parts and path.parts[0] == "work":
        return config.work_dir / Path(*path.parts[1:])
    if path.parts and path.parts[0] == "output":
        return config.output_dir / Path(*path.parts[1:])
    return path


def _known_row_counts(
    config: Config,
    stage: str,
    *,
    output_dir: Path | None = None,
) -> dict[Path, int]:
    if stage != "final_assembly":
        return {}
    metrics_path = config.work_dir / "final_assembly_metrics.json"
    try:
        metrics = json.loads(metrics_path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    setting_dirs = {"AMB": "AMBULATORY", "EMER": "EMERGENCY", "INPAT": "INPATIENT"}
    output_root = output_dir or config.output_dir
    counts: dict[Path, int] = {}
    for key, count in metrics.get("rows_written", {}).items():
        setting, category, suffix = key.split("/")
        path = (
            output_root
            / setting_dirs[setting]
            / f"RFS_{category}_ENC_{setting}_{suffix}.csv"
        )
        counts[path.resolve()] = int(count)
    return counts


def _row_count(path: Path, *, known_row_count: int | None) -> int | None:
    if known_row_count is not None:
        return known_row_count
    if path.suffix.lower() == ".parquet":
        import pyarrow.parquet as pq

        return int(pq.ParquetFile(path).metadata.num_rows)
    if path.suffix.lower() != ".csv":
        return None
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = sum(1 for _ in csv.reader(handle))
    return max(rows - 1, 0)


def _runtime_versions() -> dict[str, str | None]:
    packages = ("numpy", "pandas", "pyarrow", "pyyaml")
    versions: dict[str, str | None] = {"python": platform.python_version()}
    for package in packages:
        try:
            versions[package] = version(package)
        except PackageNotFoundError:
            versions[package] = None
    return versions


def _display_path(
    path: Path,
    config: Config,
    *,
    physical_output_dir: Path | None = None,
) -> str:
    roots = (
        ("work", config.work_dir),
        ("output", physical_output_dir or config.output_dir),
    )
    for label, root in roots:
        if path.is_relative_to(root):
            return str(Path(label) / path.relative_to(root))
    return str(path)


def _timestamp() -> str:
    return datetime.now(UTC).isoformat()

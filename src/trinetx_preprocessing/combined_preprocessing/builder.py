"""Orchestration for the canonical combined preprocessing build."""

from __future__ import annotations

import os
import subprocess
import time
import uuid
from dataclasses import dataclass, replace
from pathlib import Path

from ..config import Config
from ..filesystem import remove_tree_strict
from ..pipeline.run import run_pipeline
from ..regression import CsvHashResult, hash_csv_with_metadata
from ..work_manifest import refresh_stage_output_metadata
from .contract import compatibility_outputs
from .database import (
    COMBINED_MANIFEST_FILENAME,
    create_combined_database,
    export_compatibility_outputs,
    refresh_database_work_manifest_fingerprint,
    write_combined_manifest,
)
from .validation import CombinedValidationResult, validate_preprocessed_database


@dataclass(frozen=True)
class CombinedBuildResult:
    """Published paths and aggregate evidence for a combined build."""

    database_path: Path
    manifest_path: Path
    compatibility_paths: tuple[Path, ...]
    run_id: str
    validation: CombinedValidationResult


def build_preprocessed(
    config: Config,
    *,
    strict: bool = False,
    replace_existing: bool = False,
    timings: dict[str, float] | None = None,
) -> CombinedBuildResult:
    """Build, validate, and transactionally publish one combined product."""

    require_safe_output_location(config.work_dir, artifact_label="work directory")
    require_safe_output_location(config.output_dir, artifact_label="output directory")
    published_output = config.output_dir
    database_path = published_output / config.combined.database_name
    _validate_existing_product(
        published_output,
        database_name=config.combined.database_name,
        replace_existing=replace_existing,
    )

    staging_output = published_output.parent / (
        f".{published_output.name}.combined-build-{uuid.uuid4().hex}"
    )
    staging_output.mkdir(parents=True)
    combined_config = replace(
        config,
        combined=replace(config.combined, enabled=True),
    )
    try:
        phase_started = time.perf_counter()
        run_pipeline(
            combined_config,
            strict=strict,
            final_output_dir=staging_output,
        )
        _record_timing(timings, "pipeline", phase_started)
        baseline = _compatibility_hashes(staging_output)
        staged_database = staging_output / config.combined.database_name
        phase_started = time.perf_counter()
        manifest = create_combined_database(
            combined_config,
            staged_database,
            compatibility_hashes=baseline,
            compatibility_output_dir=staging_output,
            published_output_dir=published_output,
        )
        _record_timing(timings, "database", phase_started)
        phase_started = time.perf_counter()
        export_compatibility_outputs(
            staged_database,
            staging_output,
            memory_limit_mib=combined_config.combined.duckdb_memory_limit_mib,
        )
        refresh_stage_output_metadata(
            combined_config,
            "final_assembly",
            physical_output_dir=staging_output,
        )
        refresh_database_work_manifest_fingerprint(
            staged_database,
            combined_config,
        )
        exported = _compatibility_hashes(staging_output)
        mismatched = sorted(
            key for key, value in baseline.items() if exported.get(key) != value
        )
        if mismatched:
            raise RuntimeError(
                "Database compatibility exports changed normalized CSV contents: "
                + ", ".join(mismatched)
            )
        _record_timing(timings, "compatibility_export", phase_started)
        phase_started = time.perf_counter()
        validation = validate_preprocessed_database(
            staged_database,
            compatibility_output_dir=staging_output,
            memory_limit_mib=combined_config.combined.duckdb_memory_limit_mib,
        )
        if not validation.valid:
            raise RuntimeError(
                "Combined database validation failed: " + "; ".join(validation.errors)
            )
        _record_timing(timings, "validation", phase_started)

        manifest["database"] = str(database_path)
        manifest["database_size_bytes"] = staged_database.stat().st_size
        write_combined_manifest(
            combined_config,
            manifest,
            output_dir=staging_output,
        )
        _remove_appledouble_sidecars(staging_output)
        phase_started = time.perf_counter()
        _publish_staged_product(
            staging_output,
            published_output,
            replace_existing=replace_existing,
        )
        _record_timing(timings, "publication", phase_started)
        compatibility_paths = tuple(
            published_output / output.relative_path
            for output in compatibility_outputs()
        )
        return CombinedBuildResult(
            database_path=database_path,
            manifest_path=published_output / COMBINED_MANIFEST_FILENAME,
            compatibility_paths=compatibility_paths,
            run_id=str(manifest["run_id"]),
            validation=validation,
        )
    finally:
        if staging_output.exists():
            remove_tree_strict(
                staging_output,
                context="Combined preprocessing staging directory",
            )


def _compatibility_hashes(output_dir: Path) -> dict[str, CsvHashResult]:
    hashes: dict[str, CsvHashResult] = {}
    for output in compatibility_outputs():
        path = output_dir / output.relative_path
        metadata = hash_csv_with_metadata(path)
        hashes[output.key] = metadata
    return hashes


def _record_timing(
    timings: dict[str, float] | None,
    phase: str,
    started: float,
) -> None:
    if timings is not None:
        timings[phase] = time.perf_counter() - started


def _validate_existing_product(
    output_dir: Path,
    *,
    database_name: str,
    replace_existing: bool,
) -> None:
    if not output_dir.exists():
        return
    if output_dir.is_symlink() or not output_dir.is_dir():
        raise ValueError(f"Combined output must be a directory: {output_dir}")
    entries = list(output_dir.iterdir())
    if entries and not replace_existing:
        raise FileExistsError(
            f"Combined output already exists: {output_dir}; use --replace."
        )
    if not entries:
        return
    managed_names = {
        database_name,
        COMBINED_MANIFEST_FILENAME,
        *(output.relative_path.parts[0] for output in compatibility_outputs()),
    }
    unknown = sorted(
        entry.name
        for entry in entries
        if entry.name not in managed_names
        and entry.name != ".DS_Store"
        and not entry.name.startswith("._")
    )
    if unknown:
        raise ValueError(
            "Refusing to replace a combined output directory containing unmanaged "
            "entries: "
            + ", ".join(unknown)
        )


def _publish_staged_product(
    staging_output: Path,
    published_output: Path,
    *,
    replace_existing: bool,
) -> None:
    backup: Path | None = None
    if published_output.exists():
        if any(published_output.iterdir()) and not replace_existing:
            raise FileExistsError(
                f"Combined output already exists: {published_output}; use --replace."
            )
        backup = published_output.parent / (
            f".{published_output.name}.combined-previous-{uuid.uuid4().hex}"
        )
        os.replace(published_output, backup)
    try:
        os.replace(staging_output, published_output)
    except Exception:
        if backup is not None and backup.exists() and not published_output.exists():
            os.replace(backup, published_output)
        raise
    if backup is not None:
        remove_tree_strict(backup, context="Previous combined preprocessing output")


def _remove_appledouble_sidecars(root: Path) -> None:
    """Remove macOS metadata files before publishing the product directory."""

    for path in sorted(Path(root).rglob("._*"), reverse=True):
        if path.is_dir() and not path.is_symlink():
            remove_tree_strict(path, context="AppleDouble directory")
            continue
        path.unlink(missing_ok=True)
        if path.exists() or path.is_symlink():
            raise OSError(f"AppleDouble sidecar was not deleted: {path}")


def require_safe_output_location(
    output_dir: Path,
    *,
    artifact_label: str = "output directory",
) -> None:
    """Reject repository-local row-level combined artifacts."""

    output = Path(output_dir).resolve()
    existing_parent = output
    while not existing_parent.exists() and existing_parent != existing_parent.parent:
        existing_parent = existing_parent.parent
    try:
        result = subprocess.run(
            ["git", "-C", str(existing_parent), "rev-parse", "--show-toplevel"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return
    repository = Path(result.stdout.strip()).resolve()
    try:
        output.relative_to(repository)
    except ValueError:
        return
    raise ValueError(
        f"Refusing repository-local combined preprocessing {artifact_label}: "
        f"{output}. Confidential outputs must be outside {repository}."
    )

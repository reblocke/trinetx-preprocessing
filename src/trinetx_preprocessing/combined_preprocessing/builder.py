"""Orchestration for the canonical combined preprocessing build."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import socket
import subprocess
import time
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Iterator

from ..config import Config
from ..filesystem import remove_tree_strict, write_text_atomic
from ..pipeline.run import run_pipeline
from ..regression import CsvHashResult, hash_csv_with_metadata
from ..work_manifest import (
    STAGE_ORDER,
    StaleWorkError,
    refresh_stage_output_metadata,
    require_current_work,
    require_strict_encounter_work,
    work_identity_sha256,
)
from .contract import compatibility_outputs
from .database import (
    COMBINED_MANIFEST_FILENAME,
    create_combined_database,
    export_compatibility_outputs,
    inspect_combined_database,
    refresh_database_work_manifest_fingerprint,
    write_combined_manifest,
)
from .scratch import (
    COMBINED_BUILD_PREFIX,
    COMBINED_DUCKDB_SPILL_PREFIX,
    COMBINED_LOCK_PREFIX,
    COMBINED_PREVIOUS_PREFIX,
    COMBINED_PUBLICATION_PREFIX,
    COMBINED_VALIDATION_PREFIX,
)
from .validation import CombinedValidationResult, validate_preprocessed_database

_BUILD_STATE_SCHEMA_VERSION = 1
_PUBLICATION_JOURNAL_SCHEMA_VERSION = 1
_PHASE_ORDER = {
    "pipeline": 1,
    "database": 2,
    "compatibility_export": 3,
    "validation": 4,
}


@dataclass(frozen=True)
class CombinedBuildResult:
    """Published paths and aggregate evidence for a combined build."""

    database_path: Path
    manifest_path: Path
    compatibility_paths: tuple[Path, ...]
    run_id: str
    validation: CombinedValidationResult


@dataclass(frozen=True)
class _CombinedBuildPaths:
    staging_output: Path
    state_path: Path
    backup_output: Path
    publication_journal: Path


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
    combined_config = replace(
        config,
        combined=replace(config.combined, enabled=True),
    )
    published_output = combined_config.output_dir
    database_path = published_output / combined_config.combined.database_name

    with _canonical_build_lock(combined_config):
        build_identity = _combined_build_identity(
            combined_config,
            strict=strict,
        )
        paths = _combined_build_paths(
            published_output,
            build_identity=build_identity,
        )
        _recover_interrupted_publication(
            published_output,
            publication_journal=paths.publication_journal,
            backup_output=paths.backup_output,
            database_name=combined_config.combined.database_name,
        )
        _validate_existing_product(
            published_output,
            database_name=combined_config.combined.database_name,
            replace_existing=replace_existing,
        )
        return _build_locked(
            combined_config,
            paths=paths,
            build_identity=build_identity,
            database_path=database_path,
            strict=strict,
            replace_existing=replace_existing,
            timings=timings,
        )


def _build_locked(
    config: Config,
    *,
    paths: _CombinedBuildPaths,
    build_identity: str,
    database_path: Path,
    strict: bool,
    replace_existing: bool,
    timings: dict[str, float] | None,
) -> CombinedBuildResult:
    if paths.staging_output.is_symlink() or (
        paths.staging_output.exists() and not paths.staging_output.is_dir()
    ):
        raise ValueError(
            f"Combined staging output must be a real directory: {paths.staging_output}"
        )
    state = _load_build_state(
        paths.state_path,
        expected_identity=build_identity,
        paths=paths,
        published_output=config.output_dir,
    )
    if state is not None and not paths.staging_output.is_dir():
        raise ValueError(
            "Combined resumable state exists without its staging directory: "
            f"{paths.state_path}"
        )

    pipeline_current = _pipeline_outputs_are_current(
        config,
        paths.staging_output,
        strict=strict,
    )
    if state is None and paths.staging_output.exists() and not pipeline_current:
        _remove_staging_for_restart(
            paths.staging_output,
            database_name=config.combined.database_name,
        )

    if state is None and not pipeline_current:
        paths.staging_output.mkdir(parents=True)
        phase_started = time.perf_counter()
        run_pipeline(
            config,
            strict=strict,
            final_output_dir=paths.staging_output,
        )
        _record_timing(timings, "pipeline", phase_started)
        baseline = _compatibility_hashes(paths.staging_output)
        state = _new_build_state(
            paths,
            build_identity=build_identity,
            published_output=config.output_dir,
            baseline=baseline,
        )
        _write_build_state(paths.state_path, state)
    elif state is None:
        baseline = _compatibility_hashes(paths.staging_output)
        state = _new_build_state(
            paths,
            build_identity=build_identity,
            published_output=config.output_dir,
            baseline=baseline,
        )
        _write_build_state(paths.state_path, state)
    else:
        baseline = _deserialize_hashes(state.get("baseline"))
        if not _phase_at_least(state, "database") and not pipeline_current:
            raise ValueError(
                "Resumable combined pipeline outputs no longer match the work "
                f"manifest: {paths.staging_output}"
            )

    staged_database = paths.staging_output / config.combined.database_name
    if _phase_at_least(state, "database"):
        _require_database_state_current(
            staged_database,
            state,
            config=config,
        )
        manifest = _require_manifest_state(state)
    else:
        _remove_incomplete_database(staged_database)
        phase_started = time.perf_counter()
        manifest = create_combined_database(
            config,
            staged_database,
            compatibility_hashes=baseline,
            compatibility_output_dir=paths.staging_output,
            published_output_dir=config.output_dir,
        )
        _record_timing(timings, "database", phase_started)
        state = {
            **state,
            "phase": "database",
            "manifest": manifest,
            "database_stat": _file_stat(staged_database),
        }
        _write_build_state(paths.state_path, state)

    if _phase_at_least(state, "compatibility_export"):
        _require_database_state_current(
            staged_database,
            state,
            config=config,
        )
        _require_compatibility_state_current(paths.staging_output, state)
        exported = _deserialize_hashes(state.get("exported"))
        _require_matching_hashes(baseline, exported)
    else:
        phase_started = time.perf_counter()
        export_compatibility_outputs(
            staged_database,
            paths.staging_output,
            memory_limit_mib=config.combined.duckdb_memory_limit_mib,
        )
        refresh_stage_output_metadata(
            config,
            "final_assembly",
            physical_output_dir=paths.staging_output,
        )
        refresh_database_work_manifest_fingerprint(staged_database, config)
        exported = _compatibility_hashes(paths.staging_output)
        _require_matching_hashes(baseline, exported)
        _record_timing(timings, "compatibility_export", phase_started)
        manifest = {
            **manifest,
            "database": str(database_path),
            "database_size_bytes": staged_database.stat().st_size,
        }
        state = {
            **state,
            "phase": "compatibility_export",
            "manifest": manifest,
            "database_stat": _file_stat(staged_database),
            "compatibility_stats": _compatibility_file_stats(paths.staging_output),
            "exported": _serialize_hashes(exported),
        }
        _write_build_state(paths.state_path, state)

    manifest = _require_manifest_state(state)
    manifest = {
        **manifest,
        "database": str(database_path),
        "database_size_bytes": staged_database.stat().st_size,
    }
    if _phase_at_least(state, "validation"):
        _require_database_state_current(
            staged_database,
            state,
            config=config,
        )
        _require_compatibility_state_current(paths.staging_output, state)
        _require_file_state_current(
            paths.staging_output / COMBINED_MANIFEST_FILENAME,
            state.get("sidecar_stat"),
            label="combined product sidecar",
        )
        validation = _deserialize_validation(state.get("validation"))
        if not validation.valid:
            raise RuntimeError(
                "Resumable combined validation state is not valid: "
                + "; ".join(validation.errors)
            )
    else:
        sidecar_path = write_combined_manifest(
            config,
            manifest,
            output_dir=paths.staging_output,
        )
        phase_started = time.perf_counter()
        validation = validate_preprocessed_database(
            staged_database,
            compatibility_output_dir=paths.staging_output,
            published_database_path=database_path,
            memory_limit_mib=config.combined.duckdb_memory_limit_mib,
        )
        if not validation.valid:
            raise RuntimeError(
                "Combined database validation failed: " + "; ".join(validation.errors)
            )
        _record_timing(timings, "validation", phase_started)
        state = {
            **state,
            "phase": "validation",
            "manifest": manifest,
            "database_stat": _file_stat(staged_database),
            "compatibility_stats": _compatibility_file_stats(paths.staging_output),
            "sidecar_stat": _file_stat(sidecar_path),
            "validation": _serialize_validation(validation),
        }
        _write_build_state(paths.state_path, state)

    _remove_appledouble_sidecars(paths.staging_output)
    _validate_product_tree(
        paths.staging_output,
        database_name=config.combined.database_name,
        require_complete=True,
        allow_temporary=False,
    )
    phase_started = time.perf_counter()
    _publish_staged_product(
        paths,
        published_output=config.output_dir,
        database_name=config.combined.database_name,
        replace_existing=replace_existing,
    )
    _record_timing(timings, "publication", phase_started)
    compatibility_paths = tuple(
        config.output_dir / output.relative_path for output in compatibility_outputs()
    )
    return CombinedBuildResult(
        database_path=database_path,
        manifest_path=config.output_dir / COMBINED_MANIFEST_FILENAME,
        compatibility_paths=compatibility_paths,
        run_id=str(manifest["run_id"]),
        validation=validation,
    )


def _new_build_state(
    paths: _CombinedBuildPaths,
    *,
    build_identity: str,
    published_output: Path,
    baseline: dict[str, CsvHashResult],
) -> dict[str, object]:
    return {
        "schema_version": _BUILD_STATE_SCHEMA_VERSION,
        "build_identity": build_identity,
        "phase": "pipeline",
        "staging_output": str(paths.staging_output),
        "published_output": str(published_output),
        "baseline": _serialize_hashes(baseline),
    }


def _combined_build_paths(
    published_output: Path,
    *,
    build_identity: str,
) -> _CombinedBuildPaths:
    output = Path(published_output)
    publication_identity = hashlib.sha256(
        str(output.resolve(strict=False)).encode()
    ).hexdigest()
    build_token = build_identity[:24]
    publication_token = publication_identity[:24]
    return _CombinedBuildPaths(
        staging_output=output.parent / f"{COMBINED_BUILD_PREFIX}{build_token}",
        state_path=output.parent / f"{COMBINED_BUILD_PREFIX}{build_token}.state.json",
        backup_output=output.parent / f"{COMBINED_PREVIOUS_PREFIX}{publication_token}",
        publication_journal=output.parent
        / f"{COMBINED_PUBLICATION_PREFIX}{publication_token}.json",
    )


def _combined_build_identity(config: Config, *, strict: bool) -> str:
    """Bind resumable staging to source/code identity and execution policy."""

    payload = {
        "work_identity_sha256": work_identity_sha256(config),
        "strict": strict,
        "duckdb_memory_limit_mib": config.combined.duckdb_memory_limit_mib,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _pipeline_outputs_are_current(
    config: Config,
    staging_output: Path,
    *,
    strict: bool,
) -> bool:
    if not staging_output.is_dir():
        return False
    try:
        require_current_work(
            config,
            required_stages=STAGE_ORDER,
            physical_output_dir=staging_output,
        )
        if strict:
            require_strict_encounter_work(config)
    except (FileNotFoundError, StaleWorkError, ValueError):
        return False
    return True


def _remove_staging_for_restart(
    staging_output: Path,
    *,
    database_name: str,
) -> None:
    _validate_product_tree(
        staging_output,
        database_name=database_name,
        require_complete=False,
        allow_temporary=True,
    )
    remove_tree_strict(
        staging_output,
        context="Incomplete combined preprocessing staging directory",
    )


def _remove_incomplete_database(database_path: Path) -> None:
    for path in (
        database_path,
        database_path.with_name(f"{database_path.name}.wal"),
    ):
        if path.is_symlink() or (path.exists() and not path.is_file()):
            raise ValueError(
                f"Refusing to replace unexpected database artifact: {path}"
            )
        path.unlink(missing_ok=True)
    for path in database_path.parent.glob(f"{COMBINED_DUCKDB_SPILL_PREFIX}*"):
        if path.is_dir() and not path.is_symlink():
            remove_tree_strict(path, context="Incomplete combined DuckDB spill")
        else:
            path.unlink(missing_ok=True)


def _compatibility_hashes(output_dir: Path) -> dict[str, CsvHashResult]:
    hashes: dict[str, CsvHashResult] = {}
    for output in compatibility_outputs():
        path = output_dir / output.relative_path
        hashes[output.key] = hash_csv_with_metadata(path)
    return hashes


def _serialize_hashes(
    hashes: dict[str, CsvHashResult],
) -> dict[str, dict[str, object]]:
    return {
        key: {
            "hash": value.hash,
            "row_count": value.row_count,
            "columns": list(value.columns),
        }
        for key, value in sorted(hashes.items())
    }


def _deserialize_hashes(value: object) -> dict[str, CsvHashResult]:
    if not isinstance(value, dict):
        raise ValueError("Combined build state has no compatibility hashes.")
    expected_keys = {output.key for output in compatibility_outputs()}
    if set(value) != expected_keys:
        raise ValueError(
            "Combined build state does not contain exactly 36 compatibility hashes."
        )
    results: dict[str, CsvHashResult] = {}
    for key, record in value.items():
        if not isinstance(key, str) or not isinstance(record, dict):
            raise ValueError("Combined build compatibility hash state is invalid.")
        hash_value = record.get("hash")
        row_count = record.get("row_count")
        columns = record.get("columns")
        if (
            not isinstance(hash_value, str)
            or isinstance(row_count, bool)
            or not isinstance(row_count, int)
            or not isinstance(columns, list)
            or not all(isinstance(column, str) for column in columns)
        ):
            raise ValueError("Combined build compatibility hash state is invalid.")
        results[key] = CsvHashResult(
            hash=hash_value,
            row_count=row_count,
            columns=tuple(columns),
        )
    return results


def _require_matching_hashes(
    baseline: dict[str, CsvHashResult],
    exported: dict[str, CsvHashResult],
) -> None:
    mismatched = sorted(
        key for key, value in baseline.items() if exported.get(key) != value
    )
    if mismatched:
        raise RuntimeError(
            "Database compatibility exports changed normalized CSV contents: "
            + ", ".join(mismatched)
        )


def _compatibility_file_stats(output_dir: Path) -> dict[str, dict[str, int]]:
    return {
        output.key: _file_stat(output_dir / output.relative_path)
        for output in compatibility_outputs()
    }


def _require_compatibility_state_current(
    output_dir: Path,
    state: dict[str, object],
) -> None:
    observed = _compatibility_file_stats(output_dir)
    if state.get("compatibility_stats") != observed:
        raise ValueError("Resumable combined compatibility files changed after export.")


def _file_stat(path: Path) -> dict[str, int]:
    stat = path.stat()
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"Expected a regular generated file: {path}")
    return {
        "size_bytes": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
    }


def _require_file_state_current(
    path: Path,
    expected: object,
    *,
    label: str,
) -> None:
    if not isinstance(expected, dict) or _file_stat(path) != expected:
        raise ValueError(f"Resumable {label} changed after validation: {path}")


def _require_database_state_current(
    database_path: Path,
    state: dict[str, object],
    *,
    config: Config,
) -> None:
    _require_file_state_current(
        database_path,
        state.get("database_stat"),
        label="combined database",
    )
    manifest = _require_manifest_state(state)
    status = inspect_combined_database(
        database_path,
        memory_limit_mib=config.combined.duckdb_memory_limit_mib,
    )
    if status.get("status") != "complete" or status.get("run_id") != manifest.get(
        "run_id"
    ):
        raise ValueError(
            "Resumable combined database identity or terminal status changed."
        )


def _require_manifest_state(state: dict[str, object]) -> dict[str, Any]:
    manifest = state.get("manifest")
    if not isinstance(manifest, dict):
        raise ValueError("Combined build state has no database manifest.")
    return dict(manifest)


def _serialize_validation(
    validation: CombinedValidationResult,
) -> dict[str, object]:
    return {
        "valid": validation.valid,
        "errors": list(validation.errors),
        "warnings": list(validation.warnings),
        "counts": validation.counts,
    }


def _deserialize_validation(value: object) -> CombinedValidationResult:
    if not isinstance(value, dict):
        raise ValueError("Combined build state has no validation result.")
    valid = value.get("valid")
    errors = value.get("errors")
    warnings = value.get("warnings")
    counts = value.get("counts")
    if (
        not isinstance(valid, bool)
        or not isinstance(errors, list)
        or not all(isinstance(item, str) for item in errors)
        or not isinstance(warnings, list)
        or not all(isinstance(item, str) for item in warnings)
        or not isinstance(counts, dict)
        or any(
            not isinstance(key, str)
            or isinstance(count, bool)
            or not isinstance(count, int)
            for key, count in counts.items()
        )
    ):
        raise ValueError("Combined build validation state is invalid.")
    return CombinedValidationResult(
        valid=valid,
        errors=tuple(errors),
        warnings=tuple(warnings),
        counts=dict(counts),
    )


def _phase_at_least(state: dict[str, object], phase: str) -> bool:
    current = state.get("phase")
    return (
        isinstance(current, str) and _PHASE_ORDER.get(current, 0) >= _PHASE_ORDER[phase]
    )


def _load_build_state(
    path: Path,
    *,
    expected_identity: str,
    paths: _CombinedBuildPaths,
    published_output: Path,
) -> dict[str, object] | None:
    if not path.exists():
        return None
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"Invalid combined build state path: {path}")
    try:
        payload = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Cannot read combined build state {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"Combined build state must be a JSON object: {path}")
    expected = {
        "schema_version": _BUILD_STATE_SCHEMA_VERSION,
        "build_identity": expected_identity,
        "staging_output": str(paths.staging_output),
        "published_output": str(published_output),
    }
    mismatched = [key for key, value in expected.items() if payload.get(key) != value]
    if payload.get("phase") not in _PHASE_ORDER:
        mismatched.append("phase")
    if mismatched:
        details = ", ".join(sorted(mismatched))
        raise ValueError(f"Combined build state is stale or invalid for: {details}")
    return payload


def _write_build_state(path: Path, payload: dict[str, object]) -> None:
    write_text_atomic(path, json.dumps(payload, indent=2, sort_keys=True) + "\n")
    _fsync_directory(path.parent)


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
    if output_dir.is_symlink():
        raise ValueError(f"Combined output must be a directory: {output_dir}")
    if not output_dir.exists():
        return
    if not output_dir.is_dir():
        raise ValueError(f"Combined output must be a directory: {output_dir}")
    entries = list(output_dir.iterdir())
    if entries and not replace_existing:
        raise FileExistsError(
            f"Combined output already exists: {output_dir}; use --replace."
        )
    if entries:
        _validate_product_tree(
            output_dir,
            database_name=database_name,
            require_complete=False,
            allow_temporary=False,
        )


def _validate_product_tree(
    root: Path,
    *,
    database_name: str,
    require_complete: bool,
    allow_temporary: bool,
) -> None:
    if root.is_symlink() or not root.is_dir():
        raise ValueError(f"Combined product root must be a real directory: {root}")
    managed_files = {
        Path(database_name),
        Path(COMBINED_MANIFEST_FILENAME),
        *(output.relative_path for output in compatibility_outputs()),
    }
    managed_directories = {
        parent
        for path in managed_files
        for parent in path.parents
        if parent != Path(".")
    }
    observed_files: set[Path] = set()
    unknown: list[str] = []
    pending = [Path(root)]
    while pending:
        directory = pending.pop()
        for path in sorted(directory.iterdir(), key=lambda item: item.name):
            relative = path.relative_to(root)
            if path.is_symlink():
                unknown.append(relative.as_posix())
                continue
            if path.is_dir():
                if relative in managed_directories:
                    pending.append(path)
                elif allow_temporary and (
                    path.name.startswith(COMBINED_DUCKDB_SPILL_PREFIX)
                    or path.name.startswith(COMBINED_VALIDATION_PREFIX)
                ):
                    continue
                else:
                    unknown.append(relative.as_posix())
                continue
            if not path.is_file():
                unknown.append(relative.as_posix())
                continue
            if relative in managed_files:
                observed_files.add(relative)
                continue
            if path.name == ".DS_Store" or path.name.startswith("._"):
                continue
            if allow_temporary and _is_allowed_temporary_file(
                relative,
                managed_files=managed_files,
                database_name=database_name,
            ):
                continue
            unknown.append(relative.as_posix())
    if unknown:
        raise ValueError(
            "Refusing to replace a combined output directory containing unmanaged "
            "entries: " + ", ".join(sorted(unknown))
        )
    missing = sorted(path.as_posix() for path in managed_files - observed_files)
    if require_complete and missing:
        raise ValueError(
            "Combined staged product is missing managed files: " + ", ".join(missing)
        )


def _is_allowed_temporary_file(
    relative: Path,
    *,
    managed_files: set[Path],
    database_name: str,
) -> bool:
    if relative == Path(f"{database_name}.wal"):
        return True
    for managed in managed_files:
        if (
            relative.parent == managed.parent
            and relative.name == f".{managed.name}.tmp"
        ):
            return True
        if relative.parent == managed.parent and relative.name.startswith(
            f".{managed.name}.tmp-"
        ):
            return True
    return False


def _publish_staged_product(
    paths: _CombinedBuildPaths,
    *,
    published_output: Path,
    database_name: str,
    replace_existing: bool,
) -> None:
    if paths.publication_journal.exists() or paths.backup_output.exists():
        raise ValueError(
            "Combined publication recovery artifacts must be reconciled before "
            "publication."
        )
    had_existing = published_output.exists()
    if had_existing and any(published_output.iterdir()) and not replace_existing:
        raise FileExistsError(
            f"Combined output already exists: {published_output}; use --replace."
        )
    journal = {
        "schema_version": _PUBLICATION_JOURNAL_SCHEMA_VERSION,
        "state": "prepared",
        "had_existing": had_existing,
        "published_output": str(published_output),
        "staging_output": str(paths.staging_output),
        "backup_output": str(paths.backup_output),
        "build_state_path": str(paths.state_path),
    }
    _write_publication_journal(paths.publication_journal, journal)
    installed = False
    try:
        if had_existing:
            os.replace(published_output, paths.backup_output)
            _fsync_directory(published_output.parent)
            journal["state"] = "old_moved"
            _write_publication_journal(paths.publication_journal, journal)
        os.replace(paths.staging_output, published_output)
        installed = True
        _fsync_directory(published_output.parent)
        journal["state"] = "new_installed"
        _write_publication_journal(paths.publication_journal, journal)
    except BaseException:
        rolled_back = False
        if (
            not installed
            and paths.backup_output.exists()
            and not published_output.exists()
        ):
            os.replace(paths.backup_output, published_output)
            _fsync_directory(published_output.parent)
            rolled_back = True
        safe_to_discard_journal = (
            rolled_back
            or (
                published_output.exists()
                and paths.staging_output.exists()
                and not paths.backup_output.exists()
            )
            or (
                not had_existing
                and not published_output.exists()
                and paths.staging_output.exists()
                and not paths.backup_output.exists()
            )
        )
        if not installed and safe_to_discard_journal:
            _unlink_generated_file(paths.publication_journal)
        raise

    if paths.backup_output.exists():
        _validate_product_tree(
            paths.backup_output,
            database_name=database_name,
            require_complete=False,
            allow_temporary=False,
        )
        remove_tree_strict(
            paths.backup_output,
            context="Previous combined preprocessing output",
        )
    _unlink_generated_file(paths.state_path)
    _unlink_generated_file(paths.publication_journal)
    _fsync_directory(published_output.parent)


def _recover_interrupted_publication(
    published_output: Path,
    *,
    publication_journal: Path,
    backup_output: Path,
    database_name: str,
) -> None:
    journal_path = publication_journal
    if published_output.is_symlink() or backup_output.is_symlink():
        raise ValueError(
            "Combined publication paths must not be symbolic links: "
            f"{published_output}, {backup_output}"
        )
    if not journal_path.exists():
        if backup_output.exists():
            raise ValueError(
                "Combined publication backup exists without its recovery journal: "
                f"{backup_output}"
            )
        return
    if journal_path.is_symlink() or not journal_path.is_file():
        raise ValueError(
            f"Combined publication journal must be a regular file: {journal_path}"
        )
    try:
        journal = json.loads(journal_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(
            f"Cannot read combined publication journal {journal_path}: {exc}"
        ) from exc
    if not isinstance(journal, dict):
        raise ValueError(f"Invalid combined publication journal: {journal_path}")
    recorded_published = Path(str(journal.get("published_output", "")))
    recorded_staging = Path(str(journal.get("staging_output", "")))
    recorded_backup = Path(str(journal.get("backup_output", "")))
    recorded_state = Path(str(journal.get("build_state_path", "")))
    if (
        journal.get("schema_version") != _PUBLICATION_JOURNAL_SCHEMA_VERSION
        or recorded_published != published_output
        or recorded_backup != backup_output
        or recorded_staging.parent != published_output.parent
        or not recorded_staging.name.startswith(COMBINED_BUILD_PREFIX)
        or recorded_state.parent != published_output.parent
        or not recorded_state.name.startswith(COMBINED_BUILD_PREFIX)
        or recorded_state.name != f"{recorded_staging.name}.state.json"
    ):
        raise ValueError(
            f"Combined publication journal paths are invalid: {journal_path}"
        )
    if recorded_staging.is_symlink() or recorded_state.is_symlink():
        raise ValueError(
            f"Combined publication recovery paths must not be symbolic links: "
            f"{journal_path}"
        )
    if recorded_staging.exists() and not recorded_staging.is_dir():
        raise ValueError(
            f"Combined publication staging path must be a directory: {recorded_staging}"
        )
    if recorded_state.exists() and not recorded_state.is_file():
        raise ValueError(
            f"Combined publication state path must be a regular file: {recorded_state}"
        )
    had_existing = journal.get("had_existing")
    if not isinstance(had_existing, bool):
        raise ValueError(
            f"Combined publication journal has invalid prior state: {journal_path}"
        )

    published_exists = published_output.exists()
    staging_exists = recorded_staging.exists()
    backup_exists = backup_output.exists()
    if published_exists:
        _validate_product_tree(
            published_output,
            database_name=database_name,
            require_complete=False,
            allow_temporary=False,
        )
    if backup_exists:
        _validate_product_tree(
            backup_output,
            database_name=database_name,
            require_complete=False,
            allow_temporary=False,
        )
    if published_exists and not staging_exists:
        _validate_product_tree(
            published_output,
            database_name=database_name,
            require_complete=True,
            allow_temporary=False,
        )
        if backup_exists:
            remove_tree_strict(
                backup_output,
                context="Recovered previous combined preprocessing output",
            )
        _unlink_generated_file(recorded_state)
        _unlink_generated_file(journal_path)
        _fsync_directory(published_output.parent)
        return
    if not published_exists and backup_exists:
        os.replace(backup_output, published_output)
        _fsync_directory(published_output.parent)
        _unlink_generated_file(journal_path)
        return
    if published_exists and staging_exists and not backup_exists:
        _unlink_generated_file(journal_path)
        return
    if (
        not published_exists
        and not backup_exists
        and staging_exists
        and not had_existing
    ):
        _unlink_generated_file(journal_path)
        return
    raise ValueError(
        "Combined publication journal describes an ambiguous filesystem state: "
        f"{journal_path}"
    )


def _write_publication_journal(path: Path, payload: dict[str, object]) -> None:
    write_text_atomic(path, json.dumps(payload, indent=2, sort_keys=True) + "\n")
    _fsync_directory(path.parent)


def _unlink_generated_file(path: Path) -> None:
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise ValueError(f"Refusing to delete unexpected generated path: {path}")
    path.unlink(missing_ok=True)
    if path.exists() or path.is_symlink():
        raise OSError(f"Generated file was not deleted: {path}")


@contextmanager
def _canonical_build_lock(config: Config) -> Iterator[None]:
    lock_paths = sorted(
        {
            _lock_path(config.work_dir),
            _lock_path(config.output_dir),
        },
        key=str,
    )
    handles = []
    payload = {
        "schema_version": 1,
        "pid": os.getpid(),
        "hostname": socket.gethostname(),
        "work_dir": str(config.work_dir),
        "output_dir": str(config.output_dir),
    }
    try:
        for lock_path in lock_paths:
            lock_path.parent.mkdir(parents=True, exist_ok=True)
            handle = lock_path.open("a+", encoding="utf-8")
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                handle.seek(0)
                owner = handle.read().strip()
                handle.close()
                details = f" ({owner})" if owner else ""
                raise RuntimeError(
                    "Another combined preprocessing build holds the canonical "
                    f"work/output lock: {lock_path}{details}"
                ) from exc
            handle.seek(0)
            handle.truncate()
            handle.write(json.dumps(payload, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
            handles.append(handle)
        yield
    finally:
        for handle in reversed(handles):
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            finally:
                handle.close()


def _lock_path(root: Path) -> Path:
    resolved = Path(root).resolve(strict=False)
    token = hashlib.sha256(str(resolved).encode()).hexdigest()[:24]
    return resolved.parent / f"{COMBINED_LOCK_PREFIX}{token}"


def _fsync_directory(path: Path) -> None:
    try:
        descriptor = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)


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

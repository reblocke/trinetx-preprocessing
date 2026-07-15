"""Production orchestration for the additive GLP-1 eligibility build."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

from ..filesystem import remove_tree_strict
from .cohort import CoreCohortCounts, build_cohort_flow, build_core_cohort
from .concept_sets import load_concept_sets
from .config import load_glp1_config
from .database import initialize_database, mark_database_complete
from .discovery import validate_export
from .eligibility import build_eligibility_phenotypes
from .ingestion import build_raw_observability_summaries, ingest_core_sources
from .monitoring import RunStateWriter, state_path_for_output
from .outputs import summarize_database, write_build_outputs
from .provenance import (
    build_input_inventory,
    current_git_sha,
    deterministic_run_id,
)
from .terminology_qa import build_concept_match_summary
from .workspace import BUILD_STATE_FILENAME, prepare_workspace, publish_workspace


@dataclass(frozen=True)
class BuildResult:
    """Published paths and aggregate counts from a GLP-1 build."""

    run_id: str
    output_dir: Path
    output_paths: tuple[Path, ...]
    counts: CoreCohortCounts
    warning_count: int = 0
    reused_existing: bool = False


def build_glp1_eligibility(
    *,
    input_root: Path,
    output_dir: Path,
    config_path: Path,
    replace: bool = False,
) -> BuildResult:
    """Build and atomically publish the GLP-1 core analytic database."""

    output = Path(output_dir).resolve()
    _require_safe_output_location(output)
    state = RunStateWriter(
        output,
        "inventory-pending",
        state_path=state_path_for_output(output),
    )
    workspace = None
    connection = None
    try:
        config = load_glp1_config(config_path)
        catalog = load_concept_sets(config.concept_sets_dir)
        report = validate_export(input_root)
        if not report.valid:
            raise ValueError("Export validation failed: " + "; ".join(report.errors))
        inventory = build_input_inventory(
            input_root,
            report,
            state=state,
            catalog=catalog,
        )
        git_sha = current_git_sha()
        run_id = deterministic_run_id(
            config_sha256=config.sha256,
            input_manifest_sha256=inventory.sha256,
            concept_catalog_sha256=catalog.sha256,
            code_fingerprint=git_sha,
        )
        state.update(run_id=run_id, phase="inventory_complete")

        existing = _existing_complete_run(output)
        if existing is not None and existing.get("run_id") == run_id:
            state.complete(message="Identical completed output already exists.")
            summary = summarize_database(output / config.output.database_name)
            return BuildResult(
                run_id=run_id,
                output_dir=output,
                output_paths=_published_output_paths(output),
                counts=CoreCohortCounts(
                    hypercapnia_encounters=int(summary["hypercapnia_encounters"]),
                    patient_index_events=int(summary["patient_index_events"]),
                    primary_obesity_hypercapnia=int(
                        summary["primary_obesity_hypercapnia"]
                    ),
                    evidence_rows=int(summary["evidence_rows"]),
                ),
                warning_count=int(summary["warning_count"]),
                reused_existing=True,
            )
        if output.exists() and not replace:
            raise FileExistsError(
                f"Output exists for a different build: {output}; use --replace."
            )

        workspace = prepare_workspace(
            output,
            run_id=run_id,
            config_sha256=config.sha256,
            input_manifest_sha256=inventory.sha256,
            concept_catalog_sha256=catalog.sha256,
            git_sha=git_sha,
        )
        state = workspace.state
        database_path = workspace.staging_dir / config.output.database_name
        connection = initialize_database(
            database_path,
            run_id=run_id,
            input_root=input_root,
            config=config,
            inventory=inventory,
            catalog=catalog,
            git_sha=git_sha,
            concept_catalog_sha256=catalog.sha256,
        )
        ingest_core_sources(
            connection,
            input_root=input_root,
            inventory=inventory,
            config=config,
            state=state,
        )
        warnings = build_concept_match_summary(
            connection, catalog.required_concept_set_ids
        )
        state.update(phase="core_cohort", current_domain=None)
        counts = build_core_cohort(
            connection,
            config=config,
            run_id=run_id,
            git_sha=git_sha,
        )
        build_raw_observability_summaries(
            connection,
            input_root=input_root,
            inventory=inventory,
            state=state,
        )
        state.update(phase="component_phenotypes", current_domain=None)
        build_eligibility_phenotypes(connection, config)
        build_cohort_flow(connection, config)
        counts = CoreCohortCounts(
            hypercapnia_encounters=counts.hypercapnia_encounters,
            patient_index_events=counts.patient_index_events,
            primary_obesity_hypercapnia=counts.primary_obesity_hypercapnia,
            evidence_rows=int(
                connection.execute(
                    "SELECT COUNT(*) FROM eligibility_evidence_long"
                ).fetchone()[0]
            ),
        )
        connection.execute(
            "UPDATE source_file_inventory SET load_status = 'loaded'"
        )
        mark_database_complete(connection)
        state.update(
            phase="output_materialization",
            rows_processed=counts.evidence_rows,
        )
        write_build_outputs(
            connection,
            workspace.staging_dir,
            write_parquet=config.output.write_parquet,
            write_html_qa=config.output.write_html_qa,
        )
        connection.execute("CHECKPOINT")
        connection.close()
        connection = None
        write_ahead_log = Path(f"{database_path}.wal")
        if write_ahead_log.exists():
            raise RuntimeError(
                "DuckDB write-ahead log remained after checkpoint: "
                f"{write_ahead_log.name}"
            )
        temp_dir = workspace.staging_dir / ".duckdb_tmp"
        if temp_dir.exists():
            remove_tree_strict(temp_dir, context="DuckDB temporary directory")
        publish_workspace(workspace, replace=replace)
        return BuildResult(
            run_id,
            output,
            _published_output_paths(output),
            counts,
            warning_count=len(warnings),
        )
    except Exception as exc:
        if connection is not None:
            connection.close()
        state.fail(message=f"{type(exc).__name__}: {exc}")
        raise


def _existing_complete_run(output_dir: Path) -> dict[str, object] | None:
    path = output_dir / "run_manifest.json"
    if not path.is_file():
        return None
    payload = json.loads(path.read_text())
    return payload if payload.get("status") == "complete" else None


def _published_output_paths(output_dir: Path) -> tuple[Path, ...]:
    """Return public build files consistently for fresh and reused runs."""

    return tuple(
        sorted(
            path
            for path in output_dir.iterdir()
            if path.is_file()
            and not path.name.startswith(".")
            and path.name != BUILD_STATE_FILENAME
        )
    )


def _require_safe_output_location(output_dir: Path) -> None:
    """Reject every output path inside a Git worktree."""

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
        "Refusing repository-local GLP-1 output: "
        f"{output}. Clinical outputs must use a path outside the Git worktree "
        f"{repository}; ignore rules are defense in depth only."
    )

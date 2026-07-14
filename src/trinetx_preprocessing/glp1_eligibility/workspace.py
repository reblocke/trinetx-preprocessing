"""Restartable staging and atomic publication for GLP-1 builds."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from ..filesystem import remove_tree_strict, write_text_atomic
from .monitoring import RunStateWriter, state_path_for_output

BUILD_STATE_FILENAME = "build_workspace.json"
BUILD_STATE_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class BuildWorkspace:
    """Paths and progress state for one deterministic staged build."""

    output_dir: Path
    staging_dir: Path
    run_id: str
    config_sha256: str
    input_manifest_sha256: str
    git_sha: str
    state: RunStateWriter

    @property
    def database_path(self) -> Path:
        """Return the staging database path after config selects its filename."""

        return self.staging_dir / "glp1_hypercapnia.duckdb"


def prepare_workspace(
    output_dir: Path,
    *,
    run_id: str,
    config_sha256: str,
    input_manifest_sha256: str,
    git_sha: str,
) -> BuildWorkspace:
    """Create or validate the deterministic staging directory for a build."""

    output = Path(output_dir).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = output.parent / f".{output.name}.build-{run_id}"
    manifest_path = staging / BUILD_STATE_FILENAME
    expected = {
        "schema_version": BUILD_STATE_SCHEMA_VERSION,
        "run_id": run_id,
        "config_sha256": config_sha256,
        "input_manifest_sha256": input_manifest_sha256,
        "git_sha": git_sha,
        "status": "building",
    }

    if staging.exists():
        if not manifest_path.is_file():
            raise ValueError(
                f"Incomplete GLP-1 staging directory has no manifest: {staging}"
            )
        observed = json.loads(manifest_path.read_text())
        identity_keys = (
            "schema_version",
            "run_id",
            "config_sha256",
            "input_manifest_sha256",
            "git_sha",
        )
        if any(observed.get(key) != expected[key] for key in identity_keys):
            raise ValueError(f"Stale GLP-1 staging directory: {staging}")
    else:
        staging.mkdir()
        write_text_atomic(manifest_path, json.dumps(expected, indent=2) + "\n")

    state = RunStateWriter(
        output,
        run_id,
        state_path=state_path_for_output(output),
    )
    state.update(phase="staging", message=f"Build workspace: {staging.name}")
    return BuildWorkspace(
        output_dir=output,
        staging_dir=staging,
        run_id=run_id,
        config_sha256=config_sha256,
        input_manifest_sha256=input_manifest_sha256,
        git_sha=git_sha,
        state=state,
    )


def publish_workspace(workspace: BuildWorkspace, *, replace: bool = False) -> None:
    """Atomically publish a complete staging directory."""

    manifest_path = workspace.staging_dir / BUILD_STATE_FILENAME
    payload = json.loads(manifest_path.read_text())
    payload["status"] = "complete"
    write_text_atomic(manifest_path, json.dumps(payload, indent=2) + "\n")

    backup: Path | None = None
    if workspace.output_dir.exists():
        if not replace:
            raise FileExistsError(
                f"GLP-1 output already exists: {workspace.output_dir}"
            )
        backup = workspace.output_dir.parent / (
            f".{workspace.output_dir.name}.previous-{workspace.run_id}"
        )
        if backup.exists():
            remove_tree_strict(backup, context="Stale GLP-1 output backup")
        os.replace(workspace.output_dir, backup)
    try:
        os.replace(workspace.staging_dir, workspace.output_dir)
    except Exception:
        if backup is not None and backup.exists() and not workspace.output_dir.exists():
            os.replace(backup, workspace.output_dir)
        raise
    if backup is not None:
        remove_tree_strict(backup, context="Previous GLP-1 output backup")
    workspace.state.complete(message="Atomic output publication completed.")


def discard_workspace(workspace: BuildWorkspace) -> None:
    """Strictly remove one known staging directory."""

    remove_tree_strict(workspace.staging_dir, context="GLP-1 staging directory")

"""Atomic progress state for long GLP-1 eligibility builds."""

from __future__ import annotations

import json
import os
import socket
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from pathlib import Path

from ..filesystem import write_text_atomic

RUN_STATE_FILENAME = ".glp1_build_state.json"
RUN_STATE_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class RunState:
    """Current aggregate progress for one build process."""

    schema_version: int
    run_id: str
    status: str
    phase: str
    started_at: str
    updated_at: str
    worker_pid: int
    worker_host: str
    current_domain: str | None = None
    completed_units: int = 0
    total_units: int | None = None
    rows_processed: int = 0
    bytes_processed: int = 0
    message: str | None = None

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable representation."""

        return asdict(self)


class RunStateWriter:
    """Durably maintain one build's aggregate state file."""

    def __init__(self, output_dir: Path, run_id: str) -> None:
        self.path = Path(output_dir) / RUN_STATE_FILENAME
        now = _utc_now()
        self.state = RunState(
            schema_version=RUN_STATE_SCHEMA_VERSION,
            run_id=run_id,
            status="running",
            phase="initializing",
            started_at=now,
            updated_at=now,
            worker_pid=os.getpid(),
            worker_host=socket.gethostname(),
        )
        self._write()

    def update(self, **changes: object) -> RunState:
        """Replace selected state fields and write the new state atomically."""

        self.state = replace(self.state, updated_at=_utc_now(), **changes)
        self._write()
        return self.state

    def complete(self, *, message: str | None = None) -> RunState:
        """Mark the build complete."""

        return self.update(status="completed", phase="complete", message=message)

    def fail(self, *, message: str) -> RunState:
        """Mark the build failed without storing row-level details."""

        return self.update(status="failed", message=message)

    def _write(self) -> None:
        write_text_atomic(self.path, json.dumps(self.state.to_dict(), indent=2) + "\n")


def read_run_state(output_dir: Path) -> RunState:
    """Read and validate the state file below ``output_dir``."""

    path = Path(output_dir) / RUN_STATE_FILENAME
    if not path.is_file():
        raise FileNotFoundError(f"GLP-1 run state not found: {path}")
    payload = json.loads(path.read_text())
    if payload.get("schema_version") != RUN_STATE_SCHEMA_VERSION:
        raise ValueError("Unsupported GLP-1 run-state schema version.")
    return RunState(**payload)


def process_appears_active(state: RunState) -> bool | None:
    """Best-effort local worker check; return None for a different host."""

    if state.worker_host != socket.gethostname():
        return None
    try:
        os.kill(state.worker_pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()

"""Input inventory and deterministic build identity for GLP-1 outputs."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path

from .discovery import ExportValidationReport
from .monitoring import RunStateWriter


@dataclass(frozen=True)
class SourceFileInventory:
    """PHI-safe metadata for one source file."""

    logical_domain: str
    source_file: str
    source_file_sha256: str
    file_size_bytes: int
    source_mtime_ns: int
    row_count: int
    column_names: tuple[str, ...]
    detected_schema_version: str
    min_event_date: str | None = None
    max_event_date: str | None = None
    load_status: str = "inventoried"
    warning: str | None = None

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable representation."""

        return asdict(self)


@dataclass(frozen=True)
class InputInventory:
    """Ordered source inventory and its deterministic digest."""

    files: tuple[SourceFileInventory, ...]
    sha256: str


def build_input_inventory(
    input_root: Path,
    report: ExportValidationReport,
    *,
    state: RunStateWriter | None = None,
    block_size: int = 8 * 1024 * 1024,
) -> InputInventory:
    """Hash and count every discovered file with bounded memory."""

    if not report.valid:
        raise ValueError("Cannot inventory an export that failed validation.")
    root = Path(input_root)
    inventory: list[SourceFileInventory] = []
    total_files = len(report.files)
    total_bytes = 0

    for index, file_validation in enumerate(report.files, start=1):
        path = root / file_validation.source_file
        file_hash, data_rows, bytes_read = _hash_and_count_rows(
            path, block_size=block_size
        )
        total_bytes += bytes_read
        inventory.append(
            SourceFileInventory(
                logical_domain=file_validation.logical_domain,
                source_file=file_validation.source_file,
                source_file_sha256=file_hash,
                file_size_bytes=file_validation.file_size_bytes,
                source_mtime_ns=path.stat().st_mtime_ns,
                row_count=data_rows,
                column_names=file_validation.columns,
                detected_schema_version="trinetx_csv_v1",
            )
        )
        if state is not None:
            state.update(
                phase="input_inventory",
                current_domain=file_validation.logical_domain,
                completed_units=index,
                total_units=total_files,
                bytes_processed=total_bytes,
                message=f"Inventoried {index} of {total_files} source files.",
            )

    ordered = tuple(
        sorted(inventory, key=lambda item: (item.logical_domain, item.source_file))
    )
    serialized = json.dumps(
        [item.to_dict() for item in ordered],
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return InputInventory(ordered, hashlib.sha256(serialized).hexdigest())


def deterministic_run_id(
    *, config_sha256: str, input_manifest_sha256: str, git_sha: str
) -> str:
    """Return a stable build identifier for one code/config/input combination."""

    payload = (
        f"glp1-schema-1|{config_sha256}|{input_manifest_sha256}|{git_sha}"
    ).encode()
    return hashlib.sha256(payload).hexdigest()[:24]


def current_git_sha() -> str:
    """Return a clean commit SHA or a content-sensitive dirty-tree fingerprint."""

    try:
        root_result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            check=True,
            capture_output=True,
            text=True,
        )
        root = Path(root_result.stdout.strip())
        sha_result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        )
        status_result = subprocess.run(
            ["git", "status", "--porcelain=v1", "-z", "--untracked-files=all"],
            cwd=root,
            check=True,
            capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    commit_sha = sha_result.stdout.strip()
    if not commit_sha:
        return "unknown"
    if not status_result.stdout:
        return commit_sha

    try:
        diff_result = subprocess.run(
            ["git", "diff", "--binary", "HEAD", "--"],
            cwd=root,
            check=True,
            capture_output=True,
        )
        untracked_result = subprocess.run(
            ["git", "ls-files", "--others", "--exclude-standard", "-z"],
            cwd=root,
            check=True,
            capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return f"{commit_sha}-dirty-unknown"

    hasher = hashlib.sha256()
    hasher.update(status_result.stdout)
    hasher.update(diff_result.stdout)
    for raw_path in sorted(untracked_result.stdout.split(b"\0")):
        if not raw_path:
            continue
        relative_path = os.fsdecode(raw_path)
        path = root / relative_path
        hasher.update(raw_path)
        if path.is_symlink():
            hasher.update(os.fsencode(os.readlink(path)))
            continue
        if not path.is_file():
            continue
        with path.open("rb") as handle:
            while block := handle.read(1024 * 1024):
                hasher.update(block)
    return f"{commit_sha}-dirty-{hasher.hexdigest()[:12]}"


def _hash_and_count_rows(path: Path, *, block_size: int) -> tuple[str, int, int]:
    hasher = hashlib.sha256()
    newline_count = 0
    byte_count = 0
    last_byte = b""
    with path.open("rb") as handle:
        while block := handle.read(block_size):
            hasher.update(block)
            newline_count += block.count(b"\n")
            byte_count += len(block)
            last_byte = block[-1:]

    physical_lines = newline_count + int(byte_count > 0 and last_byte != b"\n")
    data_rows = max(physical_lines - 1, 0)
    return hasher.hexdigest(), data_rows, byte_count

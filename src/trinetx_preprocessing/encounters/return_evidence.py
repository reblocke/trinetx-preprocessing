"""Dependency identities and authenticated, atomic return validation checkpoints."""

from __future__ import annotations

import hashlib
import hmac
import importlib.metadata
import json
import os
import platform
import uuid
from pathlib import Path

from ..combined_preprocessing.builder import require_safe_output_location
from ..filesystem import fsync_directory_strict, fsync_file_strict, write_text_atomic
from .builder import sha256
from .compatibility import no_symlinks
from .return_acceptance import canonical_digest

# Known independent roles are excluded only from other role identities. Any
# unclassified package code/resource is shared and conservatively invalidates
# every role. Documentation outside the installed package is not computational.
ROLE_FILES = {
    "release_verifier": {
        "encounters/return_release.py",
        "encounters/return_controller.py",
    },
    "producer": {"encounters/returns.py", "encounters/returns_v2.py"},
    "parent_validator": {"encounters/return_parent_validation.py"},
    "outcome_validator": {
        "encounters/return_validation_v2.py",
        "encounters/return_validation.py",
        "encounters/return_validation_execution.py",
    },
    "source_stage": {"encounters/return_source_stage.py"},
    "contract": {
        "encounters/return_acceptance.py",
        "encounters/return_artifact_contract.json",
    },
}


def component_identities() -> dict:
    package = Path(__file__).resolve().parents[1]
    files = {
        str(p.relative_to(package)): sha256(p)
        for p in sorted(package.rglob("*"))
        if p.is_file()
        and p.suffix in {".py", ".json", ".yaml", ".yml", ".csv"}
        and p.relative_to(package).parts[0] != "catalog"
    }
    classified = set().union(*ROLE_FILES.values())
    shared = {n: v for n, v in files.items() if n not in classified}
    identities = {
        role: canonical_digest(
            {"shared": shared, "role": {n: files[n] for n in names if n in files}}
        )
        for role, names in ROLE_FILES.items()
    }
    # Source validation uses the conservative shared closure (including unknown
    # future modules), with explicit environment/catalog identities added by callers.
    identities["source_validator"] = canonical_digest(shared)
    identities["environment"] = canonical_digest(
        {
            "python": platform.python_version(),
            "implementation": platform.python_implementation(),
            "platform": platform.machine(),
            "packages": {
                n: importlib.metadata.version(n)
                for n in ("duckdb", "pyarrow", "pandas", "numpy")
            },
        }
    )
    return identities


def _artifact_identities(paths):
    result = {}
    for name, raw in paths.items():
        path = no_symlinks(raw)
        if not path.is_file():
            raise ValueError("Checkpoint artifact is missing")
        result[name] = {"bytes": path.stat().st_size, "sha256": sha256(path)}
    return result


class PartitionCheckpoints:
    """Locally authenticated validation evidence, independent of producer state.

    The caller explicitly supplies an external key path. Losing that key prevents
    reuse; it never relaxes validation. Historical invalid records are retained.
    """

    def __init__(self, root: Path, *, key_path: Path):
        self.root, key_path = no_symlinks(root), no_symlinks(key_path)
        require_safe_output_location(self.root, artifact_label="return checkpoints")
        require_safe_output_location(
            key_path.parent, artifact_label="checkpoint authentication"
        )
        if key_path.is_relative_to(self.root):
            raise ValueError(
                "Checkpoint authentication key must be separate from records"
            )
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        key_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if not key_path.exists():
            if any(self.root.iterdir()):
                raise ValueError(
                    "Checkpoint authentication key is missing; cannot reuse evidence"
                )
            descriptor = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "wb") as f:
                f.write(os.urandom(32))
                f.flush()
                os.fsync(f.fileno())
            fsync_directory_strict(key_path.parent)
        if key_path.stat().st_mode & 0o077:
            raise ValueError(
                "Checkpoint authentication key permissions must be owner-only"
            )
        self._key = key_path.read_bytes()
        if len(self._key) != 32:
            raise ValueError("Invalid checkpoint authentication key")

    def _path(self, partition):
        return self.root / (hashlib.sha256(partition.encode()).hexdigest() + ".json")

    def _signature(self, payload):
        return hmac.new(
            self._key, canonical_digest(payload).encode(), hashlib.sha256
        ).hexdigest()

    def authenticated_record(self, partition: str, binding: dict) -> dict | None:
        path = no_symlinks(self._path(partition))
        if not path.is_file():
            return None
        try:
            record = json.loads(path.read_text())
            payload, signature = record["payload"], record["hmac_sha256"]
            if not isinstance(signature, str) or not hmac.compare_digest(
                signature, self._signature(payload)
            ):
                return None
            if (
                payload.get("checkpoint_contract_version") != "1.0"
                or payload.get("partition") != partition
                or payload.get("binding") != binding
                or payload.get("result", {}).get("pass") is not True
            ):
                return None
            return payload
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def reusable(self, partition: str, binding: dict, artifacts: dict) -> bool:
        payload = self.authenticated_record(partition, binding)
        if payload is None:
            return False
        try:
            return payload.get("artifacts") == _artifact_identities(artifacts)
        except (OSError, ValueError, KeyError, TypeError):
            return False

    def complete(self, partition: str, binding: dict, artifacts: dict, result: dict):
        if result.get("pass") is not True:
            raise ValueError("Failed partition cannot become a completed checkpoint")
        for path in artifacts.values():
            fsync_file_strict(no_symlinks(path))
        payload = {
            "checkpoint_contract_version": "1.0",
            "partition": partition,
            "binding": binding,
            "artifacts": _artifact_identities(artifacts),
            "result": result,
        }
        path = self._path(partition)
        if path.exists():
            path.replace(path.with_name(path.name + f".historical-{uuid.uuid4().hex}"))
        write_text_atomic(
            path,
            json.dumps(
                {"payload": payload, "hmac_sha256": self._signature(payload)},
                sort_keys=True,
                indent=2,
            )
            + "\n",
        )
        fsync_directory_strict(self.root)

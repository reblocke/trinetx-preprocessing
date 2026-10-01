"""Caller-trusted acceptance boundary for a canonical cohort-source database.

This verifier does not issue an acceptance receipt or run private population
gates. The caller must supply the SHA-256 of a separately reviewed receipt.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from ..config import DEFAULT_COMBINED_DUCKDB_MEMORY_LIMIT_MIB
from .cohort_source import (
    CohortSource,
    CohortSourceMetadata,
    open_cohort_source,
    validate_cohort_source,
)
from .database import COMBINED_MANIFEST_FILENAME

ACCEPTANCE_CONTRACT_VERSION = "1.0"
ACCEPTED_PURPOSE = "glp1_abstract_population"
REQUIRED_GATES = frozenset(
    {"source_provenance", "source_scope", "historical_index_coverage"}
)
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_METADATA_FIELDS = (
    "run_id",
    "completed_at",
    "combined_schema_version",
    "cohort_source_schema_version",
    "cohort_source_schema_sha256",
    "cohort_source_catalog_sha256",
    "glp1_catalog_sha256",
    "package_version",
    "git_code_state_sha256",
    "source_work_manifest_sha256",
)


def _regular_file(path: Path, label: str) -> Path:
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{label} must be a regular file")
    return path


def _sha256(value: object, label: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ValueError(f"Invalid {label} SHA-256")
    return value


def _file_identity(path: Path) -> tuple[int, int, int, int]:
    status = path.stat()
    return status.st_dev, status.st_ino, status.st_size, status.st_mtime_ns


def _digest_unchanged(path: Path) -> tuple[str, int]:
    before = _file_identity(path)
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    if _file_identity(path) != before:
        raise ValueError("Cohort-source artifact changed during identity verification")
    return digest.hexdigest(), before[2]


def _receipt(path: Path, expected_sha256: str) -> dict:
    path = _regular_file(path, "Acceptance receipt")
    payload_bytes = path.read_bytes()
    if hashlib.sha256(payload_bytes).hexdigest() != _sha256(
        expected_sha256, "trusted receipt"
    ):
        raise ValueError("Acceptance receipt identity differs from trusted expectation")
    payload = json.loads(payload_bytes)
    if not isinstance(payload, dict):
        raise ValueError("Acceptance receipt must be a JSON object")
    return payload


def verify_accepted_cohort_source(
    database_path: Path,
    *,
    receipt_path: Path,
    expected_receipt_sha256: str,
    memory_limit_mib: int = DEFAULT_COMBINED_DUCKDB_MEMORY_LIMIT_MIB,
    spill_root: Path | None = None,
) -> CohortSourceMetadata:
    """Verify trusted population acceptance and exact canonical source bytes.

    The receipt must bind a reviewed historical-index coverage gate; that gate
    remains distinct from timing, clinical phenotype, and abstract-report
    acceptance. This function validates metadata and schema, not patient rows.
    """
    receipt = _receipt(receipt_path, expected_receipt_sha256)
    if (
        receipt.get("acceptance_contract_version") != ACCEPTANCE_CONTRACT_VERSION
        or receipt.get("status") != "accepted"
        or receipt.get("kind") != "canonical_cohort_source"
        or receipt.get("purpose") != ACCEPTED_PURPOSE
    ):
        raise ValueError(
            "Receipt does not accept the GLP-1 canonical population interface"
        )
    gates = receipt.get("gates")
    if (
        not isinstance(gates, dict)
        or set(gates) != REQUIRED_GATES
        or any(
            not isinstance(gate, dict)
            or gate.get("pass") is not True
            or _SHA256.fullmatch(str(gate.get("evidence_sha256", ""))) is None
            for gate in gates.values()
        )
    ):
        raise ValueError(
            "Cohort-source receipt lacks passing required population gates"
        )
    elements = receipt.get("required_elements")
    if (
        not isinstance(elements, list)
        or not elements
        or any(not isinstance(value, str) or not value.strip() for value in elements)
        or len(set(elements)) != len(elements)
    ):
        raise ValueError("Cohort-source receipt lacks distinct required element IDs")
    expected_metadata = receipt.get("metadata")
    if not isinstance(expected_metadata, dict) or set(expected_metadata) != set(
        _METADATA_FIELDS
    ):
        raise ValueError("Cohort-source receipt has incomplete source metadata")
    catalog_digest = _sha256(
        expected_metadata["cohort_source_catalog_sha256"], "cohort-source catalog"
    )
    database = _regular_file(database_path, "Cohort-source database")
    sidecar = _regular_file(
        database.parent / COMBINED_MANIFEST_FILENAME, "Cohort-source sidecar"
    )
    database_identity = _file_identity(database)
    sidecar_identity = _file_identity(sidecar)
    database_digest, database_size = _digest_unchanged(database)
    sidecar_digest, _ = _digest_unchanged(sidecar)
    if (
        database_digest != _sha256(receipt.get("database_sha256"), "database")
        or database_size != receipt.get("database_size_bytes")
        or sidecar_digest != _sha256(receipt.get("sidecar_sha256"), "sidecar")
    ):
        raise ValueError("Cohort-source artifact differs from trusted receipt")
    result = validate_cohort_source(
        database,
        required_elements=elements,
        expected_catalog_sha256=catalog_digest,
        memory_limit_mib=memory_limit_mib,
        spill_root=spill_root,
    )
    if not result.valid or result.metadata is None:
        raise ValueError(
            "Trusted cohort source fails current metadata/schema validation"
        )
    actual_metadata = result.metadata.to_dict()
    if any(
        actual_metadata[field] != expected_metadata[field] for field in _METADATA_FIELDS
    ):
        raise ValueError("Cohort-source metadata differs from trusted receipt")
    if (
        _file_identity(database) != database_identity
        or _file_identity(sidecar) != sidecar_identity
    ):
        raise ValueError(
            "Cohort-source artifact changed during acceptance verification"
        )
    return result.metadata


@contextmanager
def open_accepted_cohort_source(
    database_path: Path,
    *,
    receipt_path: Path,
    expected_receipt_sha256: str,
    memory_limit_mib: int = DEFAULT_COMBINED_DUCKDB_MEMORY_LIMIT_MIB,
    spill_root: Path | None = None,
) -> Iterator[CohortSource]:
    """Open the exact accepted canonical source through its read-only API."""
    database = Path(database_path)
    sidecar = database.parent / COMBINED_MANIFEST_FILENAME
    database_identity = _file_identity(
        _regular_file(database, "Cohort-source database")
    )
    sidecar_identity = _file_identity(_regular_file(sidecar, "Cohort-source sidecar"))
    metadata = verify_accepted_cohort_source(
        database,
        receipt_path=receipt_path,
        expected_receipt_sha256=expected_receipt_sha256,
        memory_limit_mib=memory_limit_mib,
        spill_root=spill_root,
    )
    with open_cohort_source(
        database,
        expected_catalog_sha256=metadata.cohort_source_catalog_sha256,
        memory_limit_mib=memory_limit_mib,
        spill_root=spill_root,
    ) as source:
        if (
            source.metadata != metadata
            or _file_identity(database) != database_identity
            or _file_identity(sidecar) != sidecar_identity
        ):
            raise ValueError("Cohort-source metadata changed before the accepted read")
        yield source
        if (
            _file_identity(database) != database_identity
            or _file_identity(sidecar) != sidecar_identity
        ):
            raise ValueError("Cohort-source artifact changed during the accepted read")

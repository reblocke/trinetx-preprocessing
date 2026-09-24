"""Input inventory and deterministic build identity for GLP-1 outputs."""

from __future__ import annotations

import hashlib
import heapq
import importlib.metadata
import io
import json
import os
import re
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path

import pyarrow as pa
import pyarrow.csv as pacsv

from .concept_sets import ConceptSetCatalog
from .discovery import ExportValidationReport
from .monitoring import RunStateWriter

UNMAPPED_TRACKER_CAPACITY = 2_000
UNMAPPED_REPORT_LIMIT_PER_DOMAIN = 100
_CONCEPT_DOMAIN_BY_LOGICAL_DOMAIN = {
    "diagnosis": "diagnosis",
    "labs": "lab",
    "vitals": "vital",
    "procedure": "procedure",
    "medication": "medication",
    "medication_ingredient": "medication",
}


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

    def identity_dict(self) -> dict[str, object]:
        """Return content-derived fields used for deterministic input identity."""

        payload = self.to_dict()
        payload.pop("source_mtime_ns")
        return payload


@dataclass(frozen=True)
class InputInventory:
    """Ordered source inventory and its deterministic digest."""

    files: tuple[SourceFileInventory, ...]
    sha256: str
    unmapped_code_frequencies: tuple["UnmappedCodeFrequency", ...] = ()


@dataclass(frozen=True)
class UnmappedCodeFrequency:
    """Bounded aggregate frequency estimate for one unmapped source code."""

    logical_domain: str
    code_system: str
    code: str
    estimated_count: int
    max_error: int


def build_input_inventory(
    input_root: Path,
    report: ExportValidationReport,
    *,
    state: RunStateWriter | None = None,
    catalog: ConceptSetCatalog | None = None,
    block_size: int = 8 * 1024 * 1024,
) -> InputInventory:
    """Hash, count, and audit every discovered file with bounded memory."""

    if not report.valid:
        raise ValueError("Cannot inventory an export that failed validation.")
    root = Path(input_root)
    inventory: list[SourceFileInventory] = []
    total_files = len(report.files)
    total_bytes = 0
    matcher = _ConceptMatcher(catalog) if catalog is not None else None
    unmapped_counters: dict[str, _BoundedFrequencyCounter] = {}

    for index, file_validation in enumerate(report.files, start=1):
        path = root / file_validation.source_file
        audit_warning = None
        if file_validation.file_kind == "export_metadata":
            if path.suffix.lower() == ".csv":
                file_hash, data_rows, bytes_read = _hash_and_count_rows(
                    path, block_size=block_size
                )
            else:
                file_hash, bytes_read = _hash_file(path, block_size=block_size)
                data_rows = 0
        elif (
            matcher is not None
            and file_validation.logical_domain in _CONCEPT_DOMAIN_BY_LOGICAL_DOMAIN
            and {"code_system", "code"}.issubset(file_validation.columns)
        ):
            domain_counter = unmapped_counters.setdefault(
                file_validation.logical_domain,
                _BoundedFrequencyCounter(UNMAPPED_TRACKER_CAPACITY),
            )
            working_counter = domain_counter.copy()
            try:
                file_hash, data_rows, bytes_read = _hash_count_and_audit_codes(
                    path,
                    logical_domain=file_validation.logical_domain,
                    matcher=matcher,
                    counter=working_counter,
                    block_size=block_size,
                )
            except pa.ArrowInvalid as exc:
                file_hash, data_rows, bytes_read = _hash_and_count_rows(
                    path, block_size=block_size
                )
                audit_warning = (
                    f"Unmapped-code audit skipped because Arrow rejected the CSV: {exc}"
                )
            else:
                unmapped_counters[file_validation.logical_domain] = working_counter
        else:
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
                detected_schema_version=(
                    "export_metadata_v1"
                    if file_validation.file_kind == "export_metadata"
                    else "trinetx_csv_v1"
                ),
                warning=audit_warning,
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
        [item.identity_dict() for item in ordered],
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    unmapped = tuple(
        frequency
        for domain in sorted(unmapped_counters)
        for frequency in unmapped_counters[domain].frequencies(
            domain,
            limit=UNMAPPED_REPORT_LIMIT_PER_DOMAIN,
        )
    )
    return InputInventory(
        ordered,
        hashlib.sha256(serialized).hexdigest(),
        unmapped,
    )


def deterministic_run_id(
    *,
    config_sha256: str,
    input_manifest_sha256: str,
    concept_catalog_sha256: str,
    code_fingerprint: str,
) -> str:
    """Return a stable build identifier for one code/config/input combination."""

    payload = (
        "glp1-schema-2|"
        f"{config_sha256}|{input_manifest_sha256}|"
        f"{concept_catalog_sha256}|{code_fingerprint}"
    ).encode()
    return hashlib.sha256(payload).hexdigest()[:24]


def current_git_sha(package_root: Path | None = None) -> str:
    """Return code identity anchored to this package, never the caller's CWD."""

    root = _package_project_root(package_root)
    if package_root is None and root == Path(__file__).resolve().parents[1]:
        return _installed_package_fingerprint(root)
    try:
        root_result = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--show-toplevel"],
            check=True,
            capture_output=True,
            text=True,
        )
        git_root = Path(root_result.stdout.strip())
        sha_result = subprocess.run(
            ["git", "-C", str(git_root), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        )
        status_result = subprocess.run(
            [
                "git",
                "-C",
                str(git_root),
                "status",
                "--porcelain=v1",
                "-z",
                "--untracked-files=all",
            ],
            check=True,
            capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return _installed_package_fingerprint(root)
    commit_sha = sha_result.stdout.strip()
    if not commit_sha:
        return "unknown"
    if not status_result.stdout:
        return commit_sha

    try:
        diff_result = subprocess.run(
            ["git", "-C", str(git_root), "diff", "--binary", "HEAD", "--"],
            check=True,
            capture_output=True,
        )
        untracked_result = subprocess.run(
            [
                "git",
                "-C",
                str(git_root),
                "ls-files",
                "--others",
                "--exclude-standard",
                "-z",
            ],
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
        path = git_root / relative_path
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


def _package_project_root(package_root: Path | None) -> Path:
    if package_root is not None:
        return Path(package_root).resolve()
    package_dir = Path(__file__).resolve().parents[1]
    for candidate in package_dir.parents:
        source_package = candidate / "src" / "trinetx_preprocessing"
        if (
            (candidate / "pyproject.toml").is_file()
            and source_package.is_dir()
            and source_package.resolve() == package_dir
        ):
            return candidate
    return package_dir


def _installed_package_fingerprint(root: Path) -> str:
    hasher = hashlib.sha256()
    package_dir = (
        root / "src" / "trinetx_preprocessing"
        if (root / "src" / "trinetx_preprocessing").is_dir()
        else Path(__file__).resolve().parents[1]
    )
    try:
        version = importlib.metadata.version("trinetx-preprocessing")
    except importlib.metadata.PackageNotFoundError:
        version = "unknown"
    hasher.update(version.encode())
    for path in sorted(package_dir.rglob("*.py")):
        hasher.update(path.relative_to(package_dir).as_posix().encode())
        hasher.update(path.read_bytes())
    return f"package-{version}-{hasher.hexdigest()[:16]}"


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


def _hash_file(path: Path, *, block_size: int) -> tuple[str, int]:
    hasher = hashlib.sha256()
    byte_count = 0
    with path.open("rb") as handle:
        while block := handle.read(block_size):
            hasher.update(block)
            byte_count += len(block)
    return hasher.hexdigest(), byte_count


class _HashingReader(io.RawIOBase):
    """Binary reader that fingerprints the bytes consumed by Arrow CSV."""

    def __init__(self, path: Path) -> None:
        self._handle = path.open("rb")
        self.hasher = hashlib.sha256()
        self.bytes_read = 0
        super().__init__()

    def readable(self) -> bool:
        return True

    def readinto(self, buffer: bytearray | memoryview) -> int:
        data = self._handle.read(len(buffer))
        size = len(data)
        buffer[:size] = data
        self.hasher.update(data)
        self.bytes_read += size
        return size

    def close(self) -> None:
        self._handle.close()
        super().close()


class _ConceptMatcher:
    """Match normalized source codes to the versioned included concepts."""

    def __init__(self, catalog: ConceptSetCatalog) -> None:
        self._rules: dict[tuple[str, str], list[tuple[str, str | re.Pattern[str]]]] = {}
        for concept in catalog.concepts:
            if not concept.include:
                continue
            rule: str | re.Pattern[str]
            if concept.match_type == "regex":
                rule = re.compile(concept.code)
            else:
                rule = concept.code
            self._rules.setdefault((concept.domain, concept.code_system), []).append(
                (concept.match_type, rule)
            )

    def matches(self, logical_domain: str, code_system: str, code: str) -> bool:
        concept_domain = _CONCEPT_DOMAIN_BY_LOGICAL_DOMAIN[logical_domain]
        for match_type, rule in self._rules.get((concept_domain, code_system), ()):
            if match_type == "exact" and code == rule:
                return True
            if match_type == "prefix" and code.startswith(str(rule)):
                return True
            if match_type == "regex" and isinstance(rule, re.Pattern):
                if rule.search(code):
                    return True
        return False


class _BoundedFrequencyCounter:
    """Weighted Space-Saving counter with deterministic bounded storage."""

    def __init__(self, capacity: int) -> None:
        self.capacity = capacity
        self._counts: dict[tuple[str, str], tuple[int, int]] = {}
        self._heap: list[tuple[int, tuple[str, str]]] = []

    def update(
        self,
        key: tuple[str, str],
        weight: int,
        *,
        inherited_error: int = 0,
    ) -> None:
        current = self._counts.get(key)
        if current is not None:
            updated = (
                current[0] + weight,
                current[1] + inherited_error,
            )
            self._counts[key] = updated
            heapq.heappush(self._heap, (updated[0], key))
        elif len(self._counts) < self.capacity:
            self._counts[key] = (weight, inherited_error)
            heapq.heappush(self._heap, (weight, key))
        else:
            minimum, discarded = self._pop_current_minimum()
            del self._counts[discarded]
            self._counts[key] = (
                minimum + weight,
                minimum + inherited_error,
            )
            heapq.heappush(self._heap, (minimum + weight, key))
        if len(self._heap) > self.capacity * 4:
            self._heap = [
                (estimate, stored_key)
                for stored_key, (estimate, _) in self._counts.items()
            ]
            heapq.heapify(self._heap)

    def frequencies(
        self,
        logical_domain: str,
        *,
        limit: int,
    ) -> tuple[UnmappedCodeFrequency, ...]:
        ordered = sorted(
            self._counts.items(),
            key=lambda item: (-item[1][0], item[0]),
        )[:limit]
        return tuple(
            UnmappedCodeFrequency(
                logical_domain=logical_domain,
                code_system=key[0],
                code=key[1],
                estimated_count=estimate,
                max_error=error,
            )
            for key, (estimate, error) in ordered
        )

    def copy(self) -> "_BoundedFrequencyCounter":
        """Return an independent checkpoint for transactional file scanning."""

        clone = _BoundedFrequencyCounter(self.capacity)
        clone._counts = self._counts.copy()
        clone._heap = self._heap.copy()
        return clone

    def _pop_current_minimum(self) -> tuple[int, tuple[str, str]]:
        while self._heap:
            estimate, key = heapq.heappop(self._heap)
            if self._counts.get(key, (None,))[0] == estimate:
                return estimate, key
        raise RuntimeError("Bounded frequency heap is unexpectedly empty.")


def _hash_count_and_audit_codes(
    path: Path,
    *,
    logical_domain: str,
    matcher: _ConceptMatcher,
    counter: _BoundedFrequencyCounter,
    block_size: int,
) -> tuple[str, int, int]:
    reader = _HashingReader(path)
    rows = 0
    try:
        stream = pacsv.open_csv(
            reader,
            read_options=pacsv.ReadOptions(block_size=block_size),
            convert_options=pacsv.ConvertOptions(
                include_columns=["code_system", "code"],
                column_types={"code_system": pa.string(), "code": pa.string()},
                strings_can_be_null=False,
            ),
        )
        for batch in stream:
            rows += batch.num_rows
            grouped = (
                pa.Table.from_batches([batch])
                .group_by(["code_system", "code"])
                .aggregate([("code", "count")])
            )
            for code_system, code, count in zip(
                grouped["code_system"].to_pylist(),
                grouped["code"].to_pylist(),
                grouped["code_count"].to_pylist(),
                strict=True,
            ):
                normalized_system = _normalize_code_system(code_system)
                normalized_code = _normalize_code(code)
                if not matcher.matches(
                    logical_domain, normalized_system, normalized_code
                ):
                    counter.update(
                        (
                            normalized_system or "<missing>",
                            normalized_code or "<missing>",
                        ),
                        int(count),
                    )
    finally:
        reader.close()
    return reader.hasher.hexdigest(), rows, reader.bytes_read


def _normalize_code_system(value: object) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(value or "").strip().upper())


def _normalize_code(value: object) -> str:
    return str(value or "").strip().upper()

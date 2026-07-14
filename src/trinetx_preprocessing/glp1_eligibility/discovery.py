"""Automatic discovery and header validation for TriNetX exports."""

from __future__ import annotations

import csv
import re
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class DomainDefinition:
    """Filename and minimum-column contract for one source domain."""

    name: str
    filename_pattern: re.Pattern[str]
    required: bool
    required_columns: tuple[str, ...]


@dataclass(frozen=True)
class FileValidation:
    """Aggregate header validation for one source CSV."""

    logical_domain: str
    source_file: str
    file_size_bytes: int
    columns: tuple[str, ...]
    missing_columns: tuple[str, ...]


@dataclass(frozen=True)
class ExportValidationReport:
    """PHI-safe export discovery and header-validation report."""

    valid: bool
    input_exists: bool
    domain_file_counts: dict[str, int]
    files: tuple[FileValidation, ...]
    errors: tuple[str, ...]
    warnings: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable representation."""

        payload = asdict(self)
        payload["files"] = [asdict(file) for file in self.files]
        return payload


DOMAIN_DEFINITIONS = (
    DomainDefinition(
        "patient",
        re.compile(r"^patient(?:_?\d+)?\.csv$", re.IGNORECASE),
        True,
        ("patient_id", "sex", "race", "ethnicity", "year_of_birth"),
    ),
    DomainDefinition(
        "encounter",
        re.compile(r"^encounter(?:_?\d+)?\.csv$", re.IGNORECASE),
        True,
        ("encounter_id", "patient_id", "start_date", "end_date", "type"),
    ),
    DomainDefinition(
        "diagnosis",
        re.compile(r"^diagnosis(?:_?\d+)?\.csv$", re.IGNORECASE),
        True,
        ("patient_id", "encounter_id", "date", "code_system", "code"),
    ),
    DomainDefinition(
        "labs",
        re.compile(r"^lab_results?(?:_?\d+)?\.csv$", re.IGNORECASE),
        True,
        (
            "patient_id",
            "encounter_id",
            "date",
            "code_system",
            "code",
            "lab_result_num_val",
            "units_of_measure",
        ),
    ),
    DomainDefinition(
        "vitals",
        re.compile(r"^vital_signs?(?:_?\d+)?\.csv$", re.IGNORECASE),
        True,
        (
            "patient_id",
            "encounter_id",
            "date",
            "code_system",
            "code",
            "value",
            "units_of_measure",
        ),
    ),
    DomainDefinition(
        "procedure",
        re.compile(r"^procedure(?:_?\d+)?\.csv$", re.IGNORECASE),
        True,
        ("patient_id", "encounter_id", "date", "code_system", "code"),
    ),
    DomainDefinition(
        "medication_ingredient",
        re.compile(
            r"^medication_ingredients?(?:_?\d+)?\.csv$", re.IGNORECASE
        ),
        False,
        ("patient_id",),
    ),
    DomainDefinition(
        "medication",
        re.compile(r"^medications?(?:_?\d+)?\.csv$", re.IGNORECASE),
        True,
        ("patient_id", "encounter_id", "code_system", "code", "start_date"),
    ),
)
_CHUNK_SUFFIX = re.compile(r"^(?P<prefix>.*?)(?:_?)(?P<index>\d+)$")


def discover_export_files(input_root: Path) -> dict[str, tuple[Path, ...]]:
    """Discover supported split or unsplit CSVs by filename."""

    root = Path(input_root)
    discovered: dict[str, list[Path]] = {
        definition.name: [] for definition in DOMAIN_DEFINITIONS
    }
    if not root.is_dir():
        return {name: () for name in discovered}

    for path in root.rglob("*.csv"):
        if not path.is_file() or any(part.startswith(".") for part in path.parts):
            continue
        for definition in DOMAIN_DEFINITIONS:
            if definition.filename_pattern.fullmatch(path.name):
                discovered[definition.name].append(path)
                break

    return {
        name: tuple(_prefer_chunked_files(paths))
        for name, paths in discovered.items()
    }


def validate_export(input_root: Path) -> ExportValidationReport:
    """Validate domain presence and CSV headers without reading patient rows."""

    root = Path(input_root)
    if not root.is_dir():
        return ExportValidationReport(
            valid=False,
            input_exists=False,
            domain_file_counts={},
            files=(),
            errors=(f"Input export directory not found: {root}",),
            warnings=(),
        )

    discovered = discover_export_files(root)
    errors: list[str] = []
    warnings: list[str] = []
    validated_files: list[FileValidation] = []
    definitions = {definition.name: definition for definition in DOMAIN_DEFINITIONS}

    for name, definition in definitions.items():
        paths = discovered[name]
        if definition.required and not paths:
            errors.append(f"Required source domain has no files: {name}")
        for path in paths:
            try:
                columns = _read_header(path)
            except (OSError, UnicodeError, csv.Error) as exc:
                errors.append(
                    f"Unable to read CSV header for {path.relative_to(root)}: {exc}"
                )
                continue
            missing = tuple(
                column
                for column in definition.required_columns
                if column not in columns
            )
            relative = path.relative_to(root).as_posix()
            if missing:
                errors.append(
                    f"{relative} is missing required column(s): {', '.join(missing)}"
                )
            if len(columns) != len(set(columns)):
                warnings.append(f"{relative} contains duplicate column names.")
            validated_files.append(
                FileValidation(
                    logical_domain=name,
                    source_file=relative,
                    file_size_bytes=path.stat().st_size,
                    columns=columns,
                    missing_columns=missing,
                )
            )

    return ExportValidationReport(
        valid=not errors,
        input_exists=True,
        domain_file_counts={name: len(paths) for name, paths in discovered.items()},
        files=tuple(validated_files),
        errors=tuple(errors),
        warnings=tuple(warnings),
    )


def _read_header(path: Path) -> tuple[str, ...]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        row = next(csv.reader(handle), None)
    if not row:
        raise csv.Error("file has no header row")
    return tuple(column.strip() for column in row)


def _prefer_chunked_files(paths: list[Path]) -> list[Path]:
    ordered = sorted(paths, key=lambda path: path.as_posix().lower())
    chunked = [path for path in ordered if _chunk_index(path) is not None]
    if not chunked:
        return ordered
    return sorted(
        chunked,
        key=lambda path: (path.parent.as_posix(), _chunk_index(path)),
    )


def _chunk_index(path: Path) -> int | None:
    match = _CHUNK_SUFFIX.fullmatch(path.stem)
    return int(match.group("index")) if match else None

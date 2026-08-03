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
    file_kind: str = "clinical_csv"


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


class ExportDiscoveryError(ValueError):
    """Raised when source discovery cannot select one export family safely."""


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
        re.compile(r"^vitals?_signs?(?:_?\d+)?\.csv$", re.IGNORECASE),
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
        re.compile(r"^medication_ingredients?(?:_?\d+)?\.csv$", re.IGNORECASE),
        False,
        ("patient_id", "code_system", "code", "start_date"),
    ),
    DomainDefinition(
        "medication",
        re.compile(r"^medications?(?:_?\d+)?\.csv$", re.IGNORECASE),
        False,
        ("patient_id", "encounter_id", "code_system", "code", "start_date"),
    ),
)
_CHUNK_SUFFIX = re.compile(r"^(?P<prefix>.*?)(?:_?)(?P<index>\d+)$")
_EXPORT_METADATA_STEMS = {
    "manifest",
    "exportmanifest",
    "datadictionary",
    "datasetdetail",
    "datasetdetails",
    "cohortdetail",
    "cohortdetails",
    "standardizedterminology",
    "terminologymetadata",
}
_EXPORT_METADATA_SUFFIXES = {".csv", ".json", ".txt", ".pdf", ".xls", ".xlsx"}
_DOMAIN_FOLDER_NAMES = {
    "patient": frozenset({"patient", "patients"}),
    "encounter": frozenset({"encounter", "encounters"}),
    "diagnosis": frozenset({"diagnosis", "diagnoses"}),
    "labs": frozenset(
        {
            "lab",
            "labs",
            "labresult",
            "labresults",
            "laboratoryresult",
            "laboratoryresults",
        }
    ),
    "vitals": frozenset({"vital", "vitals", "vitalsign", "vitalsigns"}),
    "procedure": frozenset({"procedure", "procedures"}),
    "medication": frozenset(
        {
            "medication",
            "medications",
            "medicationingredient",
            "medicationingredients",
        }
    ),
}


def discover_export_files(input_root: Path) -> dict[str, tuple[Path, ...]]:
    """Discover supported split or unsplit CSVs by filename."""

    root = Path(input_root)
    discovered: dict[str, list[Path]] = {
        definition.name: [] for definition in DOMAIN_DEFINITIONS
    }
    discovered["export_metadata"] = []
    if not root.is_dir():
        return {name: () for name in discovered}

    for path in root.rglob("*"):
        relative_parts = path.relative_to(root).parts
        if not path.is_file() or any(part.startswith(".") for part in relative_parts):
            continue
        matched_clinical = False
        if path.suffix.lower() == ".csv":
            for definition in DOMAIN_DEFINITIONS:
                if definition.filename_pattern.fullmatch(path.name):
                    discovered[definition.name].append(path)
                    matched_clinical = True
                    break
        if not matched_clinical and _is_export_metadata(path):
            discovered["export_metadata"].append(path)

    selected: dict[str, tuple[Path, ...]] = {}
    for name, paths in discovered.items():
        selected[name] = tuple(
            sorted(paths, key=lambda path: path.as_posix().lower())
            if name == "export_metadata"
            else _select_source_family(paths, root, logical_domain=name)
        )
    if _medication_split_family_has_invalid_headers(selected):
        selected["medication"] = ()
    _require_single_selected_export_root(selected, root)
    return selected


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

    try:
        discovered = discover_export_files(root)
    except ExportDiscoveryError as exc:
        return ExportValidationReport(
            valid=False,
            input_exists=True,
            domain_file_counts={},
            files=(),
            errors=(str(exc),),
            warnings=(),
        )
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
                    file_kind="clinical_csv",
                )
            )

    if not discovered["medication"] and not discovered["medication_ingredient"]:
        errors.append(
            "Required medication source has no medication or "
            "medication-ingredient files."
        )

    for path in discovered["export_metadata"]:
        relative = path.relative_to(root).as_posix()
        columns: tuple[str, ...] = ()
        if path.suffix.lower() == ".csv":
            try:
                columns = _read_header(path)
            except (OSError, UnicodeError, csv.Error) as exc:
                warnings.append(
                    f"Unable to read metadata CSV header for {relative}: {exc}"
                )
        validated_files.append(
            FileValidation(
                logical_domain="export_metadata",
                source_file=relative,
                file_size_bytes=path.stat().st_size,
                columns=columns,
                missing_columns=(),
                file_kind="export_metadata",
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


def _is_export_metadata(path: Path) -> bool:
    if path.suffix.lower() not in _EXPORT_METADATA_SUFFIXES:
        return False
    normalized_stem = re.sub(r"[^a-z0-9]", "", path.stem.lower())
    normalized_stem = re.sub(r"\d+$", "", normalized_stem)
    return normalized_stem in _EXPORT_METADATA_STEMS


def _select_source_family(
    paths: list[Path], root: Path, *, logical_domain: str
) -> list[Path]:
    """Select one nearest source family, preferring its canonical unsplit file."""

    if not paths:
        return []
    minimum_depth = min(len(path.relative_to(root).parts) for path in paths)
    nearest = [
        path for path in paths if len(path.relative_to(root).parts) == minimum_depth
    ]
    nearest_parents = {path.parent for path in nearest}
    if len(nearest_parents) > 1:
        _raise_ambiguous_source_family(logical_domain, nearest, root)

    unsplit = [path for path in nearest if _chunk_index(path) is None]
    if unsplit:
        if len(unsplit) > 1:
            _raise_ambiguous_source_family(logical_domain, unsplit, root)
        return unsplit

    chunk_prefixes = {_chunk_family_prefix(path) for path in nearest}
    if len(chunk_prefixes) > 1:
        _raise_ambiguous_source_family(logical_domain, nearest, root)
    return sorted(
        nearest,
        key=lambda path: (path.parent.as_posix().lower(), _chunk_index(path)),
    )


def _raise_ambiguous_source_family(
    logical_domain: str, paths: list[Path], root: Path
) -> None:
    candidates = ", ".join(sorted(path.relative_to(root).as_posix() for path in paths))
    raise ExportDiscoveryError(
        f"Ambiguous nearest source family for {logical_domain}: {candidates}. "
        "Pass the root of exactly one TriNetX export."
    )


def _require_single_selected_export_root(
    discovered: dict[str, tuple[Path, ...]], root: Path
) -> None:
    """Require one flat export or sibling domain directories under one root."""

    domain_parents: dict[str, Path] = {}
    for logical_domain, paths in discovered.items():
        if logical_domain == "export_metadata" or not paths:
            continue
        parents = {path.parent for path in paths}
        if len(parents) != 1:
            _raise_mixed_export_roots(discovered, root)
        domain_parents[logical_domain] = next(iter(parents))

    unique_parents = set(domain_parents.values())
    # Every selected source is a direct child of one flat export root.
    if len(unique_parents) <= 1:
        return

    groups_by_parent: dict[Path, set[str]] = {}
    for logical_domain, parent in domain_parents.items():
        physical_group = _physical_domain_group(logical_domain)
        folder_name = re.sub(r"[^a-z0-9]", "", parent.name.casefold())
        if folder_name not in _DOMAIN_FOLDER_NAMES[physical_group]:
            _raise_mixed_export_roots(discovered, root)
        groups_by_parent.setdefault(parent, set()).add(physical_group)
    if any(len(groups) > 1 for groups in groups_by_parent.values()):
        _raise_mixed_export_roots(discovered, root)

    # Each physical domain occupies one directory under the export root.
    if len({parent.parent for parent in unique_parents}) == 1:
        return

    _raise_mixed_export_roots(discovered, root)


def _physical_domain_group(logical_domain: str) -> str:
    return (
        "medication"
        if logical_domain in {"medication", "medication_ingredient"}
        else logical_domain
    )


def _raise_mixed_export_roots(
    discovered: dict[str, tuple[Path, ...]], root: Path
) -> None:
    selected_paths = "; ".join(
        f"{logical_domain}={paths[0].relative_to(root).as_posix()}"
        for logical_domain, paths in discovered.items()
        if logical_domain != "export_metadata" and paths
    )
    raise ExportDiscoveryError(
        "Selected clinical source domains do not share one export root: "
        f"{selected_paths}. Pass the root of exactly one TriNetX export."
    )


def _medication_split_family_has_invalid_headers(
    discovered: dict[str, tuple[Path, ...]],
) -> bool:
    """Ignore unsupported legacy chunks beside a valid ingredient export."""

    medication = discovered["medication"]
    ingredient = discovered["medication_ingredient"]
    if not medication or not ingredient:
        return False
    if any(_chunk_index(path) is None for path in medication):
        return False
    required = frozenset(
        next(
            definition.required_columns
            for definition in DOMAIN_DEFINITIONS
            if definition.name == "medication"
        )
    )
    try:
        return any(not required.issubset(_read_header(path)) for path in medication)
    except (OSError, UnicodeError, csv.Error):
        return False


def _chunk_index(path: Path) -> int | None:
    match = _CHUNK_SUFFIX.fullmatch(path.stem)
    return int(match.group("index")) if match else None


def _chunk_family_prefix(path: Path) -> str:
    match = _CHUNK_SUFFIX.fullmatch(path.stem)
    if match is None:
        raise ValueError(f"Path is not a chunked source: {path.name}")
    return match.group("prefix").rstrip("_").casefold()

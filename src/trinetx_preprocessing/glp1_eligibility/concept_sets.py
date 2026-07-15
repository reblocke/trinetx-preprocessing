"""Versioned clinical concept-set loading and validation."""

from __future__ import annotations

import csv
import hashlib
import json
import re
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any

import yaml


class ConceptSetError(ValueError):
    """Raised when a concept-set file is invalid."""


CONCEPT_COLUMNS = (
    "concept_set_id",
    "domain",
    "code_system",
    "code",
    "match_type",
    "include",
    "description",
    "source_authority",
    "source_version",
    "effective_start",
    "effective_end",
    "notes",
)
CONCEPT_FILES = (
    "measurements.csv",
    "diagnoses.csv",
    "procedures.csv",
    "medications.csv",
)
ALLOWED_MATCH_TYPES = {"exact", "prefix", "regex"}
ALLOWED_DOMAINS = {"diagnosis", "lab", "vital", "procedure", "medication"}
REQUIRED_SAFETY_SETS = {
    "arterial_pco2",
    "arterial_ph",
    "arterial_total_co2",
    "bmi",
    "unspecified_blood_pco2",
    "venous_pco2",
}


@dataclass(frozen=True)
class Concept:
    """One normalized concept-set rule."""

    concept_set_id: str
    domain: str
    code_system: str
    code: str
    match_type: str
    include: bool
    description: str
    source_authority: str
    source_version: str
    effective_start: date | None
    effective_end: date | None
    notes: str
    source_file: str
    source_row: int


@dataclass(frozen=True)
class ConceptSetCatalog:
    """Validated terminology rows and phenotype-rule document."""

    concepts: tuple[Concept, ...]
    phenotype_rules: dict[str, Any]

    @property
    def concept_set_ids(self) -> frozenset[str]:
        """Return all configured concept-set identifiers."""

        return frozenset(concept.concept_set_id for concept in self.concepts)

    @property
    def required_concept_set_ids(self) -> tuple[str, ...]:
        """Return concept sets that must produce at least one aggregate match."""

        return tuple(self.phenotype_rules["required_concept_sets"])

    @property
    def sha256(self) -> str:
        """Return a canonical digest of all concepts and phenotype rules."""

        concepts = []
        for concept in self.concepts:
            row = asdict(concept)
            row["effective_start"] = (
                concept.effective_start.isoformat() if concept.effective_start else None
            )
            row["effective_end"] = (
                concept.effective_end.isoformat() if concept.effective_end else None
            )
            concepts.append(row)
        payload = json.dumps(
            {
                "concepts": concepts,
                "phenotype_rules": self.phenotype_rules,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return hashlib.sha256(payload).hexdigest()


def load_concept_sets(directory: Path) -> ConceptSetCatalog:
    """Load and validate all required concept-set files from ``directory``."""

    root = Path(directory)
    if not root.is_dir():
        raise FileNotFoundError(f"Concept-set directory not found: {root}")

    concepts: list[Concept] = []
    seen: set[tuple[str, str, str, str, bool]] = set()
    for filename in CONCEPT_FILES:
        path = root / filename
        if not path.is_file():
            raise FileNotFoundError(f"Required concept-set file not found: {path}")
        for concept in _load_concept_file(path):
            key = (
                concept.concept_set_id,
                concept.code_system,
                concept.code,
                concept.match_type,
                concept.include,
            )
            if key in seen:
                raise ConceptSetError(
                    f"Duplicate concept rule in {path.name}: {key!r}."
                )
            seen.add(key)
            concepts.append(concept)

    configured = {concept.concept_set_id for concept in concepts}
    missing_safety_sets = sorted(REQUIRED_SAFETY_SETS - configured)
    if missing_safety_sets:
        raise ConceptSetError(
            "Missing required safety concept set(s): "
            + ", ".join(missing_safety_sets)
        )

    phenotype_path = root / "phenotype_rules.yml"
    if not phenotype_path.is_file():
        raise FileNotFoundError(
            f"Required phenotype-rules file not found: {phenotype_path}"
        )
    phenotype_rules = yaml.safe_load(phenotype_path.read_text())
    if not isinstance(phenotype_rules, dict):
        raise ConceptSetError("phenotype_rules.yml must contain a YAML mapping.")
    if phenotype_rules.get("schema_version") != "1.0":
        raise ConceptSetError("phenotype_rules.yml schema_version must be '1.0'.")
    if not isinstance(phenotype_rules.get("phenotypes"), dict):
        raise ConceptSetError("phenotype_rules.yml must define phenotypes mapping.")
    required_concept_sets = phenotype_rules.get("required_concept_sets")
    if not isinstance(required_concept_sets, list) or not required_concept_sets:
        raise ConceptSetError(
            "phenotype_rules.yml must define non-empty required_concept_sets."
        )
    normalized_required = tuple(str(value).strip() for value in required_concept_sets)
    if any(not value for value in normalized_required):
        raise ConceptSetError("required_concept_sets may not contain blank values.")
    unknown_required = sorted(set(normalized_required) - configured)
    if unknown_required:
        raise ConceptSetError(
            "Unknown required concept set(s): " + ", ".join(unknown_required)
        )
    phenotype_rules["required_concept_sets"] = list(normalized_required)

    return ConceptSetCatalog(tuple(concepts), phenotype_rules)


def _load_concept_file(path: Path) -> list[Concept]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != CONCEPT_COLUMNS:
            raise ConceptSetError(
                f"{path.name} columns must exactly match: {', '.join(CONCEPT_COLUMNS)}."
            )
        return [
            _parse_concept(row, source_file=path.name, source_row=row_number)
            for row_number, row in enumerate(reader, start=2)
        ]


def _parse_concept(
    row: dict[str, str], *, source_file: str, source_row: int
) -> Concept:
    required = (
        "concept_set_id",
        "domain",
        "code_system",
        "code",
        "match_type",
        "include",
        "description",
        "source_authority",
        "source_version",
    )
    missing = [key for key in required if not row[key].strip()]
    if missing:
        raise ConceptSetError(
            f"{source_file}:{source_row} has blank required field(s): "
            + ", ".join(missing)
        )

    domain = row["domain"].strip().lower()
    if domain not in ALLOWED_DOMAINS:
        raise ConceptSetError(
            f"{source_file}:{source_row} has unsupported domain {domain!r}."
        )
    match_type = row["match_type"].strip().lower()
    if match_type not in ALLOWED_MATCH_TYPES:
        raise ConceptSetError(
            f"{source_file}:{source_row} has unsupported match_type {match_type!r}."
        )
    if match_type == "regex":
        try:
            re.compile(row["code"])
        except re.error as exc:
            raise ConceptSetError(
                f"{source_file}:{source_row} has invalid regular expression."
            ) from exc

    include_text = row["include"].strip().lower()
    if include_text not in {"true", "false"}:
        raise ConceptSetError(
            f"{source_file}:{source_row} include must be true or false."
        )
    effective_start = _optional_date(
        row["effective_start"], source_file, source_row, "effective_start"
    )
    effective_end = _optional_date(
        row["effective_end"], source_file, source_row, "effective_end"
    )
    if effective_start and effective_end and effective_start > effective_end:
        raise ConceptSetError(
            f"{source_file}:{source_row} effective_start is after effective_end."
        )

    return Concept(
        concept_set_id=row["concept_set_id"].strip(),
        domain=domain,
        code_system=re.sub(r"[^A-Z0-9]", "", row["code_system"].strip().upper()),
        code=row["code"].strip().upper(),
        match_type=match_type,
        include=include_text == "true",
        description=row["description"].strip(),
        source_authority=row["source_authority"].strip(),
        source_version=row["source_version"].strip(),
        effective_start=effective_start,
        effective_end=effective_end,
        notes=row["notes"].strip(),
        source_file=source_file,
        source_row=source_row,
    )


def _optional_date(
    value: str, source_file: str, source_row: int, column: str
) -> date | None:
    text = value.strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise ConceptSetError(
            f"{source_file}:{source_row} {column} must be an ISO date."
        ) from exc

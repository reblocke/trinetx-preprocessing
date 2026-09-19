"""Packaged, immutable compatibility input schema (no execution attestation)."""

import json
from dataclasses import dataclass
from importlib.resources import files

EXPECTED_COLUMN_COUNT = 534


@dataclass(frozen=True)
class RawColumn:
    position: int
    raw_name: str
    stata_name: str
    source_status: str
    expected_import_class: str
    fixture_encoding: str


@dataclass(frozen=True)
class RawSchema:
    manifest_sha256: str
    raw_header_sha256: str
    columns: tuple[RawColumn, ...]
    source_tolerated_absent: tuple[str, ...]


def load_schema() -> RawSchema:
    data = json.loads(files(__package__).joinpath("raw_schema.json").read_text())
    columns = tuple(
        RawColumn(**{key: c[key] for key in RawColumn.__dataclass_fields__})
        for c in data["columns"]
    )
    return RawSchema(
        data["manifest"]["sha256"],
        data["header_verification"]["raw_header_sha256"],
        columns,
        tuple(data["source_optional_absent"]),
    )

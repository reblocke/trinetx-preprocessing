"""Path-free, header-only triage for a proposed GLP-1 source extract.

This does not inspect values, establish timestamp precision, or accept a source.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class DomainHeaderCapture:
    domain: str
    source_files: int
    files_with_date: int
    files_with_start_date: int
    files_with_end_date: int
    files_with_datetime_named_field: int
    files_with_order_status: int
    files_with_status: int


def screen_export_headers(
    *,
    encounter_files: list[Path],
    lab_files: list[Path],
    medication_files: list[Path],
) -> tuple[DomainHeaderCapture, ...]:
    """Count fixed header features without reading clinical rows or returning names.

    Files are supplied explicitly because a proposed alternative extract may not
    follow the current 36-file naming convention. A time-named field is only a
    discovery hint; even ``start_date`` can contain a time in a new layout.
    """
    groups = (
        ("encounter", encounter_files),
        ("labs", lab_files),
        ("medication", medication_files),
    )
    result = []
    for domain, paths in groups:
        if not paths:
            raise ValueError(f"At least one {domain} file is required")
        headers = []
        for path in paths:
            try:
                with path.open(newline="", encoding="utf-8-sig") as handle:
                    row = next(csv.reader(handle), None)
            except (OSError, UnicodeError, csv.Error) as exc:
                raise ValueError(f"Cannot read {domain} CSV header") from exc
            if not row or not any(column.strip() for column in row):
                raise ValueError(f"{domain} CSV has an empty header")
            columns = [column.strip().lower() for column in row]
            if len(columns) != len(set(columns)):
                raise ValueError(f"{domain} CSV has duplicate header names")
            headers.append(frozenset(columns))
        result.append(
            DomainHeaderCapture(
                domain=domain,
                source_files=len(headers),
                files_with_date=sum("date" in names for names in headers),
                files_with_start_date=sum("start_date" in names for names in headers),
                files_with_end_date=sum("end_date" in names for names in headers),
                files_with_datetime_named_field=sum(
                    any("time" in name for name in names) for names in headers
                ),
                files_with_order_status=sum(
                    "order_status" in names for names in headers
                ),
                files_with_status=sum("status" in names for names in headers),
            )
        )
    return tuple(result)

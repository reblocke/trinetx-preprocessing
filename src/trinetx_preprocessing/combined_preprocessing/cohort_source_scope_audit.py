"""Aggregate observability inventory for a candidate canonical cohort source.

Observed events and spans describe source capture, not continuous clinical
history or the absence of disease when no record appears.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import duckdb

from .elements import CONCEPT_DOMAIN_BY_PIPELINE_DOMAIN

_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z_0-9]*\Z")
_DOMAINS = tuple(CONCEPT_DOMAIN_BY_PIPELINE_DOMAIN)


@dataclass(frozen=True)
class DomainObservability:
    domain: str
    patients_with_records: int
    patients_without_records: int
    observed_event_rows: int
    first_observed_event: str | None
    last_observed_event: str | None
    source_files: int


@dataclass(frozen=True)
class CandidateSourceScopeAudit:
    historical_patients: int
    source_patient_present: int
    source_patient_missing: int
    invalid_observability_rows: int
    domains: tuple[DomainObservability, ...]


def audit_candidate_source_scope(
    connection: duckdb.DuckDBPyConnection,
    *,
    historical_patient_relation: str,
) -> CandidateSourceScopeAudit:
    """Summarize source capture for an authenticated historical patient set.

    The caller opens a validated read-only cohort source and registers a
    relation containing original string `patient_id` values. This does not
    inspect or return individual records, prove full history, or accept source
    scope for the abstract.
    """
    if _IDENTIFIER.fullmatch(historical_patient_relation) is None:
        raise ValueError("Historical patient relation needs a safe identifier")
    relation = f'"{historical_patient_relation}"'
    types = {
        row[0]: row[1] for row in connection.execute(f"DESCRIBE {relation}").fetchall()
    }
    if types.get("patient_id") != "VARCHAR":
        raise ValueError("Historical patient IDs must retain original strings")
    total, distinct, invalid = connection.execute(
        f"SELECT count(*), count(DISTINCT patient_id), "
        f"count(*) FILTER(WHERE patient_id IS NULL OR trim(patient_id)='') "
        f"FROM {relation}"
    ).fetchone()
    if invalid or total != distinct:
        raise ValueError(
            "Historical patient relation needs one nonblank row per patient"
        )
    source_present = connection.execute(
        f"SELECT count(DISTINCT s.patient_id) FROM source_patient AS s "
        f"SEMI JOIN {relation} AS h ON s.patient_id=h.patient_id"
    ).fetchone()[0]
    if source_present > total:
        raise AssertionError("Source patient coverage exceeds historical patients")
    allowed = ",".join("'" + domain + "'" for domain in _DOMAINS)
    invalid_observability = connection.execute(
        "SELECT count(*) FROM patient_observability "
        "WHERE patient_id IS NULL OR logical_domain IS NULL "
        f"OR logical_domain NOT IN ({allowed}) OR event_count IS NULL"
    ).fetchone()[0]
    files = dict(
        connection.execute(
            "SELECT domain, count(*) FROM source_file_inventory GROUP BY domain"
        ).fetchall()
    )
    observed = {
        row[0]: row[1:]
        for row in connection.execute(
            f"""
            SELECT o.logical_domain, count(DISTINCT o.patient_id),
                   coalesce(sum(o.event_count), 0),
                   min(o.first_event_datetime), max(o.last_event_datetime)
            FROM patient_observability AS o
            SEMI JOIN {relation} AS h ON o.patient_id=h.patient_id
            WHERE o.logical_domain IN ({allowed})
            GROUP BY o.logical_domain
            """
        ).fetchall()
    }
    domains = []
    for domain in _DOMAINS:
        covered, events, earliest, latest = observed.get(domain, (0, 0, None, None))
        if covered > total:
            raise AssertionError("Domain observability exceeds historical patients")
        inventory_domain = "meds" if domain == "medications" else domain
        domains.append(
            DomainObservability(
                domain=domain,
                patients_with_records=int(covered),
                patients_without_records=int(total - covered),
                observed_event_rows=int(events),
                first_observed_event=earliest.isoformat() if earliest else None,
                last_observed_event=latest.isoformat() if latest else None,
                source_files=int(files.get(inventory_domain, 0)),
            )
        )
    return CandidateSourceScopeAudit(
        historical_patients=int(total),
        source_patient_present=int(source_present),
        source_patient_missing=int(total - source_present),
        invalid_observability_rows=int(invalid_observability),
        domains=tuple(domains),
    )

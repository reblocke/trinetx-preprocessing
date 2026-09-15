"""Reusable source-file audit evidence for the canonical preprocessing product.

The canonical product owns this audit.  Downstream studies may copy its
metadata into study receipts, but they must not rescan protected exports merely
to recreate it.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..glp1_eligibility.concept_sets import ConceptSetCatalog
from ..glp1_eligibility.discovery import validate_export
from ..glp1_eligibility.provenance import InputInventory, build_input_inventory

AUDIT_PROFILE = "source_inventory_v1"


@dataclass(frozen=True)
class CanonicalSourceAudit:
    """Complete reusable audit evidence for one canonical source build."""

    inventory: InputInventory
    catalog_sha256: str
    profile: str = AUDIT_PROFILE


def build_canonical_source_audit(
    input_root: Path,
    *,
    catalog: ConceptSetCatalog,
) -> CanonicalSourceAudit:
    """Inventory the validated export once for canonical publication.

    This intentionally uses the established bounded audit implementation so
    file hashes, row counts, and approximate unmapped-code counts retain the
    same deterministic semantics as the reference GLP-1 workflow.
    """

    report = validate_export(input_root)
    if not report.valid:
        raise ValueError(
            "Canonical source audit requires a valid TriNetX export: "
            + "; ".join(report.errors)
        )
    return CanonicalSourceAudit(
        inventory=build_input_inventory(input_root, report, catalog=catalog),
        catalog_sha256=catalog.sha256,
    )

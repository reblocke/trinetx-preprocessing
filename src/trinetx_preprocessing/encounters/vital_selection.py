"""An optional exact-code fast path, gated by full-source selection equivalence."""

import hashlib
import json

from ..combined_preprocessing.traditional_catalog import ANY_CODE_SYSTEM
from .compatibility import file_identity, no_symlinks


def exact_vital_predicate(catalog):
    from .source_projection import _sql_string

    rules = [x for x in catalog.concepts if x.domain == "vital" and x.include]
    if not rules or any(
        x.match_type != "exact" or x.code_system == ANY_CODE_SYSTEM for x in rules
    ):
        raise ValueError("Vital fast path requires explicit exact-code catalog rules")
    return " OR ".join(
        f"(source.code_system={_sql_string(x.code_system)} "
        f"AND source.code={_sql_string(x.code)})"
        for x in rules
    )


def equivalence_query(catalog):
    """Compare truth per original source row, retaining duplicate multiplicity."""
    from .source_projection import _glp1_source_membership_sql

    old = _glp1_source_membership_sql(
        catalog, source_alias="source", logical_domain="vitals", concept_domain="vital"
    )
    new = exact_vital_predicate(catalog)
    return f"""SELECT count(*) AS source_rows,
 count(*) FILTER (WHERE prior) AS prior_selected,
 count(*) FILTER (WHERE proposed) AS proposed_selected,
 count(*) FILTER (WHERE prior IS DISTINCT FROM proposed) AS selection_differences
 FROM (SELECT coalesce(({old}),false) AS prior,
 coalesce(({new}),false) AS proposed
 FROM preprocessed.source_vital_measurement AS source)"""


def validate_acceptance(path, database, catalog):
    """Default remains membership-backed unless this exact source passed."""
    if path is None:
        return None
    receipt = json.loads(no_symlinks(path).read_text())
    expected_query = hashlib.sha256(equivalence_query(catalog).encode()).hexdigest()
    counts = [
        receipt.get(name)
        for name in ("source_rows", "prior_selected", "proposed_selected")
    ]
    if (
        not all(type(value) is int for value in counts)
        or not (0 <= counts[1] <= counts[0] and 0 <= counts[2] <= counts[0])
        or receipt.get("state") != "complete"
        or receipt.get("passed") is not True
        or receipt.get("source_rows", 0) <= 0
        or receipt.get("selection_differences") != 0
        or receipt.get("prior_selected") != receipt.get("proposed_selected")
        or receipt.get("source_file_identity") != list(file_identity(database))
        or receipt.get("catalog_sha256") != catalog.sha256
        or receipt.get("query_sha256") != expected_query
    ):
        raise ValueError("Exact vital selection acceptance does not match this source")
    return exact_vital_predicate(catalog)

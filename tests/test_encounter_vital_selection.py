import hashlib
import json
from dataclasses import replace

import duckdb
import pytest

from trinetx_preprocessing.clinical_sources.concept_sets import (
    default_catalog_directory,
    load_concept_sets,
)
from trinetx_preprocessing.encounters.compatibility import file_identity
from trinetx_preprocessing.encounters.vital_selection import (
    equivalence_query,
    exact_vital_predicate,
    validate_acceptance,
)


def test_selection_proof_counts_duplicates_nulls_and_inconsistent_membership():
    catalog = load_concept_sets(default_catalog_directory())
    with duckdb.connect() as db:
        db.execute("ATTACH ':memory:' AS preprocessed")
        db.execute("""
            CREATE TABLE preprocessed.source_vital_measurement AS
            SELECT * FROM (VALUES
                ('a','LOINC','39156-5'), ('a','LOINC','39156-5'),
                ('b','LOINC','8302-2'), ('c','OTHER','39156-5'),
                ('d','LOINC',NULL), ('e',NULL,'39156-5'),
                ('f','LOINC','not-a-selected-code')
            ) t(source_record_id,code_system,code)
        """)
        db.execute("""
            CREATE TABLE preprocessed.element_membership AS
            SELECT * FROM (VALUES ('a','source.bmi','vitals',true),
                                 ('b','source.height','vitals',true))
            t(source_record_id,element_id,logical_domain,include)
        """)
        assert db.execute(equivalence_query(catalog)).fetchone() == (7, 3, 3, 0)
        db.execute("""
            INSERT INTO preprocessed.element_membership
            VALUES ('f','source.bmi','vitals',true)
        """)
        assert db.execute(equivalence_query(catalog)).fetchone() == (7, 4, 3, 1)


@pytest.mark.parametrize(
    "changed", ["source", "catalog", "query", "difference", "missing_counts"]
)
def test_fast_path_requires_exact_current_source_acceptance(tmp_path, changed):
    catalog = load_concept_sets(default_catalog_directory())
    database = tmp_path / "synthetic-source"
    database.write_bytes(b"synthetic source identity")
    path = tmp_path / "acceptance.json"
    receipt = {
        "state": "complete",
        "passed": True,
        "source_rows": 7,
        "prior_selected": 3,
        "proposed_selected": 3,
        "selection_differences": 0,
        "source_file_identity": list(file_identity(database)),
        "catalog_sha256": catalog.sha256,
        "query_sha256": hashlib.sha256(equivalence_query(catalog).encode()).hexdigest(),
    }
    path.write_text(json.dumps(receipt))
    assert validate_acceptance(None, database, catalog) is None
    assert validate_acceptance(path, database, catalog) == exact_vital_predicate(
        catalog
    )
    if changed == "source":
        database.write_bytes(b"changed source")
    elif changed == "catalog":
        receipt["catalog_sha256"] = "wrong"
    elif changed == "query":
        receipt["query_sha256"] = "wrong"
    elif changed == "missing_counts":
        del receipt["prior_selected"]
        del receipt["proposed_selected"]
    else:
        receipt["selection_differences"] = 1
    path.write_text(json.dumps(receipt))
    with pytest.raises(ValueError, match="does not match"):
        validate_acceptance(path, database, catalog)


def test_nonexact_catalog_cannot_use_exact_fast_path():
    catalog = load_concept_sets(default_catalog_directory())
    altered = tuple(
        replace(x, match_type="prefix") if x.domain == "vital" else x
        for x in catalog.concepts
    )
    with pytest.raises(ValueError, match="exact-code"):
        exact_vital_predicate(replace(catalog, concepts=altered))

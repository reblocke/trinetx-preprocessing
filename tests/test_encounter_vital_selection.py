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


def test_cli_forwards_optional_receipt_and_cache(tmp_path, monkeypatch):
    from trinetx_preprocessing.encounters import cli

    observed = {}
    monkeypatch.setattr(
        cli, "build_encounters", lambda **kwargs: observed.update(kwargs)
    )
    arguments = []
    for name in (
        "database",
        "compatibility-database",
        "legacy-bundle",
        "legacy-acceptance",
        "coverage-bundle",
        "output-dir",
        "source-cache-dir",
        "vital-selection-acceptance",
    ):
        arguments.extend(["--" + name, str(tmp_path / name)])
    assert cli.main(arguments) == 0
    assert (
        observed["vital_selection_acceptance"]
        == tmp_path / "vital-selection-acceptance"
    )
    assert observed["source_cache_dir"] == tmp_path / "source-cache-dir"


@pytest.mark.parametrize("mode", ["--legacy-only", "--coverage-only"])
def test_cli_rejects_vital_optimization_outside_enrichment(tmp_path, mode):
    from trinetx_preprocessing.encounters.cli import main

    with pytest.raises(SystemExit) as error:
        main(
            [
                "--compatibility-database",
                str(tmp_path / "companion"),
                "--output-dir",
                str(tmp_path / "output"),
                "--vital-selection-acceptance",
                str(tmp_path / "receipt"),
                mode,
            ]
        )
    assert error.value.code == 2


def test_vital_projection_preserves_scope_duplicates_and_raw_fields():
    from trinetx_preprocessing.encounters.source_projection import (
        _create_patient_concept_source,
    )

    catalog = load_concept_sets(default_catalog_directory())
    with duckdb.connect() as db:
        db.execute("ATTACH ':memory:' AS preprocessed")
        db.execute("CREATE TABLE gas_candidate_patient AS SELECT 'p' AS patient_id")
        db.execute("""
            CREATE TABLE preprocessed.source_vital_measurement AS
            SELECT source_record_id, patient_id, 'e' AS encounter_id,
                   DATE '2020-01-02' AS date, 'loinc ' AS code_system_raw,
                   'LOINC' AS code_system, code || ' ' AS code_raw, code,
                   24.5 AS value, NULL::VARCHAR AS text_value,
                   'kg/m2' AS units_of_measure_raw,
                   false AS derived_by_TriNetX, 'site' AS source_id,
                   TIMESTAMP '2020-01-02 12:34:56' AS event_datetime,
                   'synthetic.csv' AS source_file
            FROM (VALUES ('a','p','39156-5'), ('a','p','39156-5'),
                         ('b','p','8302-2'), ('c','outside','8302-2'),
                         ('d','p',NULL), ('e','p','other'))
                 t(source_record_id,patient_id,code)
        """)
        db.execute("""
            CREATE TABLE preprocessed.element_membership AS
            SELECT * FROM (VALUES ('a','source.bmi','vitals',true),
                                 ('b','source.height','vitals',true),
                                 ('c','source.height','vitals',true))
            t(source_record_id,element_id,logical_domain,include)
        """)
        _create_patient_concept_source(db, "source_vital_measurement", catalog=catalog)
        prior = db.sql("SELECT * FROM source_vital_measurement ORDER BY ALL").fetchall()
        _create_patient_concept_source(
            db,
            "source_vital_measurement",
            catalog=catalog,
            vital_predicate=exact_vital_predicate(catalog),
        )
        current = db.sql(
            "SELECT * FROM source_vital_measurement ORDER BY ALL"
        ).fetchall()
        assert current == prior
        assert len(current) == 3
        assert all(row[0] == "p" and row[3] == "loinc " for row in current)
        assert current[0] == current[1]  # Original duplicate multiplicity survives.
        with pytest.raises(ValueError, match="another domain"):
            _create_patient_concept_source(
                db,
                "source_diagnosis",
                catalog=catalog,
                vital_predicate=exact_vital_predicate(catalog),
            )

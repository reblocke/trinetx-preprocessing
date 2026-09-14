"""Bounded membership plans must retain exact source-row semantics."""

from pathlib import Path

import duckdb
import pytest

from trinetx_preprocessing.combined_preprocessing.glp1_adapter import (
    _glp1_source_membership_sql,
)
from trinetx_preprocessing.glp1_eligibility.concept_sets import load_concept_sets
from trinetx_preprocessing.glp1_eligibility.config import load_glp1_config


@pytest.mark.parametrize(
    "logical,concept_domain",
    [
        ("labs", "lab"),
        ("vitals", "vital"),
        ("diagnosis", "diagnosis"),
        ("procedure", "procedure"),
        ("medications", "medication"),
    ],
)
def test_membership_is_spillable_semijoin_with_exact_multiset(logical, concept_domain):
    config = load_glp1_config(
        Path(__file__).resolve().parents[1] / "config/glp1_eligibility.yml"
    )
    catalog = load_concept_sets(config.concept_sets_dir)
    element = next(
        "source." + c.concept_set_id
        for c in catalog.concepts
        if c.include and c.domain == concept_domain
    )
    with duckdb.connect() as con:
        con.execute("ATTACH ':memory:' AS preprocessed")
        con.execute("CREATE TABLE source (source_record_id VARCHAR, value INTEGER)")
        con.execute(
            "INSERT INTO source VALUES ('match',1),('match',1),('match',NULL),"
            "('excluded',2),('wrong_domain',3),('other_catalog',4),('absent',5),(NULL,6)"
        )
        con.execute(
            "CREATE TABLE preprocessed.element_membership "
            "(source_record_id VARCHAR, logical_domain VARCHAR, "
            "element_id VARCHAR, include BOOLEAN)"
        )
        con.executemany(
            "INSERT INTO preprocessed.element_membership VALUES (?,?,?,?)",
            [
                ("match", logical, element, True),
                ("match", logical, element, True),
                ("excluded", logical, element, False),
                ("excluded", logical, element, None),
                ("wrong_domain", "wrong", element, True),
                ("other_catalog", logical, "source.other", True),
                (None, logical, element, True),
            ],
        )
        predicate = _glp1_source_membership_sql(
            catalog,
            source_alias="s",
            logical_domain=logical,
            concept_domain=concept_domain,
        )
        actual = "SELECT s.* FROM source s WHERE " + predicate
        expected = "SELECT * FROM source WHERE source_record_id='match'"
        assert (
            con.execute(
                f"SELECT count(*) FROM (({actual}) EXCEPT ALL ({expected}))"
            ).fetchone()[0]
            == 0
        )
        assert (
            con.execute(
                f"SELECT count(*) FROM (({expected}) EXCEPT ALL ({actual}))"
            ).fetchone()[0]
            == 0
        )
        plan = str(con.execute("EXPLAIN " + actual).fetchall())
        assert "DELIM_JOIN" not in plan
        assert "HASH_JOIN" in plan and "SEMI" in plan

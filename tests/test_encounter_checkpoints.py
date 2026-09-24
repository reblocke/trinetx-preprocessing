import json

import duckdb
import pytest

from trinetx_preprocessing.encounters.checkpoints import StageCache


def test_failed_stage_rolls_back_and_completed_stage_survives_reopen(tmp_path):
    path = tmp_path / "cache.duckdb"
    binding = {"source": "authenticated-source", "code": "producer"}
    with duckdb.connect(str(path)) as db:
        cache = StageCache(db, binding)

        def interrupted():
            db.execute("CREATE TABLE values_table AS SELECT 42 AS value")
            raise RuntimeError("synthetic interruption before commit")

        with pytest.raises(RuntimeError, match="interruption"):
            cache.run("values", ["values_table"], interrupted)
        assert not cache.receipts()
        assert not db.execute(
            "SELECT table_name FROM duckdb_tables() WHERE table_name='values_table'"
        ).fetchall()

        def completed():
            db.execute("CREATE TABLE values_table AS SELECT 42 AS value")
            return {"result": "preserved"}

        assert cache.run("values", ["values_table"], completed) == {
            "result": "preserved"
        }
    with duckdb.connect(str(path)) as db:
        cache = StageCache(db, binding)

        def must_not_repeat():
            raise AssertionError("completed computation repeated")

        assert cache.run("values", ["values_table"], must_not_repeat) == {
            "result": "preserved"
        }
        assert db.execute("SELECT value FROM values_table").fetchall() == [(42,)]
        db.execute("INSERT INTO values_table VALUES (43)")
        with pytest.raises(ValueError, match="integrity"):
            cache.run("values", ["values_table"], must_not_repeat)


def test_cache_rejects_changed_binding_and_unbound_old_database(tmp_path):
    with duckdb.connect(str(tmp_path / "bound.duckdb")) as db:
        StageCache(db, {"source": "one", "code": "same"})
        with pytest.raises(ValueError, match="binding changed"):
            StageCache(db, {"source": "two", "code": "same"})
        with pytest.raises(ValueError, match="binding changed"):
            StageCache(db, {"source": "one", "code": "changed"})
    with duckdb.connect(str(tmp_path / "old.duckdb")) as db:
        db.execute("CREATE TABLE source_keys AS SELECT 'p-e' AS key")
        with pytest.raises(ValueError, match="validated recovery"):
            StageCache(db, {"source": "one"})


@pytest.mark.parametrize(
    "mutation",
    [
        "UPDATE values_table SET value=3 WHERE value=2",
        "UPDATE values_table SET value=2 WHERE value=1 AND ordinal=2",
        "UPDATE values_table SET observed=NULL WHERE ordinal=3",
        "UPDATE values_table SET event_date=DATE '2024-01-03' WHERE ordinal=3",
        "UPDATE values_table SET decimal_value=1.25 WHERE ordinal=3",
    ],
)
def test_content_fingerprint_rejects_same_count_mutations(tmp_path, mutation):
    path = tmp_path / "cache.duckdb"
    with duckdb.connect(str(path)) as db:
        cache = StageCache(db, {"source": "one"})

        def create():
            db.execute(
                """
                CREATE TABLE values_table AS
                SELECT ordinal, value, observed, event_date, decimal_value
                FROM (VALUES
                    (1, 1, TRUE, DATE '2024-01-01', 1.00::DECIMAL(5,2)),
                    (2, 1, TRUE, DATE '2024-01-01', 1.00::DECIMAL(5,2)),
                    (3, 2, FALSE, DATE '2024-01-02', 1.00::DECIMAL(5,2))
                ) AS rows(ordinal,value,observed,event_date,decimal_value)
                """
            )
            return {"stage": "complete"}

        assert cache.run("values", ["values_table"], create) == {"stage": "complete"}
        db.execute(mutation)
    with duckdb.connect(str(path)) as db:
        cache = StageCache(db, {"source": "one"})
        with pytest.raises(ValueError, match="integrity changed"):
            cache.run("values", ["values_table"], lambda: None)


def test_legacy_receipt_cannot_be_blessed_by_hashing_current_cache(tmp_path):
    path = tmp_path / "cache.duckdb"
    with duckdb.connect(str(path)) as db:
        cache = StageCache(db, {"source": "one"})

        def create():
            db.execute("CREATE TABLE values_table AS SELECT 42 AS value")

        cache.run("values", ["values_table"], create)
        receipt = cache.receipts()["values"]
        assert receipt["fingerprint_version"] == "1.0"
        del receipt["fingerprint_version"]
        db.execute(
            "UPDATE encounter_stage_checkpoint SET receipt=? WHERE stage='values'",
            [json.dumps(receipt)],
        )
    with duckdb.connect(str(path)) as db:
        cache = StageCache(db, {"source": "one"})
        with pytest.raises(ValueError, match="Legacy encounter cache"):
            cache.run("values", ["values_table"], lambda: None)

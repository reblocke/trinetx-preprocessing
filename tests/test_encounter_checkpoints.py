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

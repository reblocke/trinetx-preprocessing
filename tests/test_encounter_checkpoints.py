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
    "replacement",
    ["UPDATE values_table SET metric=43", "duplicate_replace"],
)
def test_checkpoint_fingerprint_detects_same_count_value_or_duplicate_change(
    tmp_path, replacement
):
    path = tmp_path / "fingerprint.duckdb"
    with duckdb.connect(str(path)) as db:
        cache = StageCache(db, {"source": "synthetic"})
        cache.run(
            "values",
            ["values_table"],
            lambda: (
                db.execute(
                    "CREATE TABLE values_table AS SELECT 41 metric UNION ALL SELECT 42"
                ),
                None,
            )[1],
        )
        if replacement.startswith("UPDATE"):
            db.execute(replacement)
        else:
            db.execute("DELETE FROM values_table")
            db.execute("INSERT INTO values_table VALUES (41),(41)")
        with pytest.raises(ValueError, match="integrity"):
            cache.run("values", ["values_table"], lambda: None)


def test_checkpoint_fingerprint_preserves_null_dates_and_duplicate_multiplicity(
    tmp_path,
):
    with duckdb.connect(str(tmp_path / "typed.duckdb")) as db:
        cache = StageCache(db, {"source": "typed"})
        cache.run(
            "typed",
            ["typed_table"],
            lambda: db.execute("""
                CREATE TABLE typed_table AS SELECT CAST(NULL AS VARCHAR) label_text,
                    DATE '2024-01-01' event_date UNION ALL
                SELECT 'x',DATE '2024-01-01' UNION ALL SELECT 'x',DATE '2024-01-01'
            """).fetchall(),
        )
        # Physical reordering does not change the sorted multiset fingerprint.
        db.execute(
            "CREATE TABLE reordered AS SELECT * FROM typed_table "
            "ORDER BY label_text DESC"
        )
        db.execute("DROP TABLE typed_table")
        db.execute("ALTER TABLE reordered RENAME TO typed_table")
        assert cache.run("typed", ["typed_table"], lambda: None) == [[3]]


def test_legacy_checkpoint_receipt_requires_explicit_adoption(tmp_path):
    with duckdb.connect(str(tmp_path / "legacy-receipt.duckdb")) as db:
        StageCache(db, {"source": "legacy"})
        db.execute("CREATE TABLE values_table AS SELECT 1 metric")
        db.execute(
            "INSERT INTO encounter_stage_checkpoint VALUES ('values', ?)",
            [
                '{"tables":{"values_table":{"rows":1,"schema":[["metric","BIGINT"]]}},"result":null}'
            ],
        )
        cache = StageCache(db, {"source": "legacy"})
        with pytest.raises(ValueError, match="Legacy encounter checkpoint"):
            cache.run("values", ["values_table"], lambda: None)

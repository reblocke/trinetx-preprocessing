"""Regression checks for the extracted preprocessing boundary."""

import csv
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import pytest

from trinetx_preprocessing.combined_preprocessing.contract import compatibility_outputs
from trinetx_preprocessing.encounters.builder import CompatibilityFrames
from trinetx_preprocessing.encounters.legacy.measurement import (
    apply_pre_model_transformations,
)
from trinetx_preprocessing.encounters.legacy.pipeline import assemble_analysis_base
from trinetx_preprocessing.encounters.legacy.raw_schema import load_schema

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def compatibility_database(tmp_path_factory):
    path = tmp_path_factory.mktemp("encounter-source") / "source.duckdb"
    schema = load_schema()
    db = duckdb.connect(str(path))
    columns = ", ".join('"' + c.raw_name + '" VARCHAR' for c in schema.columns)
    db.execute(
        "CREATE TABLE preprocessed_encounter (compatibili"
        "ty_output_key VARCHAR, output_variant VARCHAR, s"
        "ource_row_order BIGINT, " + columns + ")"
    )
    for output in compatibility_outputs():
        source = ROOT / "tests/fixtures/encounter_compatibility" / output.relative_path
        with source.open(newline="") as f:
            rows = list(csv.reader(f))
        frame = pd.DataFrame(rows[1:], columns=rows[0], dtype=object)
        frame.insert(0, "source_row_order", np.arange(len(frame)))
        frame.insert(0, "output_variant", output.variant)
        frame.insert(0, "compatibility_output_key", output.key)
        db.register("fixture", frame)
        db.execute("INSERT INTO preprocessed_encounter SELECT * FROM fixture")
        db.unregister("fixture")
    db.close()
    return path


@pytest.mark.parametrize("suffix", ["BEFORE", "AFTER"])
def test_encounter_population_and_imputation(compatibility_database, suffix):
    with duckdb.connect(str(compatibility_database), read_only=True) as db:
        inputs = CompatibilityFrames(db, suffix)
        base = assemble_analysis_base(inputs)
        keys = base.frame.pat_enc_hash.copy()
        assert len(inputs.consumed) == 18
        assert keys.is_unique
        assert base.frame.patient_id.nunique() < len(base.frame)
        result = (
            apply_pre_model_transformations(base, take_ownership=True)
            if suffix == "AFTER"
            else base
        )
        pd.testing.assert_series_equal(keys, result.frame.pat_enc_hash)
        assert ("abg_o2sat_calc" in result.frame) == (suffix == "AFTER")
        assert ("vbg_o2sat_calc" in result.frame) == (suffix == "AFTER")
        assert not {"ps", "vbg_ps", "ipw", "vbg_ipw"} & set(result.frame)
        assert result.frame.first_encounter.eq(0).any()


def test_no_analysis_model_dependencies():
    import sys

    assert "xgboost" not in sys.modules
    assert "sklearn" not in sys.modules


def test_enrichment_preserves_non_glp1_encounters(compatibility_database, tmp_path):
    from test_cohort_source import _build_cohort_source_product

    from trinetx_preprocessing.clinical_sources.concept_sets import load_concept_sets
    from trinetx_preprocessing.encounters.builder import _enrich
    from trinetx_preprocessing.encounters.config import FeatureConfig

    source_root = tmp_path / "canonical"
    source_root.mkdir()
    source = _build_cohort_source_product(source_root)
    # Reuse the accepted synthetic port matrix as the encounter population.
    # The source domains intentionally have different patients: every row must
    # survive with unavailable GLP1 evidence rather than being study-filtered.
    with duckdb.connect(str(source)) as db:
        db.execute(
            "ATTACH "
            + "\x27"
            + str(compatibility_database).replace("\x27", "\x27\x27")
            + "\x27 AS compatibility (READ_ONLY)"
        )
        db.execute("DROP TABLE preprocessed_encounter")
        db.execute(
            "CREATE TABLE preprocessed_encounter AS SELECT * "
            "FROM compatibility.preprocessed_encounter"
        )
    with duckdb.connect(str(compatibility_database), read_only=True) as db:
        base = apply_pre_model_transformations(
            assemble_analysis_base(CompatibilityFrames(db, "AFTER")),
            take_ownership=True,
        )
    base_path = tmp_path / "base.parquet"
    base.frame.to_parquet(base_path, index=False)
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    destination = tmp_path / "encounters.parquet"
    qa, _ = _enrich(
        source,
        base_path,
        destination,
        scratch,
        "AFTER",
        load_concept_sets(ROOT / "config/concept_sets"),
        FeatureConfig(),
    )
    result = pd.read_parquet(destination)
    assert qa["rows"] == len(base.frame)
    assert result[["patient_id", "encounter_id"]].duplicated().sum() == 0
    assert result.glp1_medication_glp1_active_at_index.isna().all()
    assert result.first_encounter.eq(0).any()


def test_ordered_merge_preserves_master_and_fills_only_missing():
    from trinetx_preprocessing.encounters.legacy.per_file_cleaning import (
        CleaningMetadata,
    )
    from trinetx_preprocessing.encounters.legacy.pipeline import (
        PipelineResult,
        _stata_update_merge,
    )

    master = PipelineResult(
        pd.DataFrame(
            {
                "pat_enc_hash": ["p-e1", "p-e2"],
                "value": [1.0, np.nan],
                "ABG_rfs": [1.0, 1.0],
            }
        ),
        CleaningMetadata(),
    )
    using = PipelineResult(
        pd.DataFrame(
            {
                "pat_enc_hash": ["p-e1", "p-e2", "p-e3"],
                "value": [2.0, 3.0, 4.0],
                "VBG_rfs": [1.0, 1.0, 1.0],
            }
        ),
        CleaningMetadata(
            storage_types={"VBG_rfs": "byte"}, display_formats={"VBG_rfs": "%8.0g"}
        ),
    )
    result = _stata_update_merge(master, using, merge_name="_merge_test").frame
    assert result.value.tolist() == [1.0, 3.0, 4.0]
    assert result._merge_test.tolist() == [5, 4, 2]
    assert result.loc[0, ["ABG_rfs", "VBG_rfs"]].tolist() == [1.0, 1.0]


def test_catalog_evidence_time_boundaries_source_keys_and_overlap():
    from trinetx_preprocessing.combined_preprocessing.elements import (
        SOURCE_EVENT_DUCKDB_TYPES,
    )
    from trinetx_preprocessing.encounters.config import FeatureConfig
    from trinetx_preprocessing.encounters.element_features import (
        DOMAINS,
        build_element_evidence,
    )

    with duckdb.connect() as db:
        db.execute("ATTACH ':memory:' AS preprocessed")
        schema = ", ".join(f'"{k}" {v}' for k, v in SOURCE_EVENT_DUCKDB_TYPES.items())
        for table in DOMAINS.values():
            db.execute(f"CREATE TABLE preprocessed.{table} ({schema})")
        db.execute("""
            CREATE TABLE preprocessed.element_catalog AS
            SELECT 'source.hba1c' element_id, 'lab' AS domain
            UNION ALL SELECT 'source.traditional.lab.a1c', 'lab'
            UNION ALL SELECT 'source.ahi', 'lab';
            CREATE TABLE preprocessed.element_membership (
                source_record_id VARCHAR, element_id VARCHAR, include BOOLEAN
            );
            CREATE TABLE encounter_anchor (
                index_event_id VARCHAR, patient_id VARCHAR,
                encounter_id VARCHAR, index_date TIMESTAMP
            );
            INSERT INTO encounter_anchor VALUES
                ('one', 'p', 'e1', '2024-01-01'),
                ('repeat', 'p', 'e2', '2024-01-02'),
                ('other', 'q', 'e1', '2024-01-01');
        """)
        rows = [
            ("boundary", "p", "old", "2023-01-01 12:00:00", 7.0),
            ("same_day", "p", "old", "2024-01-01 18:00:00", 5.0),
            ("too_old", "p", "old", "2022-12-31", 8.0),
            ("future", "p", "new", "2024-01-03", 9.0),
            ("same_encounter", "p", "e1", "2024-01-02", 6.0),
        ]
        db.executemany(
            """
            INSERT INTO preprocessed.source_lab_measurement
                (source_record_id, patient_id, encounter_id,
                 event_datetime, numeric_value, units_of_measure)
            VALUES (?, ?, ?, ?, ?, '%')
        """,
            rows,
        )
        db.executemany(
            "INSERT INTO preprocessed.element_membership VALUES (?, ?, true)",
            [
                (r[0], e)
                for r in rows
                for e in ("source.hba1c", "source.traditional.lab.a1c")
            ],
        )
        inventory = build_element_evidence(db, FeatureConfig())
        observed = db.execute("""
            SELECT DISTINCT index_event_id,source_record_id
            FROM encounter_element_evidence ORDER BY 1,2
        """).fetchall()
        assert observed == [
            ("one", "boundary"),
            ("one", "same_day"),
            ("one", "same_encounter"),
            ("repeat", "same_day"),
            ("repeat", "same_encounter"),
        ]
        assert len(inventory) == 3
        assert all(
            c.startswith("source_element_") for row in inventory for c in row["columns"]
        )
        assert db.execute("""
            SELECT element_hba1c_record_count,element_ahi_record_count,
                   element_hba1c_latest_raw_value
            FROM element_summary WHERE index_event_id='one'
        """).fetchone() == (3, 0, 5.0)
        # Unknown patient coverage produces no summary; left join remains NULL.
        assert (
            db.execute("""
            SELECT count(*) FROM element_summary WHERE index_event_id='other'
        """).fetchone()[0]
            == 0
        )


def test_source_key_collision_rejected_before_enrichment(tmp_path):
    from trinetx_preprocessing.encounters.builder import _enrich
    from trinetx_preprocessing.encounters.config import FeatureConfig

    source = tmp_path / "source.duckdb"
    with duckdb.connect(str(source)) as db:
        db.execute("""
            CREATE TABLE preprocessed_encounter AS
            SELECT 'a-b' patient_id, 'c' encounter_id, 'AFTER' output_variant
            UNION ALL SELECT 'a', 'b-c', 'AFTER'
        """)
    base = tmp_path / "base.parquet"
    pd.DataFrame({"pat_enc_hash": ["a-b-c"]}).to_parquet(base)
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    with pytest.raises(ValueError, match="uniquely identify"):
        _enrich(
            source,
            base,
            tmp_path / "out.parquet",
            scratch,
            "AFTER",
            None,
            FeatureConfig(),
        )


def test_builder_rejects_existing_output_without_touching_source(tmp_path):
    from trinetx_preprocessing.encounters.builder import build_encounters

    source = tmp_path / "source.duckdb"
    source.write_bytes(b"unchanged")
    output = tmp_path / "output"
    output.mkdir()
    with pytest.raises(FileExistsError):
        build_encounters(database=source, output_dir=output)
    assert source.read_bytes() == b"unchanged"

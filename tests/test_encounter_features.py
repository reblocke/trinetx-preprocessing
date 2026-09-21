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
        "CREATE TABLE compatibility_input (compatibili"
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
        db.execute("INSERT INTO compatibility_input SELECT * FROM fixture")
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


def test_enrichment_preserves_non_glp1_encounters(
    compatibility_database, tmp_path, monkeypatch
):
    from test_cohort_source import _build_cohort_source_product

    from trinetx_preprocessing.clinical_sources.concept_sets import load_concept_sets
    from trinetx_preprocessing.encounters import source_projection
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
            "FROM compatibility.compatibility_input"
        )
    with duckdb.connect(str(compatibility_database), read_only=True) as db:
        base = apply_pre_model_transformations(
            assemble_analysis_base(CompatibilityFrames(db, "AFTER")),
            take_ownership=True,
        )
    # Add genuine medication evidence to an encounter that fails the old
    # obesity study criterion; enrichment must still populate its features.
    target = base.frame.iloc[0]["pat_enc_hash"]
    base.frame.loc[base.frame.pat_enc_hash.eq(target), "bmi"] = 25.0
    anchor = pd.Timestamp("1960-01-01") + pd.Timedelta(
        days=float(base.frame.iloc[0]["encounter_date"])
    )
    with duckdb.connect(str(source)) as db:
        patient, encounter = db.execute(
            "SELECT patient_id, encounter_id FROM preprocessed_encounter "
            "WHERE concat(patient_id,'-',encounter_id)=? LIMIT 1",
            [target],
        ).fetchone()
        date = (anchor - pd.Timedelta(days=1)).strftime("%Y-%m-%d")
        db.execute(
            "INSERT INTO source_medication "
            "(source_record_id,logical_domain,source_file,source_row_number,"
            "patient_id,encounter_id,code_system_raw,code_system,code_raw,code,"
            "event_datetime,start_datetime,start_date,date) "
            "VALUES ('synthetic-semaglutide','medications','synthetic.csv',1,"
            "?,?,'RXNORM','RXNORM','1991302','1991302',?,?,?,?)",
            [patient, encounter, date, date, date, date],
        )
        db.execute(
            "INSERT INTO element_membership "
            "(source_record_id,element_id,logical_domain,include,match_type,"
            "code_system,matched_code) VALUES "
            "('synthetic-semaglutide','source.glp1_semaglutide','medications',"
            "true,'exact','RXNORM','1991302')"
        )
    base_path = tmp_path / "base.parquet"
    with duckdb.connect(str(compatibility_database), read_only=True) as db:
        original = db.execute(
            "SELECT DISTINCT trim(concat(patient_id,'-',encounter_id),' ') "
            "AS pat_enc_hash, patient_id, encounter_id FROM compatibility_input"
        ).fetchdf()
    keyed = base.frame.rename(
        columns={
            "patient_id": "legacy_patient_id",
            "encounter_id": "legacy_encounter_id",
        }
    ).merge(original, on="pat_enc_hash", validate="one_to_one")
    keyed.to_parquet(base_path, index=False)
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
        source_cache=tmp_path / "source-cache",
    )
    result = pd.read_parquet(destination)
    assert qa["rows"] == len(base.frame)
    assert result[["patient_id", "encounter_id"]].duplicated().sum() == 0
    retained = result.loc[result.pat_enc_hash.eq(target)]
    assert retained.bmi.iloc[0] == 25
    assert bool(retained.glp1_medication_glp1_active_at_index.iloc[0])
    assert result.glp1_medication_glp1_active_at_index.isna().any()
    assert result.first_encounter.eq(0).any()

    def must_not_repeat(*args, **kwargs):
        raise AssertionError("completed canonical lab extraction repeated")

    monkeypatch.setattr(source_projection, "_create_lab_source", must_not_repeat)
    resumed_scratch = tmp_path / "resumed-scratch"
    resumed_scratch.mkdir()
    resumed_destination = tmp_path / "resumed.parquet"
    resumed_qa, _ = _enrich(
        source,
        base_path,
        resumed_destination,
        resumed_scratch,
        "AFTER",
        load_concept_sets(ROOT / "config/concept_sets"),
        FeatureConfig(),
        source_cache=tmp_path / "source-cache",
    )
    resumed = pd.read_parquet(resumed_destination)
    order = ["patient_id", "encounter_id"]
    pd.testing.assert_frame_equal(
        result.sort_values(order).reset_index(drop=True),
        resumed.sort_values(order).reset_index(drop=True),
    )
    assert resumed_qa == qa


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
        from trinetx_preprocessing.encounters.element_features import (
            add_availability_inventory,
        )

        db.execute("""
            CREATE TABLE encounter_source_coverage AS
            SELECT index_event_id, 'labs' AS domain,
                CASE WHEN patient_id='q' THEN 'incomplete_capture'
                     ELSE 'observed_span' END AS history_state
            FROM encounter_anchor
        """)
        with_states = add_availability_inventory(db, inventory)
        for element in with_states:
            assert (
                sum(
                    s["observed_matches"] + s["zero_matching_records"]
                    for s in element["availability_states"]
                )
                == 3
            )
        ahi = next(e for e in with_states if e["element_id"] == "source.ahi")
        assert sum(s["observed_matches"] for s in ahi["availability_states"]) == 0


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
    pd.DataFrame(
        {
            "pat_enc_hash": ["a-b-c", "a-b-c"],
            "patient_id": ["a-b", "a"],
            "encounter_id": ["c", "b-c"],
        }
    ).to_parquet(base)
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
        build_encounters(
            database=source,
            compatibility_database=source,
            legacy_bundle=tmp_path / "base",
            legacy_acceptance=tmp_path / "gate",
            coverage_bundle=tmp_path / "coverage",
            output_dir=output,
        )
    assert source.read_bytes() == b"unchanged"


def test_observability_uses_same_calendar_day_as_features():
    from trinetx_preprocessing.encounters.source_projection import (
        _create_observability_table,
    )

    with duckdb.connect() as db:
        db.execute("""
            ATTACH ':memory:' AS preprocessed;
            CREATE TABLE encounter_anchor AS
                SELECT 'p' patient_id, 'one' index_event_id,
                       DATE '2024-01-01' index_date;
            CREATE TABLE preprocessed.source_observability_event (
                patient_id VARCHAR, logical_domain VARCHAR,
                event_datetime TIMESTAMP, timestamp_precision VARCHAR,
                event_count BIGINT
            );
            INSERT INTO preprocessed.source_observability_event VALUES
                ('p','labs','2024-01-01 18:00:00','timestamp',1),
                ('p','labs','2023-01-01 12:00:00','timestamp',2),
                ('p','labs','2024-01-02 00:00:00','timestamp',4);
        """)
        _create_observability_table(
            db, output_domain="labs", stored_domain="labs", lookback_days=365
        )
        assert (
            db.execute("SELECT event_count FROM raw_labs_observability").fetchone()[0]
            == 3
        )


def test_encounter_context_prunes_unused_keys_without_changing_first_row():
    from trinetx_preprocessing.encounters.builder import (
        _create_encounter_context_source,
    )

    with duckdb.connect() as db:
        db.execute("""
            CREATE TABLE source_encounter (
                patient_id VARCHAR, encounter_id VARCHAR, type VARCHAR,
                encounter_start TIMESTAMP, source_record_hash VARCHAR,
                unused_payload VARCHAR
            );
            INSERT INTO source_encounter VALUES
                ('p','shared','INPAT','2024-01-02','a','wide'),
                ('p','shared',NULL,'2024-01-01','a','wide'),
                ('p','shared','AMB','2024-01-01','b','wide'),
                ('q','shared','EMER','2024-01-01','a','wide'),
                ('p','unused','AMB','2024-01-01','a','wide'),
                ('p',NULL,'AMB','2024-01-01','a','wide');
            CREATE TABLE source_vital_measurement AS
                SELECT * FROM (VALUES
                    ('p','shared'),('p','shared'),('q','shared'),('p',NULL)
                ) v(patient_id,encounter_id);
            CREATE TABLE original_context AS
                SELECT * EXCLUDE (observed_order) FROM (
                    SELECT *, row_number() OVER (
                        PARTITION BY patient_id,encounter_id
                        ORDER BY encounter_start,source_record_hash
                    ) observed_order FROM source_encounter
                    WHERE patient_id IS NOT NULL AND encounter_id IS NOT NULL
                ) WHERE observed_order=1;
        """)
        _create_encounter_context_source(db)
        assert db.execute(
            "SELECT * FROM encounter_context_source ORDER BY patient_id"
        ).fetchall() == [("p", "shared", None), ("q", "shared", "EMER")]
        for table in ("original_context", "encounter_context_source"):
            rows = db.execute(
                f"SELECT vital.patient_id,vital.encounter_id,context.type "
                f"FROM source_vital_measurement vital LEFT JOIN {table} context "
                "USING(patient_id,encounter_id) ORDER BY 1,2"
            ).fetchall()
            if table == "original_context":
                expected = rows
            else:
                assert rows == expected

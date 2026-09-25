"""Synthetic return episodes; no private patient rows enter this fixture."""

from __future__ import annotations

import json

import duckdb
import pytest

from trinetx_preprocessing.encounters import return_validation, returns
from trinetx_preprocessing.encounters.returns import _build_partition


def _source(db: duckdb.DuckDBPyConnection, source_path: str = ":memory:") -> None:
    db.execute(f"ATTACH '{source_path}' AS preprocessed")
    db.execute(
        """CREATE TABLE preprocessed.source_encounter (
            patient_id VARCHAR, encounter_id VARCHAR, source_record_id VARCHAR,
            source_file VARCHAR, source_row_number BIGINT, source_id VARCHAR,
            type VARCHAR, start_datetime TIMESTAMP, end_datetime TIMESTAMP,
            start_timestamp_precision VARCHAR, end_timestamp_precision VARCHAR,
            end_date_derived_by_TriNetX VARCHAR)"""
    )
    db.execute(
        """INSERT INTO preprocessed.source_encounter VALUES
        ('p','i','si','f',1,'s','IMP','2024-01-01','2024-01-02',
         'date_only','date_only',''),
        ('p','r1','sr1a','f',2,'s','EMER','2024-01-05','2024-01-05',
         'date_only','date_only',''),
        ('p','r1','sr1b','f',3,'s','IMP','2024-01-05','2024-01-07',
         'date_only','date_only',''),
        ('p','r2','sr2','f',4,'s','EMER','2024-01-10','2024-01-10',
         'date_only','date_only',''),
        ('p','same','ss','f',5,'s','EMER','2024-01-02','2024-01-02',
         'date_only','date_only',''),
        ('q','qi','sqi','f',6,'s','EMER','2024-01-01',NULL,
         'date_only',NULL,''),
        ('outside','o','so','f',7,'s','IMP','2024-01-04','2024-01-05',
        'date_only','date_only','')"""
    )
    db.execute(
        "ALTER TABLE preprocessed.source_encounter "
        "ADD COLUMN start_date_derived_by_TriNetX VARCHAR"
    )
    db.execute(
        """CREATE TABLE preprocessed.source_diagnosis (
            patient_id VARCHAR, encounter_id VARCHAR, source_record_id VARCHAR,
            source_file VARCHAR, source_row_number BIGINT, source_id VARCHAR,
            code_system VARCHAR, code VARCHAR, event_datetime TIMESTAMP,
            timestamp_precision VARCHAR)"""
    )
    db.execute(
        """INSERT INTO preprocessed.source_diagnosis VALUES
        ('p','i','di','f',1,'s','ICD-10-CM','J96.02','2024-01-01','date_only'),
        ('p','r1','dr','f',2,'s','ICD-10-CM','J96.02','2024-01-05','date_only'),
        ('p','r2','dr2','f',3,'s','ICD-10-CM','J96.9','2024-01-10','date_only')"""
    )
    db.execute(
        """CREATE TABLE preprocessed.source_lab_measurement (
            patient_id VARCHAR, encounter_id VARCHAR, source_record_id VARCHAR,
            source_file VARCHAR, source_row_number BIGINT, source_id VARCHAR,
            code_system VARCHAR, code VARCHAR, event_datetime TIMESTAMP,
            timestamp_precision VARCHAR, specimen VARCHAR, specimen_id VARCHAR,
            panel_id VARCHAR, numeric_value DOUBLE, units_of_measure VARCHAR)"""
    )
    db.execute(
        """INSERT INTO preprocessed.source_lab_measurement VALUES
        ('p','r1','g1','f',1,'s','LOINC','2019-8','2024-01-05',
         'date_only','arterial','','',45,'mmHg'),
        ('p','r1','g2','f',2,'s','LOINC','2021-4','2024-01-05',
         'date_only','venous','','',50,'mmHg'),
        ('p','r2','g3','f',3,'s','LOINC','2019-8','2024-01-10',
         'date_only','venous','','',60,'mmHg'),
        ('p','r2','g4','f',4,'s','LOINC','2021-4','2024-01-10',
         'date_only','venous','','',5,'unsupported')"""
    )
    db.execute(
        "CREATE TABLE preprocessed.element_membership "
        "(source_record_id VARCHAR, element_id VARCHAR, include BOOLEAN)"
    )
    db.execute(
        """INSERT INTO preprocessed.element_membership VALUES
        ('g1','source.arterial_pco2',true),
        ('g2','source.venous_pco2',true),
        ('g3','source.arterial_pco2',true),
        ('g4','source.venous_pco2',true)"""
    )
    db.execute(
        "CREATE TABLE preprocessed.source_patient "
        "(patient_id VARCHAR, month_year_death VARCHAR)"
    )
    db.execute(
        "INSERT INTO preprocessed.source_patient VALUES ('p','2024-01'),('q',NULL)"
    )
    db.execute(
        "CREATE TABLE preprocessed.patient_observability "
        "(patient_id VARCHAR, last_event_datetime TIMESTAMP)"
    )
    db.execute(
        "INSERT INTO preprocessed.patient_observability "
        "VALUES ('p','2024-01-15'),('q','2024-01-03')"
    )
    db.execute(
        "CREATE TABLE preprocessed.element_rule "
        "(code VARCHAR, code_system VARCHAR, domain VARCHAR, "
        "match_type VARCHAR, include BOOLEAN)"
    )
    for code in returns.RETURN_ICD_CODES:
        db.execute(
            "INSERT INTO preprocessed.element_rule VALUES "
            "(?,'ICD10CM','diagnosis','exact',true)",
            [code],
        )
    db.execute("CREATE TABLE preprocessed.element_catalog (element_id VARCHAR)")
    db.execute(
        "INSERT INTO preprocessed.element_catalog VALUES "
        "('source.arterial_pco2'),('source.venous_pco2')"
    )
    db.execute(
        "CREATE TEMP TABLE fixture_index "
        "(patient_id VARCHAR, encounter_id VARCHAR, pat_enc_hash VARCHAR)"
    )
    db.execute("INSERT INTO fixture_index VALUES ('p','i','p-i'),('q','qi','q-qi')")
    db.execute("CREATE TEMP VIEW index_file AS SELECT * FROM fixture_index")


def test_returns_preserve_union_thresholds_missingness_and_recurrence(tmp_path):
    db = duckdb.connect()
    try:
        _source(db)
        _build_partition(
            db, variant="FULL_DATA", bucket=0, partitions=1, output=tmp_path
        )
    finally:
        db.close()
    with duckdb.connect() as read:
        summary = (
            read.execute(
                "SELECT * FROM read_parquet(?) WHERE patient_id='p'",
                [str(tmp_path / "full_data_0000_summary.parquet")],
            )
            .fetchdf()
            .iloc[0]
        )
        assert summary["outcome_acute_union_all_cause_30d_count"] == 2
        assert summary["outcome_inpatient_all_cause_30d_count"] == 1
        assert summary["outcome_ed_only_all_cause_30d_count"] == 1
        assert summary["outcome_acute_union_icd_hypercapnia_30d_count"] == 1
        assert summary["outcome_inpatient_abg_ge45_30d_count"] == 1
        assert summary["outcome_inpatient_abg_gt45_30d_count"] == 0
        assert summary["outcome_inpatient_vbg_ge50_30d_count"] == 1
        assert summary["outcome_inpatient_vbg_gt50_30d_count"] == 0
        assert summary["same_day_uncertain_count"] == 1
        assert summary["month_year_death"] == "2024-01"
        assert (
            summary["outcome_followup_observation_365d"]
            == "last_observation_before_horizon"
        )
        missing = read.execute(
            "SELECT anchor_state, outcome_acute_union_all_cause_30d_flag "
            "FROM read_parquet(?) WHERE patient_id='q'",
            [str(tmp_path / "full_data_0000_summary.parquet")],
        ).fetchone()
        assert missing == ("missing_episode_end", None)
        links = read.execute(
            "SELECT count(*), count(*) FILTER (WHERE temporal_state='confirmed') "
            "FROM read_parquet(?) WHERE index_event_id='p-i'",
            [str(tmp_path / "full_data_0000_links.parquet")],
        ).fetchone()
        assert links == (3, 2)
        reasons = {
            row[0]
            for row in read.execute(
                "SELECT rejection_reason FROM read_parquet(?) "
                "WHERE rejection_reason IS NOT NULL",
                [str(tmp_path / "full_data_0000_gas_evidence.parquet")],
            ).fetchall()
        }
        assert reasons == {"contradictory_specimen", "unsupported_unit"}


def test_duplicate_return_link_rejected(tmp_path):
    db = duckdb.connect()
    try:
        _source(db)
        db.execute("INSERT INTO fixture_index VALUES ('p','i','p-i')")
        with pytest.raises(ValueError, match="Duplicate index-to-return"):
            _build_partition(
                db, variant="FULL_DATA", bucket=0, partitions=1, output=tmp_path
            )
    finally:
        db.close()


def test_link_geometry_reconciliation_detects_changed_return_time(tmp_path):
    with duckdb.connect() as db:
        _source(db)
        _build_partition(
            db, variant="FULL_DATA", bucket=0, partitions=1, output=tmp_path
        )
        for table in ("links", "summary", "episodes"):
            path = tmp_path / f"full_data_0000_{table}.parquet"
            db.execute(
                f"CREATE VIEW {table} AS SELECT * FROM "
                f"read_parquet({returns.literal(path)})"
            )
        query = return_validation._link_geometry_reconciliation_query()
        assert db.execute(query).fetchone()[0] == 0
        path = tmp_path / "full_data_0000_links.parquet"
        db.execute(
            "CREATE OR REPLACE VIEW links AS SELECT * REPLACE "
            "(CASE WHEN encounter_id='r1' THEN return_start+INTERVAL 1 DAY "
            "ELSE return_start END AS return_start) "
            f"FROM read_parquet({returns.literal(path)})"
        )
        assert db.execute(query).fetchone()[0] == 1


def test_episode_source_mapping_reconciliation_detects_changed_start(tmp_path):
    with duckdb.connect() as db:
        _source(db)
        _build_partition(
            db, variant="FULL_DATA", bucket=0, partitions=1, output=tmp_path
        )
        for table in ("episode_source", "episodes"):
            path = tmp_path / f"full_data_0000_{table}.parquet"
            db.execute(
                f"CREATE VIEW {table} AS SELECT * FROM "
                f"read_parquet({returns.literal(path)})"
            )
        query = return_validation._episode_mapping_reconciliation_query()
        assert db.execute(query).fetchone()[0] == 0
        path = tmp_path / "full_data_0000_episode_source.parquet"
        db.execute(
            "CREATE OR REPLACE VIEW episode_source AS SELECT * REPLACE "
            "(CASE WHEN encounter_id='r2' "
            "THEN start_datetime+INTERVAL 1 DAY "
            "ELSE start_datetime END AS start_datetime) "
            f"FROM read_parquet({returns.literal(path)})"
        )
        assert db.execute(query).fetchone()[0] == 1


def test_ed_index_inpatient_return_is_admission(tmp_path):
    db = duckdb.connect()
    try:
        _source(db)
        db.execute("DELETE FROM fixture_index")
        db.execute("INSERT INTO fixture_index VALUES ('p','r2','p-r2')")
        db.execute(
            "INSERT INTO preprocessed.source_encounter VALUES "
            "('p','r3','sr3','f',8,'s','IMP','2024-01-12','2024-01-14',"
            "'date_only','date_only','',NULL)"
        )
        _build_partition(
            db, variant="FULL_DATA", bucket=0, partitions=1, output=tmp_path
        )
    finally:
        db.close()
    with duckdb.connect() as read:
        row = read.execute(
            "SELECT admission_after_ed_index, readmission_after_inpatient "
            "FROM read_parquet(?) WHERE encounter_id='r3'",
            [str(tmp_path / "full_data_0000_links.parquet")],
        ).fetchone()
        assert row == (True, False)


def test_crossing_episode_is_retained_as_overlap_uncertainty(tmp_path):
    with duckdb.connect() as db:
        _source(db)
        db.execute(
            "INSERT INTO preprocessed.source_encounter VALUES "
            "('p','crossing','sc','f',9,'s','EMER','2024-01-01',"
            "'2024-01-03','date_only','date_only','',NULL)"
        )
        _build_partition(
            db, variant="FULL_DATA", bucket=0, partitions=1, output=tmp_path
        )
    with duckdb.connect() as read:
        link = read.execute(
            "SELECT temporal_state FROM read_parquet(?) "
            "WHERE index_encounter_id='i' AND encounter_id='crossing'",
            [str(tmp_path / "full_data_0000_links.parquet")],
        ).fetchone()
        summary = read.execute(
            "SELECT overlap_or_prior_count,outcome_acute_union_all_cause_30d_count "
            "FROM read_parquet(?) WHERE encounter_id='i'",
            [str(tmp_path / "full_data_0000_summary.parquet")],
        ).fetchone()
    assert link == ("overlap_or_prior",)
    assert summary == (1, 2)


def test_reversed_return_dates_cannot_be_confirmed(tmp_path):
    with duckdb.connect() as db:
        _source(db)
        db.execute(
            "INSERT INTO preprocessed.source_encounter VALUES "
            "('p','reversed','sb','f',9,'s','EMER','2024-01-12',"
            "'2024-01-11','date_only','date_only','',NULL)"
        )
        _build_partition(
            db, variant="FULL_DATA", bucket=0, partitions=1, output=tmp_path
        )
    with duckdb.connect() as read:
        link = read.execute(
            "SELECT temporal_state FROM read_parquet(?) "
            "WHERE index_encounter_id='i' AND encounter_id='reversed'",
            [str(tmp_path / "full_data_0000_links.parquet")],
        ).fetchone()
        count = read.execute(
            "SELECT invalid_return_episode_order_count, "
            "outcome_acute_union_all_cause_30d_count "
            "FROM read_parquet(?) WHERE encounter_id='i'",
            [str(tmp_path / "full_data_0000_summary.parquet")],
        ).fetchone()
    assert link == ("invalid_return_episode_order",)
    assert count == (1, 2)


def test_missing_canonical_icd_rule_blocks_build(tmp_path):
    source_file = tmp_path / "source.duckdb"
    with duckdb.connect() as db:
        _source(db, str(source_file))
        db.execute("DELETE FROM preprocessed.element_rule WHERE code='J96.02'")
    with pytest.raises(ValueError, match="J96.02"):
        returns._require_source_capabilities(source_file)


def test_gas_conversion_overflow_is_rejected(tmp_path):
    with duckdb.connect() as db:
        _source(db)
        db.execute(
            "INSERT INTO preprocessed.source_lab_measurement VALUES "
            "('p','r1','overflow','f',10,'s','LOINC','2019-8',"
            "'2024-01-05','date_only','arterial','','',1e308,'kPa')"
        )
        db.execute(
            "INSERT INTO preprocessed.element_membership VALUES "
            "('overflow','source.arterial_pco2',true)"
        )
        _build_partition(
            db, variant="FULL_DATA", bucket=0, partitions=1, output=tmp_path
        )
    with duckdb.connect() as read:
        row = read.execute(
            "SELECT rejection_reason,isfinite(value_mmhg) "
            "FROM read_parquet(?) WHERE source_record_id='overflow'",
            [str(tmp_path / "full_data_0000_gas_evidence.parquet")],
        ).fetchone()
    assert row == ("invalid_converted_value", False)


def test_wildcard_exact_icd_rule_retains_required_code(tmp_path):
    source_file = tmp_path / "source.duckdb"
    with duckdb.connect() as db:
        _source(db, str(source_file))
        db.execute("DELETE FROM preprocessed.element_rule WHERE code='J96.02'")
        db.execute(
            "INSERT INTO preprocessed.element_rule VALUES "
            "('J96.02','*','diagnosis','exact',true)"
        )
    returns._require_source_capabilities(source_file)


def test_derived_index_end_is_unavailable(tmp_path):
    with duckdb.connect() as db:
        _source(db)
        db.execute(
            "UPDATE preprocessed.source_encounter SET "
            "end_date_derived_by_TriNetX='yes' WHERE encounter_id='i'"
        )
        _build_partition(
            db, variant="FULL_DATA", bucket=0, partitions=1, output=tmp_path
        )
    with duckdb.connect() as read:
        result = read.execute(
            "SELECT anchor_state, outcome_acute_union_all_cause_30d_flag "
            "FROM read_parquet(?) WHERE patient_id='p'",
            [str(tmp_path / "full_data_0000_summary.parquet")],
        ).fetchone()
        assert result == ("derived_episode_end", None)


def test_conflicting_death_month_remains_unknown(tmp_path):
    with duckdb.connect() as db:
        _source(db)
        db.execute("INSERT INTO preprocessed.source_patient VALUES ('p','2024-02')")
        _build_partition(
            db, variant="FULL_DATA", bucket=0, partitions=1, output=tmp_path
        )
    with duckdb.connect() as read:
        death = read.execute(
            "SELECT month_year_death FROM read_parquet(?) WHERE patient_id='p'",
            [str(tmp_path / "full_data_0000_summary.parquet")],
        ).fetchone()[0]
        assert death is None


def test_precise_same_day_kpa_and_derived_return_start(tmp_path):
    precise = tmp_path / "precise"
    derived = tmp_path / "derived"
    precise.mkdir()
    derived.mkdir()
    with duckdb.connect() as db:
        _source(db)
        db.execute(
            "UPDATE preprocessed.source_encounter SET "
            "end_datetime='2024-01-02 10:00:00', "
            "end_timestamp_precision='timestamp' WHERE encounter_id='i'"
        )
        db.execute(
            "UPDATE preprocessed.source_encounter SET "
            "start_datetime='2024-01-02 12:00:00', "
            "end_datetime='2024-01-02 16:00:00', "
            "start_timestamp_precision='timestamp', "
            "end_timestamp_precision='timestamp' WHERE encounter_id='same'"
        )
        db.execute(
            "UPDATE preprocessed.source_lab_measurement SET "
            "numeric_value=6.0, units_of_measure='kPa' "
            "WHERE source_record_id='g1'"
        )
        _build_partition(
            db, variant="FULL_DATA", bucket=0, partitions=1, output=precise
        )
        db.execute(
            "UPDATE preprocessed.source_encounter SET "
            "start_date_derived_by_TriNetX='yes' WHERE encounter_id='r2'"
        )
        _build_partition(
            db, variant="FULL_DATA", bucket=0, partitions=1, output=derived
        )
    with duckdb.connect() as read:
        first = read.execute(
            "SELECT outcome_acute_union_all_cause_30d_count, "
            "outcome_acute_union_all_cause_30d_first_timestamp, "
            "outcome_inpatient_abg_gt45_30d_count "
            "FROM read_parquet(?) WHERE patient_id='p'",
            [str(precise / "full_data_0000_summary.parquet")],
        ).fetchone()
        assert first == (
            3,
            read.execute("SELECT TIMESTAMP '2024-01-02 12:00'").fetchone()[0],
            1,
        )
        second = read.execute(
            "SELECT outcome_acute_union_all_cause_30d_count, "
            "derived_return_start_count FROM read_parquet(?) WHERE patient_id='p'",
            [str(derived / "full_data_0000_summary.parquet")],
        ).fetchone()
        assert second == (2, 1)


def test_patient_partition_outputs_agree_with_unpartitioned(tmp_path):
    whole = tmp_path / "whole"
    split = tmp_path / "split"
    whole.mkdir()
    split.mkdir()
    with duckdb.connect() as db:
        _source(db)
        _build_partition(db, variant="FULL_DATA", bucket=0, partitions=1, output=whole)
        for bucket in range(2):
            _build_partition(
                db, variant="FULL_DATA", bucket=bucket, partitions=2, output=split
            )
    with duckdb.connect() as read:
        columns = (
            "patient_id, encounter_id, anchor_state, "
            "outcome_acute_union_all_cause_30d_count, "
            "outcome_acute_union_icd_hypercapnia_30d_first_date, "
            "outcome_inpatient_abg_ge45_30d_flag"
        )
        whole_rows = read.execute(
            f"SELECT {columns} FROM read_parquet(?) ORDER BY patient_id",
            [str(whole / "full_data_0000_summary.parquet")],
        ).fetchall()
        split_rows = read.execute(
            f"SELECT {columns} FROM read_parquet(?) ORDER BY patient_id",
            [str(split / "full_data_*_summary.parquet")],
        ).fetchall()
        assert split_rows == whole_rows


def test_bundle_validation_resume_and_tampering(tmp_path, monkeypatch):
    source_root = tmp_path / "source"
    source_root.mkdir()
    source_file = source_root / "source.duckdb"
    with duckdb.connect() as db:
        _source(db, str(source_file))
        parent = tmp_path / "parent"
        parent.mkdir()
        full_path = parent / "encounter_features_full_data.parquet"
        db.execute(f"COPY fixture_index TO '{full_path}' (FORMAT PARQUET)")
        db.execute(
            "CREATE TEMP TABLE after_index AS SELECT * FROM fixture_index "
            "WHERE patient_id='p'"
        )
        after_path = parent / "encounter_features_after_exclusion.parquet"
        db.execute(f"COPY after_index TO '{after_path}' (FORMAT PARQUET)")
    sidecar = source_root / "trinetx_preprocessed_manifest.json"
    sidecar.write_text('{"fixture":true}\n')
    parent_manifest = parent / "manifest.json"
    parent_manifest.write_text(
        json.dumps({"source_manifest_sha256": returns.sha256(sidecar)}) + "\n"
    )

    class SourceResult:
        valid = True
        metadata = object()

    parent_memory_limits = []

    def validate_parent(**kwargs):
        parent_memory_limits.append(
            (kwargs["memory_limit_mib"], kwargs["distinct_count_partitions"])
        )
        return {"pass": True}

    monkeypatch.setattr(returns, "validate_bundle", validate_parent)
    monkeypatch.setattr(return_validation, "validate_bundle", validate_parent)
    monkeypatch.setattr(returns, "validate_cohort_source", lambda *_: SourceResult())
    monkeypatch.setattr(
        return_validation, "validate_cohort_source", lambda *_: SourceResult()
    )
    output = tmp_path / "outcomes"
    work = tmp_path / "work"
    manifest = returns.build_returns(
        database=source_file,
        parent_bundle=parent,
        output_dir=output,
        work_dir=work,
        partitions=1,
    )
    assert manifest["kind"] == "return_outcomes"
    report = return_validation.validate_returns(
        bundle=output,
        parent_bundle=parent,
        database=source_file,
        work_dir=tmp_path / "verify",
    )
    assert report["variants"] == {"FULL_DATA": 2, "AFTER_EXCLUSION": 1}
    assert parent_memory_limits[:2] == [(4096, 32), (4096, 32)]
    manifest_path = output / "manifest.json"
    original_manifest = manifest_path.read_bytes()
    wrong_code = json.loads(original_manifest)
    wrong_code["code_sha256"] = "0" * 64
    manifest_path.write_text(json.dumps(wrong_code) + "\n")
    with pytest.raises(ValueError, match="build code identity"):
        return_validation.validate_returns(
            bundle=output,
            parent_bundle=parent,
            database=source_file,
            work_dir=tmp_path / "wrong-code-verify",
        )
    manifest_path.write_bytes(original_manifest)
    # Rehash a link alteration that is excluded from all confirmed-return
    # summaries. The validator must still detect its disagreement with evidence.
    link_path = output / "full_data_0000_links.parquet"
    link_bytes = link_path.read_bytes()
    manifest_bytes = manifest_path.read_bytes()
    progress_path = output / "progress.json"
    progress_bytes = progress_path.read_bytes()
    changed_links = tmp_path / "changed_links.parquet"
    with duckdb.connect() as tamper:
        tamper.execute(
            "COPY (SELECT * REPLACE "
            "(CASE WHEN temporal_state='same_day_uncertain' "
            "THEN true ELSE abg_gt50 END AS abg_gt50) FROM "
            f"read_parquet({returns.literal(link_path)})) TO "
            f"{returns.literal(changed_links)} (FORMAT PARQUET)"
        )
    changed_links.replace(link_path)
    progress_data = json.loads(progress_bytes)
    link_info = {"sha256": returns.sha256(link_path), "bytes": link_path.stat().st_size}
    progress_data["completed"]["FULL_DATA:0"]["links"] = link_info
    progress_path.write_text(json.dumps(progress_data) + "\n")
    manifest_data = json.loads(manifest_bytes)
    manifest_data["outputs"][link_path.name] = link_info
    manifest_data["outputs"][progress_path.name] = {
        "sha256": returns.sha256(progress_path),
        "bytes": progress_path.stat().st_size,
    }
    manifest_path.write_text(json.dumps(manifest_data) + "\n")
    with pytest.raises(ValueError, match="link evidence"):
        return_validation.validate_returns(
            bundle=output,
            parent_bundle=parent,
            database=source_file,
            work_dir=tmp_path / "tampered-link-verify",
        )
    link_path.write_bytes(link_bytes)
    manifest_path.write_bytes(manifest_bytes)
    progress_path.write_bytes(progress_bytes)
    original_parent = parent_manifest.read_bytes()
    parent_manifest.write_text('{"wrong":"receipt"}\n')
    with pytest.raises(ValueError, match="parent manifest identity"):
        return_validation.validate_returns(
            bundle=output,
            parent_bundle=parent,
            database=source_file,
            work_dir=tmp_path / "wrong-parent",
        )
    parent_manifest.write_bytes(original_parent)
    with pytest.raises(FileExistsError, match="already exists"):
        returns.build_returns(
            database=source_file,
            parent_bundle=parent,
            output_dir=output,
            work_dir=work,
            partitions=1,
        )
    # A resumed run must verify every existing part against the original identity.
    staging = tmp_path / ".outcomes.return-staging"
    output.rename(staging)
    identity_keys = (
        "return_contract_version",
        "parent_manifest_sha256",
        "source_manifest_sha256",
        "source_file_identity",
        "code_sha256",
        "partitions",
    )
    identity = {key: manifest[key] for key in identity_keys}
    (staging / "progress.json").write_text(
        json.dumps(
            {
                "identity": identity,
                "completed": {
                    "FULL_DATA:0": {
                        name: manifest["outputs"][f"full_data_0000_{name}.parquet"]
                        for name in (
                            "episode_source",
                            "episodes",
                            "diagnosis_evidence",
                            "gas_evidence",
                            "links",
                            "summary",
                        )
                    }
                },
            }
        )
        + "\n"
    )
    for path in staging.glob("after_exclusion_0000_*.parquet"):
        path.unlink()
    (staging / "manifest.json").unlink()
    (staging / "data_dictionary.json").unlink()
    with pytest.raises(ValueError, match="Resume identity differs"):
        returns.build_returns(
            database=source_file,
            parent_bundle=parent,
            output_dir=output,
            work_dir=work,
            partitions=2,
            resume=True,
        )
    staging_progress = staging / "progress.json"
    complete_progress = staging_progress.read_bytes()
    incomplete_progress = json.loads(complete_progress)
    del incomplete_progress["completed"]["FULL_DATA:0"]["summary"]
    staging_progress.write_text(json.dumps(incomplete_progress) + "\n")
    with pytest.raises(ValueError, match="part receipt is incomplete"):
        returns.build_returns(
            database=source_file,
            parent_bundle=parent,
            output_dir=output,
            work_dir=work,
            partitions=1,
            resume=True,
        )
    staging_progress.write_bytes(complete_progress)
    returns.build_returns(
        database=source_file,
        parent_bundle=parent,
        output_dir=output,
        work_dir=work,
        partitions=1,
        resume=True,
    )
    path = output / "full_data_0000_summary.parquet"
    original_summary = path.read_bytes()
    with pytest.raises(ValueError, match="artifact identity"):
        with path.open("ab") as stream:
            stream.write(b"tampered")
        return_validation.validate_returns(
            bundle=output,
            parent_bundle=parent,
            database=source_file,
            work_dir=tmp_path / "verify2",
        )
    path.write_bytes(original_summary)
    altered = output / "altered.parquet"
    with duckdb.connect() as db:
        db.execute(
            "COPY (SELECT * REPLACE "
            "(outcome_inpatient_abg_ge45_30d_count + 1 AS "
            "outcome_inpatient_abg_ge45_30d_count) "
            f"FROM read_parquet('{path}')) TO '{altered}' (FORMAT PARQUET)"
        )
    altered.replace(path)
    manifest_path = output / "manifest.json"
    manifest_data = json.loads(manifest_path.read_text())
    progress_path = output / "progress.json"
    progress_data = json.loads(progress_path.read_text())
    summary_info = {"sha256": returns.sha256(path), "bytes": path.stat().st_size}
    progress_data["completed"]["FULL_DATA:0"]["summary"] = summary_info
    progress_path.write_text(json.dumps(progress_data) + "\n")
    manifest_data["outputs"][path.name] = summary_info
    manifest_data["outputs"][progress_path.name] = {
        "sha256": returns.sha256(progress_path),
        "bytes": progress_path.stat().st_size,
    }
    manifest_path.write_text(json.dumps(manifest_data) + "\n")
    with pytest.raises(ValueError, match="metrics"):
        return_validation.validate_returns(
            bundle=output,
            parent_bundle=parent,
            database=source_file,
            work_dir=tmp_path / "verify3",
        )

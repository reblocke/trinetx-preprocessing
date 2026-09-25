#!/usr/bin/env python3
"""Retain a verifiable synthetic source-to-return partition E2E artifact.

This exercises the real return partition builder and independent reconciliation.
The accepted parent/canonical manifest boundary is tested in the private C4 run.
"""

from __future__ import annotations

import argparse
import json
import runpy
import sys
from pathlib import Path

import duckdb

from trinetx_preprocessing.combined_preprocessing.builder import (
    require_safe_output_location,
)
from trinetx_preprocessing.encounters import return_validation_v2 as validator
from trinetx_preprocessing.encounters.builder import code_identity, literal, sha256
from trinetx_preprocessing.encounters.returns_v2 import build_partition_v2
from trinetx_preprocessing.encounters.validation import (
    _prove_component_day_precision,
    _reconcile_element_summary,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/test_encounter_returns.py"
TABLES = validator.TABLES
RECEIPT = "return_v2_partition_e2e.json"


def _inventory(root: Path) -> dict:
    return {
        str(path.relative_to(root)): {
            "bytes": path.stat().st_size,
            "sha256": sha256(path),
        }
        for path in sorted(root.rglob("*"))
        if path.is_file() and path.name != RECEIPT
    }


def _extend_fixture(db: duckdb.DuckDBPyConnection) -> None:
    encounters = [
        ("n", "ni", "IMP", "2024-01-01", "2024-01-02"),
        ("n", "nr1", "IMP", "2024-01-03", "2024-01-04"),
        ("n", "nr2", "IMP", "2024-01-05", "2024-01-06"),
        ("z", "zi", "IMP", "2024-01-01", "2024-01-02"),
        ("z", "zr1", "IMP", "2024-01-03", "2024-01-04"),
        ("z", "zr2", "IMP", "2024-01-05", "2024-01-06"),
        ("a", "ai", "AMB", "2024-01-01", "2024-01-02"),
        ("u", "ui", "OTHER", "2024-01-01", "2024-01-02"),
        ("b", "bi", "IMP", "2024-01-01", "2024-01-02"),
        ("b", "br31", "EMER", "2024-02-02", "2024-02-02"),
        ("c", "ci", "IMP", "2024-01-01", "2024-01-02"),
        ("c", "cr365", "EMER", "2025-01-01", "2025-01-01"),
        ("c", "cr366", "EMER", "2025-01-02", "2025-01-02"),
        ("e", "ei", "IMP", "2024-01-01", "2024-01-02"),
        ("e", "er", "EMER", "2024-01-03", "2024-01-04"),
        ("e", "er", "IMP", "2024-01-05", "2024-01-07"),
        ("d", "di", "EMER", "2024-01-01", "2024-01-02"),
        ("d", "dr", "IMP", "2024-01-03", "2024-01-04"),
        ("m", "mi", "IMP", "2024-01-01", "2024-01-02"),
        ("m", "mr", "IMP", "2024-01-03", None),
        ("t", "ti", "IMP", "2024-01-01", "2024-01-02"),
        ("t", "tr", "IMP", "2024-01-03", "2024-01-04"),
        ("w", "wi", "IMP", "2024-01-01", "2024-01-02"),
        ("w", "wr", "IMP", "2024-01-03", "2024-01-04"),
        ("r", "ri", "IMP", "2024-01-01", "2024-01-02"),
        ("f", "fi", "IMP", "2024-01-01", "2024-01-02"),
        ("f", "fr", "IMP", "2024-01-03", "2024-01-04"),
        ("k", "ki", "IMP", "2024-01-01", "2024-01-02"),
        ("k", "kr", "IMP", "2024-01-03", "2024-01-04"),
    ]
    for row, (patient, encounter, setting, start, end) in enumerate(
        encounters, start=100
    ):
        db.execute(
            "INSERT INTO preprocessed.source_encounter VALUES "
            "(?, ?, ?, 'synthetic', ?, 'fixture', ?, ?, ?, "
            "'date_only','date_only','',NULL)",
            [patient, encounter, f"extra-{row}", row, setting, start, end],
        )
    db.execute(
        "INSERT INTO preprocessed.source_encounter VALUES "
        "('p','r1','duplicate-ed','synthetic',200,'fixture','EMER',"
        "'2024-01-05','2024-01-05','date_only','date_only','',NULL)"
    )
    db.execute(
        "UPDATE preprocessed.source_encounter SET "
        "start_date_derived_by_TriNetX='true' "
        "WHERE patient_id='t' AND encounter_id='tr'"
    )
    db.execute(
        "UPDATE preprocessed.source_encounter SET "
        "start_timestamp_precision=NULL "
        "WHERE patient_id='w' AND encounter_id='wr'"
    )
    for patient, encounter in (
        ("n", "ni"),
        ("z", "zi"),
        ("a", "ai"),
        ("u", "ui"),
        ("b", "bi"),
        ("c", "ci"),
        ("e", "ei"),
        ("d", "di"),
        ("m", "mi"),
        ("t", "ti"),
        ("w", "wi"),
        ("r", "ri"),
        ("f", "fi"),
        ("k", "ki"),
    ):
        db.execute(
            "INSERT INTO fixture_index VALUES (?,?,?)",
            [patient, encounter, f"{patient}-{encounter}"],
        )
    for record, patient, encounter, value in (
        ("normal-abg", "n", "nr1", 40.0),
        ("positive-abg", "z", "zr1", 50.0),
        ("false-abg", "f", "fr", 40.0),
    ):
        db.execute(
            "INSERT INTO preprocessed.source_lab_measurement VALUES "
            "(?,?,?,'synthetic',1,'fixture','LOINC','2019-8',"
            "'2024-01-03','date_only','arterial','','',?,'mmHg')",
            [patient, encounter, record, value],
        )
        db.execute(
            "INSERT INTO preprocessed.element_membership VALUES "
            "(?,'source.arterial_pco2',true)",
            [record],
        )
    db.execute(
        "INSERT INTO preprocessed.source_lab_measurement VALUES "
        "('k','kr','kpa-vbg','synthetic',1,'fixture','LOINC','2021-4',"
        "'2024-01-03','date_only','venous','','',8,'kPa')"
    )
    db.execute(
        "INSERT INTO preprocessed.element_membership VALUES "
        "('kpa-vbg','source.venous_pco2',true)"
    )
    for patient in (
        "n",
        "z",
        "a",
        "u",
        "b",
        "c",
        "e",
        "d",
        "m",
        "t",
        "w",
        "r",
        "f",
        "k",
    ):
        db.execute("INSERT INTO preprocessed.source_patient VALUES (?,NULL)", [patient])
        db.execute(
            "INSERT INTO preprocessed.patient_observability VALUES (?,'2025-01-03')",
            [patient],
        )


def _views(db: duckdb.DuckDBPyConnection, root: Path, partitions: int) -> None:
    for table in TABLES:
        paths = [
            root / f"full_data_{bucket:04d}_{table}.parquet"
            for bucket in range(partitions)
        ]
        path_list = "[" + ",".join(literal(path) for path in paths) + "]"
        db.execute(
            f"CREATE OR REPLACE TEMP VIEW {table} AS "
            f"SELECT * FROM read_parquet({path_list})"
        )


def _check_hand_expected(db: duckdb.DuckDBPyConnection) -> dict:
    columns = (
        "encounter_id,anchor_state,"
        "outcome_acute_union_all_cause_30d_count,"
        "outcome_acute_union_all_cause_30d_flag,"
        "outcome_inpatient_abg_ge45_30d_count,"
        "outcome_inpatient_abg_ge45_30d_flag,"
        "outcome_inpatient_abg_ge45_30d_tested_count,"
        "outcome_inpatient_abg_ge45_30d_untested_count"
    )
    rows = {
        row[0]: row[1:]
        for row in db.execute(f"SELECT {columns} FROM summary").fetchall()
    }
    expected = {
        "ni": ("available", 2, True, 0, None, 1, 1),
        "zi": ("available", 2, True, 1, True, 1, 1),
        "ai": ("not_applicable", None, None, None, None, None, None),
        "ui": ("unknown_index_setting", None, None, None, None, None, None),
        "qi": ("missing_episode_end", None, None, None, None, None, None),
        "ei": ("available", 0, None, 0, None, 0, 0),
        "di": ("available", 1, True, 0, None, 0, 1),
        "mi": ("available", 1, True, 0, None, 0, 1),
        "ti": ("available", 0, None, 0, None, 0, 0),
        "wi": ("available", 0, None, 0, None, 0, 0),
        "ri": ("available", 0, False, 0, None, 0, 0),
        "fi": ("available", 1, True, 0, False, 1, 0),
        "ki": ("available", 1, True, 0, None, 0, 1),
    }
    for key, wanted in expected.items():
        if rows.get(key) != wanted:
            raise AssertionError(
                f"Hand-authored outcome differs for {key}: {rows.get(key)}"
            )
    boundaries = db.execute(
        "SELECT outcome_acute_union_all_cause_30d_count,"
        "outcome_acute_union_all_cause_90d_count,"
        "outcome_acute_union_all_cause_365d_count "
        "FROM summary WHERE encounter_id='bi'"
    ).fetchone()
    if boundaries != (0, 1, 1):
        raise AssertionError(f"Day-31 boundary differs: {boundaries}")
    long_boundary = db.execute(
        "SELECT outcome_acute_union_all_cause_365d_count,"
        "outside_horizon_count FROM summary WHERE encounter_id='ci'"
    ).fetchone()
    if long_boundary != (1, 1):
        raise AssertionError(f"Day-365/366 boundary differs: {long_boundary}")
    p = db.execute(
        "SELECT same_day_uncertain_count,"
        "outcome_inpatient_abg_gt45_30d_count,"
        "outcome_inpatient_gas_abg_ge45_or_vbg_ge50_30d_count "
        "FROM summary WHERE encounter_id='i'"
    ).fetchone()
    if p != (1, 0, 1):
        raise AssertionError(f"Same-day or threshold boundary differs: {p}")
    admission = db.execute(
        "SELECT inpatient_event_term,outcome_inpatient_all_cause_30d_count "
        "FROM summary WHERE encounter_id='di'"
    ).fetchone()
    if admission != ("admission", 1):
        raise AssertionError(f"ED index admission differs: {admission}")
    missing_end = db.execute(
        "SELECT outcome_inpatient_all_cause_30d_count,"
        "outcome_inpatient_abg_ge45_30d_phenotype_unavailable_count "
        "FROM summary WHERE encounter_id='mi'"
    ).fetchone()
    if missing_end != (1, 1):
        raise AssertionError(f"Start-only return differs: {missing_end}")
    converted = db.execute(
        "SELECT outcome_inpatient_gas_abg_gt45_or_vbg_gt50_30d_flag "
        "FROM summary WHERE encounter_id='ki'"
    ).fetchone()
    if converted != (True,):
        raise AssertionError(f"kPa conversion differs: {converted}")
    return {
        "index_cases": len(expected),
        "day31": list(boundaries),
        "day365_366": list(long_boundary),
        "same_day_threshold": list(p),
        "ed_admission": list(admission),
        "start_only": list(missing_end),
        "converted_gas": list(converted),
    }


def _check_independent(db: duckdb.DuckDBPyConnection) -> None:
    db.execute(
        "CREATE OR REPLACE TEMP VIEW parent_index AS "
        "SELECT patient_id,encounter_id,pat_enc_hash AS index_event_id "
        "FROM fixture_index"
    )
    for check in (
        validator._check_partition_source,
        validator._check_partition_episodes,
        validator._check_partition_pairs,
        validator._check_partition_geometry,
        validator._check_partition_evidence,
        validator._check_partition_phenotypes,
        validator._check_summary_states,
    ):
        check(db)
    for days in (30, 90, 365):
        for kind in ("inpatient", "ed_only", "any_ed", "acute_union"):
            validator._check_summary_metric(db, kind=kind, days=days)


def _corruptions(db: duckdb.DuckDBPyConnection, root: Path) -> list[str]:
    paths = {
        table: literal(root / f"full_data_0000_{table}.parquet") for table in TABLES
    }
    links = f"read_parquet({paths['links']})"
    gas = f"read_parquet({paths['gas_evidence']})"
    diagnosis = f"read_parquet({paths['diagnosis_evidence']})"
    summary = f"read_parquet({paths['summary']})"
    source = f"read_parquet({paths['episode_source']})"
    cases = [
        (
            "missing_link",
            "links",
            f"SELECT * FROM {links} WHERE encounter_id<>'r1'",
            validator._check_partition_pairs,
        ),
        (
            "duplicate_link",
            "links",
            f"SELECT * FROM {links} UNION ALL (SELECT * FROM {links} LIMIT 1)",
            validator._check_partition_pairs,
        ),
        (
            "cross_patient_link",
            "links",
            "SELECT * REPLACE (CASE WHEN encounter_id='r1' "
            f"THEN 'wrong' ELSE patient_id END AS patient_id) FROM {links}",
            validator._check_partition_pairs,
        ),
        (
            "omitted_source_episode",
            "episode_source",
            f"SELECT * FROM {source} WHERE encounter_id<>'r1'",
            validator._check_partition_source,
        ),
        (
            "gas_raw_normalization",
            "gas_evidence",
            "SELECT * REPLACE (CASE WHEN source_record_id='g1' THEN 450.0 "
            "ELSE raw_value END AS raw_value, "
            "CASE WHEN source_record_id='g1' THEN 450.0 "
            f"ELSE value_mmhg END AS value_mmhg) FROM {gas}",
            validator._check_partition_evidence,
        ),
        (
            "gas_rejection",
            "gas_evidence",
            "SELECT * REPLACE (CASE WHEN source_record_id='g3' THEN NULL "
            f"ELSE rejection_reason END AS rejection_reason) FROM {gas}",
            validator._check_partition_evidence,
        ),
        (
            "diagnosis_rejection",
            "diagnosis_evidence",
            "SELECT * REPLACE (CASE WHEN source_record_id='dr' "
            "THEN 'other_code' ELSE rejection_reason END "
            f"AS rejection_reason) FROM {diagnosis}",
            validator._check_partition_evidence,
        ),
        (
            "link_phenotype",
            "links",
            "SELECT * REPLACE (CASE WHEN encounter_id='r1' THEN false "
            f"ELSE abg_ge45 END AS abg_ge45) FROM {links}",
            validator._check_partition_phenotypes,
        ),
        (
            "summary_count",
            "summary",
            "SELECT * REPLACE (CASE WHEN encounter_id='ni' THEN 0 "
            "ELSE outcome_acute_union_all_cause_30d_count END "
            f"AS outcome_acute_union_all_cause_30d_count) FROM {summary}",
            lambda connection: validator._check_summary_metric(
                connection, kind="acute_union", days=30
            ),
        ),
        (
            "summary_uncertainty",
            "summary",
            "SELECT * REPLACE (CASE WHEN encounter_id='i' "
            "THEN same_day_uncertain_count+1 "
            "ELSE same_day_uncertain_count END "
            f"AS same_day_uncertain_count) FROM {summary}",
            validator._check_summary_states,
        ),
        (
            "index_anchor",
            "summary",
            "SELECT * REPLACE (CASE WHEN encounter_id='i' "
            "THEN index_episode_end+INTERVAL 1 DAY "
            f"ELSE index_episode_end END AS index_episode_end) FROM {summary}",
            validator._check_partition_geometry,
        ),
    ]
    rejected = []
    for label, table, query, check in cases:
        _views(db, root, 1)
        db.execute(f"CREATE OR REPLACE TEMP VIEW {table} AS {query}")
        try:
            check(db)
        except ValueError:
            rejected.append(label)
        else:
            raise AssertionError(f"Corruption escaped validation: {label}")
    _views(db, root, 1)
    if rejected != [case[0] for case in cases]:
        raise AssertionError(f"Corruption rejection incomplete: {rejected}")
    return rejected


def _precision_proof_cases(db: duckdb.DuckDBPyConnection) -> dict[str, bool]:
    cases = {
        "eight_digit": (
            "SELECT '20240102'::VARCHAR AS date, "
            "TIMESTAMP '2024-01-02' AS event_datetime",
            True,
        ),
        "iso": (
            "SELECT '2024-01-02'::VARCHAR AS date, "
            "TIMESTAMP '2024-01-02' AS event_datetime",
            True,
        ),
        "wrong_day": (
            "SELECT '20240103'::VARCHAR AS date, "
            "TIMESTAMP '2024-01-02' AS event_datetime",
            False,
        ),
        "bad_format": (
            "SELECT '2024/01/02'::VARCHAR AS date, "
            "TIMESTAMP '2024-01-02' AS event_datetime",
            False,
        ),
        "contradictory_time": (
            "SELECT '20240102'::VARCHAR AS date, "
            "TIMESTAMP '2024-01-02 13:00:00' AS event_datetime",
            False,
        ),
        "explicit_wrong": (
            "SELECT '20240102'::VARCHAR AS date, "
            "TIMESTAMP '2024-01-02' AS event_datetime, "
            "'timestamp'::VARCHAR AS event_datetime_precision",
            False,
        ),
    }
    observed = {}
    for name, (query, expected) in cases.items():
        db.execute("CREATE OR REPLACE TEMP VIEW contract_table AS " + query)
        schema = {
            row[0]: row[1].upper()
            for row in db.execute("DESCRIBE contract_table").fetchall()
        }
        try:
            _prove_component_day_precision(
                db,
                artifact=name,
                table="diagnosis_component_evidence",
                schema=schema,
            )
            actual = True
        except ValueError:
            actual = False
        if actual != expected:
            raise AssertionError(f"Precision proof case {name} differs")
        observed[name] = actual
    db.execute("DROP VIEW contract_table")
    return observed


def _parent_summary_count_cases(root: Path) -> dict[str, str | int]:
    """Exercise producer NULL/zero/positive count semantics end to end."""
    part = root / "parent-summary"
    part.mkdir()
    evidence_path = part / "synthetic_encounter_element_evidence.parquet"
    columns = [
        "source_element_hba1c_record_count",
        "source_element_hba1c_latest_raw_value",
        "source_element_hba1c_latest_date",
        "source_element_hba1c_latest_unit",
    ]
    item = {"element_id": "source.hba1c", "columns": columns}
    with duckdb.connect() as db:
        db.execute(
            "CREATE TEMP TABLE features (pat_enc_hash VARCHAR, "
            "encounter_id VARCHAR, "
            "source_element_hba1c_record_count BIGINT, "
            "source_element_hba1c_latest_raw_value DOUBLE, "
            "source_element_hba1c_latest_date TIMESTAMP, "
            "source_element_hba1c_latest_unit VARCHAR)"
        )
        db.execute(
            "INSERT INTO features VALUES "
            "('a','ea',NULL,NULL,NULL,NULL), "
            "('b','eb',0,NULL,NULL,NULL), "
            "('c','ec',2,8,TIMESTAMP '2024-01-02','%')"
        )
        db.execute(
            "CREATE TEMP TABLE retained (index_event_id VARCHAR, "
            "element_id VARCHAR, event_datetime TIMESTAMP, "
            "source_record_id VARCHAR, numeric_value DOUBLE, "
            "units_of_measure VARCHAR, in_baseline_window BOOLEAN, "
            "index_date DATE, source_encounter_id VARCHAR)"
        )
        db.execute(
            "INSERT INTO retained VALUES "
            "('b','source.egfr','2024-01-01','egfr-b',50,'ml/min',true,"
            "'2024-01-02','eb'), "
            "('c','source.hba1c','2024-01-01','hba1c-c1',7,'%',true,"
            "'2024-01-02','ec'), "
            "('c','source.hba1c','2024-01-02','hba1c-c2',8,'%',true,"
            "'2024-01-02','ec')"
        )
        db.execute(f"COPY retained TO {literal(evidence_path)} (FORMAT PARQUET)")

        def reconcile() -> dict:
            return _reconcile_element_summary(
                db,
                root=part,
                stem="synthetic",
                item=item,
                token="hba1c",
                lookback_days=365,
            )

        clean = reconcile()
        if clean["count_mismatches"] != 0:
            raise AssertionError("NULL/zero/positive source summary differs")
        corruptions = (
            ("no_evidence_null_to_zero", "a", "0"),
            ("other_evidence_zero_to_null", "b", "NULL"),
            ("matching_evidence_two_to_one", "c", "1"),
        )
        for name, index, value in corruptions:
            db.execute(
                "UPDATE features SET source_element_hba1c_record_count="
                f"{value} WHERE pat_enc_hash='{index}'"
            )
            try:
                reconcile()
            except ValueError as exc:
                if "count_mismatches=1" not in str(exc):
                    raise AssertionError(f"Wrong rejection for {name}") from exc
            else:
                raise AssertionError(f"Summary corruption passed: {name}")
            original = {"a": "NULL", "b": "0", "c": "2"}[index]
            db.execute(
                "UPDATE features SET source_element_hba1c_record_count="
                f"{original} WHERE pat_enc_hash='{index}'"
            )
    return {"clean_count_mismatches": 0, "corruptions_rejected": len(corruptions)}


def run(root: Path) -> dict:
    require_safe_output_location(root, artifact_label="return E2E artifact")
    root.mkdir(mode=0o700, parents=True, exist_ok=False)
    receipt = {
        "status": "running",
        "scope": (
            "synthetic source-to-return partition; "
            "parent manifest boundary remains separate"
        ),
        "code_sha256": code_identity(),
        "fixture_sha256": sha256(FIXTURE),
        "script_sha256": sha256(Path(__file__)),
        "duckdb_version": duckdb.__version__,
        "python_version": sys.version.split()[0],
        "repeat_command": (
            "python scripts/verify_return_v2_partition_e2e.py "
            "<new-empty-external-directory>"
        ),
        "verify_command": (
            f"python scripts/verify_return_v2_partition_e2e.py {root} --verify"
        ),
    }
    try:
        source = runpy.run_path(str(FIXTURE))["_source"]
        with duckdb.connect() as db:
            source(db, str(root / "source.duckdb"))
            _extend_fixture(db)
            receipt["precision_proof_cases"] = _precision_proof_cases(db)
            receipt["parent_summary_count_cases"] = _parent_summary_count_cases(root)
            single = root / "single"
            single.mkdir()
            build_partition_v2(
                db,
                variant="FULL_DATA",
                bucket=0,
                partitions=1,
                output=single,
            )
            _views(db, single, 1)
            receipt["hand_expected"] = _check_hand_expected(db)
            _check_independent(db)
            receipt["independent_reconciliation"] = "pass"
            receipt["corruptions_rejected"] = _corruptions(db, single)
            for table in TABLES:
                db.execute(f"DROP VIEW {table}")
            triple = root / "triple"
            triple.mkdir()
            for bucket in range(3):
                build_partition_v2(
                    db,
                    variant="FULL_DATA",
                    bucket=bucket,
                    partitions=3,
                    output=triple,
                )
            for table in TABLES:
                single_file = single / f"full_data_0000_{table}.parquet"
                left = f"SELECT * FROM read_parquet({literal(single_file)})"
                paths = [
                    triple / f"full_data_{bucket:04d}_{table}.parquet"
                    for bucket in range(3)
                ]
                right = (
                    "SELECT * FROM read_parquet(["
                    + ",".join(literal(p) for p in paths)
                    + "])"
                )
                validator._assert_equal_multiset(
                    db,
                    left,
                    right,
                    f"one-versus-three {table}",
                )
            receipt["partition_equivalence"] = list(TABLES)
        receipt["status"] = "passed"
    except Exception as exc:
        receipt["status"] = "failed"
        receipt["failure"] = f"{type(exc).__name__}: {exc}"
    receipt["inventory"] = _inventory(root)
    (root / RECEIPT).write_text(json.dumps(receipt, indent=2) + "\n")
    return receipt


def verify(root: Path) -> dict:
    receipt = json.loads((root / RECEIPT).read_text())
    if receipt.get("status") != "passed":
        raise ValueError("E2E receipt did not pass")
    if receipt.get("inventory") != _inventory(root):
        raise ValueError("E2E artifact hashes differ")
    if receipt.get("code_sha256") != code_identity():
        raise ValueError("E2E producer code identity differs")
    if receipt.get("fixture_sha256") != sha256(FIXTURE):
        raise ValueError("E2E fixture changed")
    if receipt.get("script_sha256") != sha256(Path(__file__)):
        raise ValueError("E2E verifier changed")
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifact_dir", type=Path)
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    receipt = verify(args.artifact_dir) if args.verify else run(args.artifact_dir)
    print(
        json.dumps(
            {
                "status": receipt["status"],
                "artifact": str(args.artifact_dir),
                "checks": receipt.get("independent_reconciliation"),
                "failure": receipt.get("failure"),
            },
            indent=2,
        )
    )
    return 0 if receipt["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())

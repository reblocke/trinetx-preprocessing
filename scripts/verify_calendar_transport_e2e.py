#!/usr/bin/env python3
"""Retained raw source transport E2E with an independent selected-row oracle."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
import platform
import runpy
import sys
from dataclasses import asdict
from pathlib import Path

from trinetx_preprocessing.encounters.builder import sha256

ROOT = Path(__file__).resolve().parents[1]


def create_inventory(db, domains):
    from trinetx_preprocessing.combined_preprocessing.cohort_source_contract import (
        COHORT_SOURCE_TABLE_SCHEMAS,
    )

    schema = COHORT_SOURCE_TABLE_SCHEMAS["source_file_inventory"]
    db.execute(
        "CREATE TABLE source_file_inventory ("
        + ",".join(f'"{name}" {kind}' for name, kind in schema)
        + ")"
    )
    for domain in domains:
        db.execute(
            "INSERT INTO source_file_inventory VALUES (?, ?, 1, 1, 'synthetic header')",
            [domain, domain + "/synthetic.csv"],
        )


def check_availability(root):
    import duckdb

    from trinetx_preprocessing.combined_preprocessing import (
        cohort_source_calendar_transport as transport,
    )

    SourceTransportError = transport.SourceTransportError
    iter_calendar_source_records = transport.iter_calendar_source_records
    from trinetx_preprocessing.combined_preprocessing.cohort_source_contract import (
        COHORT_SOURCE_TABLE_SCHEMAS,
    )

    observations = []
    for domain, inventory_domain, table in (
        ("lab", "labs", "source_lab_measurement"),
        ("vital", "vitals", "source_vital_measurement"),
        ("diagnosis", "diagnosis", "source_diagnosis"),
        ("procedure", "procedure", "source_procedure"),
        ("medication", "meds", "source_medication"),
    ):
        with duckdb.connect() as db:
            db.execute("CREATE TABLE keys(patient_id VARCHAR,encounter_id VARCHAR)")
            db.execute(
                "INSERT INTO keys VALUES ('p','history'),('p','index'),('q','index')"
            )
            schema = COHORT_SOURCE_TABLE_SCHEMAS[table]
            db.execute(
                f"CREATE TABLE {table} ("
                + ",".join(f'"{name}" {kind}' for name, kind in schema)
                + ")"
            )
            create_inventory(db, ())

            def fetch():
                return list(
                    iter_calendar_source_records(
                        db,
                        encounter_relation="keys",
                        domain=domain,
                        code_selectors=(("synthetic", "target"),),
                        fetch_size=1,
                    )
                )

            for scenario in (
                "unsupplied",
                "temporary_inventory_shadow",
                "supplied_empty",
                "supplied_no_match",
            ):
                if scenario == "temporary_inventory_shadow":
                    db.execute(
                        "CREATE TEMP VIEW source_file_inventory AS SELECT "
                        f"'{inventory_domain}'::VARCHAR AS domain"
                    )
                elif scenario == "supplied_empty":
                    db.execute("DROP VIEW temp.main.source_file_inventory")
                    db.execute(
                        "INSERT INTO source_file_inventory VALUES "
                        "(?, 'synthetic.csv', 1, 1, 'header')",
                        [inventory_domain],
                    )
                elif scenario == "supplied_no_match":
                    db.execute(
                        f"INSERT INTO {table} "
                        "(patient_id,encounter_id,source_record_id,code_system,code) "
                        "VALUES ('p','index','unrelated','synthetic','other')"
                    )
                expected_state = (
                    "unavailable_domain"
                    if scenario in ("unsupplied", "temporary_inventory_shadow")
                    else "zero_matches"
                )
                result = fetch()
                assert [(r.patient_id, r.encounter_id, r.state) for r in result] == [
                    ("p", "history", expected_state),
                    ("p", "index", expected_state),
                    ("q", "index", expected_state),
                ], (domain, scenario)
                observations.append(
                    {
                        "domain": domain,
                        "scenario": scenario,
                        "expected_state": expected_state,
                        "rows": [asdict(r) for r in result],
                    }
                )
            for scenario in (
                "unreadable_inventory",
                "missing_inventory",
                "missing_inventory_and_table",
            ):
                if scenario == "unreadable_inventory":
                    db.execute(
                        "ALTER TABLE source_file_inventory "
                        "RENAME COLUMN domain TO broken"
                    )
                elif scenario == "missing_inventory":
                    db.execute("DROP TABLE source_file_inventory")
                else:
                    db.execute(f"DROP TABLE {table}")
                try:
                    fetch()
                except SourceTransportError as exc:
                    assert exc.state == "query_failed_or_incomplete"
                else:
                    raise AssertionError(f"{domain}/{scenario} accepted as absence")
                observations.append(
                    {
                        "domain": domain,
                        "scenario": scenario,
                        "expected_error": "SourceTransportError",
                    }
                )
    (root / "availability.json").write_text(json.dumps(observations, indent=2) + "\n")
    return observations


def run(root):
    availability = check_availability(root)
    from trinetx_preprocessing.combined_preprocessing import (
        cohort_source_calendar_transport as transport,
    )

    iter_calendar_source_records = transport.iter_calendar_source_records
    SourceTransportError = transport.SourceTransportError

    with runpy.run_path(str(ROOT / "tests/test_cohort_source_calendar_history.py"))[
        "_source"
    ]() as db:
        create_inventory(db, ("labs", "diagnosis", "procedure"))
        db.execute(
            "CREATE TEMP TABLE keys AS SELECT * FROM selected UNION ALL "
            "SELECT 'p','history'"
        )
        db.execute(
            "UPDATE source_lab_measurement SET "
            "date=NULL,event_datetime=NULL,timestamp_precision='missing',numer"
            "ic_value=NULL WHERE source_record_id='a1c-2'"
        )
        db.execute("INSERT INTO element_membership VALUES ('a1c-2','lab-a1c',TRUE)")
        db.execute(
            "INSERT INTO source_lab_measurement SELECT * REPLACE ('creat' AS "
            "source_record_id,'2160-0' AS code,'2160-0' AS code_raw,'bad' AS "
            "date,'not_numeric' AS lab_result_num_val,NULL AS numeric_value) "
            "FROM source_lab_measurement WHERE source_record_id='a1c-2'"
        )
        rows = list(
            iter_calendar_source_records(
                db,
                encounter_relation="keys",
                domain="lab",
                element_ids=("lab-a1c",),
                code_selectors=(("LOINC", "2160-0"),),
                fetch_size=1,
            )
        )
        assert [(x.patient_id, x.encounter_id, x.state) for x in rows] == [
            ("p", "history", "matched"),
            ("p", "index", "matched_unusable"),
            ("p", "index", "matched_unusable"),
            ("q", "index", "zero_matches"),
        ]
        assert [x.record["source_record_id"] if x.record else None for x in rows] == [
            "a1c-1",
            "a1c-2",
            "creat",
            None,
        ]
        assert rows[1].record["date"] is None
        assert rows[2].record["date"] == "bad"
        assert rows[2].record["lab_result_num_val"] == "not_numeric"
        assert rows[0].record["units_of_measure_raw"] == "%"
        assert rows[0].record["source_file"] == "Labs/lab_results.csv"
        assert rows[1].matched_element_ids == ("lab-a1c",)
        aliases = []
        for relation_name in (
            "selected",
            "SELECTED",
            "keyed",
            "KEYED",
            "enriched",
            "ENRICHED",
            "_transport_keyed",
            "_transport_enriched",
            "_transport_selected",
            "_TRANSPORT_SELECTED",
        ):
            if relation_name.lower() != "selected":
                db.execute(
                    f'CREATE OR REPLACE TABLE "{relation_name}" '
                    "AS SELECT * FROM selected"
                )
            result = list(
                iter_calendar_source_records(
                    db,
                    encounter_relation=relation_name,
                    domain="lab",
                    element_ids=("lab-a1c",),
                    code_selectors=(("LOINC", "2160-0"),),
                    fetch_size=1,
                )
            )
            assert [(r.patient_id, r.encounter_id, r.state) for r in result] == [
                ("p", "index", "matched_unusable"),
                ("p", "index", "matched_unusable"),
                ("q", "index", "zero_matches"),
            ], relation_name
            assert [
                r.record["source_record_id"] if r.record else None for r in result
            ] == [
                "a1c-2",
                "creat",
                None,
            ]
            aliases.append(
                {"relation": relation_name, "rows": [asdict(r) for r in result]}
            )
        (root / "relation-aliases.json").write_text(
            json.dumps(aliases, default=str, indent=2) + "\n"
        )
        unavailable = list(
            iter_calendar_source_records(
                db,
                encounter_relation="keys",
                domain="vital",
                code_selectors=(("LOINC", "39156-5"),),
            )
        )
        assert len(unavailable) == 3 and all(
            x.state == "unavailable_domain" for x in unavailable
        )
        # A broken matched-record query is an explicit failure, not absence.
        db.execute("ALTER TABLE element_membership RENAME COLUMN element_id TO broken")
        try:
            list(
                iter_calendar_source_records(
                    db,
                    encounter_relation="keys",
                    domain="lab",
                    element_ids=("lab-a1c",),
                )
            )
        except SourceTransportError as exc:
            assert exc.state == "query_failed_or_incomplete"
        else:
            raise AssertionError("Failed query was reported as zero matches")
        db.execute("ALTER TABLE element_membership RENAME COLUMN broken TO element_id")
        db.execute("ALTER TABLE source_lab_measurement DROP COLUMN code_system")
        unavailable_field = list(
            iter_calendar_source_records(
                db,
                encounter_relation="keys",
                domain="lab",
                code_selectors=(("LOINC", "2160-0"),),
            )
        )
        assert len(unavailable_field) == 3 and all(
            x.state == "unavailable_field" for x in unavailable_field
        )
        assert all("code_system" in x.missing_fields for x in unavailable_field)
        db.execute("INSERT INTO keys VALUES ('p','index')")
        try:
            list(
                iter_calendar_source_records(
                    db,
                    encounter_relation="keys",
                    domain="lab",
                    element_ids=("lab-a1c",),
                )
            )
        except ValueError:
            pass
        else:
            raise AssertionError("Duplicate requested key accepted")
        (root / "transport.json").write_text(
            json.dumps([asdict(x) for x in rows], default=str, indent=2) + "\n"
        )
    return {
        "status": "passed",
        "exit_status": 0,
        "rows_checked": len(rows),
        "failure_type": SourceTransportError.state,
        "availability_cases": len(availability),
        "relation_alias_cases": len(aliases),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("artifact_dir", type=Path)
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--receipt-sha256")
    parser.add_argument("--require-installed", action="store_true")
    args = parser.parse_args()
    if args.verify:
        receipt_path = args.artifact_dir / "receipt.json"
        if not args.receipt_sha256 or sha256(receipt_path) != args.receipt_sha256:
            raise ValueError("E2E receipt differs from trusted digest")
        saved = json.loads(receipt_path.read_text())
        actual = {
            str(p.relative_to(args.artifact_dir)): sha256(p)
            for p in args.artifact_dir.rglob("*")
            if p.is_file() and p != receipt_path
        }
        if actual != saved["inventory"] or saved["status"] != "passed":
            raise ValueError("E2E artifacts or status differ")
        if saved["source_before"] != saved["source_after"]:
            raise ValueError("Source changed during E2E")
        print("Retained E2E receipt and artifact hashes verified")
        return 0
    import trinetx_preprocessing

    package = Path(trinetx_preprocessing.__file__).resolve().parent
    installed = package.is_relative_to(Path(sys.prefix))
    if args.require_installed and (not installed or "PYTHONPATH" in os.environ):
        parser.error("Require noneditable upstream package with PYTHONPATH removed")
    try:
        args.artifact_dir.mkdir(parents=True, exist_ok=False)
    except OSError as exc:
        parser.error(f"Choose a fresh artifact directory: {exc}")
    source_paths = sorted(package.rglob("*.py"))
    source_before = {
        "src/" + str(p.relative_to(package.parent)): sha256(p) for p in source_paths
    }
    result = {"status": "failed", "exit_status": 1}
    try:
        result.update(run(args.artifact_dir))
    except Exception as exc:
        result["failure"] = f"{type(exc).__name__}: {exc}"
    result.update(
        python=platform.python_version(),
        runner_sha256=sha256(Path(__file__)),
        fixture_sha256=sha256(ROOT / "tests/test_cohort_source_calendar_history.py"),
        command=sys.argv,
        installed_noneditable=installed,
        packages={
            name: importlib.metadata.version(name)
            for name in (
                "trinetx-preprocessing",
                "duckdb",
                "pyarrow",
                "pandas",
                "numpy",
            )
        },
    )
    (args.artifact_dir / "runner.py").write_bytes(Path(__file__).read_bytes())
    result["source_before"] = source_before
    result["source_after"] = {
        "src/" + str(p.relative_to(package.parent)): sha256(p) for p in source_paths
    }
    if result["source_before"] != result["source_after"]:
        result.update(
            status="failed", exit_status=1, failure="Source changed during E2E"
        )
    result["inventory"] = {
        str(p.relative_to(args.artifact_dir)): sha256(p)
        for p in args.artifact_dir.rglob("*")
        if p.is_file()
    }
    (args.artifact_dir / "receipt.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    return result["exit_status"]


if __name__ == "__main__":
    raise SystemExit(main())

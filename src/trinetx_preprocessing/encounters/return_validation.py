"""Independent artifact and key reconciliation for return outcomes."""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import duckdb

from ..combined_preprocessing.builder import require_safe_output_location
from ..combined_preprocessing.cohort_source import validate_cohort_source
from ..combined_preprocessing.database import COMBINED_MANIFEST_FILENAME
from .builder import VARIANTS, code_identity, literal, sha256
from .compatibility import file_identity, no_symlinks
from .returns import (
    CRITERIA,
    HORIZONS,
    KINDS,
    RETURN_CONTRACT_VERSION,
    RETURN_PARENT_VALIDATION_DISTINCT_PARTITIONS,
    RETURN_PARENT_VALIDATION_MEMORY_MIB,
)
from .validation import validate_bundle


def _parquet_files(
    bundle: Path, variant: str, table: str, partitions: int
) -> list[Path]:
    return [
        bundle / f"{variant.lower()}_{bucket:04d}_{table}.parquet"
        for bucket in range(partitions)
    ]


def _file_list(files: list[Path]) -> str:
    return "[" + ",".join(literal(path) for path in files) + "]"


def _assert_zero(db: duckdb.DuckDBPyConnection, query: str, label: str) -> None:
    result = db.execute(query).fetchone()[0]
    if result:
        raise ValueError(f"Return reconciliation failed: {label} ({result})")


def _summary_reconciliation_query(kind: str, days: int) -> str:
    """Independently recompute every count, first time, and three-state flag."""
    predicate = {
        "inpatient": "l.has_inpatient",
        "ed_only": "l.ed_only",
        "any_ed": "l.has_ed",
        "acute_union": "(l.has_ed OR l.has_inpatient)",
    }[kind]
    base = (
        "l.temporal_state='confirmed' "
        f"AND {predicate} AND l.return_start <= "
        f"s.index_episode_end + INTERVAL {days} DAY"
    )
    aggregates = []
    mismatches = []
    for gas_kind, condition in (
        ("abg", "l.abg_tested"),
        ("vbg", "l.vbg_tested"),
        ("any_gas", "(l.abg_tested OR l.vbg_tested)"),
    ):
        column = f"outcome_{kind}_{gas_kind}_tested_{days}d_count"
        aggregates.append(
            f"count(l.return_episode_id) FILTER (WHERE {base} AND {condition}) "
            f"AS {gas_kind}_tested"
        )
        mismatches.append(f"s.{column} IS DISTINCT FROM e.{gas_kind}_tested")
    for criterion in CRITERIA:
        name = f"outcome_{kind}_{criterion}_{days}d"
        condition = base if criterion == "all_cause" else f"{base} AND l.{criterion}"
        aggregates.extend(
            (
                f"count(l.return_episode_id) FILTER (WHERE {condition}) "
                f"AS {criterion}_count",
                f"min(l.return_start::DATE) FILTER (WHERE {condition}) "
                f"AS {criterion}_date",
                f"min(l.return_start) FILTER (WHERE {condition} "
                f"AND l.return_start_precision='timestamp') "
                f"AS {criterion}_timestamp",
            )
        )
        mismatches.extend(
            (
                f"s.{name}_count IS DISTINCT FROM e.{criterion}_count",
                f"s.{name}_first_date IS DISTINCT FROM e.{criterion}_date",
                f"s.{name}_first_timestamp IS DISTINCT FROM e.{criterion}_timestamp",
            )
        )
        if criterion in ("all_cause", "icd_hypercapnia"):
            expected_flag = f"(e.{criterion}_count>0)"
        else:
            tested = "any_gas_tested"
            if criterion.startswith("abg_"):
                tested = "abg_tested"
            elif criterion.startswith("vbg_"):
                tested = "vbg_tested"
            expected_flag = (
                f"CASE WHEN e.{criterion}_count>0 THEN true "
                f"WHEN e.{tested}>0 THEN false ELSE NULL END"
            )
        mismatches.append(
            f"s.{name}_flag IS DISTINCT FROM "
            "(CASE WHEN e.anchor_state='available' THEN "
            f"{expected_flag} ELSE NULL END)"
        )
    return (
        "WITH expected AS (SELECT s.index_event_id, s.anchor_state, "
        + ", ".join(aggregates)
        + " FROM summary s LEFT JOIN links l "
        "ON s.index_event_id=l.index_event_id "
        "GROUP BY s.index_event_id,s.anchor_state,s.index_episode_end) "
        "SELECT count(*) FROM summary s JOIN expected e "
        "ON s.index_event_id=e.index_event_id WHERE " + " OR ".join(mismatches)
    )


def _link_evidence_reconciliation_query() -> str:
    """Derive every link outcome from the retained episode evidence."""
    gas_checks = {
        "abg_tested": "gas_kind='abg' AND rejection_reason IS NULL",
        "vbg_tested": "gas_kind='vbg' AND rejection_reason IS NULL",
    }
    for kind in ("abg", "vbg"):
        for name, operator, threshold in (
            ("gt45", ">", 45),
            ("gt50", ">", 50),
            ("ge45", ">=", 45),
            ("ge50", ">=", 50),
        ):
            gas_checks[f"{kind}_{name}"] = (
                f"gas_kind='{kind}' AND rejection_reason IS NULL "
                f"AND value_mmhg{operator}{threshold}"
            )
    gas_columns = ", ".join(
        f"bool_or({condition}) AS {name}" for name, condition in gas_checks.items()
    )
    direct = ("icd_hypercapnia", *gas_checks)
    mismatches = [f"l.{name} IS DISTINCT FROM e.{name}" for name in direct]
    for name, left, right in (
        ("any_gas_gt45", "abg_gt45", "vbg_gt45"),
        ("any_gas_gt50", "abg_gt50", "vbg_gt50"),
        ("any_gas_ge45", "abg_ge45", "vbg_ge45"),
        ("any_gas_ge50", "abg_ge50", "vbg_ge50"),
    ):
        mismatches.append(f"l.{name} IS DISTINCT FROM (e.{left} OR e.{right})")
    mismatches.append(
        "l.any_hypercapnia IS DISTINCT FROM "
        "(e.icd_hypercapnia OR e.abg_ge45 OR e.vbg_ge50)"
    )
    return (
        "WITH diagnoses AS (SELECT episode_id, "
        "bool_or(rejection_reason IS NULL) AS valid "
        "FROM diagnosis_evidence GROUP BY episode_id), "
        f"gases AS (SELECT episode_id, {gas_columns} "
        "FROM gas_evidence GROUP BY episode_id), "
        "expected AS (SELECT r.return_episode_id, "
        "coalesce(d.valid,false) AS icd_hypercapnia, "
        + ", ".join(f"g.{name}" for name in gas_checks)
        + " FROM (SELECT DISTINCT return_episode_id FROM links) r "
        "LEFT JOIN diagnoses d ON r.return_episode_id=d.episode_id "
        "LEFT JOIN gases g ON r.return_episode_id=g.episode_id) "
        "SELECT count(*) FROM links l JOIN expected e "
        "USING (return_episode_id) WHERE " + " OR ".join(mismatches)
    )


def _link_geometry_reconciliation_query() -> str:
    """Reconstruct index/return links from the independent episode tables."""
    temporal_state = (
        "CASE WHEN e.episode_start IS NULL THEN 'missing_return_start' "
        "WHEN e.has_derived_start THEN 'derived_return_start' "
        "WHEN e.distinct_starts>1 AND NOT (e.has_ed AND e.has_inpatient) "
        "THEN 'conflicting_return_start' "
        "WHEN e.start_precision NOT IN ('date_only','timestamp') "
        "THEN 'unknown_return_precision' "
        "WHEN e.episode_end IS NOT NULL "
        "AND e.episode_end<e.episode_start "
        "THEN 'invalid_return_episode_order' "
        "WHEN e.episode_start::DATE=s.index_episode_end::DATE "
        "AND (e.start_precision='date_only' "
        "OR s.index_end_precision='date_only') "
        "THEN 'same_day_uncertain' "
        "WHEN e.episode_start<=s.index_episode_end THEN 'overlap_or_prior' "
        "WHEN e.episode_start>s.index_episode_end+INTERVAL 365 DAY "
        "THEN 'outside_horizon' ELSE 'confirmed' END"
    )
    comparisons = (
        ("index_patient_id", "s.patient_id"),
        ("index_encounter_id", "s.encounter_id"),
        ("index_episode_id", "s.index_episode_id"),
        ("index_episode_end", "s.index_episode_end"),
        ("index_end_precision", "s.index_end_precision"),
        ("index_inpatient", "s.index_inpatient"),
        ("index_ed", "s.index_ed"),
        ("patient_id", "e.patient_id"),
        ("encounter_id", "e.encounter_id"),
        ("return_start", "e.episode_start"),
        ("return_start_precision", "e.start_precision"),
        ("return_end", "e.episode_end"),
        ("return_end_precision", "e.end_precision"),
        ("has_inpatient", "e.has_inpatient"),
        ("has_ed", "e.has_ed"),
        ("source_record_count", "e.source_record_count"),
        ("temporal_state", temporal_state),
        ("evidenced_ed_inpatient", "(e.has_ed AND e.has_inpatient)"),
        ("ed_only", "(e.has_ed AND NOT e.has_inpatient)"),
        (
            "admission_after_ed_index",
            "(e.has_inpatient AND s.index_ed AND NOT s.index_inpatient)",
        ),
        (
            "readmission_after_inpatient",
            "(e.has_inpatient AND s.index_inpatient)",
        ),
    )
    mismatches = [
        f"l.{column} IS DISTINCT FROM {expected}" for column, expected in comparisons
    ]
    mismatches.extend(
        (
            "s.anchor_state<>'available'",
            "l.return_episode_id=s.index_episode_id",
            "NOT (e.has_ed OR e.has_inpatient)",
            "NOT (e.episode_start IS NULL OR "
            "(e.episode_start::DATE>=s.index_episode_end::DATE AND "
            "e.episode_start::DATE<=(s.index_episode_end+INTERVAL 365 DAY)::DATE) "
            "OR (e.episode_start::DATE<s.index_episode_end::DATE "
            "AND e.episode_end>=s.index_episode_end))",
        )
    )
    return (
        "SELECT count(*) FROM links l JOIN summary s "
        "ON l.index_event_id=s.index_event_id JOIN episodes e "
        "ON l.return_episode_id=e.episode_id WHERE " + " OR ".join(mismatches)
    )


def _episode_mapping_reconciliation_query() -> str:
    """Rebuild episode attributes from every retained source encounter row."""
    columns = (
        "patient_id",
        "encounter_id",
        "episode_start",
        "episode_end",
        "start_precision",
        "end_precision",
        "has_inpatient",
        "has_ed",
        "distinct_starts",
        "distinct_ends",
        "has_derived_start",
        "has_derived_end",
        "source_record_count",
    )
    mismatches = [f"e.{column} IS DISTINCT FROM m.{column}" for column in columns]
    mismatches.extend(
        (
            "e.episode_id IS NULL",
            "m.episode_id IS NULL",
            "m.composite_key_count<>1",
            "e.episode_id IS DISTINCT FROM "
            "sha256(to_json([e.patient_id,e.encounter_id]))",
        )
    )
    return (
        "WITH mapped AS (SELECT episode_id, "
        "min(patient_id) AS patient_id, "
        "min(encounter_id) AS encounter_id, "
        "count(DISTINCT (patient_id,encounter_id)) AS composite_key_count, "
        "min(start_datetime) AS episode_start, "
        "CASE WHEN count(*) FILTER (WHERE end_datetime IS NULL)=0 "
        "THEN max(end_datetime) END AS episode_end, "
        "CASE WHEN count(DISTINCT start_timestamp_precision)=1 "
        "THEN min(start_timestamp_precision) END AS start_precision, "
        "CASE WHEN count(DISTINCT end_timestamp_precision)=1 "
        "THEN min(end_timestamp_precision) END AS end_precision, "
        "bool_or(upper(trim(source_type)) IN "
        "('IMP','INPAT','INPATIENT')) AS has_inpatient, "
        "bool_or(upper(trim(source_type)) IN "
        "('EMER','ED','EMERGENCY')) AS has_ed, "
        "count(DISTINCT start_datetime) AS distinct_starts, "
        "count(DISTINCT end_datetime) AS distinct_ends, "
        "bool_or(lower(trim(coalesce(start_date_derived_by_TriNetX,''))) "
        "IN ('1','true','yes','y')) AS has_derived_start, "
        "bool_or(lower(trim(coalesce(end_date_derived_by_TriNetX,''))) "
        "IN ('1','true','yes','y')) AS has_derived_end, "
        "count(*) AS source_record_count FROM episode_source GROUP BY 1) "
        "SELECT count(*) FROM episodes e FULL OUTER JOIN mapped m "
        "USING (episode_id) WHERE " + " OR ".join(mismatches)
    )


def validate_returns(
    *,
    bundle: Path,
    parent_bundle: Path,
    database: Path,
    work_dir: Path,
) -> dict:
    """Recompute output identity, keys, links and summary counts from artifacts."""
    bundle, parent_bundle = no_symlinks(bundle), no_symlinks(parent_bundle)
    database, work_dir = no_symlinks(database), no_symlinks(work_dir)
    require_safe_output_location(work_dir, artifact_label="return validation work")
    if any(
        work_dir.is_relative_to(input_path) or input_path.is_relative_to(work_dir)
        for input_path in (bundle, parent_bundle, database.parent)
    ):
        raise ValueError("Return validation work overlaps immutable inputs")
    if not bundle.is_dir() or not (bundle / "manifest.json").is_file():
        raise ValueError("Return bundle or manifest is missing")
    manifest_path = bundle / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    if manifest.get("schema_version") == "2.0":
        from .return_validation_v2 import validate_returns_v2

        return validate_returns_v2(
            bundle=bundle,
            parent_bundle=parent_bundle,
            database=database,
            work_dir=work_dir,
        )
    if (
        manifest.get("kind") != "return_outcomes"
        or manifest.get("status") != "complete"
        or manifest.get("schema_version") != RETURN_CONTRACT_VERSION
        or manifest.get("return_contract_version") != RETURN_CONTRACT_VERSION
        or manifest.get("variants") != list(VARIANTS)
        or manifest.get("horizons_days") != list(HORIZONS)
    ):
        raise ValueError("Return manifest contract differs")
    if manifest.get("code_sha256") != code_identity():
        raise ValueError("Return build code identity differs")
    partitions = manifest.get("partitions")
    if not isinstance(partitions, int) or not 1 <= partitions <= 1024:
        raise ValueError("Return partition count is invalid")
    if manifest.get("parent_manifest_sha256") != sha256(
        parent_bundle / "manifest.json"
    ):
        raise ValueError("Return parent manifest identity differs")
    parent_manifest = json.loads((parent_bundle / "manifest.json").read_text())
    if parent_manifest.get("source_manifest_sha256") != manifest.get(
        "source_manifest_sha256"
    ):
        raise ValueError("Return parent and canonical source differ")
    if manifest.get("source_manifest_sha256") != sha256(
        database.parent / COMBINED_MANIFEST_FILENAME
    ):
        raise ValueError("Return source manifest identity differs")
    if manifest.get("source_file_identity") != list(file_identity(database)):
        raise ValueError("Return source file identity differs")
    parent_report = validate_bundle(
        bundle=parent_bundle,
        work_dir=work_dir / f"parent-validation-{uuid.uuid4().hex}",
        memory_limit_mib=RETURN_PARENT_VALIDATION_MEMORY_MIB,
        distinct_count_partitions=RETURN_PARENT_VALIDATION_DISTINCT_PARTITIONS,
    )
    if not parent_report["pass"]:
        raise ValueError("Return parent bundle is invalid")
    source_report = validate_cohort_source(database)
    if not source_report.valid:
        raise ValueError("Return canonical source is invalid")
    expected = {"data_dictionary.json", "progress.json"}
    for variant in VARIANTS:
        for table in (
            "episode_source",
            "episodes",
            "diagnosis_evidence",
            "gas_evidence",
            "links",
            "summary",
        ):
            expected.update(
                p.name for p in _parquet_files(bundle, variant, table, partitions)
            )
    if set(manifest.get("outputs", {})) != expected:
        raise ValueError("Return artifact inventory differs")
    if {
        p.name for p in bundle.iterdir() if p.is_file() and not p.name.startswith("._")
    } != expected | {"manifest.json"}:
        raise ValueError("Return bundle contains missing or untracked files")
    for name, info in manifest["outputs"].items():
        path = bundle / name
        if (
            not path.is_file()
            or path.is_symlink()
            or sha256(path) != info.get("sha256")
            or path.stat().st_size != info.get("bytes")
        ):
            raise ValueError(f"Return artifact identity differs: {name}")
    progress = json.loads((bundle / "progress.json").read_text())
    identity_fields = (
        "return_contract_version",
        "parent_manifest_sha256",
        "source_manifest_sha256",
        "source_file_identity",
        "code_sha256",
        "partitions",
    )
    if progress.get("identity") != {key: manifest[key] for key in identity_fields}:
        raise ValueError("Return progress identity differs")
    expected_parts = {
        f"{variant}:{bucket}" for variant in VARIANTS for bucket in range(partitions)
    }
    if set(progress.get("completed", {})) != expected_parts:
        raise ValueError("Return progress is incomplete")
    expected_tables = {
        "episode_source",
        "episodes",
        "diagnosis_evidence",
        "gas_evidence",
        "links",
        "summary",
    }
    for part_key, tables in progress["completed"].items():
        if set(tables) != expected_tables:
            raise ValueError("Return part receipt is incomplete")
        variant, bucket = part_key.split(":")
        for table, info in tables.items():
            name = f"{variant.lower()}_{int(bucket):04d}_{table}.parquet"
            if manifest["outputs"].get(name) != info:
                raise ValueError("Return part receipt differs from artifact inventory")
    dictionary = json.loads((bundle / "data_dictionary.json").read_text())
    work_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    with duckdb.connect() as db:
        db.execute("SET threads=1")
        db.execute("SET memory_limit='1024MiB'")
        spill = work_dir / "spill"
        spill.mkdir(mode=0o700, parents=True, exist_ok=True)
        db.execute("SET temp_directory=?", [str(spill)])
        counts = {}
        for variant in VARIANTS:
            parent_file = (
                parent_bundle / f"encounter_features_{variant.lower()}.parquet"
            )
            for table in (
                "episode_source",
                "episodes",
                "diagnosis_evidence",
                "gas_evidence",
                "links",
                "summary",
            ):
                files = _parquet_files(bundle, variant, table, partitions)
                db.execute(
                    f"CREATE OR REPLACE VIEW {table} AS "
                    f"SELECT * FROM read_parquet({_file_list(files)})"
                )
                actual = [
                    {"column": column, "duckdb_type": kind, "role": "outcome"}
                    for column, kind, *_ in db.execute(
                        f"DESCRIBE SELECT * FROM {table}"
                    ).fetchall()
                ]
                if dictionary.get(table) != actual:
                    raise ValueError(f"Return {table} typed dictionary differs")
            db.execute(
                f"CREATE OR REPLACE VIEW parent_index AS SELECT "
                f"patient_id::VARCHAR AS patient_id, "
                f"encounter_id::VARCHAR AS encounter_id, "
                f"pat_enc_hash::VARCHAR AS index_event_id "
                f"FROM read_parquet({literal(parent_file)})"
            )
            _assert_zero(
                db,
                "SELECT count(*) FROM (SELECT patient_id,encounter_id "
                "FROM summary GROUP BY 1,2 HAVING count(*)<>1)",
                f"{variant} duplicate summary keys",
            )
            _assert_zero(
                db,
                "SELECT count(*) FROM ((SELECT patient_id,encounter_id,index_event_id "
                "FROM parent_index EXCEPT ALL "
                "SELECT patient_id,encounter_id,index_event_id "
                "FROM summary) UNION ALL "
                "(SELECT patient_id,encounter_id,index_event_id "
                "FROM summary EXCEPT ALL SELECT patient_id,encounter_id,index_event_id "
                "FROM parent_index))",
                f"{variant} parent-summary key mismatch",
            )
            _assert_zero(
                db,
                _episode_mapping_reconciliation_query(),
                f"{variant} episode/source mapping",
            )
            _assert_zero(
                db,
                "SELECT count(*) FROM (SELECT source_record_id FROM episode_source "
                "GROUP BY 1 HAVING count(*)<>1 OR source_record_id IS NULL)",
                f"{variant} duplicate source encounter records",
            )
            _assert_zero(
                db,
                "SELECT count(*) FROM (SELECT index_event_id,return_episode_id "
                "FROM links GROUP BY 1,2 HAVING count(*)<>1)",
                f"{variant} duplicate return links",
            )
            _assert_zero(
                db,
                "SELECT count(*) FROM links l LEFT JOIN summary s "
                "ON l.index_event_id=s.index_event_id "
                "WHERE s.index_event_id IS NULL OR l.index_patient_id<>s.patient_id",
                f"{variant} orphan or cross-patient link",
            )
            _assert_zero(
                db,
                "SELECT count(*) FROM links l LEFT JOIN episodes e "
                "ON l.return_episode_id=e.episode_id "
                "WHERE e.episode_id IS NULL OR l.patient_id<>e.patient_id "
                "OR l.encounter_id<>e.encounter_id",
                f"{variant} unmapped return episode",
            )
            for evidence in ("diagnosis_evidence", "gas_evidence"):
                _assert_zero(
                    db,
                    f"SELECT count(*) FROM {evidence} a LEFT JOIN episodes e "
                    "ON a.episode_id=e.episode_id LEFT JOIN "
                    "(SELECT DISTINCT return_episode_id FROM links) r "
                    "ON a.episode_id=r.return_episode_id "
                    "WHERE e.episode_id IS NULL OR r.return_episode_id IS NULL "
                    "OR a.patient_id IS DISTINCT FROM e.patient_id "
                    "OR a.encounter_id IS DISTINCT FROM e.encounter_id",
                    f"{variant} {evidence} episode mapping",
                )
            _assert_zero(
                db,
                _link_evidence_reconciliation_query(),
                f"{variant} link evidence",
            )
            _assert_zero(
                db,
                _link_geometry_reconciliation_query(),
                f"{variant} link geometry",
            )
            _assert_zero(
                db,
                "WITH states AS (SELECT index_event_id, "
                "count(*) FILTER (WHERE temporal_state='same_day_uncertain') "
                "AS same_day, "
                "count(*) FILTER (WHERE temporal_state='overlap_or_prior') "
                "AS overlap, "
                "count(*) FILTER (WHERE temporal_state='missing_return_start') "
                "AS undated, "
                "count(*) FILTER (WHERE temporal_state='derived_return_start') "
                "AS derived_start, "
                "count(*) FILTER (WHERE "
                "temporal_state='invalid_return_episode_order') "
                "AS invalid_order FROM links GROUP BY 1) "
                "SELECT count(*) FROM summary s LEFT JOIN states t "
                "ON s.index_event_id=t.index_event_id WHERE "
                "s.same_day_uncertain_count<>coalesce(t.same_day,0) OR "
                "s.overlap_or_prior_count<>coalesce(t.overlap,0) OR "
                "s.undated_return_count<>coalesce(t.undated,0) OR "
                "s.derived_return_start_count<>coalesce(t.derived_start,0) OR "
                "s.invalid_return_episode_order_count<>coalesce(t.invalid_order,0)",
                f"{variant} temporal uncertainty",
            )
            for days in HORIZONS:
                for kind in KINDS:
                    _assert_zero(
                        db,
                        _summary_reconciliation_query(kind, days),
                        f"{variant} {kind} {days}d metrics",
                    )
            counts[variant] = db.execute("SELECT count(*) FROM summary").fetchone()[0]
            for table in (
                "episode_source",
                "episodes",
                "diagnosis_evidence",
                "gas_evidence",
                "links",
                "summary",
                "parent_index",
            ):
                db.execute(f"DROP VIEW {table}")
    return {
        "pass": True,
        "validation_contract_version": RETURN_CONTRACT_VERSION,
        "bundle_manifest_sha256": sha256(manifest_path),
        "parent_manifest_sha256": manifest["parent_manifest_sha256"],
        "source_manifest_sha256": manifest["source_manifest_sha256"],
        "variants": counts,
        "limitations": manifest["limitations"],
    }

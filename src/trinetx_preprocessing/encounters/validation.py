"""Validate the full encounter artifact contract without clinical interpretation."""

from __future__ import annotations

import hashlib
import json

import duckdb

from ..combined_preprocessing.builder import require_safe_output_location
from .builder import EVIDENCE_TABLES, SCHEMA_VERSION, VARIANTS, code_identity, literal
from .compatibility import digest, no_symlinks

VALIDATION_CONTRACT_VERSION = "1.0"

# Required columns are intentionally domain-specific. Nullable values such as
# event dates and units remain representable; the schema itself may not vanish.
EVIDENCE_CONTRACTS = {
    "encounter_element_evidence": {
        "index_event_id",
        "index_date",
        "element_id",
        "source_record_id",
        "source_file",
        "source_row_number",
        "patient_id",
        "source_encounter_id",
        "event_datetime",
        "timestamp_precision",
        "numeric_value",
        "units_of_measure",
        "code_system_raw",
        "code_raw",
        "specimen",
        "specimen_id",
        "panel_id",
        "order_status",
        "status",
        "route",
        "brand",
        "strength",
        "start_date",
        "end_date",
        "lab_result_text_val",
        "text_value",
        "domain",
        "in_baseline_window",
    },
    "diagnosis_component_evidence": {
        "index_event_id",
        "index_date",
        "concept_set_id",
        "patient_id",
        "encounter_id",
        "code_system",
        "code",
        "source_record_hash",
        "source_file",
        "event_datetime",
        "event_datetime_precision",
        "days_before_index",
        "principal_diagnosis_indicator",
        "admitting_diagnosis",
        "reason_for_visit",
    },
    "procedure_component_evidence": {
        "index_event_id",
        "index_date",
        "concept_set_id",
        "patient_id",
        "encounter_id",
        "code_system",
        "code",
        "source_record_hash",
        "source_file",
        "event_datetime",
        "event_datetime_precision",
        "days_before_index",
        "principal_procedure_indicator",
    },
    "component_lab_evidence": {
        "index_event_id",
        "index_date",
        "concept_set_id",
        "patient_id",
        "encounter_id",
        "code_system",
        "code",
        "source_record_hash",
        "source_file",
        "event_datetime",
        "event_datetime_precision",
        "days_before_index",
        "lab_result_num_val",
        "lab_result_text_val",
        "units_of_measure",
        "specimen",
        "specimen_id",
        "panel_id",
        "raw_numeric_value",
        "normalized_numeric_value",
        "normalized_unit",
    },
    "component_bp_evidence": {
        "index_event_id",
        "index_date",
        "concept_set_id",
        "patient_id",
        "encounter_id",
        "code_system",
        "code",
        "source_record_hash",
        "source_file",
        "event_datetime",
        "text_value",
        "units_of_measure",
        "raw_numeric_value",
        "normalized_numeric_value",
        "encounter_type",
    },
    "medication_component_evidence": {
        "index_event_id",
        "index_date",
        "concept_set_id",
        "patient_id",
        "encounter_id",
        "code_system",
        "code",
        "source_record_hash",
        "source_file",
        "event_datetime",
        "event_datetime_precision",
        "days_before_index",
        "start_date",
        "end_date",
        "order_status",
        "status",
        "route",
        "brand",
        "strength",
        "ordered_pre_index",
        "active_at_index",
        "ordered_post_index",
    },
}
COLUMN_TYPES = {
    "index_event_id": {"VARCHAR"},
    "patient_id": {"VARCHAR"},
    "encounter_id": {"VARCHAR"},
    "source_encounter_id": {"VARCHAR"},
    "element_id": {"VARCHAR"},
    "concept_set_id": {"VARCHAR"},
    "source_record_id": {"VARCHAR"},
    "source_record_hash": {"VARCHAR"},
    "source_file": {"VARCHAR"},
    "index_date": {"DATE"},
    "event_datetime": {"TIMESTAMP", "TIMESTAMP_NS", "TIMESTAMP WITH TIME ZONE"},
    "in_baseline_window": {"BOOLEAN"},
    "ordered_pre_index": {"BOOLEAN"},
    "active_at_index": {"BOOLEAN"},
    "ordered_post_index": {"BOOLEAN"},
    "patient_linked": {"BOOLEAN"},
    "demographics_agree": {"BOOLEAN"},
    "encounter_linked": {"BOOLEAN"},
    "anchor_in_encounter": {"BOOLEAN"},
    "days_before_index": {"BIGINT", "INTEGER", "SMALLINT", "TINYINT"},
    "source_row_number": {"BIGINT", "INTEGER", "UBIGINT"},
    "baseline_lookback_days": {"BIGINT", "INTEGER", "SMALLINT", "TINYINT"},
    "captured_patient_record_count": {"BIGINT", "INTEGER", "UBIGINT"},
    "first_event_datetime": {"TIMESTAMP", "TIMESTAMP_NS", "TIMESTAMP WITH TIME ZONE"},
    "last_event_datetime": {"TIMESTAMP", "TIMESTAMP_NS", "TIMESTAMP WITH TIME ZONE"},
    "numeric_value": {"DOUBLE", "FLOAT", "DECIMAL"},
    "raw_numeric_value": {"DOUBLE", "FLOAT", "DECIMAL"},
    "normalized_numeric_value": {"DOUBLE", "FLOAT", "DECIMAL"},
}


def quote_identifier(value):
    return '"' + value.replace('"', '""') + '"'


def _coverage_policy(coverage, requested_policy, requested_exception):
    policies = {"complete_linkage", "permit_incomplete_linkage"}
    if requested_policy is not None and requested_policy not in policies:
        raise ValueError("Unsupported requested coverage policy")
    if requested_exception is not None:
        if not isinstance(requested_exception, str):
            raise ValueError("A linkage exception must be text")
        if requested_policy != "permit_incomplete_linkage":
            raise ValueError(
                "A linkage exception requires an explicit incomplete policy"
            )
    markers = {"policy", "policy_version", "exception"}
    present = markers.intersection(coverage)
    if present and present != markers:
        raise ValueError("Source coverage has a partial policy declaration")
    if present:
        policy = coverage["policy"]
        exception = coverage["exception"]
        if coverage["policy_version"] != "1.0" or policy not in policies:
            raise ValueError("Unsupported source coverage policy")
        if requested_policy is not None and requested_policy != policy:
            raise ValueError("Requested coverage policy differs from bundle")
        if requested_exception is not None and requested_exception.strip() != exception:
            raise ValueError("Requested linkage exception differs from bundle")
        origin = "bundle"
    else:
        policy = requested_policy or "complete_linkage"
        exception = requested_exception.strip() if requested_exception else None
        origin = "legacy_explicit" if requested_policy else "legacy_default"
    if policy == "permit_incomplete_linkage":
        if not isinstance(exception, str) or not exception.strip():
            raise ValueError("Incomplete linkage requires a documented exception")
        exception = exception.strip()
    elif exception is not None:
        raise ValueError("Complete linkage cannot declare an exception")
    return policy, exception, origin


def _reconcile_linkage(db, *, artifact, declared, policy, exception, legacy):
    inconsistent = db.execute("""
        SELECT count(*) FROM (
          SELECT index_event_id FROM evidence GROUP BY index_event_id
          HAVING count(DISTINCT (patient_linked, demographics_agree,
                                 encounter_linked, anchor_in_encounter)) <> 1
             OR count(*) FILTER (WHERE patient_linked IS NULL
                  OR demographics_agree IS NULL OR encounter_linked IS NULL
                  OR anchor_in_encounter IS NULL) > 0
        )
    """).fetchone()[0]
    if inconsistent:
        raise ValueError(f"{artifact}: linkage flags differ across domains")
    link = db.execute("""
        SELECT count(*), count(*) FILTER (WHERE patient_linked),
          count(*) FILTER (WHERE NOT patient_linked),
          count(*) FILTER (WHERE encounter_linked),
          count(*) FILTER (WHERE NOT encounter_linked),
          count(*) FILTER (WHERE patient_linked AND NOT demographics_agree),
          count(*) FILTER (WHERE encounter_linked AND NOT anchor_in_encounter)
        FROM evidence WHERE domain='diagnosis'
    """).fetchone()
    (
        rows,
        patients,
        missing_patients,
        encounters,
        missing_encounters,
        demographics,
        anchors,
    ) = link
    contradictions_pass = demographics == 0 and anchors == 0
    complete = rows > 0 and missing_patients == 0 and missing_encounters == 0
    passed = (
        rows > 0
        and patients > 0
        and encounters > 0
        and contradictions_pass
        and (complete or policy == "permit_incomplete_linkage")
    )
    actual = {
        "rows": rows,
        "patient_linked": patients,
        "patient_unlinked": missing_patients,
        "patient_linked_proportion": patients / rows if rows else None,
        "encounter_linked": encounters,
        "encounter_unlinked": missing_encounters,
        "encounter_linked_proportion": encounters / rows if rows else None,
        "demographic_disagreements": demographics,
        "anchor_disagreements": anchors,
        "contradictions_pass": contradictions_pass,
        "linkage_complete": complete,
        "pass": passed,
        "policy": policy,
        "policy_version": "1.0",
        "exception": exception,
    }
    required = (
        {
            "pass",
            "rows",
            "patient_linked",
            "encounter_linked",
            "demographic_disagreements",
            "anchor_disagreements",
        }
        if legacy
        else set(actual)
    )
    if not required <= declared.keys() or any(
        declared[name] != actual[name] for name in actual.keys() & declared.keys()
    ):
        raise ValueError(
            f"{artifact}: linkage totals differ from report or declared policy"
        )
    if not passed:
        raise ValueError(f"{artifact}: source linkage fails {policy} policy")
    return {**declared, **actual}


def _check_table_schema(db, path, artifact, required):
    db.execute(
        "CREATE OR REPLACE VIEW contract_table AS SELECT * FROM "
        f"read_parquet({literal(path)})"
    )
    schema = {
        row[0]: row[1].upper()
        for row in db.execute("DESCRIBE contract_table").fetchall()
    }
    missing = sorted(required - schema.keys())
    if missing:
        raise ValueError(
            f"{artifact}: evidence schema missing required fields {missing}"
        )
    incompatible = {}
    for name, allowed in COLUMN_TYPES.items():
        if name not in required or name not in schema:
            continue
        actual = schema[name]
        compatible = actual in allowed or (
            "DECIMAL" in allowed and actual.startswith("DECIMAL(")
        )
        if not compatible:
            incompatible[name] = (actual, sorted(allowed))
    if incompatible:
        raise ValueError(
            f"{artifact}: incompatible required field types {incompatible}"
        )
    return schema


def _sha256_hex(value):
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _require_validation_report(report):
    if not isinstance(report, dict) or report.get("pass") is not True:
        raise ValueError("Acceptance requires a passing validation report")
    if report.get("validation_contract_version") != VALIDATION_CONTRACT_VERSION:
        raise ValueError("Unsupported validation report contract version")
    if (
        report.get("product_kind") != "encounter_features"
        or report.get("schema_version") != SCHEMA_VERSION
        or report.get("feature_contract_version") != "1.0"
        or not _sha256_hex(report.get("bundle_manifest_sha256"))
        or not _sha256_hex(report.get("historical_producer_code_sha256"))
    ):
        raise ValueError("Validation report lacks product or producer identity")
    variants = report.get("covered_variants")
    if (
        not isinstance(variants, list)
        or not variants
        or any(not isinstance(variant, str) for variant in variants)
        or len(variants) != len(set(variants))
        or not set(variants) <= set(VARIANTS)
    ):
        raise ValueError("Validation report lacks covered variants")
    outputs = report.get("output_identities")
    if (
        not isinstance(outputs, dict)
        or not outputs
        or any(
            not isinstance(info, dict)
            or not _sha256_hex(info.get("sha256"))
            or type(info.get("bytes")) is not int
            or info["bytes"] < 1
            for info in outputs.values()
        )
    ):
        raise ValueError("Validation report lacks output identities")
    sources = report.get("source_identities")
    if not isinstance(sources, dict) or any(
        not isinstance(sources.get(name), dict) or not sources[name]
        for name in ("canonical", "compatibility")
    ):
        raise ValueError("Validation report lacks source identities")
    revision = report.get("validator_revision")
    if not isinstance(revision, dict) or not _sha256_hex(
        revision.get("encounter_package_code_sha256")
    ):
        raise ValueError("Validation report lacks validator revision")
    policy = report.get("coverage_policy")
    exception = report.get("coverage_exception", object())
    if (
        not isinstance(policy, str)
        or policy not in {"complete_linkage", "permit_incomplete_linkage"}
        or report.get("coverage_policy_origin")
        not in {"bundle", "legacy_default", "legacy_explicit"}
        or (policy == "complete_linkage" and exception is not None)
        or (
            policy == "permit_incomplete_linkage"
            and (not isinstance(exception, str) or not exception.strip())
        )
    ):
        raise ValueError("Validation report lacks a supported coverage policy")
    results = report.get("coverage_results")
    if (
        not isinstance(results, dict)
        or set(results) != set(variants)
        or any(
            not isinstance(item, dict)
            or item.get("pass") is not True
            or type(item.get("rows")) is not int
            or item["rows"] < 1
            for item in results.values()
        )
    ):
        raise ValueError("Validation report lacks coverage results")


def verify_acceptance_receipt(
    receipt,
    *,
    expected_manifest_sha256,
    expected_policy,
    expected_variants,
    expected_required_gates,
    validation_report_bytes,
):
    """Verify an externally trusted receipt against an exact report and product.

    Callers must obtain the expected manifest and receipt identity from their
    trusted release process. A neighboring JSON file is never trusted merely
    because it hashes itself.
    """
    if not isinstance(receipt, dict):
        raise ValueError("Acceptance receipt must be an object")
    if receipt.get("schema") != "trinetx.encounter.acceptance-receipt":
        raise ValueError("Unsupported acceptance receipt schema")
    if receipt.get("validation_contract_version") != VALIDATION_CONTRACT_VERSION:
        raise ValueError("Unsupported validation contract version")
    if receipt.get("bundle_manifest_sha256") != expected_manifest_sha256:
        raise ValueError("Acceptance receipt manifest identity differs")
    if receipt.get("coverage_policy") != expected_policy:
        raise ValueError("Acceptance receipt coverage policy differs")
    receipt_variants = receipt.get("covered_variants")
    if (
        not isinstance(receipt_variants, list)
        or any(not isinstance(variant, str) for variant in receipt_variants)
        or set(receipt_variants) != set(expected_variants)
    ):
        raise ValueError("Acceptance receipt variant scope differs")
    if hashlib.sha256(validation_report_bytes).hexdigest() != receipt.get(
        "validation_report_sha256"
    ):
        raise ValueError("Acceptance validation report bytes differ from receipt")
    try:
        report = json.loads(validation_report_bytes)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("Acceptance validation report is not valid JSON") from exc
    _require_validation_report(report)
    identity_fields = (
        "output_identities",
        "product_kind",
        "source_identities",
        "schema_version",
        "feature_contract_version",
        "historical_producer_code_sha256",
        "validator_revision",
        "coverage_policy_origin",
        "coverage_results",
        "coverage_exception",
    )
    if any(field not in receipt for field in identity_fields):
        raise ValueError("Acceptance receipt lacks required report identities")
    try:
        _require_validation_report({**receipt, "pass": True})
    except ValueError as exc:
        raise ValueError("Acceptance receipt has invalid report identities") from exc
    if (
        report["bundle_manifest_sha256"] != expected_manifest_sha256
        or report.get("coverage_policy") != expected_policy
        or set(report.get("covered_variants", ())) != set(expected_variants)
        or any(receipt[field] != report[field] for field in identity_fields)
    ):
        raise ValueError(
            "Acceptance receipt does not bind the successful validation report"
        )
    for field in (
        "reference_comparison",
        "producer_revision",
        "consumer_revision",
        "exceptions",
        "limitations",
    ):
        if field not in receipt:
            raise ValueError(f"Acceptance receipt lacks required field: {field}")
    if (
        not isinstance(receipt["reference_comparison"], dict)
        or not isinstance(receipt["exceptions"], list)
        or not isinstance(receipt["limitations"], list)
    ):
        raise ValueError("Acceptance receipt has invalid evidence fields")
    gates = receipt.get("gates")
    required = receipt.get("required_gates")
    if (
        not isinstance(gates, dict)
        or not isinstance(required, list)
        or not required
        or set(required) != set(expected_required_gates)
    ):
        raise ValueError("Acceptance receipt must enumerate trusted required gates")
    failures = sorted(name for name in required if gates.get(name) != "pass")
    if failures:
        raise ValueError(f"Required acceptance gates are missing or failed: {failures}")
    reference = receipt["reference_comparison"]
    if gates.get("retained_reference_parity") == "pass" and not all(
        reference.get(field) for field in ("identity", "contract", "results")
    ):
        raise ValueError(
            "Passed retained-reference gate lacks bound comparison evidence"
        )
    if gates.get("installed_pair_verification") == "pass" and not all(
        receipt.get(field) for field in ("producer_revision", "consumer_revision")
    ):
        raise ValueError("Passed installed-pair gate lacks tested revisions")
    if (
        gates.get("build_completion") == "pass"
        and gates.get("artifact_validation") != "pass"
    ):
        raise ValueError("Build completion alone does not establish acceptance")
    return {"pass": True, "gates": {name: gates[name] for name in required}}


def _reconcile_element_summary(db, *, root, stem, item, token, lookback_days):
    element_id = item["element_id"]
    outputs = item["columns"]
    count_column = next((c for c in outputs if c.endswith("_record_count")), None)
    value_column = next((c for c in outputs if c.endswith("_latest_raw_value")), None)
    date_column = next((c for c in outputs if c.endswith("_latest_date")), None)
    unit_column = next((c for c in outputs if c.endswith("_latest_unit")), None)
    if not all((count_column, value_column, date_column, unit_column)):
        raise ValueError(
            f"Catalog summary contract lacks value/date/unit for {element_id}"
        )
    evidence_path = root / f"{stem}_encounter_element_evidence.parquet"
    element = literal(element_id)
    baseline = (
        "event_datetime::DATE BETWEEN index_date - "
        f"INTERVAL {lookback_days} DAY AND index_date"
    )
    for column in (count_column, value_column, date_column, unit_column):
        if column not in {r[0] for r in db.execute("DESCRIBE features").fetchall()}:
            raise ValueError(f"{stem}.parquet: summary column missing: {column}")

    def quoted(name):
        return '"' + name.replace('"', '""') + '"'

    count_bad = db.execute(f"""
        WITH counts AS (
          SELECT index_event_id, count(*) AS n
          FROM read_parquet({literal(evidence_path)}) WHERE element_id={element}
          GROUP BY index_event_id
        )
        SELECT count(*) FROM features f LEFT JOIN counts c
          ON c.index_event_id=f.pat_enc_hash
        WHERE coalesce(c.n,0) IS DISTINCT FROM f.{quoted(count_column)}
    """).fetchone()[0]
    baseline_bad = db.execute(f"""
        SELECT count(*) FROM read_parquet({literal(evidence_path)})
        WHERE element_id={element}
          AND in_baseline_window IS DISTINCT FROM ({baseline})
    """).fetchone()[0]
    latest_bad = db.execute(f"""
        WITH eligible AS (
          SELECT index_event_id,numeric_value,event_datetime,units_of_measure,
            row_number() OVER (PARTITION BY index_event_id
              ORDER BY event_datetime DESC NULLS LAST, source_record_id DESC) AS winner
          FROM read_parquet({literal(evidence_path)})
          WHERE element_id={element} AND {baseline}
        )
        SELECT count(*) FROM features f LEFT JOIN eligible e
          ON e.index_event_id=f.pat_enc_hash AND e.winner=1
        WHERE f.{quoted(value_column)} IS DISTINCT FROM e.numeric_value
           OR f.{quoted(date_column)} IS DISTINCT FROM e.event_datetime
           OR f.{quoted(unit_column)} IS DISTINCT FROM e.units_of_measure
    """).fetchone()[0]
    no_baseline = db.execute(f"""
        SELECT count(DISTINCT e.index_event_id)
        FROM read_parquet({literal(evidence_path)}) e
        WHERE e.element_id={element}
          AND NOT EXISTS (
            SELECT 1 FROM read_parquet({literal(evidence_path)}) eligible
            WHERE eligible.element_id={element}
              AND eligible.index_event_id=e.index_event_id
              AND eligible.event_datetime::DATE BETWEEN
                  eligible.index_date - INTERVAL {lookback_days} DAY
                  AND eligible.index_date
          )
    """).fetchone()[0]
    future = db.execute(f"""
        SELECT count(*) FROM read_parquet({literal(evidence_path)}) e
        JOIN features f ON e.index_event_id=f.pat_enc_hash
          AND e.source_encounter_id=f.encounter_id
        WHERE e.element_id={element} AND e.event_datetime::DATE > e.index_date
    """).fetchone()[0]
    future_in_baseline = db.execute(f"""
        SELECT count(*) FROM read_parquet({literal(evidence_path)})
        WHERE element_id={element} AND event_datetime::DATE > index_date
          AND in_baseline_window
    """).fetchone()[0]
    if count_bad or baseline_bad or latest_bad or future_in_baseline:
        raise ValueError(
            f"{stem}: catalogue summary reconciliation failed for {element_id}; "
            f"count_mismatches={count_bad}, baseline_flag_mismatches={baseline_bad}, "
            f"value_date_unit_mismatches={latest_bad}, "
            f"future_context_baseline_rows={future_in_baseline}"
        )
    return {
        "example": token,
        "element_id": element_id,
        "count_column": count_column,
        "value_date_unit_columns": [value_column, date_column, unit_column],
        "count_mismatches": count_bad,
        "baseline_flag_mismatches": baseline_bad,
        "value_date_unit_mismatches": latest_bad,
        "encounters_without_eligible_baseline_with_retained_evidence": no_baseline,
        "future_same_encounter_context_rows": future,
        "future_context_baseline_rows": future_in_baseline,
        "rule": (
            f"inclusive {lookback_days}-day window; latest eligible row by "
            "timestamp descending, nulls last, "
            "source_record_id descending; value/date/unit travel together"
        ),
    }


def _reconcile_normalized_summaries(db, *, root, stem):
    lab = root / f"{stem}_component_lab_evidence.parquet"
    bp = root / f"{stem}_component_bp_evidence.parquet"
    lab_bad = db.execute(f"""
        WITH ranked AS (
          SELECT index_event_id,normalized_numeric_value,event_datetime,
            row_number() OVER (PARTITION BY index_event_id
              ORDER BY event_datetime DESC,source_record_hash DESC) AS winner
          FROM read_parquet({literal(lab)}) WHERE concept_set_id='hba1c'
        )
        SELECT count(*) FROM features f LEFT JOIN ranked r
          ON r.index_event_id=f.pat_enc_hash AND r.winner=1
        WHERE f.glp1_lab_a1c_latest IS DISTINCT FROM r.normalized_numeric_value
           OR f.glp1_lab_a1c_latest_date IS DISTINCT FROM r.event_datetime
    """).fetchone()[0]
    lab_units_bad = db.execute(f"""
        SELECT count(*) FROM read_parquet({literal(lab)})
        WHERE concept_set_id='hba1c' AND
          (normalized_unit IS DISTINCT FROM '%' OR
           normalized_numeric_value IS DISTINCT FROM CASE
             WHEN lower(trim(coalesce(units_of_measure,''))) IN ('%','percent')
             THEN raw_numeric_value ELSE NULL END)
    """).fetchone()[0]
    bp_bad = db.execute(f"""
        WITH ranked AS (
          SELECT index_event_id,concept_set_id,normalized_numeric_value,event_datetime,
            row_number() OVER (PARTITION BY index_event_id,concept_set_id
              ORDER BY CASE WHEN upper(trim(encounter_type))='AMB' THEN 0 ELSE 1 END,
                       event_datetime DESC,source_record_hash DESC) AS winner
          FROM read_parquet({literal(bp)})
        ), expected AS (
          SELECT index_event_id,
            max(normalized_numeric_value) FILTER
              (WHERE concept_set_id='systolic_bp' AND winner=1) AS latest_sbp,
            max(normalized_numeric_value) FILTER
              (WHERE concept_set_id='diastolic_bp' AND winner=1) AS latest_dbp,
            max(event_datetime) FILTER (WHERE winner=1) AS latest_bp_date
          FROM ranked GROUP BY index_event_id
        )
        SELECT count(*) FROM features f LEFT JOIN expected e
          ON e.index_event_id=f.pat_enc_hash
        WHERE f.glp1_bp_latest_sbp IS DISTINCT FROM e.latest_sbp
           OR f.glp1_bp_latest_dbp IS DISTINCT FROM e.latest_dbp
           OR f.glp1_bp_latest_bp_date IS DISTINCT FROM e.latest_bp_date
    """).fetchone()[0]
    bp_units_bad = db.execute(f"""
        SELECT count(*) FROM read_parquet({literal(bp)})
        WHERE normalized_numeric_value IS DISTINCT FROM CASE
          WHEN lower(trim(coalesce(units_of_measure,''))) IN
            ('mmhg','mm hg','mm_hg','mm[hg]','torr') THEN raw_numeric_value
          WHEN lower(trim(coalesce(units_of_measure,'')))='kpa'
            THEN raw_numeric_value * 7.5006168270417
          ELSE NULL END
    """).fetchone()[0]
    if any((lab_bad, lab_units_bad, bp_bad, bp_units_bad)):
        raise ValueError(
            f"{stem}: normalized lab/vital summary reconciliation failed; "
            f"lab_summary={lab_bad}, lab_unit={lab_units_bad}, "
            f"bp_summary={bp_bad}, bp_unit={bp_units_bad}"
        )
    return {
        "lab": {
            "example": "hba1c",
            "value_date_mismatches": lab_bad,
            "raw_to_normalized_unit_mismatches": lab_units_bad,
            "normalized_unit": "%",
        },
        "vital": {
            "example": "systolic_bp_and_diastolic_bp",
            "value_date_unit_mismatches": bp_bad,
            "raw_to_normalized_unit_mismatches": bp_units_bad,
        },
        "scope": (
            "explicit laboratory and blood-pressure summaries only; "
            "not exhaustive phenotype validation"
        ),
    }


def validate_bundle(*, bundle, work_dir, linkage_policy=None, linkage_exception=None):
    root = no_symlinks(bundle)
    work = no_symlinks(work_dir)
    require_safe_output_location(work, artifact_label="encounter validation scratch")
    work.mkdir(mode=0o700, parents=True, exist_ok=False)
    manifest_hash = digest(root / "manifest.json")
    manifest = json.loads((root / "manifest.json").read_text())
    if (
        manifest.get("schema_version") != SCHEMA_VERSION
        or manifest.get("status") != "complete"
        or manifest.get("kind") != "encounter_features"
        or manifest.get("feature_contract_version") != "1.0"
    ):
        raise ValueError("Unsupported or incomplete feature bundle")
    windows = manifest.get("windows")
    if not isinstance(windows, dict) or any(
        not isinstance(windows.get(name), int)
        or isinstance(windows[name], bool)
        or windows[name] < 1
        for name in ("measurement_lookback_days", "lookback_days")
    ):
        raise ValueError("Encounter manifest lacks valid baseline window lengths")
    required = {"data_dictionary.json", "quality_summary.json", "source_coverage.json"}
    for variant in VARIANTS:
        stem = f"encounter_features_{variant.lower()}"
        required.update(
            {
                stem + ".parquet",
                stem + "_element_inventory.json",
                stem + "_encounter_source_coverage.parquet",
            }
        )
        required.update(f"{stem}_{table}.parquet" for table in EVIDENCE_TABLES)
    if set(manifest["outputs"]) != required:
        raise ValueError("Encounter artifact inventory differs from required contract")
    for name, info in manifest["outputs"].items():
        path = no_symlinks(root / name)
        if path.stat().st_size != info["bytes"] or digest(path) != info["sha256"]:
            raise ValueError("Encounter artifact does not match manifest")
    dictionary = json.loads((root / "data_dictionary.json").read_text())
    qa = json.loads((root / "quality_summary.json").read_text())
    coverage = json.loads((root / "source_coverage.json").read_text())
    policy, exception, policy_origin = _coverage_policy(
        coverage, linkage_policy, linkage_exception
    )
    if (
        not coverage["pass"]
        or coverage["source"] != manifest["source"]
        or coverage.get("contract_version") != "1.0"
        or set(coverage.get("variants", {})) != set(VARIANTS)
    ):
        raise ValueError("Source coverage provenance differs")
    results = {}
    summary_results = {}
    coverage_results = {}
    with duckdb.connect(str(work / "validation.duckdb")) as db:
        db.execute("SET memory_limit='1024MiB'")
        db.execute("SET threads=1")
        db.execute("SET temp_directory=?", [str(work / "spill")])
        for variant in VARIANTS:
            stem = f"encounter_features_{variant.lower()}"
            db.execute(
                "CREATE OR REPLACE VIEW features AS SELECT * FROM "
                f"read_parquet({literal(root / (stem + '.parquet'))})"
            )
            counts = db.execute("""
                SELECT count(*), count(DISTINCT (patient_id,encounter_id)),
                       count(DISTINCT pat_enc_hash),
                       count(*) FILTER(WHERE patient_id IS NULL OR encounter_id IS NULL
                           OR trim(concat(patient_id,'-',encounter_id),' ')
                           IS DISTINCT FROM pat_enc_hash)
                FROM features
            """).fetchone()
            if counts[:3] != (qa[variant]["rows"],) * 3 or counts[3]:
                raise ValueError("Encounter output membership or key integrity differs")
            columns = {r[0] for r in db.execute("DESCRIBE features").fetchall()}
            entries = dictionary[variant]
            if (
                len(entries) != len(columns)
                or {e["column"] for e in entries} != columns
                or any(e.get("anchor_precision") != "calendar day" for e in entries)
                or set(qa[variant]["null_counts"]) != columns
            ):
                raise ValueError("Encounter dictionary/QA schema is incomplete")
            actual_null_counts = {
                name: value
                for name, value in zip(
                    sorted(columns),
                    db.execute(
                        "SELECT "
                        + ", ".join(
                            f"count(*) FILTER (WHERE {quote_identifier(name)} IS NULL)"
                            for name in sorted(columns)
                        )
                        + " FROM features"
                    ).fetchone(),
                    strict=True,
                )
            }
            declared_null_counts = {
                k: int(v) for k, v in qa[variant]["null_counts"].items()
            }
            if actual_null_counts != declared_null_counts:
                differences = {
                    name: {
                        "declared": declared_null_counts.get(name),
                        "actual": actual_null_counts.get(name),
                    }
                    for name in columns
                    if actual_null_counts.get(name) != declared_null_counts.get(name)
                }
                raise ValueError(
                    "quality_summary.json["
                    f"{variant}]: missingness discrepancy {differences}"
                )
            inventory = json.loads(
                (root / (stem + "_element_inventory.json")).read_text()
            )
            if len({e["element_id"] for e in inventory}) != len(inventory):
                raise ValueError("Element inventory duplicates required elements")
            if {e["element_id"] for e in inventory} != set(
                manifest["required_source_elements"]
            ):
                raise ValueError("Element inventory omits required source elements")
            for element in inventory:
                if not set(element["columns"]) <= columns or not element.get(
                    "availability_states"
                ):
                    raise ValueError(
                        "Required element lacks fields or availability states"
                    )
                total = sum(
                    s["observed_matches"] + s["zero_matching_records"]
                    for s in element["availability_states"]
                )
                if total != counts[0] or any(
                    s["zero_matching_records"] < 0
                    for s in element["availability_states"]
                ):
                    raise ValueError(
                        "Element availability does not cover every encounter"
                    )
            evidence_counts = {}
            for table in (*EVIDENCE_TABLES, "encounter_source_coverage"):
                path = root / f"{stem}_{table}.parquet"
                if table in EVIDENCE_CONTRACTS:
                    _check_table_schema(db, path, path.name, EVIDENCE_CONTRACTS[table])
                else:
                    coverage_required = {
                        "index_event_id",
                        "patient_id",
                        "encounter_id",
                        "domain",
                        "baseline_lookback_days",
                        "patient_linked",
                        "demographics_agree",
                        "encounter_linked",
                        "anchor_in_encounter",
                        "first_event_datetime",
                        "last_event_datetime",
                        "captured_patient_record_count",
                        "history_state",
                    }
                    _check_table_schema(db, path, path.name, coverage_required)
                db.execute(
                    "CREATE OR REPLACE VIEW evidence AS "
                    f"SELECT * FROM read_parquet({literal(path)})"
                )
                if db.execute(
                    "SELECT count(*) FROM evidence e ANTI JOIN features f "
                    "ON e.index_event_id=f.pat_enc_hash"
                ).fetchone()[0]:
                    raise ValueError("Evidence has keys outside its encounter variant")
                evidence_counts[table] = db.execute(
                    "SELECT count(*) FROM evidence"
                ).fetchone()[0]
                if table == "encounter_element_evidence":
                    distinct_memberships, distinct_records = db.execute(
                        "SELECT count(DISTINCT (index_event_id,element_id)), "
                        "count(DISTINCT source_record_id) FROM evidence"
                    ).fetchone()
                    evidence_counts[table] = {
                        "retained_rows": evidence_counts[table],
                        "distinct_encounter_element_memberships": distinct_memberships,
                        "distinct_source_record_ids": distinct_records,
                    }
                if table == "encounter_source_coverage":
                    n, unique = db.execute(
                        "SELECT count(*),count(DISTINCT (index_event_id,domain)) "
                        "FROM evidence"
                    ).fetchone()
                    if n != unique or n != 5 * counts[0]:
                        raise ValueError(
                            "Domain coverage does not cover every encounter"
                        )
                    domains = {
                        row[0]
                        for row in db.execute(
                            "SELECT DISTINCT domain FROM evidence"
                        ).fetchall()
                    }
                    if domains != {
                        "diagnosis",
                        "labs",
                        "vitals",
                        "medications",
                        "procedure",
                    }:
                        raise ValueError(
                            f"{path.name}: required source coverage domains differ"
                        )
                    states = [
                        {"domain": domain, "state": state, "rows": amount}
                        for domain, state, amount in db.execute(
                            "SELECT domain,history_state,count(*) FROM evidence "
                            "GROUP BY 1,2 ORDER BY 1,2"
                        ).fetchall()
                    ]
                    if states != coverage["variants"][variant].get("history_states"):
                        raise ValueError(
                            f"{path.name}: source-coverage history totals "
                            "differ from report"
                        )
                    coverage_results[variant] = _reconcile_linkage(
                        db,
                        artifact=path.name,
                        declared=coverage["variants"][variant],
                        policy=policy,
                        exception=exception,
                        legacy=policy_origin != "bundle",
                    )
            element_evidence_path = root / (
                stem + "_encounter_element_evidence.parquet"
            )
            encounter_coverage_path = root / (
                stem + "_encounter_source_coverage.parquet"
            )
            actual_availability = db.execute(f"""
                WITH observed AS (
                  SELECT e.element_id,e.domain,c.history_state,
                         count(DISTINCT e.index_event_id) AS n
                  FROM read_parquet({literal(element_evidence_path)}) e
                  JOIN read_parquet({literal(encounter_coverage_path)}) c
                    ON c.index_event_id=e.index_event_id AND c.domain=e.domain
                  GROUP BY e.element_id,e.domain,c.history_state
                ), totals AS (
                  SELECT domain,history_state,count(*) AS n
                  FROM read_parquet({literal(encounter_coverage_path)})
                  GROUP BY domain,history_state
                )
                SELECT o.element_id,o.domain,o.history_state,coalesce(o.n,0),t.n
                FROM observed o
                JOIN totals t ON t.domain=o.domain AND t.history_state=o.history_state
            """).fetchall()
            observed_lookup = {
                (element_id, domain, state): (observed, total)
                for element_id, domain, state, observed, total in actual_availability
            }
            for element in inventory:
                for state_info in element["availability_states"]:
                    key = (
                        element["element_id"],
                        element["domain"],
                        state_info["history_state"],
                    )
                    observed, total = observed_lookup.get(key, (0, None))
                    total = (
                        total
                        if total is not None
                        else db.execute(
                            "SELECT count(*) FROM read_parquet(?) "
                            "WHERE domain=? AND history_state=?",
                            [
                                str(
                                    root / (stem + "_encounter_source_coverage.parquet")
                                ),
                                element["domain"],
                                state_info["history_state"],
                            ],
                        ).fetchone()[0]
                    )
                    if (
                        observed != state_info["observed_matches"]
                        or total - observed != state_info["zero_matching_records"]
                    ):
                        raise ValueError(
                            f"{stem}_element_inventory.json: availability totals "
                            f"differ for {element['element_id']} / "
                            f"{state_info['history_state']}"
                        )
            summaries = []
            for token in ("hba1c", "systolic_bp", "egfr"):
                selected = next(
                    (
                        element
                        for element in inventory
                        if token in element["element_id"].lower()
                    ),
                    None,
                )
                if selected is None:
                    raise ValueError(
                        f"Element inventory lacks required summary example {token}"
                    )
                summaries.append(
                    _reconcile_element_summary(
                        db,
                        root=root,
                        stem=stem,
                        item=selected,
                        token=token,
                        lookback_days=windows["measurement_lookback_days"],
                    )
                )
            summaries.append(_reconcile_normalized_summaries(db, root=root, stem=stem))
            summary_results[variant] = summaries
            results[variant] = {
                "rows": counts[0],
                "elements": len(inventory),
                "evidence_rows": evidence_counts,
                "pass": True,
            }
    if digest(root / "manifest.json") != manifest_hash:
        raise ValueError("Manifest changed during validation")
    validator_hash = code_identity()
    return {
        "pass": True,
        "validation_contract_version": VALIDATION_CONTRACT_VERSION,
        "product_kind": manifest["kind"],
        "bundle_manifest_sha256": manifest_hash,
        "schema_version": SCHEMA_VERSION,
        "feature_contract_version": "1.0",
        "covered_variants": sorted(VARIANTS),
        "output_identities": manifest["outputs"],
        "source_identities": {
            "canonical": manifest.get("source"),
            "compatibility": manifest.get("compatibility"),
        },
        "historical_producer_code_sha256": manifest.get("code_sha256"),
        "legacy_reference_gate_sha256": manifest.get("legacy_gate_sha256"),
        "validator_revision": {"encounter_package_code_sha256": validator_hash},
        "coverage_policy": policy,
        "coverage_policy_origin": policy_origin,
        "coverage_exception": exception,
        "coverage_results": coverage_results,
        "summary_reconciliations": summary_results,
        "reference_comparison": {"status": "not_performed_by_upstream_validator"},
        "installed_pair_verification": {
            "status": "not_performed_by_upstream_validator"
        },
        "scientific_analysis_acceptance": {
            "status": "not_established_by_upstream_validator"
        },
        "required_production_gates": [
            "artifact_validation",
            "retained_reference_parity",
            "installed_pair_verification",
            "scientific_analysis_acceptance",
        ],
        "variants": results,
    }

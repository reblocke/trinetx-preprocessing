"""Validate the full encounter artifact contract without clinical interpretation."""

from __future__ import annotations

import json

import duckdb

from ..combined_preprocessing.builder import require_safe_output_location
from .acceptance import (
    ACCEPTANCE_CONTRACT_VERSION,
    load_artifact_contract,
    verify_companion_schema,
    verify_feature_schema,
)
from .builder import EVIDENCE_TABLES, SCHEMA_VERSION, VARIANTS, ident, literal
from .compatibility import digest, no_symlinks

SUMMARY_RECONCILIATIONS = (
    "source.hba1c raw",
    "source.bmi raw",
    "glp1_lab_a1c_latest normalized",
    "glp1_bp_latest_sbp normalized",
)
RAW_SUMMARY_ELEMENTS = ("source.hba1c", "source.bmi")


class ArtifactInvariantError(ValueError):
    """A private-safe aggregate discrepancy tied to a published artifact."""

    def __init__(self, artifact: str, invariant: str, discrepancy: str):
        self.artifact = artifact
        self.invariant = invariant
        self.discrepancy = discrepancy
        super().__init__(discrepancy)


def validate_bundle(*, bundle, work_dir):
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
    load_artifact_contract()
    qa = json.loads((root / "quality_summary.json").read_text())
    coverage = json.loads((root / "source_coverage.json").read_text())
    if not coverage["pass"] or coverage["source"] != manifest["source"]:
        raise ValueError("Source coverage provenance differs")
    results = {}
    with duckdb.connect(str(work / "validation.duckdb")) as db:
        db.execute("SET memory_limit='1024MiB'")
        db.execute("SET threads=1")
        db.execute("SET temp_directory=?", [str(work / "spill")])
        for variant in VARIANTS:
            stem = f"encounter_features_{variant.lower()}"
            try:
                verify_feature_schema(
                    root, manifest, variant, root / (stem + ".parquet")
                )
            except ValueError as exc:
                raise ArtifactInvariantError(
                    stem + ".parquet", "feature_schema", str(exc)
                ) from exc
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
            names = [entry["column"] for entry in entries]
            actual_nulls = db.execute(
                "SELECT "
                + ", ".join(
                    f"count(*) FILTER (WHERE {ident(name)} IS NULL)" for name in names
                )
                + " FROM features"
            ).fetchone()
            differences = [
                name
                for name, count in zip(names, actual_nulls, strict=True)
                if qa[variant]["null_counts"].get(name) != count
            ]
            if differences:
                discrepancy = (
                    f"Encounter QA null counts differ for {variant}: {differences[:10]}"
                )
                raise ArtifactInvariantError(
                    "quality_summary.json",
                    "feature_null_counts",
                    discrepancy,
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
                try:
                    verify_companion_schema(path, table)
                except ValueError as exc:
                    raise ArtifactInvariantError(
                        path.name, "companion_schema", str(exc)
                    ) from exc
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
                if table == "encounter_source_coverage":
                    n, unique = db.execute(
                        "SELECT count(*),count(DISTINCT (index_event_id,domain)) "
                        "FROM evidence"
                    ).fetchone()
                    if n != unique or n != 5 * counts[0]:
                        raise ValueError(
                            "Domain coverage does not cover every encounter"
                        )
            _reconcile_element_evidence(db, root, stem, inventory)
            _reconcile_normalized_summaries(db, root, stem)
            results[variant] = {
                "rows": counts[0],
                "elements": len(inventory),
                "evidence_rows": evidence_counts,
                "summary_reconciliations": list(SUMMARY_RECONCILIATIONS),
                "pass": True,
            }
    if digest(root / "manifest.json") != manifest_hash:
        raise ValueError("Manifest changed during validation")
    return {
        "pass": True,
        "validation_contract_version": ACCEPTANCE_CONTRACT_VERSION,
        "bundle_manifest_sha256": manifest_hash,
        "kind": manifest["kind"],
        "schema_version": SCHEMA_VERSION,
        "feature_contract_version": "1.0",
        "outputs": manifest["outputs"],
        "source": manifest.get("source"),
        "compatibility": manifest.get("compatibility"),
        "producer_code_sha256": manifest.get("code_sha256"),
        "variants": results,
    }


def _reconcile_element_evidence(db, root, stem, inventory):
    """Check published catalogue counts and selected raw latest triplets."""
    evidence = root / f"{stem}_encounter_element_evidence.parquet"
    coverage = root / f"{stem}_encounter_source_coverage.parquet"
    db.execute(
        "CREATE OR REPLACE VIEW element_evidence AS SELECT * FROM "
        f"read_parquet({literal(evidence)})"
    )
    db.execute(
        "CREATE OR REPLACE VIEW domain_coverage AS SELECT * FROM "
        f"read_parquet({literal(coverage)})"
    )
    actual_counts = dict(
        db.execute(
            "SELECT element_id,count(*) FROM element_evidence GROUP BY element_id"
        ).fetchall()
    )
    known = {row["element_id"] for row in inventory}
    if set(actual_counts) - known:
        raise ValueError("Element evidence contains an undeclared catalogue element")
    # Every evidence row is one encounter/catalogue membership, including
    # legitimate repeated source records and multi-catalogue membership.
    count_columns = [
        next(
            (name for name in row["columns"] if name.endswith("_record_count")),
            None,
        )
        for row in inventory
    ]
    if any(name is None for name in count_columns):
        raise ValueError("Element inventory lacks a source-record count column")
    feature_counts = db.execute(
        "SELECT "
        + ",".join(f"coalesce(sum({ident(name)}),0)" for name in count_columns)
        + " FROM features"
    ).fetchone()
    for row, feature_count in zip(inventory, feature_counts, strict=True):
        if feature_count != actual_counts.get(row["element_id"], 0):
            evidence_count = actual_counts.get(row["element_id"], 0)
            raise ArtifactInvariantError(
                f"{stem}.parquet",
                "catalogue_membership_count",
                f"Element source-record count differs: {row['element_id']} "
                f"feature={feature_count} evidence={evidence_count}",
            )
    observed = {
        (element, state): n
        for element, state, n in db.execute("""
            SELECT matched.element_id, coverage.history_state, count(*)
            FROM (
                SELECT DISTINCT index_event_id,element_id,domain
                FROM element_evidence
            ) matched
            JOIN domain_coverage coverage USING (index_event_id,domain)
            GROUP BY 1,2
        """).fetchall()
    }
    totals = {
        (domain, state): n
        for domain, state, n in db.execute("""
            SELECT domain,history_state,count(*) FROM domain_coverage GROUP BY 1,2
        """).fetchall()
    }
    for row in inventory:
        element, domain = row["element_id"], row["domain"]
        states = row["availability_states"]
        if {s["history_state"] for s in states} != {
            state for name, state in totals if name == domain
        }:
            raise ValueError(f"Element availability states differ: {element}")
        for state in states:
            label = state["history_state"]
            matched = observed.get((element, label), 0)
            total = totals[(domain, label)]
            if (
                state["observed_matches"] != matched
                or state["zero_matching_records"] != total - matched
            ):
                raise ArtifactInvariantError(
                    f"{stem}_element_inventory.json",
                    "availability_reconciliation",
                    f"Element availability differs: {element} {label} "
                    f"observed={matched} coverage={total}",
                )
    # These raw value/date/unit triplets are selected together from one
    # baseline record. A later same-encounter context row stays in evidence.
    for element in RAW_SUMMARY_ELEMENTS:
        row = next(
            (entry for entry in inventory if entry["element_id"] == element), None
        )
        if row is None:
            raise ValueError(f"Required summary element missing: {element}")
        value, date, unit = (
            next(name for name in row["columns"] if name.endswith(suffix))
            for suffix in ("_latest_raw_value", "_latest_date", "_latest_unit")
        )
        mismatches = db.execute(f"""
            WITH latest AS (
                SELECT index_event_id,numeric_value,event_datetime,units_of_measure,
                       row_number() OVER (
                         PARTITION BY index_event_id
                         ORDER BY event_datetime DESC NULLS LAST,
                                  source_record_id DESC
                       ) AS rn
                FROM element_evidence
                WHERE element_id={literal(element)} AND in_baseline_window
            )
            SELECT count(*) FROM features f
            LEFT JOIN latest l ON f.pat_enc_hash=l.index_event_id AND l.rn=1
            WHERE f.{ident(value)} IS DISTINCT FROM l.numeric_value
               OR f.{ident(date)} IS DISTINCT FROM l.event_datetime
               OR f.{ident(unit)} IS DISTINCT FROM l.units_of_measure
        """).fetchone()[0]
        if mismatches:
            raise ArtifactInvariantError(
                f"{stem}.parquet",
                "raw_latest_triplet",
                f"Element latest raw value/date/unit differs: {element} "
                f"encounters={mismatches}",
            )


def _reconcile_normalized_summaries(db, root, stem):
    """Independently check two selected normalized clinical summaries."""
    lab = root / f"{stem}_component_lab_evidence.parquet"
    bp = root / f"{stem}_component_bp_evidence.parquet"
    db.execute(
        "CREATE OR REPLACE VIEW lab_evidence AS SELECT * FROM "
        f"read_parquet({literal(lab)})"
    )
    db.execute(
        "CREATE OR REPLACE VIEW bp_evidence AS SELECT * FROM "
        f"read_parquet({literal(bp)})"
    )
    lab_mismatches = db.execute("""
        WITH ranked AS (
            SELECT index_event_id,normalized_numeric_value,event_datetime,
                   row_number() OVER (
                     PARTITION BY index_event_id
                     ORDER BY event_datetime DESC,source_record_hash DESC
                   ) AS rn
            FROM lab_evidence WHERE concept_set_id='hba1c'
        )
        SELECT count(*) FROM features f
        LEFT JOIN ranked l ON f.pat_enc_hash=l.index_event_id AND l.rn=1
        WHERE f.glp1_lab_a1c_latest IS DISTINCT FROM l.normalized_numeric_value
           OR f.glp1_lab_a1c_latest_date IS DISTINCT FROM l.event_datetime
    """).fetchone()[0]
    if lab_mismatches:
        raise ArtifactInvariantError(
            f"{stem}.parquet",
            "normalized_a1c_latest",
            f"Normalized HBA1c latest value/date differs: encounters={lab_mismatches}",
        )
    bp_unit_mismatches = db.execute("""
        SELECT count(*) FROM bp_evidence
        WHERE normalized_numeric_value IS DISTINCT FROM
          CASE
            WHEN unit_key IN ('mmhg','mm hg','mm_hg','mm[hg]','torr')
              THEN raw_numeric_value
            WHEN unit_key='kpa' THEN raw_numeric_value * 7.5006168270417
            ELSE NULL
          END
    """).fetchone()[0]
    if bp_unit_mismatches:
        raise ArtifactInvariantError(
            f"{stem}_component_bp_evidence.parquet",
            "bp_unit_conversion",
            f"Blood-pressure normalized value/unit differs: rows={bp_unit_mismatches}",
        )
    bp_mismatches = db.execute("""
        WITH ranked AS (
            SELECT index_event_id,normalized_numeric_value,
                   row_number() OVER (
                     PARTITION BY index_event_id
                     ORDER BY CASE WHEN upper(trim(encounter_type))='AMB'
                                       THEN 0 ELSE 1 END,
                              event_datetime DESC,source_record_hash DESC
                   ) AS rn
            FROM bp_evidence WHERE concept_set_id='systolic_bp'
        )
        SELECT count(*) FROM features f
        LEFT JOIN ranked b ON f.pat_enc_hash=b.index_event_id AND b.rn=1
        WHERE f.glp1_bp_latest_sbp IS DISTINCT FROM b.normalized_numeric_value
    """).fetchone()[0]
    if bp_mismatches:
        raise ArtifactInvariantError(
            f"{stem}.parquet",
            "normalized_bp_latest",
            f"Normalized systolic BP latest value differs: encounters={bp_mismatches}",
        )

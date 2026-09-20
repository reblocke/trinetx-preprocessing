"""Validate the full encounter artifact contract without clinical interpretation."""

from __future__ import annotations

import json

import duckdb

from ..combined_preprocessing.builder import require_safe_output_location
from .builder import EVIDENCE_TABLES, SCHEMA_VERSION, VARIANTS, literal
from .compatibility import digest, no_symlinks


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
            results[variant] = {
                "rows": counts[0],
                "elements": len(inventory),
                "evidence_rows": evidence_counts,
                "pass": True,
            }
    if digest(root / "manifest.json") != manifest_hash:
        raise ValueError("Manifest changed during validation")
    return {
        "pass": True,
        "bundle_manifest_sha256": manifest_hash,
        "schema_version": SCHEMA_VERSION,
        "feature_contract_version": "1.0",
        "variants": results,
    }

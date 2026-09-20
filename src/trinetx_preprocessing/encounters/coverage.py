"""Versioned key corroboration and source-history availability before enrichment."""

from __future__ import annotations

import json
from pathlib import Path

import duckdb

from ..combined_preprocessing.builder import require_safe_output_location
from ..combined_preprocessing.cohort_source import open_cohort_source
from ..pipeline.final_features import (
    LEGACY_ETHNICITY_CODES,
    LEGACY_LOCATION_CODES,
    LEGACY_RACE_CODES,
    LEGACY_SEX_CODES,
)
from .compatibility import artifact_inventory, digest, file_identity, no_symlinks

FEATURE_CONTRACT_VERSION = "1.0"
DOMAINS = {
    "diagnosis": 730,
    "labs": 365,
    "vitals": 365,
    "procedure": 730,
    "medications": 730,
}
HISTORY_LIMITATION = (
    "Observation span does not establish continuous capture. All-history "
    "components use all records captured in the canonical export, not lifetime history."
)


def _case(column, mapping):
    from .builder import literal

    terms = " ".join(
        f"WHEN {literal(k)} THEN {v}" for k, v in mapping.items() if isinstance(v, int)
    )
    return f"CASE {column} {terms} ELSE NULL END"


def coverage_tables(db):
    """Cheap patient/composite-encounter checks; no clinical evidence expansion."""
    from .builder import literal

    expressions = [
        f'{_case("p." + raw, mapping)} AS "{name}"'
        for name, raw, mapping in (
            ("sex", "sex", LEGACY_SEX_CODES),
            ("race", "race", LEGACY_RACE_CODES),
            ("ethnicity", "ethnicity", LEGACY_ETHNICITY_CODES),
            ("location", "patient_regional_location", LEGACY_LOCATION_CODES),
        )
    ]
    db.execute(
        "CREATE TABLE source_demographics AS SELECT DISTINCT p.patient_id, "
        + ",".join(expressions)
        + " FROM preprocessed.source_patient p "
        "SEMI JOIN legacy_base b USING(patient_id)"
    )
    # Require corroborating attributes beyond matching de-identified strings.
    db.execute("""
        CREATE TABLE key_coverage AS
        WITH demographics AS (
            SELECT b.pat_enc_hash, count(p.patient_id)>0 AS patient_linked,
                   coalesce(bool_or(b.sex IS NOT DISTINCT FROM p.sex
                     AND b.race IS NOT DISTINCT FROM p.race
                     AND b.ethnicity IS NOT DISTINCT FROM p.ethnicity
                     AND b.location IS NOT DISTINCT FROM p.location),false)
                     AS demographics_agree
            FROM legacy_base b LEFT JOIN source_demographics p USING(patient_id)
            GROUP BY b.pat_enc_hash
        ), encounters AS (
            SELECT b.pat_enc_hash, count(e.encounter_id)>0 AS encounter_linked,
                   coalesce(bool_or(DATE '1960-01-01'
                       + cast(b.encounter_date AS INTEGER)
                       >= e.start_datetime::DATE AND
                       (e.end_datetime IS NULL OR
                        DATE '1960-01-01' + cast(b.encounter_date AS INTEGER)
                        <= e.end_datetime::DATE)),false) AS anchor_in_encounter
            FROM legacy_base b LEFT JOIN preprocessed.source_encounter e
              ON b.patient_id=e.patient_id AND b.encounter_id=e.encounter_id
            GROUP BY b.pat_enc_hash
        )
        SELECT * FROM demographics JOIN encounters USING(pat_enc_hash)
    """)
    corroboration = db.execute("""
        SELECT count(*), count(*) FILTER(WHERE patient_linked),
          count(*) FILTER(WHERE patient_linked AND NOT demographics_agree),
          count(*) FILTER(WHERE encounter_linked),
          count(*) FILTER(WHERE encounter_linked AND NOT anchor_in_encounter)
        FROM key_coverage
    """).fetchone()
    # A mismatch remains a diagnosis gate, never an automatic source remapping.
    passed = corroboration[1] > 0 and corroboration[2] == 0 and corroboration[4] == 0
    selects = []
    for domain, days in DOMAINS.items():
        selects.append(f"""
            SELECT b.pat_enc_hash AS index_event_id, b.patient_id, b.encounter_id,
                {literal(domain)} AS domain, {days} AS baseline_lookback_days,
                k.patient_linked, k.demographics_agree, k.encounter_linked,
                k.anchor_in_encounter, o.first_event_datetime, o.last_event_datetime,
                o.event_count AS captured_patient_record_count,
                CASE WHEN NOT EXISTS (
                    SELECT 1 FROM preprocessed.canonical_source_file_audit
                    WHERE logical_domain={literal(domain)}) THEN 'unavailable_domain'
                  WHEN NOT k.patient_linked OR o.patient_id IS NULL
                    THEN 'incomplete_capture'
                  WHEN o.first_event_datetime::DATE > DATE '1960-01-01'
                    + cast(b.encounter_date AS INTEGER) - INTERVAL {days} DAY
                    OR o.last_event_datetime::DATE < DATE '1960-01-01'
                    + cast(b.encounter_date AS INTEGER) THEN 'incomplete_capture'
                  ELSE 'observed_span' END AS history_state
            FROM legacy_base b JOIN key_coverage k ON b.pat_enc_hash=k.pat_enc_hash
            LEFT JOIN preprocessed.patient_observability o
              ON b.patient_id=o.patient_id AND o.logical_domain={literal(domain)}
        """)
    db.execute(
        "CREATE TABLE encounter_source_coverage AS " + " UNION ALL ".join(selects)
    )
    states = db.execute(
        "SELECT domain, history_state, count(*) FROM encounter_source_coverage "
        "GROUP BY 1,2 ORDER BY 1,2"
    ).fetchall()
    return {
        "pass": passed,
        "rows": corroboration[0],
        "patient_linked": corroboration[1],
        "demographic_disagreements": corroboration[2],
        "encounter_linked": corroboration[3],
        "anchor_disagreements": corroboration[4],
        "history_states": [dict(domain=d, state=s, rows=n) for d, s, n in states],
        "limitation": HISTORY_LIMITATION,
        "cache_policy": "Fresh projections of the complete canonical source "
        "for restored patients; failed-build caches are not reused",
    }


def build_coverage(*, database, legacy_bundle, legacy_acceptance, output_dir):
    from .builder import VARIANTS, literal

    database = no_symlinks(database)
    before = file_identity(database)
    legacy = no_symlinks(legacy_bundle)
    manifest_hash = digest(legacy / "manifest.json")
    gate = json.loads(Path(legacy_acceptance).read_text())
    if not gate.get("pass") or gate.get("bundle_manifest_sha256") != manifest_hash:
        raise ValueError("Legacy population/value acceptance required before coverage")
    manifest = json.loads((legacy / "manifest.json").read_text())
    output = no_symlinks(output_dir)
    require_safe_output_location(output, artifact_label="encounter source coverage")
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    with open_cohort_source(database) as source:
        source_metadata = source.metadata.to_dict()
    reports = {}
    for variant in VARIANTS:
        base = legacy / f"encounter_features_{variant.lower()}.parquet"
        if digest(base) != manifest["outputs"][base.name]["sha256"]:
            raise ValueError("Legacy base changed after acceptance")
        scratch = output / ("." + variant)
        scratch.mkdir()
        with duckdb.connect(str(scratch / "coverage.duckdb")) as db:
            db.execute("SET memory_limit='1024MiB'")
            db.execute("SET threads=1")
            db.execute("SET temp_directory=?", [str(scratch / "spill")])
            db.execute(f"ATTACH {literal(database)} AS preprocessed (READ_ONLY)")
            db.execute(
                "CREATE VIEW legacy_base AS "
                f"SELECT * FROM read_parquet({literal(base)})"
            )
            reports[variant] = coverage_tables(db)
            target = output / f"{variant}_source_coverage.parquet"
            db.execute(
                f"COPY encounter_source_coverage TO {literal(target)} "
                "(FORMAT PARQUET, COMPRESSION ZSTD)"
            )
        from ..filesystem import remove_tree_strict

        remove_tree_strict(scratch)
    if (
        before != file_identity(database)
        or digest(legacy / "manifest.json") != manifest_hash
    ):
        raise ValueError("Source changed during coverage validation")
    result = {
        "contract_version": FEATURE_CONTRACT_VERSION,
        "pass": all(r["pass"] for r in reports.values()),
        "source": source_metadata,
        "source_file_identity": before,
        "legacy_manifest_sha256": manifest_hash,
        "variants": reports,
        "outputs": artifact_inventory(output),
    }
    (output / "coverage.json").write_text(json.dumps(result, indent=2) + "\n")
    if not result["pass"]:
        raise ValueError(
            "Source linkage corroboration failed; inspect private coverage report"
        )
    return result

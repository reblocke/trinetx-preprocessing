"""Build versioned encounter features from the accepted canonical source."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import logging
import os
import shutil
import tempfile
from collections.abc import Mapping
from dataclasses import asdict
from pathlib import Path

import duckdb
import pandas as pd

from ..clinical_sources.concept_sets import default_catalog_directory, load_concept_sets
from ..combined_preprocessing.cohort_source import open_cohort_source
from ..combined_preprocessing.contract import compatibility_outputs
from . import feature_sources as features
from . import source_projection as projection
from .compatibility import file_identity, no_symlinks, read_frame, validate_companion
from .config import FeatureConfig
from .element_features import add_availability_inventory, build_element_evidence
from .legacy.per_file_cleaning import RfsFamily, clean_per_file
from .legacy.pipeline import SETTINGS
from .legacy.raw_schema import load_schema

SCHEMA_VERSION = "2.0"
VARIANTS = {"FULL_DATA": "BEFORE", "AFTER_EXCLUSION": "AFTER"}
SUMMARY_TABLES = {
    "element_summary": "source",
    "diagnosis_component_summary": "diagnosis",
    "procedure_component_summary": "procedure",
    "component_lab_summary": "lab",
    "component_bp_summary": "bp",
    "medication_component_summary": "medication",
    "component_observability_summary": "observability",
}
EVIDENCE_TABLES = (
    "encounter_element_evidence",
    "diagnosis_component_evidence",
    "procedure_component_evidence",
    "component_lab_evidence",
    "component_bp_evidence",
    "medication_component_evidence",
)
LOGGER = logging.getLogger(__name__)


def ident(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def literal(value: object) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def code_identity() -> str:
    package = Path(__file__).resolve().parents[1]
    h = hashlib.sha256()
    for path in sorted(package.rglob("*.py")):
        h.update(str(path.relative_to(package)).encode())
        h.update(path.read_bytes())
    h.update((Path(__file__).parent / "legacy/raw_schema.json").read_bytes())
    return h.hexdigest()


class CompatibilityFrames(Mapping):
    """Load each ordered compatibility projection once, without CSV roundtrips."""

    def __init__(self, connection, suffix, key_sink=None):
        self.connection = connection
        self.key_sink = key_sink
        if key_sink is not None:
            key_sink.execute(
                "CREATE TABLE cleaned_source_keys (pat_enc_hash VARCHAR, "
                "patient_id VARCHAR, encounter_id VARCHAR)"
            )
        self.schema = load_schema()
        self.outputs = {
            (RfsFamily(output.category), setting): output
            for output in compatibility_outputs()
            if output.variant == suffix
            for setting, code in zip(SETTINGS, ("AMB", "EMER", "INPAT"), strict=True)
            if output.setting == code
        }
        self.consumed = set()

    def __len__(self):
        return len(self.outputs)

    def __iter__(self):
        return iter(self.outputs)

    def __getitem__(self, key):
        if key in self.consumed:
            raise ValueError("Compatibility projection consumed twice")
        output = self.outputs[key]
        LOGGER.info("Reading authenticated compatibility partition %s", output.key)
        raw = read_frame(self.connection, output.key)
        LOGGER.info("Completed compatibility read %s: %s rows", output.key, len(raw))
        if tuple(raw.columns) != tuple(c.raw_name for c in self.schema.columns):
            raise ValueError(
                "Canonical compatibility schema differs from accepted port"
            )
        self.consumed.add(key)
        result = clean_per_file(
            raw,
            schema=self.schema,
            setting=key[1],
            raw_suffix=output.variant,
            family=key[0],
        )
        LOGGER.info("Completed compatibility cleaning %s", output.key)
        if self.key_sink is not None:
            keys = result.frame[["pat_enc_hash", "patient_id", "encounter_id"]]
            self.key_sink.register("_cleaned_keys", keys)
            self.key_sink.execute(
                "INSERT INTO cleaned_source_keys SELECT DISTINCT * FROM _cleaned_keys"
            )
            self.key_sink.unregister("_cleaned_keys")
        return result


def _create_encounter_context_source(connection):
    # BP evidence needs only encounter type for keys present in vital records.
    # Avoid sorting every wide historical encounter row for candidate patients.
    # Keep the original first-row rule, including NULL type on the selected row.
    connection.execute("""
        CREATE TEMP TABLE encounter_context_source AS
        SELECT patient_id, encounter_id, type FROM (
            SELECT source.patient_id, source.encounter_id, source.type,
                   row_number() OVER (
                       PARTITION BY source.patient_id, source.encounter_id
                       ORDER BY source.encounter_start, source.source_record_hash
                   ) AS observed_order
            FROM source_encounter AS source
            SEMI JOIN source_vital_measurement AS vital
              ON source.patient_id = vital.patient_id
             AND source.encounter_id = vital.encounter_id
            WHERE source.patient_id IS NOT NULL AND source.encounter_id IS NOT NULL
        ) WHERE observed_order = 1
    """)


def _materialize_features(connection, catalog, config):
    projection._require_matching_glp1_catalog(connection, catalog)
    connection.execute(
        "CREATE TEMP TABLE gas_candidate_patient AS SELEC"
        "T DISTINCT patient_id FROM encounter_anchor"
    )
    connection.execute(
        "CREATE TEMP TABLE gas_candidate_encounter AS SEL"
        "ECT DISTINCT encounter_id FROM encounter_anchor"
    )
    rows = pd.DataFrame([asdict(concept) for concept in catalog.concepts])
    connection.register("_concepts", rows)
    connection.execute("CREATE TABLE concept_set AS SELECT * FROM _concepts")
    connection.unregister("_concepts")
    LOGGER.info("Materializing canonical lab source")
    projection._create_lab_source(connection, catalog=catalog)
    LOGGER.info("Completed canonical lab source; materializing encounters/patients")
    projection._create_encounter_source(connection)
    projection._create_patient_source(connection)
    LOGGER.info("Completed canonical encounters/patients")
    for name in (
        "source_vital_measurement",
        "source_diagnosis",
        "source_procedure",
        "source_medication",
    ):
        LOGGER.info("Materializing %s", name)
        projection._create_patient_concept_source(connection, name, catalog=catalog)
        LOGGER.info("Completed %s", name)
    _create_encounter_context_source(connection)
    LOGGER.info("Completed bounded encounter context")
    for output_domain, stored_domain, days in (
        ("diagnosis", "diagnosis", 730),
        ("labs", "labs", 365),
        ("vitals", "vitals", None),
        ("procedure", "procedure", None),
        ("medication", "medications", 730),
    ):
        projection._create_observability_table(
            connection,
            output_domain=output_domain,
            stored_domain=stored_domain,
            lookback_days=days,
        )
        LOGGER.info("Completed %s observability", output_domain)
    LOGGER.info("Building diagnosis evidence")
    features._build_diagnosis_evidence(connection, config)
    LOGGER.info("Completed diagnosis evidence; building procedure evidence")
    features._build_procedure_evidence(connection, config)
    LOGGER.info("Completed procedure evidence; normalizing component labs")
    features._build_normalized_component_labs(connection)
    features._build_lab_summary(connection, config)
    LOGGER.info("Completed component labs; building blood pressure evidence")
    features._build_blood_pressure_summary(connection, config)
    LOGGER.info("Completed blood pressure evidence; building medication evidence")
    features._build_medication_evidence(connection, config)
    LOGGER.info("Completed medication evidence; building observability summary")
    features._build_observability_summary(connection)
    LOGGER.info("Completed observability; building source-element evidence")
    result = build_element_evidence(connection, config)
    LOGGER.info("Completed source-element evidence")
    return result


def _enrich(
    database,
    base_path,
    destination,
    scratch,
    suffix,
    catalog,
    config,
    coverage_path=None,
):
    connection = duckdb.connect(str(scratch / "features.duckdb"))
    try:
        connection.execute("SET memory_limit = '2816MiB'")
        connection.execute("SET threads = 1")
        connection.execute("SET preserve_insertion_order = false")
        connection.execute("SET temp_directory = ?", [str(scratch / "spill")])
        connection.execute(f"ATTACH {literal(database)} AS preprocessed (READ_ONLY)")
        connection.execute(
            "CREATE VIEW legacy_base AS "
            f"SELECT * FROM read_parquet({literal(base_path)})"
        )
        connection.execute(
            "CREATE TABLE source_keys AS SELECT pat_enc_hash, patient_id, "
            "encounter_id FROM legacy_base"
        )
        duplicate = connection.execute(
            "SELECT count(*) FROM (SELECT pat_enc_hash FROM s"
            "ource_keys GROUP BY 1 HAVING count(*) <> 1)"
        ).fetchone()[0]
        if duplicate:
            raise ValueError(
                "Legacy hash cannot uniquely identify source patient-encounter keys"
            )
        connection.execute("""
            CREATE TABLE encounter_anchor AS
            SELECT base.pat_enc_hash AS index_event_id,
                   keys.patient_id, keys.encounter_id,
                   DATE '1960-01-01' + cast(base.encounter_date AS INTEGER)
                       AS index_date
            FROM legacy_base AS base LEFT JOIN source_keys AS keys USING (pat_enc_hash)
        """)
        if connection.execute(
            "SELECT count(*) FROM encounter_anchor WHERE pati"
            "ent_id IS NULL OR encounter_id IS NULL"
        ).fetchone()[0]:
            raise ValueError("Encounter feature source-key linkage is incomplete")
        if coverage_path is not None:
            connection.execute(
                "CREATE VIEW encounter_source_coverage AS "
                f"SELECT * FROM read_parquet({literal(coverage_path)})"
            )
        element_inventory = _materialize_features(connection, catalog, config)
        if coverage_path is not None:
            element_inventory = add_availability_inventory(
                connection, element_inventory
            )
        (destination.parent / f"{destination.stem}_element_inventory.json").write_text(
            json.dumps(element_inventory, indent=2) + "\n"
        )
        select = [
            "base.* EXCLUDE (patient_id, encounter_id)",
            "anchor.patient_id",
            "anchor.encounter_id",
            "anchor.index_date AS encounter_anchor_date",
        ]
        joins = []
        dictionary = []
        for number, (table, prefix) in enumerate(SUMMARY_TABLES.items()):
            columns = connection.execute(f"DESCRIBE {ident(table)}").fetchall()
            alias = f"feature{number}"
            if connection.execute(
                f"SELECT count(*) FROM (SELECT index_event_id FROM {ident(table)} "
                "GROUP BY 1 HAVING count(*) > 1)"
            ).fetchone()[0]:
                raise ValueError("Feature summary has duplicate encounter keys")
            joins.append(
                f"LEFT JOIN {ident(table)} AS {alias} "
                f"ON {alias}.index_event_id = anchor.index_event_id"
            )
            for column, *_ in columns:
                if column == "index_event_id":
                    continue
                name = (
                    f"source_{column}"
                    if table == "element_summary"
                    else f"glp1_{prefix}_{column}"
                )
                select.append(f"{alias}.{ident(column)} AS {ident(name)}")
                dictionary.append(
                    {"column": name, "source": table, "source_column": column}
                )
        query = (
            "SELECT "
            + ", ".join(select)
            + " FROM legacy_base AS base JOIN encounter_anchor AS anchor "
            "ON base.pat_enc_hash = anchor.index_event_id " + " ".join(joins)
        )
        connection.execute(
            f"COPY ({query}) TO {literal(destination)} "
            "(FORMAT PARQUET, COMPRESSION ZSTD)"
        )
        counts = connection.execute(
            "SELECT count(*), count(DISTINCT (patient_id,encounter_id)) "
            f"FROM read_parquet({literal(destination)})"
        ).fetchone()
        sources = {entry["column"]: entry for entry in dictionary}
        dictionary = [
            {
                "column": column,
                "dtype": dtype,
                **sources.get(column, {"source": "accepted_legacy_transformation"}),
                "missing": "Unavailable; never interpreted as clinical absence",
            }
            for column, dtype, *_ in connection.execute(
                f"DESCRIBE SELECT * FROM read_parquet({literal(destination)})"
            ).fetchall()
        ]
        for entry in dictionary:
            column = entry["column"]
            entry["anchor_precision"] = "calendar day"
            entry["anchor"] = "legacy encounter_date; not admission or blood-gas time"
            entry["row_order"] = "Consumer must sort by patient_id, encounter_id"
            if column.startswith("source_element_"):
                entry["temporal_rule"] = (
                    "Inclusive 365-day measurements or 730-day other domains; "
                    "same-encounter context retained outside baseline; latest "
                    "raw values require in_baseline_window"
                )
                entry["value_units"] = "Raw values; latest_unit identifies source units"
                entry["source_dates"] = (
                    "event_datetime and timestamp_precision in catalog evidence"
                )
                entry["availability"] = (
                    "encounter_source_coverage by index_event_id and domain"
                )
            elif column.startswith("glp1_"):
                source_name = entry.get("source_column", "")
                all_history = (
                    column.startswith("glp1_diagnosis_")
                    and source_name in features.ALL_HISTORY_DIAGNOSIS_COMPONENTS
                ) or (
                    column.startswith("glp1_procedure_")
                    and source_name in features.ALL_HISTORY_PROCEDURE_COMPONENTS
                )
                entry["temporal_rule"] = (
                    "All captured history on or before the anchor day"
                    if all_history
                    else "Component-specific inclusive calendar-day windows; "
                    "diagnosis/procedure 730 days, labs/BP 365 days, medications "
                    "730 days history and 365 days follow-up; follow-up is context"
                )
                entry["value_units"] = (
                    "Normalized component values; rules in feature_sources.py"
                    if column.startswith(("glp1_lab_", "glp1_bp_"))
                    else "Records, indicators or dates; no clinical-absence inference"
                )
                entry["source_dates"] = (
                    "event_datetime and raw source dates retained in component evidence"
                )
                entry["availability"] = (
                    "encounter_source_coverage; observed span is not continuous capture"
                )
            if entry["column"] in {"patient_id", "encounter_id"}:
                entry["source"] = "authenticated_compatibility_source_identity"
            elif entry["column"] == "encounter_anchor_date":
                entry["source"] = "legacy encounter_date; Stata days since 1960-01-01"
        original = connection.execute("SELECT count(*) FROM legacy_base").fetchone()[0]
        if counts != (original, original):
            raise ValueError("Enrichment changed encounter membership or uniqueness")
        # Retain normalized dates, units, source hashes and raw evidence without
        # embedding repeated observations into the one-row-per-encounter product.
        for table in EVIDENCE_TABLES:
            path = destination.parent / f"{destination.stem}_{table}.parquet"
            connection.execute(
                f"COPY {ident(table)} TO {literal(path)} "
                "(FORMAT PARQUET, COMPRESSION ZSTD)"
            )
        missingness = (
            connection.execute(
                "SELECT "
                + ", ".join(
                    f"count(*) FILTER (WHERE {ident(row[0])} IS NULL) "
                    f"AS {ident(row[0])}"
                    for row in connection.execute(
                        f"DESCRIBE SELECT * FROM read_parquet({literal(destination)})"
                    ).fetchall()
                )
                + f" FROM read_parquet({literal(destination)})"
            )
            .fetchdf()
            .iloc[0]
            .to_dict()
        )
        return {
            "rows": original,
            "unique_encounters": original,
            "null_counts": {k: int(v) for k, v in missingness.items()},
        }, dictionary
    finally:
        connection.close()


def build_encounters(
    *,
    database: Path,
    compatibility_database: Path,
    legacy_bundle: Path,
    legacy_acceptance: Path,
    coverage_bundle: Path,
    output_dir: Path,
    concept_sets_dir: Path | None = None,
):
    """Publish both variants atomically; never overwrite inputs or accepted output."""
    from ..combined_preprocessing.builder import require_safe_output_location

    database = Path(database).absolute()
    output = Path(output_dir).absolute()
    if output.exists():
        raise FileExistsError("Encounter output already exists")
    companion = no_symlinks(compatibility_database)
    companion_identity = file_identity(companion)
    companion_metadata = validate_companion(companion)
    legacy_bundle = no_symlinks(legacy_bundle)
    base_manifest_path = legacy_bundle / "manifest.json"
    base_manifest = json.loads(base_manifest_path.read_text())
    gate = json.loads(Path(legacy_acceptance).read_text())
    if (
        base_manifest.get("kind") != "legacy_base"
        or base_manifest.get("status") != "complete"
        or base_manifest["compatibility"] != companion_metadata
        or gate.get("bundle_manifest_sha256") != sha256(base_manifest_path)
        or not gate.get("pass")
        or set(gate.get("variants", {})) != set(VARIANTS)
        or not all(v["pass"] for v in gate["variants"].values())
    ):
        raise ValueError("Authenticated legacy population/value gate is required")
    legacy_metadata = json.loads((legacy_bundle / "legacy_metadata.json").read_text())
    coverage_bundle = no_symlinks(coverage_bundle)
    coverage = json.loads((coverage_bundle / "coverage.json").read_text())
    if (
        not coverage.get("pass")
        or coverage.get("contract_version") != "1.0"
        or coverage.get("legacy_manifest_sha256") != sha256(base_manifest_path)
        or tuple(coverage.get("source_file_identity", ())) != file_identity(database)
    ):
        raise ValueError("Source linkage/history coverage gate is required")
    for name, info in coverage["outputs"].items():
        if sha256(coverage_bundle / name) != info["sha256"]:
            raise ValueError("Source coverage artifact changed")
    for name, info in base_manifest["outputs"].items():
        if sha256(legacy_bundle / name) != info["sha256"]:
            raise ValueError("Legacy base changed after acceptance")
    for path in (database, output, *database.parents, *output.parents):
        if path.is_symlink():
            raise ValueError("Encounter source/output paths must not contain symlinks")
    require_safe_output_location(output, artifact_label="encounter feature output")
    if output.exists():
        raise FileExistsError("Encounter output already exists")
    if output == database.parent or database.is_relative_to(output):
        raise ValueError("Encounter output overlaps its source")
    output.parent.mkdir(parents=True, exist_ok=True)
    catalog_path = concept_sets_dir or default_catalog_directory()
    catalog = load_concept_sets(catalog_path)
    config = FeatureConfig()
    before = database.stat()
    identity = code_identity()
    from ..combined_preprocessing.database import COMBINED_MANIFEST_FILENAME

    sidecar = database.parent / COMBINED_MANIFEST_FILENAME
    source_manifest_hash = sha256(sidecar)
    # Validation precedes publication and any clinical transformation.
    with open_cohort_source(database) as source:
        source_metadata = source.metadata.to_dict()
        required_elements = [
            row[0]
            for row in source.connection.execute(
                "SELECT element_id FROM element_catalog "
                "WHERE starts_with(element_id,'source.') ORDER BY element_id"
            ).fetchall()
        ]
        if catalog.sha256 != source.metadata.glp1_catalog_sha256:
            raise ValueError("Encounter terminology differs from the validated source")
    staging = Path(
        tempfile.mkdtemp(prefix=f".{output.name}.encounters-", dir=output.parent)
    )
    os.chmod(staging, 0o700)
    try:
        qa = {}
        dictionary = {}
        for variant, suffix in VARIANTS.items():
            LOGGER.info("Building encounter variant %s", variant)
            scratch = staging / f".{variant}"
            scratch.mkdir()
            base_path = legacy_bundle / f"encounter_features_{variant.lower()}.parquet"
            metadata = legacy_metadata[variant]
            destination = staging / f"encounter_features_{variant.lower()}.parquet"
            LOGGER.info("Enriching source evidence for %s", variant)
            qa[variant], dictionary[variant] = _enrich(
                database,
                base_path,
                destination,
                scratch,
                suffix,
                catalog,
                config,
                coverage_bundle / f"{variant}_source_coverage.parquet",
            )
            shutil.copyfile(
                coverage_bundle / f"{variant}_source_coverage.parquet",
                staging
                / (
                    f"encounter_features_{variant.lower()}"
                    "_encounter_source_coverage.parquet"
                ),
            )
            for entry in dictionary[variant]:
                name = entry["column"]
                if name in {"legacy_patient_id", "legacy_encounter_id"}:
                    name = name.removeprefix("legacy_")
                label_name = metadata["variable_value_labels"].get(name)
                entry["label"] = metadata["variable_labels"].get(name)
                entry["value_labels"] = metadata["value_label_definitions"].get(
                    label_name, {}
                )
                entry["legacy_display_format"] = metadata["display_formats"].get(name)
            # This directory contains only scratch created by this build.
            from ..filesystem import remove_tree_strict

            remove_tree_strict(scratch)
            LOGGER.info("Completed %s: %s encounters", variant, qa[variant]["rows"])
        (staging / "data_dictionary.json").write_text(
            json.dumps(dictionary, indent=2) + "\n"
        )
        (staging / "quality_summary.json").write_text(json.dumps(qa, indent=2) + "\n")
        (staging / "source_coverage.json").write_text(
            json.dumps(coverage, indent=2) + "\n"
        )
        source_after = database.stat()
        if (
            (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
            != (
                source_after.st_dev,
                source_after.st_ino,
                source_after.st_size,
                source_after.st_mtime_ns,
            )
            or file_identity(companion) != companion_identity
            or code_identity() != identity
            or sha256(sidecar) != source_manifest_hash
        ):
            raise ValueError("Source or implementation changed during build")
        inventory = {
            p.name: {"sha256": sha256(p), "bytes": p.stat().st_size}
            for p in sorted(staging.iterdir())
            if p.is_file()
        }
        manifest = {
            "schema_version": SCHEMA_VERSION,
            "runtime": {
                name: importlib.metadata.version(name)
                for name in ("numpy", "pandas", "duckdb", "pyarrow")
            },
            "status": "complete",
            "source": source_metadata,
            "source_manifest_sha256": source_manifest_hash,
            "compatibility": companion_metadata,
            "legacy_gate_sha256": sha256(Path(legacy_acceptance)),
            "legacy_bundle_manifest_sha256": sha256(base_manifest_path),
            "kind": "encounter_features",
            "feature_contract_version": "1.0",
            "required_source_elements": required_elements,
            "row_order": "Unspecified; consumers must sort by patient_id, encounter_id",
            "code_sha256": identity,
            "windows": asdict(config),
            "variants": qa,
            "outputs": inventory,
            "unit": "patient_id + encounter_id",
            "boundary": "Measurements and evidence only; no GLP-1 eligibi"
            "lity or propensity models",
        }
        (staging / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        if output.exists():
            raise FileExistsError("Encounter output appeared during build")
        staging.rename(output)
        return manifest
    except BaseException as exc:
        (staging / "failure.json").write_text(
            json.dumps({"status": "failed", "error_type": type(exc).__name__}) + "\n"
        )
        raise

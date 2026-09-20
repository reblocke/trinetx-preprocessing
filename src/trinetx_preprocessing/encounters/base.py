"""Independent legacy variants, stopped before clinical enrichment."""

from __future__ import annotations

import gc
import json
import logging
import os
import tempfile
from dataclasses import asdict
from pathlib import Path

import duckdb

from ..combined_preprocessing.builder import require_safe_output_location
from .compatibility import digest, file_identity, no_symlinks, validate_companion
from .legacy.measurement import apply_pre_model_transformations
from .legacy.pipeline import assemble_analysis_base


def publish_keyed_base(connection, base_path, destination):
    """Carry keys retained by the cleaner through the accepted hash-key merges."""
    from .builder import literal

    connection.execute(
        "CREATE TABLE source_keys AS SELECT DISTINCT * FROM cleaned_source_keys"
    )
    if connection.execute(
        "SELECT count(*) FROM (SELECT pat_enc_hash FROM source_keys "
        "GROUP BY 1 HAVING count(*)<>1)"
    ).fetchone()[0]:
        raise ValueError("Legacy hash cannot uniquely identify original composite keys")
    if connection.execute(
        "SELECT count(*) FROM source_keys WHERE coalesce(patient_id,'')='' "
        "OR coalesce(encounter_id,'')='' "
        "OR pat_enc_hash IS DISTINCT FROM trim(concat(patient_id,'-',encounter_id),' ')"
    ).fetchone()[0]:
        raise ValueError("Original source keys are blank or inconsistent")
    connection.execute(
        f"CREATE VIEW legacy_base AS SELECT * FROM read_parquet({literal(base_path)})"
    )
    n, unique = connection.execute(
        "SELECT count(*),count(DISTINCT pat_enc_hash) FROM legacy_base"
    ).fetchone()
    if (
        n != unique
        or connection.execute(
            "SELECT count(*) FROM legacy_base ANTI JOIN source_keys USING(pat_enc_hash)"
        ).fetchone()[0]
    ):
        raise ValueError("Legacy base source-key linkage is incomplete or nonunique")
    connection.execute(
        "COPY (SELECT base.* EXCLUDE(patient_id,encounter_id), "
        "base.patient_id AS legacy_patient_id, "
        "base.encounter_id AS legacy_encounter_id, "
        "keys.patient_id, keys.encounter_id FROM legacy_base base "
        "JOIN source_keys keys USING(pat_enc_hash)) "
        f"TO {literal(destination)} (FORMAT PARQUET, COMPRESSION ZSTD)"
    )
    return n


def build_legacy_bases(*, compatibility_database, output_dir):
    from .builder import VARIANTS, CompatibilityFrames, code_identity

    companion = no_symlinks(compatibility_database)
    source = validate_companion(companion)
    before = file_identity(companion)
    output = no_symlinks(output_dir)
    require_safe_output_location(output, artifact_label="legacy encounter base")
    if output.exists():
        raise FileExistsError("Legacy base destination already exists")
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(prefix=f".{output.name}.legacy-", dir=output.parent)
    )
    identity = code_identity()
    metadata, counts = {}, {}
    for variant, suffix in VARIANTS.items():
        logging.info("Building legacy base %s", variant)
        scratch = staging / ("." + variant)
        scratch.mkdir()
        with duckdb.connect(str(scratch / "keys.duckdb")) as keys:
            keys.execute("SET memory_limit='512MiB'")
            keys.execute("SET threads=1")
            keys.execute("SET temp_directory=?", [str(scratch / "spill")])
            with duckdb.connect(str(companion), read_only=True) as db:
                db.execute("SET memory_limit='512MiB'")
                db.execute("SET threads=1")
                inputs = CompatibilityFrames(db, suffix, key_sink=keys)
                result = assemble_analysis_base(inputs)
                if len(inputs.consumed) != 18:
                    raise ValueError("Legacy variant did not consume every partition")
            if variant == "AFTER_EXCLUSION":
                logging.info("Applying accepted AFTER_EXCLUSION imputation")
                result = apply_pre_model_transformations(result, take_ownership=True)
            metadata[variant] = asdict(result.metadata)
            base_path = scratch / "legacy_base.parquet"
            result.frame.to_parquet(base_path, index=False)
            del result, inputs
            gc.collect()
            counts[variant] = publish_keyed_base(
                keys,
                base_path,
                staging / f"encounter_features_{variant.lower()}.parquet",
            )
        logging.info(
            "Completed legacy base %s: %s encounters", variant, counts[variant]
        )
        from ..filesystem import remove_tree_strict

        remove_tree_strict(scratch)
    (staging / "legacy_metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
    if before != file_identity(companion) or identity != code_identity():
        raise ValueError("Companion or implementation changed during legacy build")
    manifest = {
        "schema_version": "2.0",
        "status": "complete",
        "kind": "legacy_base",
        "compatibility": source,
        "code_sha256": identity,
        "rows": counts,
        "row_order": "Unspecified; consumers must sort by patient_id, encounter_id",
        "outputs": {
            p.name: {"sha256": digest(p), "bytes": p.stat().st_size}
            for p in staging.iterdir()
            if p.is_file()
        },
    }
    (staging / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    os.replace(staging, output)
    return manifest

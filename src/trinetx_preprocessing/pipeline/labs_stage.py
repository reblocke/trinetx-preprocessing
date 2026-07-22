"""Lab-results stage runner built from legacy notebook logic."""

from __future__ import annotations

import json
import logging
import re
from contextlib import ExitStack
from dataclasses import asdict
from pathlib import Path

import pandas as pd

from ..combined_preprocessing.elements import (
    ElementCaptureWriter,
    available_source_columns,
)
from ..config import Config, ConfigError, collect_domain_paths
from ..filesystem import write_text_atomic
from ..guardrails import log_row_count
from ..io.csv import iter_csv
from ..storage import WorkTableWriter
from ..transform.lab_features import (
    LAB_FEATURE_SOURCE_COLUMN,
    classify_lab_feature_rows,
    stack_lab_feature_rows,
)
from ..transform.labs import LAB_COLUMNS, RAW_LAB_COLUMNS, normalize_lab_results_chunk
from ..transform.rfs import (
    ABG_VALUE_MAX,
    RFS_EVENT_COLUMNS,
    VBG_VALUE_MAX,
    derive_lab_rfs_event_frames_with_audit,
)
from .analysis_index import RFS_CATEGORY_COLUMN, stack_rfs_events

RAW_DTYPE = {
    "patient_id": "string",
    "encounter_id": "string",
    "code_system": "string",
    "code": "string",
    "lab_result_text_val": "string",
    "units_of_measure": "string",
    "derived_by_TriNetX": "string",
    "source_id": "string",
}


def run_labs_stage(config: Config) -> list[Path]:
    """Run the lab-results stage and write outputs under ``work_dir``.

    Args:
        config: Pipeline configuration.

    Returns:
        List of written file paths.
    """

    logger = logging.getLogger(__name__)
    domain_paths = collect_domain_paths(config)
    labs_paths = domain_paths.get("labs")
    if not labs_paths:
        raise ConfigError("Labs domain is not configured.")

    config.work_dir.mkdir(parents=True, exist_ok=True)

    output_paths: list[Path] = []
    chunksize = config.chunking.lines_per_chunk if config.chunking.enabled else None
    rfs_rows = 0
    feature_rows = 0
    availability_rows = 0
    audit_counts = {
        category: {
            "considered": 0,
            "accepted": 0,
            "rejected_code_system": 0,
            "rejected_unit": 0,
            "rejected_non_numeric": 0,
            "rejected_range": 0,
        }
        for category in ("ABG", "VBG")
    }
    with ExitStack() as stack:
        element_writer = stack.enter_context(ElementCaptureWriter(config, "labs"))
        rfs_writer = stack.enter_context(
            WorkTableWriter(config, "analysis_rfs_labs.csv")
        )
        feature_writer = stack.enter_context(
            WorkTableWriter(config, "analysis_lab_features.csv")
        )
        availability_writer = stack.enter_context(
            WorkTableWriter(config, "analysis_lab_availability.csv")
        )
        for index, path in enumerate(labs_paths, start=1):
            logger.info("Reading lab-results export: %s", path.name)
            rows_read = 0
            rows_written = 0
            source_columns = available_source_columns(
                path,
                RAW_LAB_COLUMNS,
                domain="labs",
            )
            with WorkTableWriter(
                config,
                _normalized_filename(path, index),
                enabled=config.storage.emit_normalized_domain_tables,
            ) as writer:
                for chunk in iter_csv(
                    path,
                    chunksize=chunksize,
                    usecols=source_columns,
                    dtype=(
                        {column: "string" for column in source_columns}
                        if config.combined.enabled
                        else RAW_DTYPE
                    ),
                    parse_dates=None if config.combined.enabled else ["date"],
                ):
                    rows_read += len(chunk)
                    element_writer.add_chunk(chunk, source_path=path)
                    normalized = normalize_lab_results_chunk(chunk)
                    rows_written += len(normalized)
                    writer.write(normalized)
                    availability = normalized.loc[:, ["encounter_id"]].dropna()
                    availability = availability.drop_duplicates(keep="first")
                    if not availability.empty:
                        availability_writer.write(availability)
                        availability_rows += len(availability)
                    feature_index = stack_lab_feature_rows(
                        classify_lab_feature_rows(normalized)
                    )
                    if not feature_index.empty:
                        feature_writer.write(feature_index)
                        feature_rows += len(feature_index)
                    events, audits = derive_lab_rfs_event_frames_with_audit(
                        normalized,
                        abg_min_pco2_mmhg=config.rfs.abg_min_pco2_mmhg,
                        vbg_min_pco2_mmhg=config.rfs.vbg_min_pco2_mmhg,
                    )
                    for category, audit in audits.items():
                        for field, count in asdict(audit).items():
                            audit_counts[category][field] += int(count)
                    indexed = stack_rfs_events(
                        events,
                        event_columns=RFS_EVENT_COLUMNS,
                    )
                    if not indexed.empty:
                        rfs_writer.write(indexed)
                        rfs_rows += len(indexed)
                output_paths.extend(writer.written_paths)
                log_row_count(logger, f"labs read {path.name}", rows_read)
                log_row_count(logger, f"labs normalized {path.name}", rows_written)
                if writer.written_paths:
                    logger.info(
                        "Wrote %s rows to %s",
                        rows_written,
                        writer.written_paths[0].name,
                    )
        if rfs_rows == 0:
            rfs_writer.write(
                pd.DataFrame(columns=[RFS_CATEGORY_COLUMN, *RFS_EVENT_COLUMNS])
            )
        if feature_rows == 0:
            feature_writer.write(
                pd.DataFrame(columns=[LAB_FEATURE_SOURCE_COLUMN, *LAB_COLUMNS])
            )
        if availability_rows == 0:
            availability_writer.write(pd.DataFrame(columns=["encounter_id"]))
        output_paths.extend(rfs_writer.written_paths)
        output_paths.extend(feature_writer.written_paths)
        output_paths.extend(availability_writer.written_paths)

    output_paths.extend(element_writer.written_paths)

    audit_payload = {
        "schema_version": 1,
        "ruleset": config.rfs.ruleset,
        "categories": {
            "ABG": {
                "min_pco2_mmhg_exclusive": config.rfs.abg_min_pco2_mmhg,
                "max_pco2_mmhg_exclusive": ABG_VALUE_MAX,
                **audit_counts["ABG"],
            },
            "VBG": {
                "min_pco2_mmhg_exclusive": config.rfs.vbg_min_pco2_mmhg,
                "max_pco2_mmhg_exclusive": VBG_VALUE_MAX,
                **audit_counts["VBG"],
            },
        },
    }
    audit_path = config.work_dir / "rfs_rule_audit.json"
    write_text_atomic(
        audit_path,
        json.dumps(audit_payload, indent=2, sort_keys=True) + "\n",
    )

    return output_paths


def _normalized_filename(path: Path, index: int) -> str:
    match = re.search(r"(\d{4})$", path.stem)
    suffix = match.group(1) if match else f"{index:04}"
    return f"lab_results_NEW_{suffix}.csv"

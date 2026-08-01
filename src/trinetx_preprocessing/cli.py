"""Command-line interface for the preprocessing pipeline."""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Sequence

import yaml

from . import __version__
from .combined_preprocessing.builder import (
    CombinedLockError,
    build_preprocessed,
    export_legacy_compatibility_outputs,
    require_safe_output_location,
)
from .combined_preprocessing.contract import compatibility_outputs
from .combined_preprocessing.database import (
    inspect_combined_database,
)
from .combined_preprocessing.elements import (
    COMBINED_MEDICATION_REQUIRED_COLUMNS,
    is_medication_ingredient_export,
)
from .combined_preprocessing.scratch import (
    COMBINED_SCRATCH_PATH_PREFIXES,
    is_combined_scratch_name,
)
from .combined_preprocessing.validation import validate_preprocessed_database
from .config import (
    Config,
    ConfigError,
    DomainInspection,
    collect_domain_paths,
    inspect_domain_paths,
    load_config,
    pattern_search_dir,
    patterns_search_dir,
    validate_config,
)
from .filesystem import remove_tree_strict, write_text_atomic
from .logging_utils import configure_logging
from .pipeline.diagnosis_stage import run_diagnosis_stage
from .pipeline.encounter_stage import run_encounter_stage
from .pipeline.final_assembly import run_final_assembly
from .pipeline.labs_stage import run_labs_stage
from .pipeline.medications_stage import run_medications_stage
from .pipeline.procedure_stage import run_procedure_stage
from .pipeline.rfs_stage import run_rfs_stage
from .pipeline.run import run_pipeline
from .pipeline.vitals_stage import run_vitals_stage
from .profiling import (
    current_git_code_dirty,
    current_git_code_state_sha256,
    run_profile,
)
from .regression import (
    DEFAULT_CSV_HASH_CHUNK_ROWS,
    HASH_ALGORITHM,
    HASH_MANIFEST_FILENAME,
    HASH_SCOPE_VALUES,
    HASH_SCRATCH_PREFIX,
    ManifestComparisonResult,
    TableHashEntry,
    collect_directory_entries,
    collect_output_entries,
    collect_output_hashes,
    compare_hashes,
    compare_manifest_entries,
    load_hash_manifest,
    load_hash_manifest_entries,
    write_hash_manifest,
)
from .tools.split_csv import split_csv
from .validation import validate_csv_columns
from .work_manifest import (
    DOMAIN_STAGES,
    FINAL_ASSEMBLY_PREREQUISITES,
    StaleWorkError,
    initialize_work_manifest,
    mark_stage_complete,
    mark_stage_started,
    require_current_work,
    require_strict_encounter_work,
)

REQUIRED_COLUMNS: dict[str, list[str]] = {
    "encounter": [
        "encounter_id",
        "patient_id",
        "start_date",
        "end_date",
        "type",
        "start_date_derived_by_TriNetX",
        "end_date_derived_by_TriNetX",
        "derived_by_TriNetX",
        "source_id",
    ],
    "diagnosis": [
        "patient_id",
        "encounter_id",
        "code_system",
        "code",
        "principal_diagnosis_indicator",
        "admitting_diagnosis",
        "reason_for_visit",
        "date",
        "derived_by_TriNetX",
        "source_id",
    ],
    "labs": [
        "patient_id",
        "encounter_id",
        "code_system",
        "code",
        "date",
        "lab_result_num_val",
        "lab_result_text_val",
        "units_of_measure",
        "derived_by_TriNetX",
        "source_id",
    ],
    "meds": [
        "patient_id",
        "encounter_id",
        "unique_id",
        "code_system",
        "code",
        "start_date",
        "route",
        "brand",
        "strength",
        "derived_by_TriNetX",
        "source_id",
    ],
    "procedure": [
        "patient_id",
        "encounter_id",
        "code_system",
        "code",
        "principal_procedure_indicator",
        "date",
        "derived_by_TriNetX",
        "source_id",
    ],
    "vitals": [
        "patient_id",
        "encounter_id",
        "code_system",
        "code",
        "date",
        "value",
        "text_value",
        "units_of_measure",
        "derived_by_TriNetX",
        "source_id",
    ],
    "patient": [
        "patient_id",
        "sex",
        "race",
        "ethnicity",
        "year_of_birth",
        "patient_regional_location",
        "month_year_death",
    ],
}

DEFAULT_DOMAIN_PATTERNS: dict[str, str | tuple[str, ...]] = {
    "encounter": "Encounter/encounter*.csv",
    "diagnosis": "Diagnosis/diagnosis*.csv",
    "labs": "Lab Results/lab_result*.csv",
    "meds": (
        "Medications/medication[0-9]*.csv",
        "Medications/medication_ingredient*.csv",
    ),
    "procedure": "Procedure/procedure*.csv",
    "vitals": "Vital Signs/vital*_signs*.csv",
    "patient": "Patient/patient*.csv",
}

INPUT_STATUS_PATH_SAMPLE_LIMIT = 10
INPUT_STATUS_SCHEMA_VERSION = 1
COMPARISON_REPORT_SCHEMA_VERSION = 1
FINAL_VALIDATION_MIN_FREE_GB = 100.0
REQUIRED_FILESYSTEM_LABELS = ("data_dir", "work_dir", "output_dir")
MANIFEST_METADATA_BLOCKER_SAMPLE_LIMIT = 20
SCRATCH_CLEANUP_SCHEMA_VERSION = 1
SCRATCH_PATH_PREFIXES = (
    HASH_SCRATCH_PREFIX,
    ".trinetx-encounter-reducer-",
    ".trinetx-rfs-membership-",
    ".trinetx-rfs-encounters-",
    ".trinetx-demographics-",
    ".trinetx-final-encounters-",
    ".trinetx-final-cohorts-",
    ".trinetx-final-events-",
    ".trinetx-final-feature-sources-",
    ".trinetx-final-labs-",
    ".trinetx-final-patients-",
    ".trinetx-final-prev-vitals-",
    ".trinetx-data-check-ids-",
    ".trinetx-glp1-concept-ingest-",
    ".trinetx-glp1-observability-scan-",
    ".trinetx-glp1-terminology-qa-",
    ".trinetx-glp1-vital-ingest-",
    *COMBINED_SCRATCH_PATH_PREFIXES,
)
COMBINED_MUTATING_COMMANDS = {
    "run",
    "run-all",
    "build-preprocessed",
    "profile",
    "baseline",
    "compare",
    "run-encounter",
    "run-labs",
    "run-diagnosis",
    "run-meds",
    "run-procedure",
    "run-vitals",
    "run-rfs",
    "run-final-assembly",
}


def _require_safe_combined_mutation_locations(
    config: Config,
    *,
    command: str,
) -> None:
    """Guard every combined route that can write confidential artifacts."""

    if not config.combined.enabled or command not in COMBINED_MUTATING_COMMANDS:
        return
    require_safe_output_location(
        config.work_dir,
        artifact_label="work directory",
    )
    require_safe_output_location(
        config.output_dir,
        artifact_label="output directory",
    )


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser."""

    parser = argparse.ArgumentParser(
        prog="trinetx-preprocessing",
        description=(
            "TriNetX preprocessing pipeline for the hypercapnia cohort.\n"
            "Run the full pipeline with 'run' or individual stages with\n"
            "'run-<stage>' commands."
        ),
        epilog=(
            "Examples:\n"
            "  python -m trinetx_preprocessing --help\n"
            "  python -m trinetx_preprocessing run --config config.yaml\n"
            "  python -m trinetx_preprocessing run-encounter --config config.yaml\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose logging.",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    validate_config_parser = subparsers.add_parser(
        "validate-config",
        help="Validate configuration paths and patterns.",
        description=(
            "Validate that configured directories exist and domain patterns\n"
            "match at least one file."
        ),
        epilog=(
            "Example:\n"
            "  python -m trinetx_preprocessing validate-config --config config.yaml"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    validate_config_parser.add_argument(
        "--config",
        type=Path,
        required=True,
        help="Path to a YAML configuration file.",
    )

    validate_inputs_parser = subparsers.add_parser(
        "validate-inputs",
        help="Validate input files and headers.",
        description=(
            "Check CSV headers for required columns across configured domains."
        ),
        epilog=(
            "Example:\n"
            "  python -m trinetx_preprocessing validate-inputs --config config.yaml"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    validate_inputs_parser.add_argument(
        "--config",
        type=Path,
        required=True,
        help="Path to a YAML configuration file.",
    )

    inspect_inputs_parser = subparsers.add_parser(
        "inspect-inputs",
        help="List configured input-domain matches without reading row data.",
        description=(
            "Inspect configured domain glob patterns and report all missing "
            "domains at once. This is useful while a large external restore is "
            "still in progress."
        ),
        epilog=(
            "Example:\n"
            "  python -m trinetx_preprocessing inspect-inputs --config config.yaml\n"
            "  python -m trinetx_preprocessing inspect-inputs --config config.yaml "
            "--json-out artifacts/input_status.json"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    inspect_inputs_parser.add_argument(
        "--config",
        type=Path,
        required=True,
        help="Path to a YAML configuration file.",
    )
    inspect_inputs_parser.add_argument(
        "--allow-missing",
        action="store_true",
        help="Return success even if one or more domains have zero matches.",
    )
    inspect_inputs_parser.add_argument(
        "--json",
        action="store_true",
        help="Print a machine-readable JSON summary to stdout.",
    )
    inspect_inputs_parser.add_argument(
        "--json-out",
        type=Path,
        default=None,
        help="Write a machine-readable JSON summary to this path.",
    )
    inspect_inputs_parser.add_argument(
        "--min-free-gb",
        type=float,
        default=None,
        help=(
            "Require data/work/output filesystems to have at least this many GiB free."
        ),
    )
    inspect_inputs_parser.add_argument(
        "--max-matches",
        type=int,
        default=None,
        help=(
            "Stop scanning each domain after this many matched files. "
            "Useful for quick external-restore readiness checks."
        ),
    )
    inspect_inputs_parser.add_argument(
        "--domain",
        action="append",
        default=None,
        help=(
            "Inspect only this configured domain. Can be repeated to inspect "
            "a subset during external-restore troubleshooting."
        ),
    )
    inspect_inputs_parser.add_argument(
        "--skip-space-check",
        action="store_true",
        help="Skip filesystem free-space checks during input inspection.",
    )
    inspect_inputs_parser.add_argument(
        "--domain-timeout-seconds",
        type=float,
        default=None,
        help=(
            "Probe each selected domain in a subprocess with this timeout. "
            "Useful when one directory on an external restore can stall."
        ),
    )

    scaffold_validation_parser = subparsers.add_parser(
        "scaffold-validation",
        help="Create an external validation directory layout and config.",
        description=(
            "Create refactor, legacy, manifest, profile, log, and uv-cache "
            "directories under a validation root, then write a Parquet-mode "
            "config for real-data validation."
        ),
        epilog=(
            "Example:\n"
            "  python -m trinetx_preprocessing scaffold-validation\n"
            "    --data-dir /path/to/TriNetX\n"
            "    --validation-root /path/to/trinetx-preprocessing-validation"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    scaffold_validation_parser.add_argument(
        "--data-dir",
        type=Path,
        required=True,
        help="Raw TriNetX export root for the generated config.",
    )
    scaffold_validation_parser.add_argument(
        "--validation-root",
        type=Path,
        required=True,
        help="External/private validation root to create.",
    )
    scaffold_validation_parser.add_argument(
        "--config-out",
        type=Path,
        default=None,
        help="Optional config output path (default: validation-root/config.yaml).",
    )
    scaffold_validation_parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite an existing generated config file.",
    )
    scaffold_validation_parser.add_argument(
        "--lines-per-chunk",
        type=int,
        default=250_000,
        help="Chunk size for the generated config.",
    )
    scaffold_validation_parser.add_argument(
        "--parquet-row-group-size",
        type=int,
        default=250_000,
        help="Parquet row-group size for the generated config.",
    )
    scaffold_validation_parser.add_argument(
        "--emit-legacy-csv-intermediates",
        action="store_true",
        help="Emit CSV companions for Parquet work tables in the generated config.",
    )

    run_parser = subparsers.add_parser(
        "run",
        help="Run the full preprocessing pipeline.",
        description=(
            "Run all pipeline stages in order and write final outputs to\n"
            "the configured output directory."
        ),
        epilog=("Example:\n  python -m trinetx_preprocessing run --config config.yaml"),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    run_parser.add_argument(
        "--config",
        type=Path,
        required=True,
        help="Path to a YAML configuration file.",
    )
    run_parser.add_argument(
        "--strict",
        action="store_true",
        help="Enable guardrail assertions during the run.",
    )

    build_preprocessed_parser = subparsers.add_parser(
        "build-preprocessed",
        help="Build the canonical combined preprocessing database.",
        description=(
            "Run shared domain preprocessing once, publish the combined DuckDB, "
            "and regenerate all 36 historical compatibility CSVs."
        ),
    )
    build_preprocessed_parser.add_argument(
        "--config",
        type=Path,
        required=True,
        help="Path to a YAML configuration file.",
    )
    build_preprocessed_parser.add_argument(
        "--strict",
        action="store_true",
        help="Enable strict encounter and guardrail validation.",
    )
    build_preprocessed_parser.add_argument(
        "--replace",
        action="store_true",
        help="Replace an existing combined product after a successful build.",
    )

    preprocessed_status_parser = subparsers.add_parser(
        "preprocessed-status",
        help="Report aggregate status for a combined preprocessing database.",
    )
    preprocessed_status_parser.add_argument(
        "--database",
        type=Path,
        required=True,
        help="Path to trinetx_preprocessed.duckdb.",
    )
    preprocessed_status_parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON.",
    )

    inspect_preprocessed_parser = subparsers.add_parser(
        "inspect-preprocessed",
        help="Inspect aggregate table counts in a combined database.",
    )
    inspect_preprocessed_parser.add_argument(
        "--database",
        type=Path,
        required=True,
        help="Path to trinetx_preprocessed.duckdb.",
    )
    inspect_preprocessed_parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON.",
    )

    validate_preprocessed_parser = subparsers.add_parser(
        "validate-preprocessed",
        help="Validate the combined database and optional compatibility CSVs.",
    )
    validate_preprocessed_parser.add_argument(
        "--database",
        type=Path,
        required=True,
        help="Path to trinetx_preprocessed.duckdb.",
    )
    validate_preprocessed_parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Optional root containing the 36 compatibility CSVs.",
    )
    validate_preprocessed_parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON.",
    )

    export_legacy_parser = subparsers.add_parser(
        "export-legacy",
        help="Regenerate the 36 historical CSVs from a combined database.",
    )
    export_legacy_parser.add_argument(
        "--database",
        type=Path,
        required=True,
        help="Path to trinetx_preprocessed.duckdb.",
    )
    export_legacy_parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="Destination root for compatibility CSVs.",
    )
    export_legacy_parser.add_argument(
        "--replace",
        action="store_true",
        help="Atomically replace an existing compatibility-only export tree.",
    )

    run_all_parser = subparsers.add_parser(
        "run-all",
        help="Alias for the full preprocessing pipeline.",
        description="Alias for `run` (runs the full preprocessing pipeline).",
        epilog=(
            "Example:\n  python -m trinetx_preprocessing run-all --config config.yaml"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    run_all_parser.add_argument(
        "--config",
        type=Path,
        required=True,
        help="Path to a YAML configuration file.",
    )
    run_all_parser.add_argument(
        "--strict",
        action="store_true",
        help="Enable guardrail assertions during the run.",
    )

    run_encounter_parser = subparsers.add_parser(
        "run-encounter",
        help="Run the encounter preprocessing stage.",
        description=(
            "Normalize encounter exports and write encounter subsets for\n"
            "AMB/EMER/INPAT settings."
        ),
        epilog=(
            "Example:\n"
            "  python -m trinetx_preprocessing run-encounter --config config.yaml"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    run_encounter_parser.add_argument(
        "--config",
        type=Path,
        required=True,
        help="Path to a YAML configuration file.",
    )
    run_encounter_parser.add_argument(
        "--strict",
        action="store_true",
        help="Fail when encounter IDs appear in multiple settings.",
    )

    run_labs_parser = subparsers.add_parser(
        "run-labs",
        help="Run the lab-results preprocessing stage.",
        description="Normalize lab results and write `lab_results_NEW_*.csv`.",
        epilog=(
            "Example:\n  python -m trinetx_preprocessing run-labs --config config.yaml"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    run_labs_parser.add_argument(
        "--config",
        type=Path,
        required=True,
        help="Path to a YAML configuration file.",
    )

    run_diagnosis_parser = subparsers.add_parser(
        "run-diagnosis",
        help="Run the diagnosis preprocessing stage.",
        description=(
            "Normalize diagnosis data and emit `diagnosis_NEW_*.csv` plus\n"
            "HAS_*.csv extracts."
        ),
        epilog=(
            "Example:\n"
            "  python -m trinetx_preprocessing run-diagnosis --config config.yaml"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    run_diagnosis_parser.add_argument(
        "--config",
        type=Path,
        required=True,
        help="Path to a YAML configuration file.",
    )

    run_meds_parser = subparsers.add_parser(
        "run-meds",
        help="Run the medications preprocessing stage.",
        description=(
            "Normalize medications data and emit `medication_NEW_*.csv` plus\n"
            "IP/OP medication lists."
        ),
        epilog=(
            "Example:\n  python -m trinetx_preprocessing run-meds --config config.yaml"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    run_meds_parser.add_argument(
        "--config",
        type=Path,
        required=True,
        help="Path to a YAML configuration file.",
    )

    run_procedure_parser = subparsers.add_parser(
        "run-procedure",
        help="Run the procedure preprocessing stage.",
        description=(
            "Normalize procedures data and emit `procedure_NEW_*.csv` plus\n"
            "HAS_*.csv extracts."
        ),
        epilog=(
            "Example:\n"
            "  python -m trinetx_preprocessing run-procedure --config config.yaml"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    run_procedure_parser.add_argument(
        "--config",
        type=Path,
        required=True,
        help="Path to a YAML configuration file.",
    )

    run_vitals_parser = subparsers.add_parser(
        "run-vitals",
        help="Run the vital-signs preprocessing stage.",
        description=(
            "Normalize vital signs data and emit `vital_signs_NEW_*.csv` plus\n"
            "value_*.csv extracts."
        ),
        epilog=(
            "Example:\n"
            "  python -m trinetx_preprocessing run-vitals --config config.yaml"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    run_vitals_parser.add_argument(
        "--config",
        type=Path,
        required=True,
        help="Path to a YAML configuration file.",
    )

    run_rfs_parser = subparsers.add_parser(
        "run-rfs",
        help="Run the RFS derivation stage.",
        description=("Derive RFS flags and event extracts from normalized work files."),
        epilog=(
            "Example:\n  python -m trinetx_preprocessing run-rfs --config config.yaml"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    run_rfs_parser.add_argument(
        "--config",
        type=Path,
        required=True,
        help="Path to a YAML configuration file.",
    )

    run_final_assembly_parser = subparsers.add_parser(
        "run-final-assembly",
        help="Run only the final assembly stage.",
        description=(
            "Build final analytic CSV outputs from existing work_dir "
            "intermediates without rerunning raw-domain preprocessing."
        ),
        epilog=(
            "Example:\n"
            "  python -m trinetx_preprocessing run-final-assembly"
            " --config config.yaml"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    run_final_assembly_parser.add_argument(
        "--config",
        type=Path,
        required=True,
        help="Path to a YAML configuration file.",
    )
    run_final_assembly_parser.add_argument(
        "--strict",
        action="store_true",
        help="Enable guardrail assertions during final assembly.",
    )

    baseline_parser = subparsers.add_parser(
        "baseline",
        help="Run the pipeline and store output hashes for regression.",
        description=(
            "Run the full pipeline and write a hash manifest for regression\n"
            "comparisons."
        ),
        epilog=(
            "Example:\n"
            "  python -m trinetx_preprocessing baseline --config config.yaml\n"
            "    --out artifacts/baseline"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    baseline_parser.add_argument(
        "--config",
        type=Path,
        required=True,
        help="Path to a YAML configuration file.",
    )
    baseline_parser.add_argument(
        "--out",
        type=Path,
        required=True,
        help="Output directory for hash manifests.",
    )
    baseline_parser.add_argument(
        "--strict",
        action="store_true",
        help="Enable guardrail assertions during the run.",
    )

    compare_parser = subparsers.add_parser(
        "compare",
        help="Run the pipeline and compare output hashes to a baseline.",
        description=(
            "Run the pipeline and compare output hashes to a baseline manifest."
        ),
        epilog=(
            "Example:\n"
            "  python -m trinetx_preprocessing compare --config config.yaml\n"
            "    --baseline artifacts/baseline"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    compare_parser.add_argument(
        "--config",
        type=Path,
        required=True,
        help="Path to a YAML configuration file.",
    )
    compare_parser.add_argument(
        "--baseline",
        type=Path,
        required=True,
        help="Baseline directory containing hash manifests.",
    )
    compare_parser.add_argument(
        "--strict",
        action="store_true",
        help="Enable guardrail assertions during the run.",
    )

    hash_outputs_parser = subparsers.add_parser(
        "hash-outputs",
        help="Hash existing work/output directories for golden-master comparison.",
        description=(
            "Create a hash manifest from existing legacy or refactor output "
            "directories without running the pipeline."
        ),
        epilog=(
            "Example:\n"
            "  python -m trinetx_preprocessing hash-outputs\n"
            "    --output-dir artifacts/private_legacy/output\n"
            "    --scope final\n"
            "    --out artifacts/private_legacy_hashes"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    hash_outputs_parser.add_argument(
        "--work-dir",
        type=Path,
        default=None,
        help="Directory containing intermediate work tables.",
    )
    hash_outputs_parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Directory containing final output tables.",
    )
    hash_outputs_parser.add_argument(
        "--scope",
        choices=sorted(HASH_SCOPE_VALUES),
        default="all",
        help="Which tables to hash: final outputs, work intermediates, or all.",
    )
    hash_outputs_parser.add_argument(
        "--out",
        type=Path,
        required=True,
        help="Output directory for hash manifest.",
    )
    hash_outputs_parser.add_argument(
        "--hash-chunk-rows",
        type=int,
        default=DEFAULT_CSV_HASH_CHUNK_ROWS,
        help=(
            "Maximum table rows to sort in memory while hashing CSV files "
            "or Parquet record batches "
            f"(default: {DEFAULT_CSV_HASH_CHUNK_ROWS})."
        ),
    )

    compare_manifests_parser = subparsers.add_parser(
        "compare-manifests",
        help="Compare two existing hash manifests without rerunning the pipeline.",
        description=(
            "Compare current and baseline hash manifests already written by "
            "`baseline`, `compare`, or `hash-outputs`."
        ),
        epilog=(
            "Example:\n"
            "  python -m trinetx_preprocessing compare-manifests\n"
            "    --baseline artifacts/private_legacy_hashes\n"
            "    --current artifacts/refactor_hashes"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    compare_manifests_parser.add_argument(
        "--baseline",
        type=Path,
        required=True,
        help="Baseline manifest file or directory.",
    )
    compare_manifests_parser.add_argument(
        "--current",
        type=Path,
        required=True,
        help="Current manifest file or directory.",
    )
    compare_manifests_parser.add_argument(
        "--report",
        type=Path,
        default=None,
        help="Optional path for a JSON comparison report.",
    )

    validation_status_parser = subparsers.add_parser(
        "validation-status",
        help="Summarize external validation artifacts without reading row data.",
        description=(
            "Read input status, hash manifests, comparison reports, and profile "
            "provenance to determine whether the real-data validation gate is ready."
        ),
        epilog=(
            "Example:\n"
            "  python -m trinetx_preprocessing validation-status\n"
            "    --input-status artifacts/input_status.json\n"
            "    --legacy-manifest artifacts/legacy_final\n"
            "    --refactor-manifest artifacts/refactor_final\n"
            "    --comparison-report artifacts/final_comparison.json\n"
            "    --profile-provenance artifacts/profile/provenance.json"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    validation_status_parser.add_argument(
        "--input-status",
        type=Path,
        default=None,
        help="Path to inspect-inputs JSON status.",
    )
    validation_status_parser.add_argument(
        "--legacy-manifest",
        type=Path,
        default=None,
        help="Legacy output hash manifest file or directory.",
    )
    validation_status_parser.add_argument(
        "--refactor-manifest",
        type=Path,
        default=None,
        help="Refactor output hash manifest file or directory.",
    )
    validation_status_parser.add_argument(
        "--comparison-report",
        type=Path,
        default=None,
        help="Path to compare-manifests JSON report.",
    )
    validation_status_parser.add_argument(
        "--profile-provenance",
        type=Path,
        default=None,
        help="Path to profile provenance.json.",
    )
    validation_status_parser.add_argument(
        "--required-root",
        type=Path,
        default=None,
        help=(
            "Optional external root that validation artifacts and configured "
            "data/work/output paths must live under."
        ),
    )
    validation_status_parser.add_argument(
        "--required-root-min-free-gb",
        type=float,
        default=None,
        help=(
            "Optional minimum free GiB required on --required-root for the "
            "external validation bundle."
        ),
    )
    validation_status_parser.add_argument(
        "--json",
        action="store_true",
        help="Print a machine-readable JSON summary to stdout.",
    )
    validation_status_parser.add_argument(
        "--json-out",
        type=Path,
        default=None,
        help="Write a machine-readable JSON summary to this path.",
    )
    validation_status_parser.add_argument(
        "--markdown-out",
        type=Path,
        default=None,
        help="Write a human-readable Markdown summary to this path.",
    )
    validation_status_parser.add_argument(
        "--allow-incomplete",
        action="store_true",
        help="Return success even when one or more validation gates are incomplete.",
    )

    clean_scratch_parser = subparsers.add_parser(
        "clean-scratch",
        help="Inventory or delete known hidden pipeline scratch artifacts.",
        description=(
            "Find known .trinetx-* scratch files/directories left by interrupted "
            "hashing or pipeline stages. The default is a dry run; pass --delete "
            "to remove the matched artifacts."
        ),
        epilog=(
            "Example:\n"
            "  python -m trinetx_preprocessing clean-scratch\n"
            "    --root /Volumes/LOCKE STUDY/trinetx-preprocessing-validation"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    clean_scratch_parser.add_argument(
        "--root",
        type=Path,
        required=True,
        help=(
            "Directory tree to scan, usually the external validation root or work_dir."
        ),
    )
    clean_scratch_parser.add_argument(
        "--delete",
        action="store_true",
        help="Delete matched scratch artifacts. Without this flag, only report them.",
    )
    clean_scratch_parser.add_argument(
        "--json",
        action="store_true",
        help="Print a machine-readable JSON summary to stdout.",
    )
    clean_scratch_parser.add_argument(
        "--json-out",
        type=Path,
        default=None,
        help="Write a machine-readable JSON summary to this path.",
    )

    profile_parser = subparsers.add_parser(
        "profile",
        help="Profile the full pipeline with cProfile.",
        description=(
            "Run the full pipeline under the Python profiler and write stats"
            " plus stage timings."
        ),
        epilog=(
            "Example:\n"
            "  python -m trinetx_preprocessing profile --config config.yaml"
            " --out artifacts/profile"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    profile_parser.add_argument(
        "--config",
        type=Path,
        required=True,
        help="Path to a YAML configuration file.",
    )
    profile_parser.add_argument(
        "--out",
        type=Path,
        required=True,
        help="Directory for profiling artifacts (pstats + provenance).",
    )
    profile_parser.add_argument(
        "--strict",
        action="store_true",
        help="Enable guardrail assertions during the run.",
    )

    split_parser = subparsers.add_parser(
        "split",
        help="Split a large CSV into chunked files.",
        description=("Split a large CSV into chunked files while preserving headers."),
        epilog=(
            "Example:\n"
            "  python -m trinetx_preprocessing split --input "
            "data/Encounter/encounter.csv\n"
            "    --out data/Encounter --lines-per-chunk 10000000\n"
            "    --prefix encounter"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    split_parser.add_argument(
        "--input",
        type=Path,
        required=True,
        help="Path to the input CSV file.",
    )
    split_parser.add_argument(
        "--out",
        type=Path,
        required=True,
        help="Output directory for chunked CSV files.",
    )
    split_parser.add_argument(
        "--lines-per-chunk",
        type=int,
        default=10_000_000,
        help="Number of data rows per chunk (excludes header).",
    )
    split_parser.add_argument(
        "--prefix",
        type=str,
        default=None,
        help="Optional output filename prefix (defaults to input stem).",
    )

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI entry point."""

    parser = build_parser()
    args = parser.parse_args(argv)
    configure_logging(args.verbose)
    logger = logging.getLogger(__name__)

    try:
        if args.command == "split":
            output_paths = split_csv(
                args.input,
                args.out,
                args.lines_per_chunk,
                prefix=args.prefix,
            )
            logger.info("Wrote %s chunk file(s) to %s.", len(output_paths), args.out)
            return 0

        if args.command == "scaffold-validation":
            config_path = scaffold_validation(
                data_dir=args.data_dir,
                validation_root=args.validation_root,
                config_out=args.config_out,
                overwrite=args.overwrite,
                lines_per_chunk=args.lines_per_chunk,
                parquet_row_group_size=args.parquet_row_group_size,
                emit_legacy_csv_intermediates=args.emit_legacy_csv_intermediates,
            )
            logger.info("Validation scaffold written to %s", config_path)
            return 0

        if args.command == "hash-outputs":
            work_dir, output_dir = _resolve_hash_dirs(
                work_dir=args.work_dir,
                output_dir=args.output_dir,
                scope=args.scope,
            )
            entries = collect_directory_entries(
                work_dir=work_dir,
                output_dir=output_dir,
                scope=args.scope,
                csv_chunk_rows=args.hash_chunk_rows,
            )
            manifest_path = write_hash_manifest(
                args.out,
                entries,
                scope=args.scope,
                work_dir=work_dir if args.scope in {"work", "all"} else None,
                output_dir=output_dir if args.scope in {"final", "all"} else None,
            )
            logger.info("Output hashes written to %s", manifest_path)
            return 0

        if args.command == "compare-manifests":
            baseline_entries = load_hash_manifest_entries(args.baseline)
            current_entries = load_hash_manifest_entries(args.current)
            comparison = compare_manifest_entries(current_entries, baseline_entries)
            if args.report is not None:
                _write_manifest_comparison_report(
                    args.report,
                    comparison,
                    baseline=args.baseline,
                    current=args.current,
                )
            if comparison.ok:
                logger.info("All manifest entries match baseline.")
                return 0
            _log_manifest_comparison_errors(logger, comparison)
            return 1

        if args.command == "validation-status":
            payload = _validation_status_payload(
                input_status=args.input_status,
                legacy_manifest=args.legacy_manifest,
                refactor_manifest=args.refactor_manifest,
                comparison_report=args.comparison_report,
                profile_provenance=args.profile_provenance,
                required_root=args.required_root,
                required_root_min_free_gb=args.required_root_min_free_gb,
            )
            _emit_validation_status(
                payload,
                json_output=args.json,
                json_out=args.json_out,
                markdown_out=args.markdown_out,
            )
            if payload["ready"] or args.allow_incomplete:
                return 0
            return 1

        if args.command == "clean-scratch":
            payload = clean_scratch_artifacts(args.root, delete=args.delete)
            _emit_scratch_cleanup(
                payload,
                json_output=args.json,
                json_out=args.json_out,
            )
            action = "Deleted" if args.delete else "Found"
            logger.info(
                "%s %s scratch artifact(s), %s byte(s).",
                action,
                payload["artifact_count"],
                payload["total_size_bytes"],
            )
            return 0

        if args.command in {"preprocessed-status", "inspect-preprocessed"}:
            payload = inspect_combined_database(args.database)
            if args.json:
                print(json.dumps(payload, indent=2, sort_keys=True))
            else:
                logger.info(
                    "Combined preprocessing %s: %s (%s bytes)",
                    payload["run_id"],
                    payload["status"],
                    payload["database_size_bytes"],
                )
                for table, count in sorted(payload["counts"].items()):
                    logger.info("%s: %s rows", table, count)
            return 0

        if args.command == "validate-preprocessed":
            require_safe_output_location(
                args.database.parent,
                artifact_label="validation database/spill directory",
            )
            if args.output_dir is not None:
                require_safe_output_location(
                    args.output_dir,
                    artifact_label="validation compatibility output directory",
                )
                compatibility_hash_directories = sorted(
                    {
                        args.output_dir / output.relative_path.parent
                        for output in compatibility_outputs()
                    },
                    key=lambda path: path.as_posix(),
                )
                for directory in compatibility_hash_directories:
                    require_safe_output_location(
                        directory,
                        artifact_label="validation compatibility hash directory",
                    )
            result = validate_preprocessed_database(
                args.database,
                compatibility_output_dir=args.output_dir,
            )
            payload = {
                "valid": result.valid,
                "errors": list(result.errors),
                "warnings": list(result.warnings),
                "counts": result.counts,
            }
            if args.json:
                print(json.dumps(payload, indent=2, sort_keys=True))
            else:
                for warning in result.warnings:
                    logger.warning("%s", warning)
                for error in result.errors:
                    logger.error("%s", error)
                logger.info("Combined preprocessing valid: %s", result.valid)
            return 0 if result.valid else 1

        if args.command == "export-legacy":
            paths = export_legacy_compatibility_outputs(
                args.database,
                args.output_dir,
                replace_existing=args.replace,
            )
            logger.info(
                "Wrote %s compatibility CSVs to %s.", len(paths), args.output_dir
            )
            return 0

        config = load_config(args.config)
        if args.command == "inspect-inputs":
            return inspect_input_paths(
                config,
                config_path=args.config,
                allow_missing=args.allow_missing,
                json_output=args.json,
                json_out=args.json_out,
                min_free_gb=args.min_free_gb,
                max_matches=args.max_matches,
                selected_domains=set(args.domain) if args.domain else None,
                skip_space_check=args.skip_space_check,
                domain_timeout_seconds=args.domain_timeout_seconds,
            )

        validate_config(config)
        _require_safe_combined_mutation_locations(
            config,
            command=args.command,
        )
        if args.command == "validate-config":
            logger.info("Configuration validated successfully.")
            return 0
        if args.command == "validate-inputs":
            validate_input_headers(config)
            logger.info("Input files validated successfully.")
            return 0
        if args.command in {"run", "run-all"}:
            if config.combined.enabled:
                result = build_preprocessed(config, strict=args.strict)
                logger.info(
                    "Combined preprocessing completed: %s (%s compatibility CSVs).",
                    result.database_path,
                    len(result.compatibility_paths),
                )
                return 0
            output_paths = run_pipeline(config, strict=args.strict)
            logger.info(
                "Pipeline completed; wrote %s file(s) to %s and %s.",
                len(output_paths),
                config.work_dir,
                config.output_dir,
            )
            return 0
        if args.command == "build-preprocessed":
            result = build_preprocessed(
                config,
                strict=args.strict,
                replace_existing=args.replace,
            )
            logger.info(
                "Combined preprocessing completed: %s (%s compatibility CSVs).",
                result.database_path,
                len(result.compatibility_paths),
            )
            return 0
        if args.command == "profile":
            output_paths = run_profile(
                config,
                args.out,
                strict=args.strict,
                config_path=args.config,
            )
            logger.info(
                "Profile run completed; wrote %s file(s) to %s and %s.",
                len(output_paths),
                config.work_dir,
                config.output_dir,
            )
            return 0
        if args.command == "baseline":
            output_paths = run_pipeline(config, strict=args.strict)
            entries = collect_output_entries(
                output_paths,
                work_dir=config.work_dir,
                output_dir=config.output_dir,
            )
            manifest_path = write_hash_manifest(
                args.out,
                entries,
                scope="all",
                work_dir=config.work_dir,
                output_dir=config.output_dir,
            )
            logger.info("Baseline hashes written to %s", manifest_path)
            return 0
        if args.command == "compare":
            output_paths = run_pipeline(config, strict=args.strict)
            current_hashes = collect_output_hashes(
                output_paths,
                work_dir=config.work_dir,
                output_dir=config.output_dir,
            )
            baseline_hashes = load_hash_manifest(args.baseline)
            comparison = compare_hashes(current_hashes, baseline_hashes)
            if comparison.ok:
                logger.info("All hashes match baseline.")
                return 0
            if comparison.missing:
                logger.error(
                    "Missing outputs in current run: %s",
                    ", ".join(comparison.missing),
                )
            if comparison.extra:
                logger.error(
                    "Unexpected outputs in current run: %s",
                    ", ".join(comparison.extra),
                )
            for key, (baseline_hash, current_hash) in comparison.mismatched.items():
                logger.error(
                    "Hash mismatch for %s (baseline %s, current %s)",
                    key,
                    baseline_hash,
                    current_hash,
                )
            return 1
        if args.command == "run-encounter":
            initialize_work_manifest(config)
            mark_stage_started(config, "encounter")
            output_paths = run_encounter_stage(config, strict=args.strict)
            mark_stage_complete(config, "encounter", output_paths)
            logger.info(
                "Encounter stage completed; wrote %s file(s) to %s.",
                len(output_paths),
                config.work_dir,
            )
            return 0
        if args.command == "run-labs":
            initialize_work_manifest(config)
            mark_stage_started(config, "labs")
            output_paths = run_labs_stage(config)
            mark_stage_complete(config, "labs", output_paths)
            logger.info(
                "Labs stage completed; wrote %s file(s) to %s.",
                len(output_paths),
                config.work_dir,
            )
            return 0
        if args.command == "run-diagnosis":
            initialize_work_manifest(config)
            mark_stage_started(config, "diagnosis")
            output_paths = run_diagnosis_stage(config)
            mark_stage_complete(config, "diagnosis", output_paths)
            logger.info(
                "Diagnosis stage completed; wrote %s file(s) to %s.",
                len(output_paths),
                config.work_dir,
            )
            return 0
        if args.command == "run-meds":
            initialize_work_manifest(config)
            mark_stage_started(config, "medications")
            output_paths = run_medications_stage(config)
            mark_stage_complete(config, "medications", output_paths)
            logger.info(
                "Medications stage completed; wrote %s file(s) to %s.",
                len(output_paths),
                config.work_dir,
            )
            return 0
        if args.command == "run-procedure":
            initialize_work_manifest(config)
            mark_stage_started(config, "procedure")
            output_paths = run_procedure_stage(config)
            mark_stage_complete(config, "procedure", output_paths)
            logger.info(
                "Procedure stage completed; wrote %s file(s) to %s.",
                len(output_paths),
                config.work_dir,
            )
            return 0
        if args.command == "run-vitals":
            initialize_work_manifest(config)
            mark_stage_started(config, "vitals")
            output_paths = run_vitals_stage(config)
            mark_stage_complete(config, "vitals", output_paths)
            logger.info(
                "Vitals stage completed; wrote %s file(s) to %s.",
                len(output_paths),
                config.work_dir,
            )
            return 0
        if args.command == "run-rfs":
            require_current_work(config, required_stages=DOMAIN_STAGES)
            mark_stage_started(config, "rfs")
            output_paths = run_rfs_stage(config)
            mark_stage_complete(config, "rfs", output_paths)
            logger.info(
                "RFS stage completed; wrote %s file(s) to %s.",
                len(output_paths),
                config.work_dir,
            )
            return 0
        if args.command == "run-final-assembly":
            require_current_work(
                config,
                required_stages=FINAL_ASSEMBLY_PREREQUISITES,
            )
            if args.strict:
                require_strict_encounter_work(config)
            mark_stage_started(config, "final_assembly")
            output_paths = run_final_assembly(config, strict=args.strict)
            mark_stage_complete(config, "final_assembly", output_paths)
            logger.info(
                "Final assembly completed; wrote %s file(s) to %s.",
                len(output_paths),
                config.output_dir,
            )
            return 0
    except (
        CombinedLockError,
        ConfigError,
        FileExistsError,
        FileNotFoundError,
        StaleWorkError,
        ValueError,
    ) as exc:
        logger.error("%s", exc)
        return 2

    parser.print_usage(sys.stderr)
    return 2


def _resolve_hash_dirs(
    *,
    work_dir: Path | None,
    output_dir: Path | None,
    scope: str,
) -> tuple[Path, Path]:
    if scope in {"work", "all"} and work_dir is None:
        raise ValueError("--work-dir is required when --scope is 'work' or 'all'.")
    if scope in {"final", "all"} and output_dir is None:
        raise ValueError("--output-dir is required when --scope is 'final' or 'all'.")
    if work_dir is None and output_dir is None:
        raise ValueError("At least one of --work-dir or --output-dir is required.")
    resolved_work_dir = work_dir
    resolved_output_dir = output_dir
    if resolved_work_dir is None:
        resolved_work_dir = output_dir.parent / "__trinetx_unused_work_dir__"
    if resolved_output_dir is None:
        resolved_output_dir = work_dir.parent / "__trinetx_unused_output_dir__"
    return resolved_work_dir, resolved_output_dir


def scaffold_validation(
    *,
    data_dir: Path,
    validation_root: Path,
    config_out: Path | None = None,
    overwrite: bool = False,
    lines_per_chunk: int = 250_000,
    parquet_row_group_size: int = 250_000,
    emit_legacy_csv_intermediates: bool = False,
) -> Path:
    """Create the external validation directory layout and config file."""

    if lines_per_chunk <= 0:
        raise ValueError("--lines-per-chunk must be positive.")
    if parquet_row_group_size <= 0:
        raise ValueError("--parquet-row-group-size must be positive.")

    root = validation_root.expanduser().resolve(strict=False)
    raw_data_dir = data_dir.expanduser().resolve(strict=False)
    config_path = (
        config_out.expanduser().resolve(strict=False)
        if config_out is not None
        else root / "config.yaml"
    )

    directories = [
        root / "refactor" / "work",
        root / "refactor" / "output",
        root / "legacy" / "work",
        root / "legacy" / "output",
        root / "manifests",
        root / "profile",
        root / "logs",
        root / "uv-cache",
    ]
    for directory in directories:
        directory.mkdir(parents=True, exist_ok=True)

    if config_path.exists() and not overwrite:
        raise ValueError(
            f"Config already exists; pass --overwrite to replace: {config_path}"
        )
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        _validation_config_text(
            data_dir=raw_data_dir,
            validation_root=root,
            lines_per_chunk=lines_per_chunk,
            parquet_row_group_size=parquet_row_group_size,
            emit_legacy_csv_intermediates=emit_legacy_csv_intermediates,
        )
    )
    return config_path


def _validation_config_text(
    *,
    data_dir: Path,
    validation_root: Path,
    lines_per_chunk: int,
    parquet_row_group_size: int,
    emit_legacy_csv_intermediates: bool,
) -> str:
    emit_csv = "true" if emit_legacy_csv_intermediates else "false"
    lines = [
        "# Local real-data validation config. Do not commit.",
        f"data_dir: {_yaml_string(data_dir)}",
        f"work_dir: {_yaml_string(validation_root / 'refactor' / 'work')}",
        f"output_dir: {_yaml_string(validation_root / 'refactor' / 'output')}",
        "",
        "chunking:",
        "  enabled: true",
        f"  lines_per_chunk: {lines_per_chunk}",
        "",
        "storage:",
        "  intermediate_format: parquet",
        f"  emit_legacy_csv_intermediates: {emit_csv}",
        f"  parquet_row_group_size: {parquet_row_group_size}",
        "",
        "guardrails:",
        "  max_join_multiplier: 1.0",
        "",
        "domains:",
    ]
    for name, patterns in DEFAULT_DOMAIN_PATTERNS.items():
        lines.append(f"  {name}:")
        if isinstance(patterns, str):
            lines.append(f"    pattern: {_yaml_string(patterns)}")
        else:
            lines.append("    patterns:")
            for pattern in patterns:
                lines.append(f"      - {_yaml_string(pattern)}")
    lines.extend(["", "rfs:", "  enabled: true", ""])
    return "\n".join(lines)


def _yaml_string(value: object) -> str:
    return json.dumps(str(value))


def clean_scratch_artifacts(root: Path, *, delete: bool = False) -> dict[str, object]:
    """Inventory or remove known hidden pipeline scratch artifacts."""

    resolved_root = root.expanduser().resolve()
    if not resolved_root.exists():
        raise FileNotFoundError(f"Scratch cleanup root does not exist: {resolved_root}")
    if not resolved_root.is_dir():
        raise NotADirectoryError(
            f"Scratch cleanup root is not a directory: {resolved_root}"
        )

    artifacts = _find_scratch_artifacts(resolved_root)
    payload_artifacts: list[dict[str, object]] = []
    total_size = 0
    for path in artifacts:
        size = _path_size_bytes(path)
        total_size += size
        payload_artifacts.append(
            {
                "path": str(path),
                "relative_path": str(path.relative_to(resolved_root)),
                "kind": "directory"
                if path.is_dir() and not path.is_symlink()
                else "file",
                "size_bytes": size,
            }
        )

    deleted_count = 0
    deleted_size = 0
    if delete:
        for path, artifact in zip(artifacts, payload_artifacts, strict=True):
            _delete_scratch_path(path)
            deleted_count += 1
            deleted_size += int(artifact["size_bytes"])

    return {
        "schema_version": SCRATCH_CLEANUP_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "root": str(resolved_root),
        "mode": "delete" if delete else "dry_run",
        "artifact_count": len(payload_artifacts),
        "total_size_bytes": total_size,
        "deleted_count": deleted_count,
        "deleted_size_bytes": deleted_size,
        "artifacts": payload_artifacts,
    }


def _emit_scratch_cleanup(
    payload: dict[str, object],
    *,
    json_output: bool,
    json_out: Path | None,
) -> None:
    text = json.dumps(payload, indent=2, sort_keys=True)
    if json_output:
        print(text)
    if json_out is not None:
        write_text_atomic(json_out, f"{text}\n")


def _find_scratch_artifacts(root: Path) -> list[Path]:
    matches: list[Path] = []

    def visit(directory: Path) -> None:
        try:
            entries = sorted(directory.iterdir(), key=lambda path: path.name)
        except OSError:
            return
        for path in entries:
            if _is_known_scratch_path(path):
                matches.append(path)
                continue
            try:
                is_directory = path.is_dir() and not path.is_symlink()
            except OSError:
                continue
            if is_directory:
                visit(path)

    visit(root)
    return matches


def _is_known_scratch_path(path: Path) -> bool:
    return any(
        path.name.startswith(prefix) for prefix in SCRATCH_PATH_PREFIXES
    ) or is_combined_scratch_name(path.name)


def _path_size_bytes(path: Path) -> int:
    try:
        if path.is_symlink() or path.is_file():
            return path.lstat().st_size
        if not path.is_dir():
            return 0
    except FileNotFoundError:
        return 0

    total = 0
    for child in path.rglob("*"):
        try:
            if child.is_symlink() or child.is_file():
                total += child.lstat().st_size
        except FileNotFoundError:
            continue
    return total


def _delete_scratch_path(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        remove_tree_strict(path, context="Scratch directory")
        return
    path.unlink(missing_ok=True)
    if path.exists() or path.is_symlink():
        raise OSError(f"Scratch file was not deleted: {path}")


def _log_manifest_comparison_errors(
    logger: logging.Logger,
    comparison: ManifestComparisonResult,
) -> None:
    if comparison.missing:
        logger.error(
            "Missing outputs in current manifest: %s",
            ", ".join(comparison.missing),
        )
    if comparison.extra:
        logger.error(
            "Unexpected outputs in current manifest: %s",
            ", ".join(comparison.extra),
        )
    for key, (baseline_hash, current_hash) in comparison.hash_mismatched.items():
        logger.error(
            "Hash mismatch for %s (baseline %s, current %s)",
            key,
            baseline_hash,
            current_hash,
        )
    for key, (baseline_count, current_count) in comparison.row_count_mismatched.items():
        logger.error(
            "Row-count mismatch for %s (baseline %s, current %s)",
            key,
            baseline_count,
            current_count,
        )
    for key, (
        baseline_columns,
        current_columns,
    ) in comparison.columns_mismatched.items():
        logger.error(
            "Column mismatch for %s (baseline %s, current %s)",
            key,
            baseline_columns,
            current_columns,
        )


def _write_manifest_comparison_report(
    path: Path,
    comparison: ManifestComparisonResult,
    *,
    baseline: Path,
    current: Path,
) -> None:
    payload = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "baseline": str(baseline.resolve()),
        "baseline_manifest_sha256": _hash_manifest_sha256(baseline),
        "current": str(current.resolve()),
        "current_manifest_sha256": _hash_manifest_sha256(current),
        "ok": comparison.ok,
        "counts": _manifest_comparison_counts(comparison),
        "missing": list(comparison.missing),
        "extra": list(comparison.extra),
        "hash_mismatched": [
            {
                "key": key,
                "baseline_hash": baseline_hash,
                "current_hash": current_hash,
            }
            for key, (baseline_hash, current_hash) in sorted(
                comparison.hash_mismatched.items()
            )
        ],
        "row_count_mismatched": [
            {
                "key": key,
                "baseline_row_count": baseline_count,
                "current_row_count": current_count,
            }
            for key, (baseline_count, current_count) in sorted(
                comparison.row_count_mismatched.items()
            )
        ],
        "columns_mismatched": [
            {
                "key": key,
                "baseline_columns": list(baseline_columns)
                if baseline_columns is not None
                else None,
                "current_columns": list(current_columns)
                if current_columns is not None
                else None,
            }
            for key, (baseline_columns, current_columns) in sorted(
                comparison.columns_mismatched.items()
            )
        ],
    }
    write_text_atomic(path, json.dumps(payload, indent=2, sort_keys=True) + "\n")


def _validation_status_payload(
    *,
    input_status: Path | None,
    legacy_manifest: Path | None,
    refactor_manifest: Path | None,
    comparison_report: Path | None,
    profile_provenance: Path | None,
    required_root: Path | None = None,
    required_root_min_free_gb: float | None = None,
) -> dict[str, object]:
    input_status_check = _input_status_check(input_status)
    profile_provenance_check = _profile_provenance_check(profile_provenance)
    checks = {
        "input_status": input_status_check,
        "legacy_manifest": _manifest_check(legacy_manifest),
        "refactor_manifest": _manifest_check(refactor_manifest),
        "comparison_report": _comparison_report_check(
            comparison_report,
            baseline=legacy_manifest,
            current=refactor_manifest,
        ),
        "profile_provenance": profile_provenance_check,
        "artifact_consistency": _artifact_consistency_check(
            input_status_check=input_status_check,
            profile_provenance_check=profile_provenance_check,
        ),
        "profile_refactor_outputs": _profile_refactor_outputs_check(
            refactor_manifest=refactor_manifest,
            profile_provenance_check=profile_provenance_check,
        ),
        "required_root": _required_root_check(
            required_root=required_root,
            min_free_gb=required_root_min_free_gb,
            input_status=input_status,
            legacy_manifest=legacy_manifest,
            refactor_manifest=refactor_manifest,
            comparison_report=comparison_report,
            profile_provenance=profile_provenance,
            input_status_check=input_status_check,
            profile_provenance_check=profile_provenance_check,
        ),
    }
    ready = all(bool(check["ok"]) for check in checks.values())
    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "ready": ready,
        "checks": checks,
    }


def _emit_validation_status(
    payload: dict[str, object],
    *,
    json_output: bool,
    json_out: Path | None,
    markdown_out: Path | None,
) -> None:
    rendered = json.dumps(payload, indent=2, sort_keys=True)
    if json_output:
        print(rendered)
    elif json_out is None and markdown_out is None:
        ready = "yes" if payload["ready"] else "no"
        print(f"Validation ready: {ready}")
        checks = payload["checks"]
        if isinstance(checks, dict):
            for name, raw_check in checks.items():
                if not isinstance(raw_check, dict):
                    continue
                state = "pass" if raw_check.get("ok") else "fail"
                message = raw_check.get("message", "")
                print(f"- {name}: {state} ({message})")
    if json_out is not None:
        write_text_atomic(json_out, f"{rendered}\n")
    if markdown_out is not None:
        write_text_atomic(markdown_out, _render_validation_status_markdown(payload))


def _render_validation_status_markdown(payload: dict[str, object]) -> str:
    ready = "yes" if payload["ready"] else "no"
    generated_at = payload.get("generated_at", "")
    lines = [
        "# TriNetX Refactor Validation Status",
        "",
        f"- Ready: {ready}",
        f"- Generated at: {generated_at}",
        "",
        "| Gate | Status | Message |",
        "| --- | --- | --- |",
    ]
    checks = payload.get("checks")
    if isinstance(checks, dict):
        for name, raw_check in checks.items():
            if not isinstance(raw_check, dict):
                continue
            state = "pass" if raw_check.get("ok") else "fail"
            message = str(raw_check.get("message", ""))
            lines.append(f"| `{name}` | {state} | {message} |")
        blocker_rows = _validation_blocker_rows(checks)
        if blocker_rows:
            lines.extend(
                [
                    "",
                    "## Gate Blockers",
                    "",
                    "| Gate | Blocker |",
                    "| --- | --- |",
                ]
            )
            lines.extend(blocker_rows)
        input_mode_lines = _input_status_mode_lines(checks)
        if input_mode_lines:
            lines.extend(["", "## Input Status Mode", ""])
            lines.extend(input_mode_lines)
        artifact_lines = _artifact_consistency_lines(checks)
        if artifact_lines:
            lines.extend(["", "## Artifact Consistency", ""])
            lines.extend(artifact_lines)
        required_root_lines = _required_root_lines(checks)
        if required_root_lines:
            lines.extend(["", "## Required Root", ""])
            lines.extend(required_root_lines)
        missing = _missing_input_domains(checks)
        if missing:
            lines.extend(["", "## Missing Input Domains", ""])
            lines.extend(f"- `{domain}`" for domain in missing)
        timed_out = _timed_out_input_domains(checks)
        if timed_out:
            lines.extend(["", "## Timed-Out Input Domains", ""])
            lines.extend(f"- `{domain}`" for domain in timed_out)
        probe_errors = _input_probe_errors(checks)
        if probe_errors:
            lines.extend(["", "## Input Probe Errors", ""])
            lines.extend(
                f"- `{domain}`: {message}"
                for domain, message in sorted(probe_errors.items())
            )
        domain_statuses = _input_domain_statuses(checks)
        if domain_statuses:
            lines.extend(
                [
                    "",
                    "## Input Domain Status",
                    "",
                    (
                        "| Domain | Count | Timed Out | Search Dir Exists | "
                        "First Path | Probe Error |"
                    ),
                    "| --- | ---: | --- | --- | --- | --- |",
                ]
            )
            for item in domain_statuses:
                lines.append(_render_input_domain_status_row(item))
    lines.append("")
    return "\n".join(lines)


def _artifact_consistency_lines(checks: dict[str, object]) -> list[str]:
    artifact_consistency = checks.get("artifact_consistency")
    if not isinstance(artifact_consistency, dict):
        return []
    fields = [
        (
            "Input config path",
            str(artifact_consistency.get("input_config_path") or ""),
        ),
        (
            "Profile config path",
            str(artifact_consistency.get("profile_config_path") or ""),
        ),
        (
            "Config path match",
            _markdown_bool_or_unknown(artifact_consistency.get("config_path_matches")),
        ),
        (
            "Config SHA-256 match",
            _markdown_bool_or_unknown(
                artifact_consistency.get("config_sha256_matches")
            ),
        ),
        (
            "Current config SHA-256 match",
            _markdown_bool_or_unknown(
                artifact_consistency.get("current_config_sha256_matches")
            ),
        ),
    ]
    return [f"- {label}: {value}" for label, value in fields]


def _required_root_lines(checks: dict[str, object]) -> list[str]:
    required_root = checks.get("required_root")
    if not isinstance(required_root, dict):
        return []
    root = required_root.get("required_root")
    if not isinstance(root, str) or not root:
        return []
    fields = [
        ("Required root", root),
        ("Root placement", "pass" if required_root.get("ok") else "fail"),
        ("Checked paths", str(required_root.get("checked_path_count") or 0)),
        ("Blockers", str(required_root.get("blocker_count") or 0)),
    ]
    min_free_gb = required_root.get("min_free_gb")
    free_gb = required_root.get("free_gb")
    space_ok = required_root.get("space_ok")
    if _is_number(min_free_gb):
        fields.extend(
            [
                ("Minimum free GiB", f"{float(min_free_gb):.3f}"),
                (
                    "Observed free GiB",
                    f"{float(free_gb):.3f}" if _is_number(free_gb) else "unknown",
                ),
                ("Free-space threshold", _markdown_bool_or_unknown(space_ok)),
            ]
        )
    return [f"- {label}: {value}" for label, value in fields]


def _validation_blocker_rows(checks: dict[str, object]) -> list[str]:
    rows: list[str] = []
    blocker_fields = (
        "blockers",
        "header_blockers",
        "final_scope_blockers",
        "metadata_blockers",
        "source_path_blockers",
        "space_evidence_blockers",
    )
    for name, raw_check in checks.items():
        if not isinstance(raw_check, dict):
            continue
        for field in blocker_fields:
            blockers = raw_check.get(field)
            if not isinstance(blockers, list):
                continue
            for blocker in blockers:
                rows.append(
                    f"| `{_markdown_cell(str(name))}` | "
                    f"{_markdown_cell(str(blocker))} |"
                )
    return rows


def _missing_input_domains(checks: dict[str, object]) -> list[str]:
    input_status = checks.get("input_status")
    if not isinstance(input_status, dict):
        return []
    missing = input_status.get("missing")
    if not isinstance(missing, list):
        return []
    return [str(domain) for domain in missing]


def _input_status_mode_lines(checks: dict[str, object]) -> list[str]:
    input_status = checks.get("input_status")
    if not isinstance(input_status, dict) or not input_status.get("provided"):
        return []
    fields = [
        ("Schema version", str(input_status.get("schema_version"))),
        (
            "Current schema",
            _markdown_bool_or_unknown(input_status.get("schema_current")),
        ),
        (
            "Exact input status",
            _markdown_bool_or_unknown(input_status.get("exact_input_status")),
        ),
        ("Max matches", str(input_status.get("max_matches"))),
        (
            "Domain timeout seconds",
            str(input_status.get("domain_timeout_seconds")),
        ),
        (
            "Space check skipped",
            _markdown_bool_or_unknown(input_status.get("space_check_skipped")),
        ),
        ("Min free GiB", str(input_status.get("min_free_gb"))),
        (
            "Free-space evidence",
            _markdown_bool_or_unknown(input_status.get("space_evidence_ok")),
        ),
    ]
    return [f"- {label}: {value}" for label, value in fields]


def _timed_out_input_domains(checks: dict[str, object]) -> list[str]:
    input_status = checks.get("input_status")
    if not isinstance(input_status, dict):
        return []
    timed_out = input_status.get("timed_out")
    if not isinstance(timed_out, list):
        return []
    return [str(domain) for domain in timed_out]


def _input_probe_errors(checks: dict[str, object]) -> dict[str, str]:
    input_status = checks.get("input_status")
    if not isinstance(input_status, dict):
        return {}
    probe_errors = input_status.get("probe_errors")
    if not isinstance(probe_errors, dict):
        return {}
    return {str(domain): str(message) for domain, message in probe_errors.items()}


def _input_domain_statuses(checks: dict[str, object]) -> list[dict[str, object]]:
    input_status = checks.get("input_status")
    if not isinstance(input_status, dict):
        return []
    domains = input_status.get("domains")
    if not isinstance(domains, list):
        return []
    return [item for item in domains if isinstance(item, dict)]


def _render_input_domain_status_row(item: dict[str, object]) -> str:
    name = str(item.get("name", ""))
    matched_count = str(item.get("matched_count", ""))
    timed_out = _markdown_bool_or_unknown(item.get("timed_out"))
    search_dir_exists = _markdown_bool_or_unknown(item.get("search_dir_exists"))
    first_path = str(item.get("first_path") or "")
    probe_error = str(item.get("probe_error") or "")
    return (
        f"| `{name}` | {matched_count} | {timed_out} | {search_dir_exists} | "
        f"{_markdown_cell(first_path)} | {_markdown_cell(probe_error)} |"
    )


def _markdown_bool_or_unknown(value: object) -> str:
    if isinstance(value, bool):
        return "yes" if value else "no"
    return "unknown"


def _markdown_cell(value: str) -> str:
    if not value:
        return ""
    return value.replace("|", "\\|")


def _input_status_check(path: Path | None) -> dict[str, object]:
    base = _artifact_check_base(path)
    if not base["provided"] or not base["exists"]:
        return base
    raw, error = _load_json_object(path)
    if error is not None:
        return {**base, "ok": False, "message": error}
    schema_version = raw.get("schema_version")
    schema_current = schema_version == INPUT_STATUS_SCHEMA_VERSION
    all_present = raw.get("all_present") is True
    space_ok = raw.get("space_ok") is True
    missing = raw.get("missing")
    domains = raw.get("domains")
    timed_out = raw.get("timed_out")
    probe_errors = raw.get("probe_errors")
    max_matches = raw.get("max_matches")
    domain_timeout_seconds = raw.get("domain_timeout_seconds")
    min_free_gb = raw.get("min_free_gb")
    filesystems = raw.get("filesystems")
    space_evidence_blockers = _input_status_space_evidence_blockers(
        min_free_gb=min_free_gb,
        filesystems=filesystems,
    )
    space_evidence_ok = not space_evidence_blockers
    exact_input_status = _is_exact_input_status(
        max_matches=max_matches,
        domain_timeout_seconds=domain_timeout_seconds,
        timed_out=timed_out,
        probe_errors=probe_errors,
        domains=domains,
    )
    blockers = _input_status_blockers(
        schema_current=schema_current,
        all_present=all_present,
        space_ok=space_ok,
        max_matches=max_matches,
        domain_timeout_seconds=domain_timeout_seconds,
        missing=missing,
        timed_out=timed_out,
        probe_errors=probe_errors,
        domains=domains,
    )
    ok = (
        schema_current
        and all_present
        and space_ok
        and exact_input_status
        and space_evidence_ok
    )
    message = _input_status_gate_message(
        schema_current=schema_current,
        all_present=all_present,
        space_ok=space_ok,
        exact_input_status=exact_input_status,
        space_evidence_ok=space_evidence_ok,
    )
    return {
        **base,
        "ok": ok,
        "message": message,
        "blockers": blockers,
        "schema_version": schema_version,
        "expected_schema_version": INPUT_STATUS_SCHEMA_VERSION,
        "schema_current": schema_current,
        "all_present": raw.get("all_present"),
        "space_ok": raw.get("space_ok"),
        "space_check_skipped": raw.get("space_check_skipped"),
        "min_free_gb": min_free_gb,
        "required_min_free_gb": FINAL_VALIDATION_MIN_FREE_GB,
        "space_evidence_ok": space_evidence_ok,
        "space_evidence_blockers": space_evidence_blockers,
        "filesystems": _input_status_filesystem_details(filesystems)
        if isinstance(filesystems, list)
        else None,
        "exact_input_status": exact_input_status,
        "max_matches": max_matches,
        "domain_timeout_seconds": domain_timeout_seconds,
        "missing": missing if isinstance(missing, list) else None,
        "timed_out": timed_out if isinstance(timed_out, list) else None,
        "probe_errors": probe_errors if isinstance(probe_errors, dict) else None,
        "domains": _input_status_domain_details(domains)
        if isinstance(domains, list)
        else None,
        "domain_count": len(domains) if isinstance(domains, list) else None,
        "generated_at": raw.get("generated_at"),
        "config_path": raw.get("config_path"),
        "config_sha256": raw.get("config_sha256"),
    }


def _input_status_blockers(
    *,
    schema_current: bool,
    all_present: bool,
    space_ok: bool,
    max_matches: object,
    domain_timeout_seconds: object,
    missing: object,
    timed_out: object,
    probe_errors: object,
    domains: object,
) -> list[str]:
    blockers: list[str] = []
    if not schema_current:
        blockers.append("input status schema is stale or missing")
    if not all_present:
        if isinstance(missing, list) and missing:
            blockers.append(
                "missing input domains: " + ", ".join(str(item) for item in missing)
            )
        else:
            blockers.append("all input domains are not present")
    if not space_ok:
        blockers.append("input free-space check did not pass")
    if max_matches is not None:
        blockers.append("input status was capped with max_matches")
    if domain_timeout_seconds is not None:
        blockers.append("input status used domain timeouts")
    if isinstance(timed_out, list) and timed_out:
        blockers.append(
            "input domain probes timed out: "
            + ", ".join(str(item) for item in timed_out)
        )
    if isinstance(probe_errors, dict) and probe_errors:
        blockers.append(
            "input domain probe errors: "
            + ", ".join(str(key) for key in sorted(probe_errors))
        )
    if not isinstance(domains, list):
        blockers.append("input domain details unavailable")
    else:
        inexact_domains = [
            str(domain.get("name"))
            for domain in domains
            if isinstance(domain, dict) and domain.get("matched_count_exact") is False
        ]
        if inexact_domains:
            blockers.append(
                "input domain counts are capped: " + ", ".join(inexact_domains)
            )
        timed_out_domains = [
            str(domain.get("name"))
            for domain in domains
            if isinstance(domain, dict) and domain.get("timed_out") is True
        ]
        if timed_out_domains:
            blockers.append(
                "input domain details timed out: " + ", ".join(timed_out_domains)
            )
        errored_domains = [
            str(domain.get("name"))
            for domain in domains
            if isinstance(domain, dict) and domain.get("probe_error") not in (None, "")
        ]
        if errored_domains:
            blockers.append(
                "input domain details have probe errors: " + ", ".join(errored_domains)
            )
    return blockers


def _is_exact_input_status(
    *,
    max_matches: object,
    domain_timeout_seconds: object,
    timed_out: object,
    probe_errors: object,
    domains: object,
) -> bool:
    if max_matches is not None or domain_timeout_seconds is not None:
        return False
    if isinstance(timed_out, list) and timed_out:
        return False
    if isinstance(probe_errors, dict) and probe_errors:
        return False
    if not isinstance(domains, list):
        return False
    for domain in domains:
        if not isinstance(domain, dict):
            return False
        if domain.get("matched_count_exact") is False:
            return False
        if domain.get("timed_out") is True:
            return False
        if domain.get("probe_error") not in (None, ""):
            return False
    return True


def _input_status_space_evidence_blockers(
    *,
    min_free_gb: object,
    filesystems: object,
) -> list[str]:
    blockers: list[str] = []
    if not _is_number(min_free_gb) or float(min_free_gb) < FINAL_VALIDATION_MIN_FREE_GB:
        blockers.append(
            f"min_free_gb must be at least {FINAL_VALIDATION_MIN_FREE_GB:g}"
        )
    if not isinstance(filesystems, list):
        blockers.append("filesystems must be a list")
        return blockers
    filesystem_by_label = _filesystem_evidence_by_label(filesystems)
    missing_labels = [
        label
        for label in REQUIRED_FILESYSTEM_LABELS
        if label not in filesystem_by_label
    ]
    if missing_labels:
        blockers.append(
            "filesystems missing required label(s): " + ", ".join(missing_labels)
        )
    threshold = float(min_free_gb) if _is_number(min_free_gb) else None
    for label, item in filesystem_by_label.items():
        free_gb = item.get("free_gb")
        if not _is_number(free_gb):
            blockers.append(f"filesystems[{label}].free_gb must be numeric")
            continue
        if threshold is not None and float(free_gb) < threshold:
            blockers.append(f"filesystems[{label}].free_gb below min_free_gb")
        checked_path = item.get("checked_path")
        if not isinstance(checked_path, str) or not checked_path:
            blockers.append(f"filesystems[{label}].checked_path must be present")
    return blockers


def _filesystem_evidence_by_label(
    filesystems: list[object],
) -> dict[str, dict[str, object]]:
    evidence: dict[str, dict[str, object]] = {}
    for item in filesystems:
        if not isinstance(item, dict):
            continue
        label = item.get("label")
        if isinstance(label, str) and label:
            evidence[label] = item
    return evidence


def _input_status_gate_message(
    *,
    schema_current: bool,
    all_present: bool,
    space_ok: bool,
    exact_input_status: bool,
    space_evidence_ok: bool,
) -> str:
    if not schema_current:
        return "input status schema is stale or missing"
    if all_present and space_ok and exact_input_status and space_evidence_ok:
        return "exact inputs and space checks passed"
    if all_present and space_ok and exact_input_status and not space_evidence_ok:
        return "free-space evidence missing or below threshold"
    if all_present and space_ok and not exact_input_status:
        return "input status is capped or timeout-based"
    return "input or space gate failed"


def _input_status_domain_details(raw_domains: list[object]) -> list[dict[str, object]]:
    details: list[dict[str, object]] = []
    for raw_domain in raw_domains:
        if not isinstance(raw_domain, dict):
            continue
        details.append(
            {
                "name": raw_domain.get("name"),
                "matched_count": raw_domain.get("matched_count"),
                "matched_count_exact": raw_domain.get("matched_count_exact"),
                "timed_out": raw_domain.get("timed_out"),
                "search_dir": raw_domain.get("search_dir"),
                "search_dir_exists": raw_domain.get("search_dir_exists"),
                "first_path": raw_domain.get("first_path"),
                "probe_error": raw_domain.get("probe_error"),
            }
        )
    return details


def _input_status_filesystem_details(
    raw_filesystems: list[object],
) -> list[dict[str, object]]:
    details: list[dict[str, object]] = []
    for raw_filesystem in raw_filesystems:
        if not isinstance(raw_filesystem, dict):
            continue
        details.append(
            {
                "label": raw_filesystem.get("label"),
                "path": raw_filesystem.get("path"),
                "checked_path": raw_filesystem.get("checked_path"),
                "free_gb": raw_filesystem.get("free_gb"),
                "free_bytes": raw_filesystem.get("free_bytes"),
            }
        )
    return details


def _manifest_check(path: Path | None) -> dict[str, object]:
    base = _artifact_check_base(path)
    if not base["provided"] or not base["exists"]:
        return base
    manifest_path = _hash_manifest_file_path(path)
    if manifest_path is None:
        return {**base, "ok": False, "message": "manifest path unavailable"}
    raw_manifest, raw_error = _load_json_object(manifest_path)
    if raw_error is not None:
        return {**base, "ok": False, "message": raw_error}
    try:
        entries = load_hash_manifest_entries(path)
    except (OSError, ValueError) as exc:
        return {**base, "ok": False, "message": str(exc)}
    table_count = len(entries)
    header_blockers = _manifest_header_blockers(raw_manifest)
    metadata_blockers = _manifest_metadata_blockers(entries)
    non_final_keys = _manifest_non_final_keys(entries)
    final_scope_blockers = _manifest_final_scope_blockers(non_final_keys)
    manifest_output_dir = _manifest_output_dir(raw_manifest)
    source_path_blockers = _manifest_source_path_blockers(
        entries,
        output_dir=manifest_output_dir,
    )
    header_complete = not header_blockers
    metadata_complete = not metadata_blockers
    final_scope = not final_scope_blockers
    source_paths_available = not source_path_blockers
    ok = (
        table_count > 0
        and header_complete
        and metadata_complete
        and final_scope
        and source_paths_available
    )
    if ok:
        message = (
            f"{table_count} final table(s) hashed with row counts, "
            "schema, and source files"
        )
    elif table_count == 0:
        message = "manifest has no tables"
    elif not header_complete:
        message = "manifest header metadata incomplete"
    elif not final_scope:
        message = "manifest includes non-final output keys"
    elif not metadata_complete:
        message = "manifest metadata incomplete"
    else:
        message = "manifest source files unavailable or mismatched"
    return {
        **base,
        "ok": ok,
        "message": message,
        "manifest_schema_version": raw_manifest.get("schema_version"),
        "hash_algorithm": raw_manifest.get("hash_algorithm"),
        "manifest_generated_at": raw_manifest.get("generated_at"),
        "manifest_scope": raw_manifest.get("scope"),
        "manifest_work_dir": raw_manifest.get("work_dir"),
        "manifest_output_dir": raw_manifest.get("output_dir"),
        "header_complete": header_complete,
        "header_blocker_count": len(header_blockers),
        "header_blockers": header_blockers[:MANIFEST_METADATA_BLOCKER_SAMPLE_LIMIT],
        "table_count": table_count,
        "metadata_complete": metadata_complete,
        "metadata_blocker_count": len(metadata_blockers),
        "metadata_blockers": metadata_blockers[:MANIFEST_METADATA_BLOCKER_SAMPLE_LIMIT],
        "final_scope": final_scope,
        "final_scope_blocker_count": len(final_scope_blockers),
        "final_scope_blockers": final_scope_blockers[
            :MANIFEST_METADATA_BLOCKER_SAMPLE_LIMIT
        ],
        "non_final_key_count": len(non_final_keys),
        "non_final_keys": non_final_keys[:MANIFEST_METADATA_BLOCKER_SAMPLE_LIMIT],
        "source_paths_available": source_paths_available,
        "source_path_blocker_count": len(source_path_blockers),
        "source_path_blockers": source_path_blockers[
            :MANIFEST_METADATA_BLOCKER_SAMPLE_LIMIT
        ],
    }


def _manifest_header_blockers(raw_manifest: dict[str, object]) -> list[str]:
    blockers: list[str] = []
    if raw_manifest.get("schema_version") != 2:
        blockers.append("schema_version must be 2")
    if not isinstance(raw_manifest.get("generated_at"), str):
        blockers.append("generated_at must be present")
    if raw_manifest.get("hash_algorithm") != HASH_ALGORITHM:
        blockers.append(f"hash_algorithm must be {HASH_ALGORITHM}")
    if raw_manifest.get("scope") != "final":
        blockers.append("scope must be final")
    output_dir = raw_manifest.get("output_dir")
    if not isinstance(output_dir, str) or not output_dir:
        blockers.append("output_dir must be present")
    if not isinstance(raw_manifest.get("tables"), list):
        blockers.append("tables must be a list")
    return blockers


def _manifest_output_dir(raw_manifest: dict[str, object]) -> Path | None:
    output_dir = raw_manifest.get("output_dir")
    if not isinstance(output_dir, str) or not output_dir:
        return None
    return Path(output_dir).resolve(strict=False)


def _manifest_metadata_blockers(
    entries: dict[str, TableHashEntry],
) -> list[str]:
    blockers: list[str] = []
    for key, entry in sorted(entries.items()):
        if not key.endswith(".csv"):
            blockers.append(f"{key}: final output key must end with .csv")

        row_count = entry.row_count
        if not isinstance(row_count, int) or isinstance(row_count, bool):
            blockers.append(f"{key}: row_count must be a nonnegative integer")
        elif row_count < 0:
            blockers.append(f"{key}: row_count must be a nonnegative integer")

        columns = entry.columns
        if columns is None:
            blockers.append(f"{key}: columns metadata missing")
        elif not columns:
            blockers.append(f"{key}: columns metadata must include at least one column")

        if entry.physical_format != "csv":
            blockers.append(f"{key}: physical_format must be csv")
    return blockers


def _manifest_non_final_keys(entries: dict[str, TableHashEntry]) -> list[str]:
    return sorted(key for key in entries if not key.startswith("output_dir/"))


def _manifest_final_scope_blockers(non_final_keys: Sequence[str]) -> list[str]:
    return [f"{key}: key must be under output_dir/" for key in non_final_keys]


def _manifest_source_path_blockers(
    entries: dict[str, TableHashEntry],
    *,
    output_dir: Path | None,
) -> list[str]:
    blockers: list[str] = []
    for key, entry in sorted(entries.items()):
        if not entry.source_path:
            blockers.append(f"{key}: source_path metadata missing")
            continue
        source_path = Path(entry.source_path)
        resolved_source_path = source_path.resolve(strict=False)
        if output_dir is not None and not resolved_source_path.is_relative_to(
            output_dir
        ):
            blockers.append(f"{key}: source_path must be under manifest output_dir")
        if source_path.suffix.lower() != ".csv":
            blockers.append(f"{key}: source_path must be a CSV file")
        if source_path.name != Path(key).name:
            blockers.append(f"{key}: source_path filename must match manifest key")
        try:
            source_stat = source_path.stat()
        except FileNotFoundError:
            blockers.append(f"{key}: source_path file does not exist")
            continue
        except OSError as exc:
            blockers.append(f"{key}: source_path cannot be statted: {exc}")
            continue
        if not stat.S_ISREG(source_stat.st_mode):
            blockers.append(f"{key}: source_path must be a file")
        source_size_bytes = entry.source_size_bytes
        if not isinstance(source_size_bytes, int) or isinstance(
            source_size_bytes, bool
        ):
            blockers.append(f"{key}: source_size_bytes must be a nonnegative integer")
        elif source_size_bytes < 0:
            blockers.append(f"{key}: source_size_bytes must be a nonnegative integer")
        elif source_size_bytes != source_stat.st_size:
            blockers.append(
                f"{key}: source_size_bytes does not match current file size"
            )

        source_mtime_ns = entry.source_mtime_ns
        if not isinstance(source_mtime_ns, int) or isinstance(source_mtime_ns, bool):
            blockers.append(f"{key}: source_mtime_ns must be a nonnegative integer")
        elif source_mtime_ns < 0:
            blockers.append(f"{key}: source_mtime_ns must be a nonnegative integer")
        elif source_mtime_ns != source_stat.st_mtime_ns:
            blockers.append(f"{key}: source_mtime_ns does not match current file mtime")
    return blockers


def _manifest_comparison_counts(
    comparison: ManifestComparisonResult,
) -> dict[str, int]:
    return {
        "missing": len(comparison.missing),
        "extra": len(comparison.extra),
        "hash_mismatched": len(comparison.hash_mismatched),
        "row_count_mismatched": len(comparison.row_count_mismatched),
        "columns_mismatched": len(comparison.columns_mismatched),
    }


def _current_manifest_comparison(
    *,
    baseline: Path | None,
    current: Path | None,
) -> tuple[ManifestComparisonResult | None, str | None]:
    if baseline is None or current is None:
        return None, "legacy and refactor manifest paths must be provided"
    try:
        baseline_entries = load_hash_manifest_entries(baseline)
        current_entries = load_hash_manifest_entries(current)
    except (OSError, ValueError) as exc:
        return None, str(exc)
    return compare_manifest_entries(current_entries, baseline_entries), None


def _comparison_ok_matches(
    *,
    reported_ok: object,
    computed_comparison: ManifestComparisonResult | None,
) -> bool | None:
    if not isinstance(reported_ok, bool) or computed_comparison is None:
        return None
    return reported_ok is computed_comparison.ok


def _comparison_counts_match(
    *,
    reported_counts: object,
    computed_counts: dict[str, int] | None,
) -> bool | None:
    if not isinstance(reported_counts, dict) or computed_counts is None:
        return None
    normalized_reported_counts: dict[str, int] = {}
    for key in computed_counts:
        value = reported_counts.get(key)
        if not isinstance(value, int) or isinstance(value, bool):
            return False
        normalized_reported_counts[key] = value
    return normalized_reported_counts == computed_counts


def _comparison_report_check(
    path: Path | None,
    *,
    baseline: Path | None,
    current: Path | None,
) -> dict[str, object]:
    base = _artifact_check_base(path)
    if not base["provided"] or not base["exists"]:
        return base
    raw, error = _load_json_object(path)
    if error is not None:
        return {**base, "ok": False, "message": error}
    reported_baseline = raw.get("baseline")
    reported_current = raw.get("current")
    expected_baseline = (
        str(baseline.resolve(strict=False)) if baseline is not None else None
    )
    expected_current = (
        str(current.resolve(strict=False)) if current is not None else None
    )
    reported_baseline_sha256 = raw.get("baseline_manifest_sha256")
    reported_current_sha256 = raw.get("current_manifest_sha256")
    expected_baseline_sha256 = _hash_manifest_sha256(baseline)
    expected_current_sha256 = _hash_manifest_sha256(current)
    computed_comparison, computed_error = _current_manifest_comparison(
        baseline=baseline,
        current=current,
    )
    computed_counts = (
        _manifest_comparison_counts(computed_comparison)
        if computed_comparison is not None
        else None
    )
    reported_counts = raw.get("counts")
    comparison_ok_matches = _comparison_ok_matches(
        reported_ok=raw.get("ok"),
        computed_comparison=computed_comparison,
    )
    comparison_counts_match = _comparison_counts_match(
        reported_counts=reported_counts,
        computed_counts=computed_counts,
    )
    baseline_matches = (
        reported_baseline == expected_baseline
        if expected_baseline is not None
        else None
    )
    current_matches = (
        reported_current == expected_current if expected_current is not None else None
    )
    blockers = _comparison_report_blockers(
        schema_current=raw.get("schema_version") == COMPARISON_REPORT_SCHEMA_VERSION,
        comparison_ok=raw.get("ok") is True,
        baseline_matches=baseline_matches,
        current_matches=current_matches,
        baseline_sha256_matches=_digest_matches(
            reported_baseline_sha256,
            expected_baseline_sha256,
        ),
        current_sha256_matches=_digest_matches(
            reported_current_sha256,
            expected_current_sha256,
        ),
        computed_comparison_ok=computed_comparison.ok
        if computed_comparison is not None
        else None,
        comparison_ok_matches=comparison_ok_matches,
        comparison_counts_match=comparison_counts_match,
    )
    ok = not blockers
    return {
        **base,
        "ok": ok,
        "message": _comparison_report_message(blockers),
        "blockers": blockers,
        "schema_version": raw.get("schema_version"),
        "schema_current": raw.get("schema_version") == COMPARISON_REPORT_SCHEMA_VERSION,
        "reported_baseline": reported_baseline
        if isinstance(reported_baseline, str)
        else None,
        "expected_baseline": expected_baseline,
        "baseline_matches": baseline_matches,
        "reported_baseline_manifest_sha256": reported_baseline_sha256
        if _is_sha256_hex(reported_baseline_sha256)
        else None,
        "expected_baseline_manifest_sha256": expected_baseline_sha256,
        "baseline_manifest_sha256_matches": _digest_matches(
            reported_baseline_sha256,
            expected_baseline_sha256,
        ),
        "reported_current": reported_current
        if isinstance(reported_current, str)
        else None,
        "expected_current": expected_current,
        "current_matches": current_matches,
        "reported_current_manifest_sha256": reported_current_sha256
        if _is_sha256_hex(reported_current_sha256)
        else None,
        "expected_current_manifest_sha256": expected_current_sha256,
        "current_manifest_sha256_matches": _digest_matches(
            reported_current_sha256,
            expected_current_sha256,
        ),
        "counts": reported_counts if isinstance(reported_counts, dict) else None,
        "computed_counts": computed_counts,
        "current_manifest_comparison_ok": computed_comparison.ok
        if computed_comparison is not None
        else None,
        "comparison_ok_matches": comparison_ok_matches,
        "comparison_counts_match": comparison_counts_match,
        "comparison_error": computed_error,
        "generated_at": raw.get("generated_at"),
    }


def _comparison_report_blockers(
    *,
    schema_current: bool,
    comparison_ok: bool,
    baseline_matches: bool | None,
    current_matches: bool | None,
    baseline_sha256_matches: bool | None,
    current_sha256_matches: bool | None,
    computed_comparison_ok: bool | None,
    comparison_ok_matches: bool | None,
    comparison_counts_match: bool | None,
) -> list[str]:
    blockers: list[str] = []
    if not schema_current:
        blockers.append(f"schema_version must be {COMPARISON_REPORT_SCHEMA_VERSION}")
    if not comparison_ok:
        blockers.append("manifest comparison failed")
    if baseline_matches is False:
        blockers.append("comparison report baseline does not match legacy manifest")
    if current_matches is False:
        blockers.append("comparison report current does not match refactor manifest")
    if baseline_sha256_matches is False:
        blockers.append("comparison report baseline manifest contents are stale")
    if current_sha256_matches is False:
        blockers.append("comparison report current manifest contents are stale")
    if baseline_sha256_matches is None:
        blockers.append("comparison report baseline manifest digest unavailable")
    if current_sha256_matches is None:
        blockers.append("comparison report current manifest digest unavailable")
    if computed_comparison_ok is False:
        blockers.append("current manifests do not match")
    if computed_comparison_ok is None:
        blockers.append("current manifest comparison unavailable")
    if comparison_ok_matches is False:
        blockers.append("comparison report ok flag does not match current manifests")
    if comparison_ok_matches is None:
        blockers.append("comparison report ok flag unavailable")
    if comparison_counts_match is False:
        blockers.append("comparison report counts do not match current manifests")
    if comparison_counts_match is None:
        blockers.append("comparison report counts unavailable")
    return blockers


def _comparison_report_message(blockers: Sequence[str]) -> str:
    if not blockers:
        return "manifest comparison passed"
    if len(blockers) == 1 and any("schema_version" in blocker for blocker in blockers):
        return "manifest comparison report schema is stale or missing"
    if any("contents are stale" in blocker for blocker in blockers):
        return "manifest comparison report does not match current manifest contents"
    if any("current manifests do not match" in blocker for blocker in blockers):
        return "current manifests do not match"
    if any("current manifests" in blocker for blocker in blockers):
        return "manifest comparison report does not match current manifests"
    if any("does not match" in blocker for blocker in blockers):
        return "manifest comparison report does not match requested manifests"
    if any("digest unavailable" in blocker for blocker in blockers):
        return "manifest comparison report lacks manifest digests"
    return "manifest comparison failed"


def _profile_provenance_check(path: Path | None) -> dict[str, object]:
    base = _artifact_check_base(path)
    if not base["provided"] or not base["exists"]:
        return base
    raw, error = _load_json_object(path)
    if error is not None:
        return {**base, "ok": False, "message": error}
    output_count = raw.get("output_file_count")
    generated_count = raw.get("generated_file_count")
    total_seconds = raw.get("total_seconds")
    peak_rss_mb = raw.get("peak_rss_mb")
    disk_footprint = raw.get("disk_footprint_bytes")
    stage_timings = raw.get("stage_timings_seconds")
    output_files = raw.get("output_files")
    current_code_state_sha256 = current_git_code_state_sha256()
    blockers = _profile_provenance_blockers(
        schema_version=raw.get("schema_version"),
        output_count=output_count,
        generated_count=generated_count,
        total_seconds=total_seconds,
        peak_rss_mb=peak_rss_mb,
        disk_footprint=disk_footprint,
        stage_timings=stage_timings,
        started_at=raw.get("started_at"),
        ended_at=raw.get("ended_at"),
        package_version=raw.get("package_version"),
        python_version=raw.get("python_version"),
        git_commit=raw.get("git_commit"),
        git_dirty=raw.get("git_dirty"),
        git_code_dirty=raw.get("git_code_dirty"),
        git_code_state_sha256=raw.get("git_code_state_sha256"),
        current_git_code_state_sha256=current_code_state_sha256,
        config_path=raw.get("config_path"),
        config_sha256=raw.get("config_sha256"),
        strict=raw.get("strict"),
        output_files=output_files,
    )
    ok = not blockers
    return {
        **base,
        "ok": ok,
        "message": "profile provenance complete"
        if ok
        else "profile provenance incomplete",
        "blockers": blockers,
        "schema_version": raw.get("schema_version"),
        "generated_file_count": generated_count,
        "output_file_count": output_count,
        "total_seconds": total_seconds,
        "peak_rss_mb": peak_rss_mb,
        "disk_footprint_bytes": disk_footprint
        if isinstance(disk_footprint, dict)
        else None,
        "stage_timings_seconds": stage_timings
        if isinstance(stage_timings, dict)
        else None,
        "started_at": raw.get("started_at"),
        "ended_at": raw.get("ended_at"),
        "package_version": raw.get("package_version"),
        "python_version": raw.get("python_version"),
        "git_commit": raw.get("git_commit"),
        "git_dirty": raw.get("git_dirty"),
        "git_code_dirty": raw.get("git_code_dirty"),
        "git_code_state_sha256": raw.get("git_code_state_sha256"),
        "current_git_code_dirty": current_git_code_dirty(),
        "current_git_code_state_sha256": current_code_state_sha256,
        "current_git_code_state_sha256_matches": _digest_matches(
            raw.get("git_code_state_sha256"),
            current_code_state_sha256,
        ),
        "config_path": raw.get("config_path"),
        "config_sha256": raw.get("config_sha256"),
        "strict": raw.get("strict"),
        "output_files": output_files if isinstance(output_files, list) else None,
    }


def _artifact_consistency_check(
    *,
    input_status_check: dict[str, object],
    profile_provenance_check: dict[str, object],
) -> dict[str, object]:
    input_config_path = input_status_check.get("config_path")
    profile_config_path = profile_provenance_check.get("config_path")
    input_config_sha256 = input_status_check.get("config_sha256")
    profile_config_sha256 = profile_provenance_check.get("config_sha256")
    config_path_matches = (
        input_config_path == profile_config_path
        if isinstance(input_config_path, str)
        and isinstance(profile_config_path, str)
        and input_config_path
        and profile_config_path
        else None
    )
    config_sha256_matches = (
        input_config_sha256 == profile_config_sha256
        if _is_sha256_hex(input_config_sha256) and _is_sha256_hex(profile_config_sha256)
        else None
    )
    current_config_sha256 = (
        _file_sha256(Path(input_config_path))
        if isinstance(input_config_path, str) and input_config_path
        else None
    )
    current_config_sha256_matches = _digest_matches(
        current_config_sha256,
        input_config_sha256 if _is_sha256_hex(input_config_sha256) else None,
    )
    blockers = _artifact_consistency_blockers(
        config_path_matches=config_path_matches,
        config_sha256_matches=config_sha256_matches,
        current_config_sha256_matches=current_config_sha256_matches,
    )
    ok = not blockers
    return {
        "ok": ok,
        "message": "artifact config identity matches"
        if ok
        else "artifact config identity unavailable or mismatched",
        "blockers": blockers,
        "input_config_path": input_config_path
        if isinstance(input_config_path, str)
        else None,
        "profile_config_path": profile_config_path
        if isinstance(profile_config_path, str)
        else None,
        "config_path_matches": config_path_matches,
        "input_config_sha256": input_config_sha256
        if _is_sha256_hex(input_config_sha256)
        else None,
        "profile_config_sha256": profile_config_sha256
        if _is_sha256_hex(profile_config_sha256)
        else None,
        "config_sha256_matches": config_sha256_matches,
        "current_config_sha256": current_config_sha256
        if _is_sha256_hex(current_config_sha256)
        else None,
        "current_config_sha256_matches": current_config_sha256_matches,
    }


def _artifact_consistency_blockers(
    *,
    config_path_matches: bool | None,
    config_sha256_matches: bool | None,
    current_config_sha256_matches: bool | None,
) -> list[str]:
    blockers: list[str] = []
    if config_path_matches is False:
        blockers.append("input and profile config paths differ")
    elif config_path_matches is None:
        blockers.append("input/profile config paths unavailable")
    if config_sha256_matches is False:
        blockers.append("input and profile config SHA-256 values differ")
    elif config_sha256_matches is None:
        blockers.append("input/profile config SHA-256 values unavailable")
    if current_config_sha256_matches is False:
        blockers.append("recorded config SHA-256 does not match current config file")
    elif current_config_sha256_matches is None:
        blockers.append("current config SHA-256 check unavailable")
    return blockers


def _required_root_check(
    *,
    required_root: Path | None,
    min_free_gb: float | None,
    input_status: Path | None,
    legacy_manifest: Path | None,
    refactor_manifest: Path | None,
    comparison_report: Path | None,
    profile_provenance: Path | None,
    input_status_check: dict[str, object],
    profile_provenance_check: dict[str, object],
) -> dict[str, object]:
    if required_root is None:
        return {
            "ok": True,
            "message": "required external root not configured",
            "required_root": None,
            "min_free_gb": min_free_gb,
            "free_gb": None,
            "space_ok": None,
            "blockers": [],
            "checked_paths": [],
        }

    root = required_root.expanduser().resolve(strict=False)
    checked_paths: list[dict[str, object]] = []
    blockers: list[str] = []
    free_gb: float | None = None
    space_ok: bool | None = None

    if min_free_gb is not None:
        if min_free_gb < 0:
            blockers.append("required_root_min_free_gb must be nonnegative")
            space_ok = False
        else:
            try:
                free_bytes = shutil.disk_usage(root).free
            except OSError as exc:
                blockers.append(f"required root free-space check failed: {exc}")
                space_ok = False
            else:
                free_gb = free_bytes / 1024**3
                space_ok = free_gb >= min_free_gb
                if not space_ok:
                    blockers.append("required root free_gb below min_free_gb")

    for label, path in (
        ("input_status_artifact", input_status),
        ("legacy_manifest_artifact", legacy_manifest),
        ("refactor_manifest_artifact", refactor_manifest),
        ("comparison_report_artifact", comparison_report),
        ("profile_provenance_artifact", profile_provenance),
    ):
        if path is not None:
            _append_required_root_path(
                label=label,
                path=path,
                root=root,
                checked_paths=checked_paths,
                blockers=blockers,
            )

    for label, raw_path in (
        ("input_config_path", input_status_check.get("config_path")),
        ("profile_config_path", profile_provenance_check.get("config_path")),
    ):
        if isinstance(raw_path, str) and raw_path:
            config_path = Path(raw_path)
            _append_required_root_path(
                label=label,
                path=config_path,
                root=root,
                checked_paths=checked_paths,
                blockers=blockers,
            )
            config_paths, config_error = _config_root_paths(config_path)
            if config_error is not None:
                blockers.append(f"{label}: {config_error}")
            else:
                for config_label, config_root in config_paths.items():
                    _append_required_root_path(
                        label=f"{label}.{config_label}",
                        path=config_root,
                        root=root,
                        checked_paths=checked_paths,
                        blockers=blockers,
                    )

    _append_manifest_required_root_paths(
        label="legacy_manifest",
        manifest=legacy_manifest,
        root=root,
        checked_paths=checked_paths,
        blockers=blockers,
    )
    _append_manifest_required_root_paths(
        label="refactor_manifest",
        manifest=refactor_manifest,
        root=root,
        checked_paths=checked_paths,
        blockers=blockers,
    )
    _append_profile_required_root_paths(
        profile_provenance_check=profile_provenance_check,
        root=root,
        checked_paths=checked_paths,
        blockers=blockers,
    )

    ok = not blockers
    return {
        "ok": ok,
        "message": _required_root_message(ok=ok, space_ok=space_ok),
        "required_root": str(root),
        "min_free_gb": min_free_gb,
        "free_gb": free_gb,
        "space_ok": space_ok,
        "blockers": blockers[:MANIFEST_METADATA_BLOCKER_SAMPLE_LIMIT],
        "blocker_count": len(blockers),
        "checked_paths": checked_paths[:MANIFEST_METADATA_BLOCKER_SAMPLE_LIMIT],
        "checked_path_count": len(checked_paths),
    }


def _required_root_message(*, ok: bool, space_ok: bool | None) -> str:
    if ok:
        if space_ok is True:
            return (
                "validation artifacts are under required external root "
                "with enough space"
            )
        return "validation artifacts are under required external root"
    if space_ok is False:
        return (
            "validation artifacts are outside required external root "
            "or lack required space"
        )
    return "validation artifacts are outside required external root"


def _append_required_root_path(
    *,
    label: str,
    path: Path,
    root: Path,
    checked_paths: list[dict[str, object]],
    blockers: list[str],
) -> None:
    resolved_path = path.expanduser().resolve(strict=False)
    under_root = resolved_path.is_relative_to(root)
    checked_paths.append(
        {
            "label": label,
            "path": str(resolved_path),
            "under_root": under_root,
        }
    )
    if not under_root:
        blockers.append(f"{label} must be under required root")


def _config_root_paths(config_path: Path) -> tuple[dict[str, Path], str | None]:
    try:
        raw = yaml.safe_load(config_path.read_text())
    except OSError as exc:
        return {}, f"config file unavailable for root check: {exc}"
    except ValueError as exc:
        return {}, f"config file unreadable for root check: {exc}"
    if not isinstance(raw, dict):
        return {}, "config file must contain a mapping for root check"
    roots: dict[str, Path] = {}
    for key in ("data_dir", "work_dir", "output_dir"):
        value = raw.get(key)
        if not isinstance(value, str) or not value.strip():
            return {}, f"config {key} missing for root check"
        path = Path(value).expanduser()
        if not path.is_absolute():
            path = config_path.parent / path
        roots[key] = path.resolve(strict=False)
    return roots, None


def _append_manifest_required_root_paths(
    *,
    label: str,
    manifest: Path | None,
    root: Path,
    checked_paths: list[dict[str, object]],
    blockers: list[str],
) -> None:
    if manifest is None:
        return
    manifest_path = _hash_manifest_file_path(manifest)
    if manifest_path is None or not manifest_path.exists():
        return
    raw_manifest, raw_error = _load_json_object(manifest_path)
    if raw_error is None:
        for root_key in ("work_dir", "output_dir"):
            raw_root = raw_manifest.get(root_key)
            if isinstance(raw_root, str) and raw_root:
                _append_required_root_path(
                    label=f"{label}.{root_key}",
                    path=Path(raw_root),
                    root=root,
                    checked_paths=checked_paths,
                    blockers=blockers,
                )
    try:
        entries = load_hash_manifest_entries(manifest)
    except (OSError, ValueError):
        return
    for key, entry in sorted(entries.items()):
        if entry.source_path:
            _append_required_root_path(
                label=f"{label}.source_path.{key}",
                path=Path(entry.source_path),
                root=root,
                checked_paths=checked_paths,
                blockers=blockers,
            )


def _append_profile_required_root_paths(
    *,
    profile_provenance_check: dict[str, object],
    root: Path,
    checked_paths: list[dict[str, object]],
    blockers: list[str],
) -> None:
    output_files = profile_provenance_check.get("output_files")
    if not isinstance(output_files, list):
        return
    for index, item in enumerate(output_files):
        if not isinstance(item, dict):
            continue
        raw_path = item.get("path")
        if isinstance(raw_path, str) and raw_path:
            _append_required_root_path(
                label=f"profile_output_files[{index}]",
                path=Path(raw_path),
                root=root,
                checked_paths=checked_paths,
                blockers=blockers,
            )


def _profile_refactor_outputs_check(
    *,
    refactor_manifest: Path | None,
    profile_provenance_check: dict[str, object],
) -> dict[str, object]:
    base = _artifact_check_base(refactor_manifest)
    if not base["provided"] or not base["exists"]:
        return {
            **base,
            "message": "refactor manifest missing for profile output check",
        }
    try:
        entries = load_hash_manifest_entries(refactor_manifest)
    except (OSError, ValueError) as exc:
        return {**base, "ok": False, "message": str(exc)}

    profile_paths = _profile_output_path_set(profile_provenance_check)
    configured_output_dir, configured_output_dir_error = _profile_config_output_dir(
        profile_provenance_check
    )
    manifest_paths: list[str] = []
    missing_source_path_keys: list[str] = []
    non_final_keys: list[str] = []
    for key, entry in sorted(entries.items()):
        if not key.startswith("output_dir/"):
            non_final_keys.append(key)
        if not entry.source_path:
            missing_source_path_keys.append(key)
            continue
        manifest_paths.append(_normalized_manifest_path(entry.source_path))

    manifest_path_set = set(manifest_paths)
    missing_from_profile = sorted(manifest_path_set - profile_paths)
    missing_from_manifest = sorted(profile_paths - manifest_path_set)
    manifest_paths_outside_output_dir = _paths_outside_root(
        manifest_path_set,
        configured_output_dir,
    )
    profile_paths_outside_output_dir = _paths_outside_root(
        profile_paths,
        configured_output_dir,
    )
    manifest_key_source_mismatches = _manifest_key_source_mismatches(
        entries,
        configured_output_dir,
    )
    blockers: list[str] = []
    if not entries:
        blockers.append("refactor manifest has no tables")
    if non_final_keys:
        blockers.append("refactor manifest must use final-output scope")
    if configured_output_dir_error is not None:
        blockers.append(configured_output_dir_error)
    if manifest_paths_outside_output_dir:
        blockers.append("refactor manifest source paths outside configured output_dir")
    if profile_paths_outside_output_dir:
        blockers.append("profile output inventory paths outside configured output_dir")
    if manifest_key_source_mismatches:
        blockers.append("refactor manifest keys do not match configured source paths")
    if missing_source_path_keys:
        blockers.append("refactor manifest table source_path metadata missing")
    if missing_from_profile:
        blockers.append(
            "refactor manifest source paths absent from profile output inventory"
        )
    if missing_from_manifest:
        blockers.append("profile output inventory paths absent from refactor manifest")

    ok = not blockers
    return {
        **base,
        "ok": ok,
        "message": "profile output inventory covers refactor manifest outputs"
        if ok
        else "profile output inventory does not cover refactor manifest outputs",
        "blockers": blockers,
        "table_count": len(entries),
        "profile_output_file_count": len(profile_paths),
        "manifest_source_path_count": len(manifest_paths),
        "configured_output_dir": str(configured_output_dir)
        if configured_output_dir is not None
        else None,
        "missing_source_path_keys": missing_source_path_keys,
        "non_final_keys": non_final_keys,
        "manifest_paths_outside_output_dir": manifest_paths_outside_output_dir,
        "profile_paths_outside_output_dir": profile_paths_outside_output_dir,
        "manifest_key_source_mismatches": manifest_key_source_mismatches,
        "missing_from_profile": missing_from_profile,
        "missing_from_manifest": missing_from_manifest,
    }


def _manifest_key_source_mismatches(
    entries: dict[str, TableHashEntry],
    configured_output_dir: Path | None,
) -> list[dict[str, str]]:
    if configured_output_dir is None:
        return []
    resolved_output_dir = configured_output_dir.resolve(strict=False)
    mismatches: list[dict[str, str]] = []
    for key, entry in sorted(entries.items()):
        if not entry.source_path:
            continue
        source_path = Path(entry.source_path).resolve(strict=False)
        if not source_path.is_relative_to(resolved_output_dir):
            continue
        expected_key = (
            "output_dir/" + source_path.relative_to(resolved_output_dir).as_posix()
        )
        if key != expected_key:
            mismatches.append(
                {
                    "key": key,
                    "expected_key": expected_key,
                    "source_path": str(source_path),
                }
            )
    return mismatches


def _profile_config_output_dir(
    profile_provenance_check: dict[str, object],
) -> tuple[Path | None, str | None]:
    config_path = profile_provenance_check.get("config_path")
    if not isinstance(config_path, str) or not config_path:
        return None, "profile config path unavailable for output_dir check"
    config_file = Path(config_path)
    try:
        raw = yaml.safe_load(config_file.read_text())
    except (OSError, yaml.YAMLError) as exc:
        return None, f"profile config output_dir unavailable: {exc}"
    if not isinstance(raw, dict):
        return None, "profile config output_dir unavailable: config is not a mapping"
    output_dir = raw.get("output_dir")
    if not isinstance(output_dir, str) or not output_dir.strip():
        return None, "profile config output_dir unavailable: output_dir missing"
    path = Path(output_dir).expanduser()
    if not path.is_absolute():
        path = config_file.parent / path
    return path.resolve(strict=False), None


def _paths_outside_root(paths: Iterable[str], root: Path | None) -> list[str]:
    if root is None:
        return []
    resolved_root = root.resolve(strict=False)
    return sorted(
        path
        for path in paths
        if not Path(path).resolve(strict=False).is_relative_to(resolved_root)
    )


def _profile_output_path_set(profile_provenance_check: dict[str, object]) -> set[str]:
    output_files = profile_provenance_check.get("output_files")
    if not isinstance(output_files, list):
        return set()
    paths: set[str] = set()
    for item in output_files:
        if not isinstance(item, dict):
            continue
        path = item.get("path")
        if isinstance(path, str) and path:
            paths.add(_normalized_manifest_path(path))
    return paths


def _normalized_manifest_path(path: str) -> str:
    return str(Path(path).resolve(strict=False))


def _profile_provenance_blockers(
    *,
    schema_version: object,
    output_count: object,
    generated_count: object,
    total_seconds: object,
    peak_rss_mb: object,
    disk_footprint: object,
    stage_timings: object,
    started_at: object,
    ended_at: object,
    package_version: object,
    python_version: object,
    git_commit: object,
    git_dirty: object,
    git_code_dirty: object,
    git_code_state_sha256: object,
    current_git_code_state_sha256: object,
    config_path: object,
    config_sha256: object,
    strict: object,
    output_files: object,
) -> list[str]:
    blockers: list[str] = []
    if schema_version != 2:
        blockers.append("schema_version must be 2")
    if not isinstance(output_count, int) or output_count <= 0:
        blockers.append("output_file_count must be a positive integer")
    if not isinstance(generated_count, int) or generated_count <= 0:
        blockers.append("generated_file_count must be a positive integer")
    elif isinstance(output_count, int) and generated_count < output_count:
        blockers.append("generated_file_count must be at least output_file_count")
    if not isinstance(total_seconds, (int, float)) or total_seconds < 0:
        blockers.append("total_seconds must be a nonnegative number")
    if not isinstance(peak_rss_mb, (int, float)) or peak_rss_mb <= 0:
        blockers.append("peak_rss_mb must be a positive number")
    if not isinstance(disk_footprint, dict):
        blockers.append("disk_footprint_bytes must be a mapping")
    else:
        for key in ("work_dir", "output_dir"):
            value = disk_footprint.get(key)
            if not isinstance(value, int) or value < 0:
                blockers.append(
                    f"disk_footprint_bytes.{key} must be a nonnegative integer"
                )
    if not isinstance(stage_timings, dict):
        blockers.append("stage_timings_seconds must be a mapping")
    if not isinstance(started_at, str) or not started_at:
        blockers.append("started_at must be present")
    if not isinstance(ended_at, str) or not ended_at:
        blockers.append("ended_at must be present")
    if not isinstance(package_version, str) or not package_version:
        blockers.append("package_version must be present")
    if not isinstance(python_version, str) or not python_version:
        blockers.append("python_version must be present")
    if not isinstance(git_commit, str) or not git_commit:
        blockers.append("git_commit must be present")
    if not isinstance(git_dirty, bool):
        blockers.append("git_dirty must be a boolean")
    if not isinstance(git_code_dirty, bool):
        blockers.append("git_code_dirty must be a boolean")
    if not _is_sha256_hex(git_code_state_sha256):
        blockers.append("git_code_state_sha256 must be a SHA-256 hex digest")
    elif not _is_sha256_hex(current_git_code_state_sha256):
        blockers.append("current git_code_state_sha256 unavailable")
    elif git_code_state_sha256 != current_git_code_state_sha256:
        blockers.append("git_code_state_sha256 must match current code state")
    if not isinstance(config_path, str) or not config_path:
        blockers.append("config_path must be present")
    if not _is_sha256_hex(config_sha256):
        blockers.append("config_sha256 must be a SHA-256 hex digest")
    if strict is not True:
        blockers.append("strict must be true")
    blockers.extend(
        _profile_output_file_blockers(
            output_count=output_count,
            output_files=output_files,
        )
    )
    return blockers


def _profile_output_file_blockers(
    *,
    output_count: object,
    output_files: object,
) -> list[str]:
    blockers: list[str] = []
    if not isinstance(output_files, list):
        return ["output_files must be a list"]
    if isinstance(output_count, int) and len(output_files) != output_count:
        blockers.append("output_files length must match output_file_count")
    for index, raw_file in enumerate(output_files):
        prefix = f"output_files[{index}]"
        if not isinstance(raw_file, dict):
            blockers.append(f"{prefix} must be a mapping")
            continue
        path = raw_file.get("path")
        exists = raw_file.get("exists")
        size_bytes = raw_file.get("size_bytes")
        mtime_ns = raw_file.get("mtime_ns")
        if not isinstance(path, str) or not path:
            blockers.append(f"{prefix}.path must be present")
            current_path = None
        else:
            current_path = Path(path)
            if current_path.suffix.lower() != ".csv":
                blockers.append(f"{prefix}.path must be a CSV file")
        if exists is not True:
            blockers.append(f"{prefix}.exists must be true")
        if not isinstance(size_bytes, int) or size_bytes < 0:
            blockers.append(f"{prefix}.size_bytes must be a nonnegative integer")
            expected_size = None
        else:
            expected_size = size_bytes
        if not isinstance(mtime_ns, int) or isinstance(mtime_ns, bool) or mtime_ns < 0:
            blockers.append(f"{prefix}.mtime_ns must be a nonnegative integer")
            expected_mtime_ns = None
        else:
            expected_mtime_ns = mtime_ns
        if current_path is None:
            continue
        try:
            current_stat = current_path.stat()
        except FileNotFoundError:
            blockers.append(f"{prefix}.path does not exist on disk")
            continue
        except OSError as exc:
            blockers.append(f"{prefix}.path cannot be statted: {exc}")
            continue
        if not stat.S_ISREG(current_stat.st_mode):
            blockers.append(f"{prefix}.path must be a file")
        if expected_size is not None and current_stat.st_size != expected_size:
            blockers.append(f"{prefix}.size_bytes does not match current file size")
        if (
            expected_mtime_ns is not None
            and current_stat.st_mtime_ns != expected_mtime_ns
        ):
            blockers.append(f"{prefix}.mtime_ns does not match current file mtime")
    return blockers


def _is_sha256_hex(value: object) -> bool:
    if not isinstance(value, str) or len(value) != 64:
        return False
    return all(character in "0123456789abcdefABCDEF" for character in value)


def _is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _digest_matches(reported: object, expected: str | None) -> bool | None:
    if not _is_sha256_hex(reported) or expected is None:
        return None
    return reported == expected


def _hash_manifest_sha256(path: Path | None) -> str | None:
    return _file_sha256(_hash_manifest_file_path(path))


def _hash_manifest_file_path(path: Path | None) -> Path | None:
    if path is None:
        return None
    if path.is_dir():
        return path / HASH_MANIFEST_FILENAME
    return path


def _file_sha256(path: Path | None) -> str | None:
    if path is None or not path.exists():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _artifact_check_base(path: Path | None) -> dict[str, object]:
    if path is None:
        return {
            "provided": False,
            "exists": False,
            "ok": False,
            "path": None,
            "message": "artifact path not provided",
            "blockers": ["artifact path not provided"],
        }
    exists = path.exists()
    return {
        "provided": True,
        "exists": exists,
        "ok": False,
        "path": str(path.resolve(strict=False)),
        "message": "artifact found" if exists else "artifact missing",
        "blockers": [] if exists else ["artifact missing"],
    }


def _load_json_object(path: Path) -> tuple[dict[str, object], str | None]:
    try:
        raw = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        return {}, str(exc)
    if not isinstance(raw, dict):
        return {}, "artifact JSON must be an object"
    return raw, None


def validate_input_headers(config: Config) -> None:
    """Validate headers for all matched input files."""

    logger = logging.getLogger(__name__)
    domain_paths = collect_domain_paths(config)
    for domain_name, paths in domain_paths.items():
        required = REQUIRED_COLUMNS.get(domain_name)
        if not required:
            logger.info(
                "No schema defined for domain '%s'; skipping header check.",
                domain_name,
            )
            continue
        for path in paths:
            file_required = required
            if domain_name == "meds" and is_medication_ingredient_export(path):
                file_required = list(COMBINED_MEDICATION_REQUIRED_COLUMNS)
            try:
                validate_csv_columns(path, file_required)
            except ValueError as exc:
                raise ConfigError(f"{exc} (domain '{domain_name}')") from exc
        logger.info("Validated %s file(s) for domain '%s'.", len(paths), domain_name)


def inspect_input_paths(
    config: Config,
    *,
    config_path: Path | None = None,
    allow_missing: bool = False,
    json_output: bool = False,
    json_out: Path | None = None,
    min_free_gb: float | None = None,
    max_matches: int | None = None,
    selected_domains: set[str] | None = None,
    skip_space_check: bool = False,
    domain_timeout_seconds: float | None = None,
) -> int:
    """Log configured domain matches and return nonzero when any are missing."""

    logger = logging.getLogger(__name__)
    if domain_timeout_seconds is not None:
        if domain_timeout_seconds <= 0:
            raise ConfigError("domain-timeout-seconds must be positive when provided.")
        if max_matches is None:
            raise ConfigError(
                "domain-timeout-seconds requires max_matches so timeout-based "
                "status snapshots remain bounded."
            )
        inspections, timed_out_domains, probe_errors = (
            _inspect_domain_paths_with_timeouts(
                config,
                config_path=config_path,
                max_matches=max_matches,
                selected_domains=selected_domains,
                timeout_seconds=domain_timeout_seconds,
            )
        )
    else:
        inspections = inspect_domain_paths(
            config,
            max_matches=max_matches,
            domain_names=selected_domains,
        )
        timed_out_domains = set()
        probe_errors = {}
    missing = [inspection.name for inspection in inspections if not inspection.paths]
    filesystems = [] if skip_space_check else _filesystem_statuses(config)
    low_space = _low_space_labels(filesystems, min_free_gb)
    if json_output or json_out is not None:
        payload = _input_inspection_payload(
            config=config,
            config_path=config_path,
            inspections=inspections,
            missing=missing,
            filesystems=filesystems,
            low_space=low_space,
            min_free_gb=min_free_gb,
            max_matches=max_matches,
            selected_domains=selected_domains,
            skip_space_check=skip_space_check,
            timed_out_domains=timed_out_domains,
            probe_errors=probe_errors,
            domain_timeout_seconds=domain_timeout_seconds,
        )
        rendered = json.dumps(payload, indent=2, sort_keys=True)
        if json_output:
            print(rendered)
        if json_out is not None:
            write_text_atomic(json_out, f"{rendered}\n")
        return _inspection_exit_code(
            missing=missing,
            low_space=low_space,
            timed_out=sorted(timed_out_domains),
            probe_errors=probe_errors,
            allow_missing=allow_missing,
        )

    for inspection in inspections:
        first_path = inspection.first_path
        if first_path is None:
            logger.warning(
                "Domain '%s' matched 0 file(s) using pattern '%s'.",
                inspection.name,
                inspection.pattern,
            )
            continue
        match_summary = (
            f"at least {inspection.matched_count}"
            if inspection.truncated
            else str(inspection.matched_count)
        )
        logger.info(
            "Domain '%s' matched %s file(s); first: %s",
            inspection.name,
            match_summary,
            first_path,
        )
    if missing and not allow_missing:
        logger.error("Missing input domains: %s", ", ".join(missing))
    if timed_out_domains:
        logger.warning(
            "Input inspection timed out for domain(s): %s",
            ", ".join(sorted(timed_out_domains)),
        )
    if probe_errors:
        logger.warning(
            "Input inspection failed for domain(s): %s",
            ", ".join(sorted(probe_errors)),
        )
    if skip_space_check:
        logger.info("Filesystem free-space checks skipped.")
    else:
        for item in filesystems:
            logger.info(
                "%s filesystem has %.2f GiB free at %s.",
                item["label"],
                item["free_gb"],
                item["checked_path"],
            )
    if low_space:
        logger.error(
            "Filesystems below %.2f GiB free: %s",
            min_free_gb,
            ", ".join(low_space),
        )
    return _inspection_exit_code(
        missing=missing,
        low_space=low_space,
        timed_out=sorted(timed_out_domains),
        probe_errors=probe_errors,
        allow_missing=allow_missing,
    )


def _inspect_domain_paths_with_timeouts(
    config: Config,
    *,
    config_path: Path | None,
    max_matches: int | None,
    selected_domains: set[str] | None,
    timeout_seconds: float,
) -> tuple[list[DomainInspection], set[str], dict[str, str]]:
    if config_path is None:
        raise ConfigError("config_path is required for timeout-based input probing.")

    domain_names = selected_domains or set(config.domains)
    unknown = sorted(domain_names - set(config.domains))
    if unknown:
        raise ConfigError(f"Unknown configured domain(s): {', '.join(unknown)}")

    inspections: list[DomainInspection] = []
    timed_out_domains: set[str] = set()
    probe_errors: dict[str, str] = {}
    domain_items = list(config.domains.items())
    for index, (domain_name, domain) in enumerate(domain_items):
        if domain_name not in domain_names:
            continue
        inspection = _inspect_one_domain_with_timeout(
            config_path=config_path,
            domain_name=domain_name,
            pattern=domain.pattern,
            max_matches=max_matches,
            timeout_seconds=timeout_seconds,
        )
        inspections.append(
            _with_search_dir_path(
                inspection.inspection,
                data_dir=config.data_dir,
            )
        )
        if inspection.timed_out:
            timed_out_domains.add(domain_name)
        if inspection.error:
            probe_errors[domain_name] = inspection.error
        if inspection.process_unreleased:
            for remaining_name, remaining_domain in domain_items[index + 1 :]:
                if remaining_name not in domain_names:
                    continue
                inspections.append(
                    _with_search_dir_path(
                        DomainInspection(
                            name=remaining_name,
                            pattern=remaining_domain.pattern,
                            paths=(),
                            search_dir=patterns_search_dir(
                                config.data_dir,
                                remaining_domain.pattern_list,
                            ),
                        ),
                        data_dir=config.data_dir,
                    )
                )
                probe_errors[remaining_name] = (
                    "skipped after previous domain probe timed out and did not "
                    "release promptly"
                )
            break
    return inspections, timed_out_domains, probe_errors


def _with_search_dir_path(
    inspection: DomainInspection,
    *,
    data_dir: Path,
) -> DomainInspection:
    if inspection.search_dir is not None:
        return inspection
    search_dir = pattern_search_dir(data_dir, inspection.pattern)
    return DomainInspection(
        name=inspection.name,
        pattern=inspection.pattern,
        paths=inspection.paths,
        truncated=inspection.truncated,
        matched_count_override=inspection.matched_count,
        search_dir=search_dir,
        search_dir_exists=None,
    )


@dataclass(frozen=True)
class _TimedDomainInspection:
    inspection: DomainInspection
    timed_out: bool = False
    error: str | None = None
    process_unreleased: bool = False


@dataclass(frozen=True)
class _DomainProbeCommandResult:
    completed: subprocess.CompletedProcess[str] | None
    process_unreleased: bool = False


def _inspect_one_domain_with_timeout(
    *,
    config_path: Path,
    domain_name: str,
    pattern: str,
    max_matches: int | None,
    timeout_seconds: float,
) -> _TimedDomainInspection:
    command = [
        sys.executable,
        "-m",
        "trinetx_preprocessing",
        "inspect-inputs",
        "--config",
        str(config_path),
        "--allow-missing",
        "--json",
        "--domain",
        domain_name,
        "--skip-space-check",
    ]
    if max_matches is not None:
        command.extend(["--max-matches", str(max_matches)])

    result = _run_domain_probe_command(command, timeout_seconds=timeout_seconds)
    if result.completed is None:
        return _TimedDomainInspection(
            DomainInspection(name=domain_name, pattern=pattern, paths=()),
            timed_out=True,
            process_unreleased=result.process_unreleased,
        )
    completed = result.completed

    if completed.returncode != 0:
        message = (completed.stderr or completed.stdout or "subprocess failed").strip()
        return _TimedDomainInspection(
            DomainInspection(name=domain_name, pattern=pattern, paths=()),
            error=message[-1000:],
        )

    try:
        payload = json.loads(completed.stdout)
        domain_payload = next(
            item for item in payload["domains"] if item["name"] == domain_name
        )
        search_dir = domain_payload.get("search_dir")
        search_dir_exists = domain_payload.get("search_dir_exists")
        return _TimedDomainInspection(
            DomainInspection(
                name=domain_name,
                pattern=domain_payload["pattern"],
                paths=tuple(Path(path) for path in domain_payload.get("paths", [])),
                truncated=bool(domain_payload["truncated"]),
                matched_count_override=int(domain_payload["matched_count"]),
                search_dir=Path(search_dir) if isinstance(search_dir, str) else None,
                search_dir_exists=search_dir_exists
                if isinstance(search_dir_exists, bool)
                else None,
            )
        )
    except (
        KeyError,
        StopIteration,
        TypeError,
        ValueError,
        json.JSONDecodeError,
    ) as exc:
        return _TimedDomainInspection(
            DomainInspection(name=domain_name, pattern=pattern, paths=()),
            error=f"Could not parse subprocess output: {exc}",
        )


def _run_domain_probe_command(
    command: Sequence[str],
    *,
    timeout_seconds: float,
) -> _DomainProbeCommandResult:
    with tempfile.TemporaryDirectory(prefix="trinetx-domain-probe-") as temp_dir:
        stdout_path = Path(temp_dir) / "stdout.txt"
        stderr_path = Path(temp_dir) / "stderr.txt"
        stdout_handle = stdout_path.open("w", encoding="utf-8")
        stderr_handle = stderr_path.open("w", encoding="utf-8")
        try:
            process = subprocess.Popen(
                command,
                stdout=stdout_handle,
                stderr=stderr_handle,
                text=True,
                start_new_session=True,
            )
            deadline = time.monotonic() + timeout_seconds
            while process.poll() is None:
                remaining_seconds = deadline - time.monotonic()
                if remaining_seconds <= 0:
                    _kill_process_group(process)
                    process_unreleased = _process_still_running(
                        process,
                        timeout_seconds=0.1,
                    )
                    stdout_handle.close()
                    stderr_handle.close()
                    return _DomainProbeCommandResult(
                        completed=None,
                        process_unreleased=process_unreleased,
                    )
                time.sleep(min(0.05, remaining_seconds))

            stdout_handle.close()
            stderr_handle.close()
            return _DomainProbeCommandResult(
                completed=subprocess.CompletedProcess(
                    args=command,
                    returncode=process.returncode,
                    stdout=stdout_path.read_text(),
                    stderr=stderr_path.read_text(),
                )
            )
        except BaseException:
            stdout_handle.close()
            stderr_handle.close()
            raise


def _kill_process_group(process: subprocess.Popen[str]) -> None:
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        return


def _process_still_running(
    process: subprocess.Popen[str],
    *,
    timeout_seconds: float,
) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if process.poll() is not None:
            return False
        time.sleep(0.01)
    return process.poll() is None


def _input_inspection_payload(
    *,
    config: Config,
    config_path: Path | None,
    inspections: Sequence[DomainInspection],
    missing: list[str],
    filesystems: list[dict[str, object]],
    low_space: list[str],
    min_free_gb: float | None,
    max_matches: int | None,
    selected_domains: set[str] | None,
    skip_space_check: bool,
    timed_out_domains: set[str] | None = None,
    probe_errors: dict[str, str] | None = None,
    domain_timeout_seconds: float | None = None,
) -> dict[str, object]:
    timed_out_domains = timed_out_domains or set()
    probe_errors = probe_errors or {}
    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "config_path": str(config_path.resolve()) if config_path is not None else None,
        "config_sha256": _file_sha256(config_path),
        "data_dir": str(config.data_dir),
        "work_dir": str(config.work_dir),
        "output_dir": str(config.output_dir),
        "all_present": not missing,
        "space_ok": None if skip_space_check else not low_space,
        "min_free_gb": min_free_gb,
        "max_matches": max_matches,
        "selected_domains": sorted(selected_domains) if selected_domains else None,
        "space_check_skipped": skip_space_check,
        "domain_timeout_seconds": domain_timeout_seconds,
        "timed_out": sorted(timed_out_domains),
        "probe_errors": probe_errors,
        "missing": missing,
        "low_space": low_space,
        "filesystems": filesystems,
        "domains": [
            _input_inspection_domain_payload(
                inspection,
                timed_out=inspection.name in timed_out_domains,
                probe_error=probe_errors.get(inspection.name),
            )
            for inspection in inspections
        ],
    }


def _input_inspection_domain_payload(
    inspection: DomainInspection,
    *,
    timed_out: bool,
    probe_error: str | None,
) -> dict[str, object]:
    path_sample = tuple(inspection.paths[:INPUT_STATUS_PATH_SAMPLE_LIMIT])
    paths_are_complete = len(path_sample) == inspection.matched_count
    return {
        "name": inspection.name,
        "pattern": inspection.pattern,
        "matched_count": inspection.matched_count,
        "matched_count_exact": not inspection.truncated,
        "truncated": inspection.truncated,
        "first_path": (
            str(inspection.first_path) if inspection.first_path is not None else None
        ),
        "search_dir": (
            str(inspection.search_dir) if inspection.search_dir is not None else None
        ),
        "search_dir_exists": inspection.search_dir_exists,
        "paths": [str(path) for path in path_sample],
        "path_sample_limit": INPUT_STATUS_PATH_SAMPLE_LIMIT,
        "paths_are_complete": paths_are_complete,
        "timed_out": timed_out,
        "probe_error": probe_error,
    }


def _inspection_exit_code(
    *,
    missing: list[str],
    low_space: list[str],
    timed_out: list[str],
    probe_errors: dict[str, str],
    allow_missing: bool,
) -> int:
    if low_space:
        return 2
    if (timed_out or probe_errors) and not allow_missing:
        return 2
    if missing and not allow_missing:
        return 2
    return 0


def _filesystem_statuses(config: Config) -> list[dict[str, object]]:
    return [
        _filesystem_status("data_dir", config.data_dir),
        _filesystem_status("work_dir", config.work_dir),
        _filesystem_status("output_dir", config.output_dir),
    ]


def _filesystem_status(label: str, path: Path) -> dict[str, object]:
    checked_path = _nearest_existing_path(path)
    usage = shutil.disk_usage(checked_path)
    free_gb = usage.free / (1024**3)
    return {
        "label": label,
        "path": str(path),
        "checked_path": str(checked_path),
        "total_bytes": usage.total,
        "used_bytes": usage.used,
        "free_bytes": usage.free,
        "free_gb": round(free_gb, 3),
    }


def _nearest_existing_path(path: Path) -> Path:
    candidate = path
    while not candidate.exists() and candidate != candidate.parent:
        candidate = candidate.parent
    return candidate


def _low_space_labels(
    filesystems: list[dict[str, object]],
    min_free_gb: float | None,
) -> list[str]:
    if min_free_gb is None:
        return []
    return [
        str(item["label"])
        for item in filesystems
        if float(item["free_gb"]) < min_free_gb
    ]

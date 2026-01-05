"""Command-line interface for the preprocessing pipeline."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Sequence

from . import __version__
from .config import (
    Config,
    ConfigError,
    collect_domain_paths,
    load_config,
    validate_config,
)
from .logging_utils import configure_logging
from .pipeline.diagnosis_stage import run_diagnosis_stage
from .pipeline.encounter_stage import run_encounter_stage
from .pipeline.labs_stage import run_labs_stage
from .pipeline.medications_stage import run_medications_stage
from .pipeline.procedure_stage import run_procedure_stage
from .pipeline.rfs_stage import run_rfs_stage
from .pipeline.run import run_pipeline
from .pipeline.vitals_stage import run_vitals_stage
from .profiling import run_profile
from .regression import (
    collect_output_hashes,
    compare_hashes,
    load_hash_manifest,
    write_hash_manifest,
)
from .tools.split_csv import split_csv
from .validation import validate_csv_columns

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

        config = load_config(args.config)
        validate_config(config)
        if args.command == "validate-config":
            logger.info("Configuration validated successfully.")
            return 0
        if args.command == "validate-inputs":
            validate_input_headers(config)
            logger.info("Input files validated successfully.")
            return 0
        if args.command in {"run", "run-all"}:
            output_paths = run_pipeline(config, strict=args.strict)
            logger.info(
                "Pipeline completed; wrote %s file(s) to %s and %s.",
                len(output_paths),
                config.work_dir,
                config.output_dir,
            )
            return 0
        if args.command == "profile":
            output_paths = run_profile(config, args.out, strict=args.strict)
            logger.info(
                "Profile run completed; wrote %s file(s) to %s and %s.",
                len(output_paths),
                config.work_dir,
                config.output_dir,
            )
            return 0
        if args.command == "baseline":
            output_paths = run_pipeline(config, strict=args.strict)
            hashes = collect_output_hashes(
                output_paths,
                work_dir=config.work_dir,
                output_dir=config.output_dir,
            )
            manifest_path = write_hash_manifest(args.out, hashes)
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
            output_paths = run_encounter_stage(config)
            logger.info(
                "Encounter stage completed; wrote %s file(s) to %s.",
                len(output_paths),
                config.work_dir,
            )
            return 0
        if args.command == "run-labs":
            output_paths = run_labs_stage(config)
            logger.info(
                "Labs stage completed; wrote %s file(s) to %s.",
                len(output_paths),
                config.work_dir,
            )
            return 0
        if args.command == "run-diagnosis":
            output_paths = run_diagnosis_stage(config)
            logger.info(
                "Diagnosis stage completed; wrote %s file(s) to %s.",
                len(output_paths),
                config.work_dir,
            )
            return 0
        if args.command == "run-meds":
            output_paths = run_medications_stage(config)
            logger.info(
                "Medications stage completed; wrote %s file(s) to %s.",
                len(output_paths),
                config.work_dir,
            )
            return 0
        if args.command == "run-procedure":
            output_paths = run_procedure_stage(config)
            logger.info(
                "Procedure stage completed; wrote %s file(s) to %s.",
                len(output_paths),
                config.work_dir,
            )
            return 0
        if args.command == "run-vitals":
            output_paths = run_vitals_stage(config)
            logger.info(
                "Vitals stage completed; wrote %s file(s) to %s.",
                len(output_paths),
                config.work_dir,
            )
            return 0
        if args.command == "run-rfs":
            output_paths = run_rfs_stage(config)
            logger.info(
                "RFS stage completed; wrote %s file(s) to %s.",
                len(output_paths),
                config.work_dir,
            )
            return 0
    except (ConfigError, FileNotFoundError, ValueError) as exc:
        logger.error("%s", exc)
        return 2

    parser.print_usage(sys.stderr)
    return 2


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
            try:
                validate_csv_columns(path, required)
            except ValueError as exc:
                raise ConfigError(f"{exc} (domain '{domain_name}')") from exc
        logger.info("Validated %s file(s) for domain '%s'.", len(paths), domain_name)

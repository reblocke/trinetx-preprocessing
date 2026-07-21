"""Command-line interface for the additive GLP-1 eligibility build."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Sequence

from ..filesystem import write_text_atomic
from .builder import build_glp1_eligibility
from .concept_sets import ConceptSetError, load_concept_sets
from .config import GLP1ConfigError, load_glp1_config
from .discovery import validate_export
from .monitoring import process_appears_active, read_run_state
from .outputs import summarize_database


def build_parser() -> argparse.ArgumentParser:
    """Build the GLP-1 command parser."""

    parser = argparse.ArgumentParser(
        prog="trinetx-glp1-eligibility",
        description=(
            "Build and inspect the additive GLP-1 eligibility database without "
            "changing the legacy-compatible preprocessing outputs."
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate_config_parser = subparsers.add_parser(
        "validate-config", help="Validate GLP-1 YAML and concept-set files."
    )
    validate_config_parser.add_argument("--config", type=Path, required=True)

    validate_export_parser = subparsers.add_parser(
        "validate-export", help="Discover supported source files and validate headers."
    )
    validate_export_parser.add_argument("--input", type=Path, required=True)
    validate_export_parser.add_argument("--json-out", type=Path)

    build_command = subparsers.add_parser(
        "build", help="Build the versioned GLP-1 DuckDB and Parquet outputs."
    )
    build_command.add_argument("--input", type=Path, required=True)
    build_command.add_argument("--output", type=Path, required=True)
    build_command.add_argument("--config", type=Path, required=True)
    build_command.add_argument(
        "--replace",
        action="store_true",
        help="Atomically replace a completed output from a different build.",
    )

    summarize_parser = subparsers.add_parser(
        "summarize", help="Print aggregate counts from a completed database."
    )
    summarize_parser.add_argument("--database", type=Path, required=True)
    summarize_parser.add_argument("--json", action="store_true")

    status_parser = subparsers.add_parser(
        "status", help="Read a long-running build's atomic progress state."
    )
    status_parser.add_argument("--output", type=Path, required=True)
    status_parser.add_argument("--json", action="store_true")
    status_parser.add_argument(
        "--watch",
        action="store_true",
        help="Poll until the build finishes, fails, or its local worker exits.",
    )
    status_parser.add_argument(
        "--interval-seconds",
        type=_positive_interval,
        default=30.0,
        help="Polling interval for --watch (default: 30 seconds).",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the GLP-1 CLI."""

    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "validate-config":
            config = load_glp1_config(args.config)
            catalog = load_concept_sets(config.concept_sets_dir)
            print(
                f"Valid GLP-1 config {config.schema_version}; "
                f"loaded {len(catalog.concepts)} concept rules."
            )
            return 0

        if args.command == "validate-export":
            report = validate_export(args.input)
            payload = json.dumps(report.to_dict(), indent=2) + "\n"
            if args.json_out:
                write_text_atomic(args.json_out, payload)
            print(payload, end="")
            return 0 if report.valid else 2

        if args.command == "build":
            result = build_glp1_eligibility(
                input_root=args.input,
                output_dir=args.output,
                config_path=args.config,
                replace=args.replace,
            )
            print(
                json.dumps(
                    {
                        "run_id": result.run_id,
                        "output_dir": str(result.output_dir),
                        "output_files": [path.name for path in result.output_paths],
                        "reused_existing": result.reused_existing,
                        "warning_count": result.warning_count,
                        "counts": {
                            "hypercapnia_encounters": (
                                result.counts.hypercapnia_encounters
                            ),
                            "patient_index_events": result.counts.patient_index_events,
                            "primary_obesity_hypercapnia": (
                                result.counts.primary_obesity_hypercapnia
                            ),
                            "evidence_rows": result.counts.evidence_rows,
                        },
                    },
                    indent=2,
                )
            )
            return 0

        if args.command == "summarize":
            summary = summarize_database(args.database)
            if args.json:
                print(json.dumps(summary, indent=2))
            else:
                print(
                    "GLP-1 eligibility summary: "
                    + ", ".join(f"{key}={value}" for key, value in summary.items())
                )
            return 0

        if args.command == "status":
            while True:
                state = read_run_state(args.output)
                worker_active = process_appears_active(state)
                payload = state.to_dict()
                payload["worker_process_detected"] = worker_active
                if args.json:
                    indent = None if args.watch else 2
                    print(json.dumps(payload, indent=indent), flush=True)
                else:
                    print(
                        f"{state.status}: phase={state.phase}, "
                        f"domain={state.current_domain or '-'}, "
                        f"rows={state.rows_processed:,}, "
                        f"updated={state.updated_at}, "
                        f"worker_active={worker_active}",
                        flush=True,
                    )
                if not args.watch:
                    return 0
                if state.status == "completed":
                    return 0
                if state.status == "failed" or worker_active is False:
                    return 1
                time.sleep(args.interval_seconds)
    except (FileNotFoundError, ValueError, GLP1ConfigError, ConceptSetError) as exc:
        parser.exit(2, f"error: {exc}\n")
    raise AssertionError(f"Unhandled command: {args.command}")


def _positive_interval(value: str) -> float:
    interval = float(value)
    if interval <= 0:
        raise argparse.ArgumentTypeError("interval must be greater than zero")
    return interval

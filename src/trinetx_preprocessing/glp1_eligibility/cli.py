"""Command-line interface for the additive GLP-1 eligibility build."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from ..filesystem import write_text_atomic
from .concept_sets import ConceptSetError, load_concept_sets
from .config import GLP1ConfigError, load_glp1_config
from .discovery import validate_export
from .monitoring import process_appears_active, read_run_state


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

    status_parser = subparsers.add_parser(
        "status", help="Read a long-running build's atomic progress state."
    )
    status_parser.add_argument("--output", type=Path, required=True)
    status_parser.add_argument("--json", action="store_true")
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

        if args.command == "status":
            state = read_run_state(args.output)
            payload = state.to_dict()
            payload["worker_process_detected"] = process_appears_active(state)
            if args.json:
                print(json.dumps(payload, indent=2))
            else:
                print(
                    f"{state.status}: phase={state.phase}, "
                    f"domain={state.current_domain or '-'}, "
                    f"rows={state.rows_processed:,}, "
                    f"updated={state.updated_at}, "
                    f"worker_active={payload['worker_process_detected']}"
                )
            return 0
    except (FileNotFoundError, ValueError, GLP1ConfigError, ConceptSetError) as exc:
        parser.exit(2, f"error: {exc}\n")
    raise AssertionError(f"Unhandled command: {args.command}")

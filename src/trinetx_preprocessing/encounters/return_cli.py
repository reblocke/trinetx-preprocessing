"""Opt-in CLI for the separate return-outcome bundle."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ..combined_preprocessing.builder import require_safe_output_location
from .return_validation import validate_returns
from .returns import build_returns


def build_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="trinetx-preprocessing build-returns")
    for name in ("database", "parent-bundle", "output-dir", "work-dir"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--partitions", type=int, default=32)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args(argv)
    build_returns(
        database=args.database,
        parent_bundle=args.parent_bundle,
        output_dir=args.output_dir,
        work_dir=args.work_dir,
        partitions=args.partitions,
        resume=args.resume,
    )
    return 0


def validate_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="trinetx-preprocessing validate-returns")
    for name in ("bundle", "parent-bundle", "database", "work-dir", "report"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args(argv)
    require_safe_output_location(args.report, artifact_label="return validation report")
    if any(
        args.report.absolute().is_relative_to(path.absolute())
        for path in (args.bundle, args.parent_bundle, args.database.parent)
    ):
        raise ValueError("Return validation report overlaps immutable inputs")
    if args.report.exists():
        raise FileExistsError("Return validation report destination already exists")
    args.report.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        result = validate_returns(
            bundle=args.bundle,
            parent_bundle=args.parent_bundle,
            database=args.database,
            work_dir=args.work_dir,
        )
    except Exception as exc:
        result = {"pass": False, "failure": type(exc).__name__}
        args.report.write_text(json.dumps(result, indent=2) + "\n")
        return 1
    args.report.write_text(json.dumps(result, indent=2) + "\n")
    return 0

"""Command-line encounter preprocessing."""

import argparse
import logging
from pathlib import Path

from .builder import build_encounters


def main(argv=None):
    parser = argparse.ArgumentParser(prog="trinetx-preprocessing build-encounters")
    parser.add_argument("--database", type=Path)
    parser.add_argument("--compatibility-database", type=Path, required=True)
    parser.add_argument("--legacy-only", action="store_true")
    parser.add_argument("--coverage-only", action="store_true")
    parser.add_argument(
        "--coverage-policy",
        choices=("complete_linkage", "approved_incomplete_linkage"),
        default="complete_linkage",
    )
    parser.add_argument("--approved-incomplete-linkage-exception")
    parser.add_argument("--coverage-bundle", type=Path)
    parser.add_argument("--legacy-bundle", type=Path)
    parser.add_argument("--legacy-acceptance", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--concept-sets-dir", type=Path)
    parser.add_argument("--source-cache-dir", type=Path)
    parser.add_argument("--vital-selection-acceptance", type=Path)
    args = parser.parse_args(argv)
    if args.source_cache_dir and (args.legacy_only or args.coverage_only):
        parser.error("--source-cache-dir is only supported for enrichment")
    if args.vital_selection_acceptance and (args.legacy_only or args.coverage_only):
        parser.error("--vital-selection-acceptance is only supported for enrichment")
    if args.approved_incomplete_linkage_exception and not args.coverage_only:
        parser.error("Linkage exception is only supported with --coverage-only")
    if args.coverage_policy == "approved_incomplete_linkage" and not (
        args.coverage_only and args.approved_incomplete_linkage_exception
    ):
        parser.error("Incomplete linkage requires an approved exception")
    if (
        args.coverage_policy == "complete_linkage"
        and args.approved_incomplete_linkage_exception
    ):
        parser.error("Complete linkage cannot carry an exception")
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    if args.legacy_only:
        from .base import build_legacy_bases

        build_legacy_bases(
            compatibility_database=args.compatibility_database,
            output_dir=args.output_dir,
        )
        return 0
    if not all((args.database, args.legacy_bundle, args.legacy_acceptance)):
        parser.error(
            "enrichment requires --database, --legacy-bundle and --legacy-acceptance"
        )
    if args.coverage_only:
        from .coverage import build_coverage

        build_coverage(
            database=args.database,
            legacy_bundle=args.legacy_bundle,
            legacy_acceptance=args.legacy_acceptance,
            output_dir=args.output_dir,
            policy=args.coverage_policy,
            approved_exception=args.approved_incomplete_linkage_exception,
        )
        return 0
    if args.coverage_bundle is None:
        parser.error("enrichment requires --coverage-bundle")
    build_encounters(
        database=args.database,
        compatibility_database=args.compatibility_database,
        legacy_bundle=args.legacy_bundle,
        legacy_acceptance=args.legacy_acceptance,
        coverage_bundle=args.coverage_bundle,
        output_dir=args.output_dir,
        concept_sets_dir=args.concept_sets_dir,
        source_cache_dir=args.source_cache_dir,
        vital_selection_acceptance=args.vital_selection_acceptance,
    )
    return 0


def import_main(argv=None):
    from .compatibility import import_compatibility

    parser = argparse.ArgumentParser(prog="trinetx-preprocessing import-compatibility")
    for name in ("input-root", "identity-receipt", "database"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args(argv)
    import_compatibility(
        input_root=args.input_root,
        identity_receipt=args.identity_receipt,
        database=args.database,
    )
    return 0


def validate_main(argv=None):
    import json
    import sys

    from .acceptance import ACCEPTANCE_CONTRACT_VERSION
    from .validation import ArtifactInvariantError, validate_bundle

    parser = argparse.ArgumentParser(prog="trinetx-preprocessing validate-encounters")
    for name in ("bundle", "work-dir", "report"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = validate_bundle(bundle=args.bundle, work_dir=args.work_dir)
    except Exception as exc:
        result = {
            "pass": False,
            "validation_contract_version": ACCEPTANCE_CONTRACT_VERSION,
            "failures": [
                {
                    "artifact": (
                        exc.artifact
                        if isinstance(exc, ArtifactInvariantError)
                        else "encounter_bundle"
                    ),
                    "invariant": (
                        exc.invariant
                        if isinstance(exc, ArtifactInvariantError)
                        else type(exc).__name__
                    ),
                    "aggregate_discrepancy": str(exc),
                }
            ],
        }
        args.report.write_text(json.dumps(result, indent=2) + "\n")
        print(f"Encounter validation failed; see {args.report}", file=sys.stderr)
        return 1
    args.report.write_text(json.dumps(result, indent=2) + "\n")
    return 0

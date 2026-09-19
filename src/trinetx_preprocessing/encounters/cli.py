"""Command-line encounter preprocessing."""

import argparse
import logging
from pathlib import Path

from .builder import build_encounters


def main(argv=None):
    parser = argparse.ArgumentParser(prog="trinetx-preprocessing build-encounters")
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--concept-sets-dir", type=Path)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO)
    build_encounters(
        database=args.database,
        output_dir=args.output_dir,
        concept_sets_dir=args.concept_sets_dir,
    )
    return 0

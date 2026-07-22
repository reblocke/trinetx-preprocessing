"""Capture PHI-safe normalized hashes for the 36 compatibility CSVs."""

from __future__ import annotations

import argparse
from pathlib import Path

from trinetx_preprocessing.combined_preprocessing.evidence import (
    capture_compatibility_evidence,
    write_evidence,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    payload = capture_compatibility_evidence(args.output_dir)
    write_evidence(args.out, payload)
    print(
        f"Captured {payload['table_count']} tables and "
        f"{payload['total_rows']} rows in {args.out}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

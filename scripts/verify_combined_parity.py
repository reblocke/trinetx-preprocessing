"""Verify combined compatibility outputs against an aggregate baseline."""

from __future__ import annotations

import argparse
from pathlib import Path

from trinetx_preprocessing.combined_preprocessing.evidence import (
    verify_compatibility_evidence,
    write_evidence,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    payload = verify_compatibility_evidence(
        args.database,
        args.output_dir,
        args.baseline,
    )
    write_evidence(args.out, payload)
    print(f"Combined compatibility parity ready: {payload['ready']}.")
    return 0 if payload["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

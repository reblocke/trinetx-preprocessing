"""Report aggregate source-element catalog and observed-match completeness."""

from __future__ import annotations

import argparse
from pathlib import Path

from trinetx_preprocessing.combined_preprocessing.evidence import (
    inspect_element_completeness,
    write_evidence,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    payload = inspect_element_completeness(args.database)
    write_evidence(args.out, payload)
    print(
        f"Element contract complete: {payload['complete']}; "
        f"{payload.get('source_element_count', 0)} source elements."
    )
    return 0 if payload["complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

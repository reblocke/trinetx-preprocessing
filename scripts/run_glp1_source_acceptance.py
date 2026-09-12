"""Run the private, sequential GLP raw-versus-canonical acceptance gate.

All paths are supplied by the operator and receipts are written only to the
specified private directory.  The launcher deliberately stops at the first
failed gate and never replaces an existing GLP output.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--compatibility-output", type=Path, required=True)
    parser.add_argument("--raw-input", type=Path, required=True)
    parser.add_argument("--raw-output", type=Path, required=True)
    parser.add_argument("--canonical-output", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--receipt-dir", type=Path, required=True)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the ordered commands without reading inputs or writing outputs.",
    )
    return parser


def acceptance_commands(args: argparse.Namespace) -> tuple[tuple[str, ...], ...]:
    python = sys.executable
    return (
        (
            python,
            "-m",
            "trinetx_preprocessing",
            "validate-preprocessed",
            "--database",
            str(args.database),
            "--output-dir",
            str(args.compatibility_output),
            "--json",
        ),
        (
            python,
            "-m",
            "trinetx_preprocessing.glp1_eligibility",
            "build",
            "--input",
            str(args.raw_input),
            "--raw-reference",
            "--output",
            str(args.raw_output),
            "--config",
            str(args.config),
        ),
        (
            python,
            "-m",
            "trinetx_preprocessing.glp1_eligibility",
            "build",
            "--database",
            str(args.database),
            "--output",
            str(args.canonical_output),
            "--config",
            str(args.config),
        ),
        (
            python,
            "-m",
            "trinetx_preprocessing.glp1_eligibility",
            "compare-reference-outputs",
            "--raw-output",
            str(args.raw_output),
            "--canonical-output",
            str(args.canonical_output),
            "--json",
        ),
    )


def run(args: argparse.Namespace) -> int:
    commands = acceptance_commands(args)
    if args.dry_run:
        print(json.dumps({"commands": commands}, indent=2))
        return 0

    receipt_dir = args.receipt_dir.resolve()
    receipt_dir.mkdir(parents=True, exist_ok=False)
    started_at = datetime.now(UTC).isoformat()
    for index, command in enumerate(commands, start=1):
        completed = subprocess.run(command, check=False, capture_output=True, text=True)
        receipt = {
            "command": list(command),
            "exit_code": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
        }
        (receipt_dir / f"{index:02d}_receipt.json").write_text(
            json.dumps(receipt, indent=2) + "\n"
        )
        if completed.returncode:
            print(
                f"Acceptance gate {index} failed; see {receipt_dir}.",
                file=sys.stderr,
            )
            return completed.returncode
    completion = {
        "started_at": started_at,
        "completed_at": datetime.now(UTC).isoformat(),
    }
    (receipt_dir / "acceptance_complete.json").write_text(
        json.dumps(completion, indent=2) + "\n"
    )
    print(f"GLP source acceptance passed; receipts: {receipt_dir}")
    return 0


def main(argv: list[str] | None = None) -> int:
    return run(_parser().parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())

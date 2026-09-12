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
        "--compatibility-baseline",
        type=Path,
        help=(
            "Approved aggregate 36-file compatibility baseline. Supply this "
            "with both evidence output paths for full source acceptance."
        ),
    )
    parser.add_argument(
        "--compatibility-parity-out",
        type=Path,
        help=(
            "Private aggregate receipt for 36-file schema, row-count, and hash parity."
        ),
    )
    parser.add_argument(
        "--element-completeness-out",
        type=Path,
        help=(
            "Private aggregate receipt for shared traditional and GLP-1 "
            "catalog coverage."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the ordered commands without reading inputs or writing outputs.",
    )
    return parser


def acceptance_commands(args: argparse.Namespace) -> tuple[tuple[str, ...], ...]:
    python = sys.executable
    commands: list[tuple[str, ...]] = [
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
    ]
    if args.compatibility_baseline is not None:
        assert args.compatibility_parity_out is not None
        assert args.element_completeness_out is not None
        commands.extend(
            [
                (
                    python,
                    "scripts/verify_combined_parity.py",
                    "--database",
                    str(args.database),
                    "--output-dir",
                    str(args.compatibility_output),
                    "--baseline",
                    str(args.compatibility_baseline),
                    "--out",
                    str(args.compatibility_parity_out),
                ),
                (
                    python,
                    "scripts/verify_element_completeness.py",
                    "--database",
                    str(args.database),
                    "--out",
                    str(args.element_completeness_out),
                ),
            ]
        )
    return tuple(commands)


def _has_full_source_evidence(args: argparse.Namespace) -> bool:
    values = (
        args.compatibility_baseline,
        args.compatibility_parity_out,
        args.element_completeness_out,
    )
    any_present = any(value is not None for value in values)
    all_present = all(value is not None for value in values)
    if any_present and not all_present:
        raise ValueError(
            "--compatibility-baseline, --compatibility-parity-out, and "
            "--element-completeness-out must be supplied together"
        )
    return all_present


def run(args: argparse.Namespace) -> int:
    full_source_evidence = _has_full_source_evidence(args)
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
        "full_source_evidence": full_source_evidence,
    }
    if not full_source_evidence:
        (receipt_dir / "acceptance_incomplete.json").write_text(
            json.dumps(
                {
                    **completion,
                    "missing": [
                        "approved compatibility baseline",
                        "36-file parity receipt",
                        "element-completeness receipt",
                    ],
                },
                indent=2,
            )
            + "\n"
        )
        print(
            "GLP comparison passed, but full source acceptance is incomplete; "
            "supply the approved compatibility baseline.",
            file=sys.stderr,
        )
        return 2
    (receipt_dir / "acceptance_complete.json").write_text(
        json.dumps(completion, indent=2) + "\n"
    )
    print(f"GLP source acceptance passed; receipts: {receipt_dir}")
    return 0


def main(argv: list[str] | None = None) -> int:
    return run(_parser().parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())

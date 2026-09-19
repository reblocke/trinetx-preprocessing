"""Command-line entry point for trinetx_preprocessing."""

from __future__ import annotations

import sys
from typing import Sequence

from .cli import main as cli_main


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI entry point."""
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments and arguments[0] == "build-encounters":
        from .encounters.cli import main as encounters_main

        return encounters_main(arguments[1:])
    if arguments and arguments[0] == "verify-update":
        raise SystemExit(
            "Study verification moved: python -m trinetx_analysis.glp1_verification.cli"
        )
    return cli_main(arguments)


if __name__ == "__main__":
    raise SystemExit(main())

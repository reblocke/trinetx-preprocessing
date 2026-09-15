"""Command-line entry point for trinetx_preprocessing."""

from __future__ import annotations

import sys
from typing import Sequence

from .cli import main as cli_main


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI entry point."""
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments and arguments[0] == "verify-update":
        from .verification.cli import main as verify_main

        return verify_main(arguments[1:])
    return cli_main(arguments)


if __name__ == "__main__":
    raise SystemExit(main())

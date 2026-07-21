"""Command-line entry point for trinetx_preprocessing."""

from __future__ import annotations

from typing import Sequence

from .cli import main as cli_main


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI entry point."""
    return cli_main(argv)


if __name__ == "__main__":
    raise SystemExit(main())

"""Logging helpers for the preprocessing pipeline."""

from __future__ import annotations

import logging


def configure_logging(verbose: bool) -> None:
    """Configure standard logging for CLI usage.

    Args:
        verbose: Whether to enable debug-level logging.

    Notes:
        Do not log patient identifiers or row-level data.
    """

    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logging.captureWarnings(True)

"""Stable names for confidential combined-build scratch families."""

from __future__ import annotations

COMBINED_BUILD_PREFIX = ".trinetx-combined-build-"
COMBINED_PREVIOUS_PREFIX = ".trinetx-combined-previous-"
COMBINED_PUBLICATION_PREFIX = ".trinetx-combined-publication-"
COMBINED_DUCKDB_SPILL_PREFIX = ".trinetx-combined-duckdb-spill-"
COMBINED_VALIDATION_PREFIX = ".trinetx-combined-validation-"
COMBINED_LOCK_PREFIX = ".trinetx-combined-lock-"
LEGACY_COMBINED_SCRATCH_NAME_FRAGMENTS = (
    ".combined-build-",
    ".duckdb-tmp-",
)

COMBINED_SCRATCH_PATH_PREFIXES = (
    COMBINED_BUILD_PREFIX,
    f".{COMBINED_BUILD_PREFIX}",
    COMBINED_PREVIOUS_PREFIX,
    COMBINED_PUBLICATION_PREFIX,
    f".{COMBINED_PUBLICATION_PREFIX}",
    COMBINED_DUCKDB_SPILL_PREFIX,
    COMBINED_VALIDATION_PREFIX,
)


def is_combined_scratch_name(name: str) -> bool:
    """Recognize current, legacy, and AppleDouble combined scratch names."""

    if name.startswith(f"._{COMBINED_LOCK_PREFIX}"):
        return True
    candidate = name
    while candidate.startswith("._"):
        candidate = candidate[2:]
    return any(
        candidate.startswith(prefix) for prefix in COMBINED_SCRATCH_PATH_PREFIXES
    ) or (
        candidate.startswith(".")
        and any(
            fragment in candidate for fragment in LEGACY_COMBINED_SCRATCH_NAME_FRAGMENTS
        )
    )

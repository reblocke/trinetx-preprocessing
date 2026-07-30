"""Stable public contract for the combined preprocessing database."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..pipeline.final_assembly import SETTING_OUTPUT_DIRS, SETTINGS
from ..pipeline.final_output_schema import FINAL_OUTPUT_COLUMNS
from ..transform.rfs import RFS_CATEGORIES

COMBINED_SCHEMA_VERSION = "1.0"
DATABASE_MANIFEST_SCHEMA_VERSION = 2
COMPATIBILITY_VARIANTS = ("BEFORE", "AFTER")
PREPROCESSED_ENCOUNTER_TABLE = "preprocessed_encounter"


@dataclass(frozen=True)
class CompatibilityOutput:
    """One legacy-compatible output represented as a database view."""

    setting: str
    category: str
    variant: str
    relative_path: Path
    view_name: str

    @property
    def key(self) -> str:
        """Return a stable slash-separated output key."""

        return self.relative_path.as_posix()


def compatibility_outputs() -> tuple[CompatibilityOutput, ...]:
    """Return the complete ordered 36-file compatibility contract."""

    outputs: list[CompatibilityOutput] = []
    for setting in SETTINGS:
        output_directory = SETTING_OUTPUT_DIRS[setting]
        for category in RFS_CATEGORIES:
            for variant in COMPATIBILITY_VARIANTS:
                filename = f"RFS_{category}_ENC_{setting}_{variant}.csv"
                outputs.append(
                    CompatibilityOutput(
                        setting=setting,
                        category=category,
                        variant=variant,
                        relative_path=Path(output_directory) / filename,
                        view_name=(f"compat_{category}_{setting}_{variant}".lower()),
                    )
                )
    return tuple(outputs)


def final_output_columns() -> tuple[str, ...]:
    """Return the immutable ordered historical final-column contract."""

    return tuple(FINAL_OUTPUT_COLUMNS)

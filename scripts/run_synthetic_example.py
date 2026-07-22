"""Run the pipeline against synthetic fixtures for onboarding."""

from __future__ import annotations

import argparse
import tempfile
from pathlib import Path

from trinetx_preprocessing.cli import main as cli_main

ROOT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_DATA_DIR = ROOT_DIR / "tests" / "fixtures" / "example_data"
DEFAULT_OUTPUT_ROOT = (
    Path(tempfile.gettempdir()) / "trinetx-preprocessing-synthetic-example"
)


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI parser for the synthetic example script."""

    parser = argparse.ArgumentParser(
        description="Run the preprocessing pipeline on synthetic fixtures.",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=DEFAULT_DATA_DIR,
        help=(
            "Path to synthetic fixture data (defaults to tests/fixtures/example_data)."
        ),
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=DEFAULT_OUTPUT_ROOT,
        help="Root directory for generated work/output data.",
    )
    return parser


def write_config(
    config_path: Path,
    data_dir: Path,
    work_dir: Path,
    output_dir: Path,
) -> None:
    """Write a minimal config YAML for the synthetic example."""

    content = (
        f'data_dir: "{data_dir}"\n'
        f'work_dir: "{work_dir}"\n'
        f'output_dir: "{output_dir}"\n'
        "domains:\n"
        "  encounter:\n"
        '    pattern: "Encounter/encounter*.csv"\n'
        "  diagnosis:\n"
        '    pattern: "Diagnosis/diagnosis*.csv"\n'
        "  labs:\n"
        '    pattern: "Lab Results/lab_result*.csv"\n'
        "  meds:\n"
        "    patterns:\n"
        '      - "Medications/medication[0-9]*.csv"\n'
        '      - "Medications/medication_ingredient*.csv"\n'
        "  procedure:\n"
        '    pattern: "Procedure/procedure*.csv"\n'
        "  vitals:\n"
        '    pattern: "Vital Signs/vital*_signs*.csv"\n'
        "  patient:\n"
        '    pattern: "Patient/patient*.csv"\n'
        "\n"
        "chunking:\n"
        "  enabled: false\n"
        "  lines_per_chunk: 10000000\n"
        "\n"
        "combined:\n"
        "  enabled: true\n"
        "  database_name: trinetx_preprocessed.duckdb\n"
        '  schema_version: "1.0"\n'
        "\n"
        "rfs:\n"
        "  enabled: true\n"
    )
    config_path.write_text(content)


def main() -> int:
    """Run the synthetic example and return the exit code."""

    parser = build_parser()
    arguments = parser.parse_args()

    data_dir = arguments.data_dir.expanduser().resolve()
    if not data_dir.exists():
        raise FileNotFoundError(f"Synthetic data directory not found: {data_dir}")

    output_root = arguments.output_root.expanduser().resolve()
    work_dir = output_root / "work"
    output_dir = output_root / "output"
    output_root.mkdir(parents=True, exist_ok=True)
    work_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    config_path = output_root / "config.yaml"
    write_config(config_path, data_dir, work_dir, output_dir)

    result = cli_main(
        ["build-preprocessed", "--config", str(config_path), "--replace"]
    )
    if result == 0:
        print(f"Synthetic combined product written to {output_dir}")
    return result


if __name__ == "__main__":
    raise SystemExit(main())

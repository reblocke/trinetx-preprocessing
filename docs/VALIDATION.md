# Validation

This document records evidence that the refactor preserves intended outputs.

## Baseline definition
- Baseline code reference: <git sha / tag / commit>
- Baseline run config: <path to config used>
- Fixture dataset: `tests/fixtures/<name>`

## What is compared
- Row counts per stage
- Key derived flags (e.g., RFS categories)
- Final output tables (sorted + schema-checked)
- Optional: hashes of normalized CSV outputs

## Automated coverage
- Encounter transforms: filtering, deduplication, LOS calculation.
- Encounter stage runner: end-to-end outputs + CLI invocation on synthetic data.
- Lab-results transforms: column selection, code retention, missing numeric values.
- Lab-results stage runner: normalized output generation + CLI invocation on synthetic data.
- Diagnosis transforms: indicator cleanup + code-group filters.
- Diagnosis stage runner: normalized output generation + code-group extracts.
- Medications transforms: column selection + code-group filters.
- Medications stage runner: normalized output generation + code-group extracts.
- Procedure transforms: column selection + code-group filters.
- Procedure stage runner: normalized output generation + code-group extracts.
- Vital-sign transforms: temperature conversions + range filters + code groups.
- Vital-signs stage runner: normalized output generation + code-group extracts.
- RFS transforms: category filters + encounter-level flag derivation.
- RFS stage runner: end-to-end outputs on synthetic cohort.

## Regression harness (real data, optional)
- Use the CLI to hash refactor outputs on real data:
  - `python -m trinetx_preprocessing baseline --config path/to/config.yaml --out artifacts/baseline`
- Re-run the pipeline and compare hashes:
  - `python -m trinetx_preprocessing compare --config path/to/config.yaml --baseline artifacts/baseline`
- Hash manifests contain only SHA-256 hashes and output keys; do not commit real-data artifacts.
- Legacy pipeline is notebook-based; to build a legacy baseline:
  1. Run the legacy notebooks and copy their outputs to a dedicated directory.
  2. Generate a hash manifest (example):
     ```bash
     python - <<'PY'
     from pathlib import Path
     from trinetx_preprocessing.regression import hash_csv, write_hash_manifest

     legacy_dir = Path("artifacts/legacy_outputs")
     hashes = {path.name: hash_csv(path) for path in legacy_dir.glob("*.csv")}
     write_hash_manifest(Path("artifacts/legacy"), hashes)
     PY
     ```
  3. Compare against the refactor with `compare --baseline artifacts/legacy`.

## Results

### Fixture: <name>
- Baseline commit:
- Refactor commit:
- Summary:
  - Encounter rows:
  - Diagnosis rows:
  - Lab rows:
  - Final output rows:
- Notes:

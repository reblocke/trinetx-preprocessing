# Onboarding

This guide covers the CLI-driven pipeline plus a reference for the legacy
notebook workflow.

## Prerequisites
- Python >= 3.11 with `uv`
- Jupyter + `nbconvert` (for legacy notebooks)
- Sufficient disk and RAM for cohort size

## Quickstart (synthetic fixtures)
```bash
mkdir -p .uv_cache
export UV_CACHE_DIR="$PWD/.uv_cache"
uv sync

cp config.example.yaml config.yaml
./.venv/bin/python scripts/run_synthetic_example.py
```
The helper writes the canonical database and all 36 compatibility CSVs under
`/tmp/trinetx-preprocessing-synthetic-example/`.
It is safe to rerun: the existing synthetic product is replaced only after the
new product passes combined validation.

## Getting started example script
The helper script writes a config for you and runs the pipeline on synthetic
fixtures:
```bash
./.venv/bin/python scripts/run_synthetic_example.py \
  --output-root /tmp/trinetx-preprocessing-synthetic-example
```

## CLI run (real data)
1. Keep the TriNetX export in a private location using the folder names:
   ```
   /private/path/TriNetX/
     Encounter/
     Diagnosis/
     Lab Results/
     Medications/
     Procedure/
     Vital Signs/
     Patient/
   ```
2. Scaffold a non-repository validation root. The generated config keeps
   `work_dir`, `output_dir`, logs, and manifests external and separate:
   ```bash
   ./.venv/bin/python -m trinetx_preprocessing scaffold-validation \
     --data-dir /private/path/TriNetX \
     --validation-root /private/path/trinetx-preprocessing-validation
   ```
3. In the generated config, add or update the `combined` block:
   ```yaml
   combined:
     enabled: true
     database_name: trinetx_preprocessed.duckdb
     schema_version: "1.0"
     concept_sets_dir: /absolute/path/to/repository/config/concept_sets
     duckdb_memory_limit_mib: 3072
     duckdb_core_memory_limit_mib: 2816
   ```
   Keep `work_dir` and `output_dir` disjoint; equality or either directory
   nested under the other is rejected before any mutation.
4. Validate configuration and inputs:
   ```bash
   CONFIG=/private/path/trinetx-preprocessing-validation/config.yaml
   ./.venv/bin/python -m trinetx_preprocessing validate-config --config "$CONFIG"
   ./.venv/bin/python -m trinetx_preprocessing validate-inputs --config "$CONFIG"
   ```
5. Run the canonical builder in the accepted deterministic non-strict mode:
   ```bash
   ./.venv/bin/python -m trinetx_preprocessing build-preprocessed \
     --config "$CONFIG"
   ```
With combined mode enabled, `run` and `run-all` route to the same builder.
The accepted source contains 286 documented encounter-setting conflicts, so
the prescribed `run-final-assembly --strict` resume check is the separate
fail-closed adjudication proof. On the current source it exits before
final-output writes; do not run a full strict replacement build against the
accepted product.

The recommended finalization config uses Parquet work tables. Final analytic
outputs remain CSV, but intermediates under `work_dir` may have `.parquet`
suffixes unless `storage.emit_legacy_csv_intermediates` is enabled.

## Legacy notebook workflow (reference only)

This workflow is preserved for historical diagnosis and comparison. New runs
should use the canonical CLI above.
1. Download + unzip the TriNetX export.
2. Organize raw files into the domain folders above (see `README.txt`).
3. Split large CSVs with the portable Python splitter (recommended), adjusting paths to your local data directory.
   - Example: `./.venv/bin/python -m trinetx_preprocessing split --input data/Encounter/encounter.csv --out data/Encounter --lines-per-chunk 10000000 --prefix encounter`.
   - The splitter preserves the header in each chunk and uses four-digit zero padding (`encounter0001.csv`) to match notebook expectations.
   - The removed shell splitter is not required; use the supported Python CLI.
4. Run preprocessing notebooks and set `database_dir`, `working_dir`, and `num_spreadsheets` in each:
   - `Hypercapnia NEW DATA - Encounter (CSV Processing).ipynb`
   - `Hypercapnia NEW DATA - Prior Diagnosis (CSV Processing).ipynb`
   - `Hypercapnia NEW DATA - Current Diagnosis (CSV Processing).ipynb`
   - `Hypercapnia NEW DATA - Lab Results (CSV Processing).ipynb`
   - `Hypercapnia NEW DATA - Medication (CSV Processing).ipynb`
   - `Hypercapnia NEW DATA - Procedure (CSV Processing).ipynb`
   - `Hypercapnia NEW DATA - Vital Signs (CSV Processing).ipynb`
   These write `*_NEW_####.csv` intermediates plus `AMB_encounters.csv`, `EMER_encounters.csv`, `INPAT_encounters.csv` under `working_dir`.
5. Run RFS derivation: `Hypercapnia NEW DATA - RFS Processing.ipynb` to create `RFS_*.csv` in `working_dir`.
6. Generate final datasets:
   - Use `Hypercapnia Final Dataset Generation - Master.ipynb` with `rfs`, `setting`, and `output_dir` (see `Hypercapnia Master.ipynb` for examples).
   - Outputs land in `output/<output_dir>/RFS_<RFS>_ENC_<SETTING>_{BEFORE,AFTER}.csv`.
   - CLI alternative: `./.venv/bin/python -m trinetx_preprocessing run --config config.yaml` writes the same naming scheme under `output/`.
7. Generate data checks (used for filtering in final outputs):
   - Run `Hypercapnia Data Checks.ipynb` after all RFS/setting permutations are available, or execute `Hypercapnia Master.ipynb`, which writes `Hypercapnia Data Checks - Executed.ipynb`.
8. Optional checks: `Hypercapnia Final Data Checks only.ipynb`.

## First-success checklist
- [ ] Raw exports and every generated row-level artifact remain external and
      untracked.
- [ ] `work_dir` and `output_dir` are external, real, and non-overlapping.
- [ ] The product contains one DuckDB, one adjacent manifest, and exactly 36
      compatibility CSVs under `AMBULATORY`, `EMERGENCY`, and `INPATIENT`.
- [ ] `validate-preprocessed --database ... --output-dir ...` reports valid.
- [ ] Any strict conflict check is recorded separately from the accepted
      non-strict build.

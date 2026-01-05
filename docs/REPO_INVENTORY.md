# Repo Inventory

## Top-level layout
- `AGENTS.md` — contributor instructions and guardrails.
- `CONTINUITY.md` — continuity ledger for the workspace.
- `README.txt` — legacy pipeline run steps.
- `split_db.sh` — chunking script for raw CSV exports (referenced in `README.txt`).
- `Hypercapnia*.ipynb` — legacy pipeline notebooks at repo root.
- `Executed Notebooks/` — executed copies of parameterized final dataset notebooks.
- `docs/` — documentation and prompts.
- `data/` — sensitive TriNetX exports (git-ignored).
- `artifacts/` — analysis artifacts (currently empty).
- `notebooks/` — notebook home (`notebooks/legacy/` empty).
- `scripts/` — helper scripts (currently empty).
- `src/` — future package code (currently empty).
- `tests/` — pytest suite (currently empty).
- `trinetx_codex_prompts.zip`, `trinetx_preprocessing_scaffold_md.zip` — archived prompts/templates.
- `CHANGELOG.md`, `CONTRIBUTING.md`, `LICENSE`, `SECURITY.md` — repo metadata.

## Legacy pipeline notebooks (root)
### Orchestration
- `Hypercapnia Master.ipynb` — runs preprocessing, RFS, data checks, and final dataset generation.

### Preprocessing (chunked CSV → `*_NEW_####.csv`)
- `Hypercapnia NEW DATA - Encounter (CSV Processing).ipynb` — encounter cleaning; outputs `encounter_NEW_####.csv` and `AMB/EMER/INPAT_encounters.csv`.
- `Hypercapnia NEW DATA - Prior Diagnosis (CSV Processing).ipynb`
- `Hypercapnia NEW DATA - Current Diagnosis (CSV Processing).ipynb`
- `Hypercapnia NEW DATA - Lab Results (CSV Processing).ipynb`
- `Hypercapnia NEW DATA - Medication (CSV Processing).ipynb`
- `Hypercapnia NEW DATA - Procedure (CSV Processing).ipynb`
- `Hypercapnia NEW DATA - Vital Signs (CSV Processing).ipynb`

### RFS derivation
- `Hypercapnia NEW DATA - RFS Processing.ipynb` — builds `RFS_ABG.csv`, `RFS_VBG.csv`, `RFS_RESPFAIL.csv`, `RFS_OBESITY.csv`, `RFS_VENTSUPPORT.csv`, `RFS_PREDISPOSITION.csv`.

### Data checks + final datasets
- `Hypercapnia Data Checks.ipynb` — writes `data_checks/*.csv`.
- `Hypercapnia Data Checks - Executed.ipynb` — executed output from the data checks notebook.
- `Hypercapnia Final Dataset Generation - Master.ipynb` — parameterized final dataset builder (`rfs`, `setting`, `output_dir`).
- `Hypercapnia Final Data Checks only.ipynb` — additional checks.

## Executed notebooks
- `Executed Notebooks/Hypercapnia Final Dataset Generation - RFS_*_ENC_*.ipynb` — executed outputs for each RFS/setting permutation.

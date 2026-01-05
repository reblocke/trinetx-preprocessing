# Decisions Log

Record decisions that affect behavior, reproducibility, or maintainability.

## Template
- Date:
- Decision:
- Context:
- Options considered:
- Rationale:
- Consequences:
- References (files/lines, links):

## Entries

### 2025-02-13 — Optional strict performance guardrails
- Date: 2025-02-13
- Decision: Add optional strict guardrails for join explosions and missing IDs, configured via `guardrails.max_join_multiplier` and enabled with `--strict`.
- Context: Profiling work needed safety checks without changing default pipeline semantics.
- Options considered:
  - Always-on assertions
  - Optional guardrails gated behind `--strict` (chosen)
- Rationale: Keeps existing runs unchanged while providing opt-in diagnostics.
- Consequences: Strict runs may fail early if joins expand unexpectedly or IDs are missing.
- References: `src/trinetx_preprocessing/guardrails.py:11`, `src/trinetx_preprocessing/pipeline/final_assembly.py:81`, `src/trinetx_preprocessing/config.py:38`, `src/trinetx_preprocessing/cli.py:429`, `docs/CONFIG.md:12`.

### 2025-02-08 — Canonical encounter processing logic
- Date: 2025-02-08
- Decision: Use `Hypercapnia NEW DATA - Encounter (CSV Processing).ipynb` as the canonical encounter-stage source and preserve its filtering, deduplication, and LOS logic.
- Context: Encounter preprocessing had to be extracted into pure transforms and a stage runner while preserving legacy semantics.
- Options considered:
  - Use the executed notebook variants in `Executed Notebooks/`
  - Use `Hypercapnia NEW DATA - Encounter (CSV Processing).ipynb` (chosen)
- Rationale: The notebook contains the explicit filtering rules and output naming used in the legacy encounter stage.
- Consequences: Encounter outputs retain AMB/EMER/IMP filters, `start_date >= 2022-01-01`, missing `end_date` filled with `2022-12-31`, deduplication by `encounter_id`, and LOS calculations with invalid LOS removed.
- References: `Hypercapnia NEW DATA - Encounter (CSV Processing).ipynb:50`, `Hypercapnia NEW DATA - Encounter (CSV Processing).ipynb:94`, `Hypercapnia NEW DATA - Encounter (CSV Processing).ipynb:157`, `Hypercapnia NEW DATA - Encounter (CSV Processing).ipynb:223`.

### 2025-02-08 — Canonical lab-results processing logic
- Date: 2025-02-08
- Decision: Use `Hypercapnia NEW DATA - Lab Results (CSV Processing).ipynb` as the canonical lab-results preprocessing source and preserve its column selection and output naming.
- Context: The lab-results stage needed extraction into pure transforms and a stage runner while matching the legacy CSV reformatting.
- Options considered:
  - Use executed notebooks in `Executed Notebooks/` (none cover lab preprocessing)
  - Use `Hypercapnia NEW DATA - Lab Results (CSV Processing).ipynb` (chosen)
- Rationale: The notebook explicitly defines the column list, dropped fields, and `lab_results_NEW_####.csv` outputs used downstream.
- Consequences: Lab-results preprocessing drops `code_system`, text/unit fields, and TriNetX metadata while retaining `patient_id`, `encounter_id`, `code`, `date`, and `lab_result_num_val`.
- References: `Hypercapnia NEW DATA - Lab Results (CSV Processing).ipynb:49`, `Hypercapnia NEW DATA - Lab Results (CSV Processing).ipynb:61`, `Hypercapnia NEW DATA - Lab Results (CSV Processing).ipynb:64`, `Hypercapnia NEW DATA - Lab Results (CSV Processing).ipynb:68`, `Hypercapnia NEW DATA - Lab Results (CSV Processing).ipynb:69`.

### 2025-02-08 — Canonical diagnosis processing logic
- Date: 2025-02-08
- Decision: Use `Hypercapnia NEW DATA - Prior Diagnosis (CSV Processing).ipynb` for normalization rules and `Hypercapnia NEW DATA - Current Diagnosis (CSV Processing).ipynb` for code-group extracts and output naming.
- Context: Diagnosis preprocessing must be extracted into pure transforms and a stage runner while preserving legacy filters and code lists.
- Options considered:
  - Use executed notebooks in `Executed Notebooks/`
  - Use the prior + current diagnosis preprocessing notebooks (chosen)
- Rationale: The prior notebook defines the `diagnosis_NEW_####.csv` normalization and indicator cleanup, while the current notebook enumerates the required `HAS_*.csv` code-group outputs used downstream.
- Consequences: Diagnosis preprocessing outputs normalized files plus code-group extracts, including both `HAS_I50.csv` (broad prefix) and `HAS_I50_acute.csv` (acute subsets).
- References: `Hypercapnia NEW DATA - Prior Diagnosis (CSV Processing).ipynb:62`, `Hypercapnia NEW DATA - Prior Diagnosis (CSV Processing).ipynb:1546`, `Hypercapnia NEW DATA - Current Diagnosis (CSV Processing).ipynb:112`, `Hypercapnia NEW DATA - Current Diagnosis (CSV Processing).ipynb:2198`.

### 2025-02-09 — Canonical medications processing logic
- Date: 2025-02-09
- Decision: Use `Hypercapnia NEW DATA - Medication (CSV Processing).ipynb` as the canonical medications preprocessing source and preserve its code-group extracts.
- Context: Medication preprocessing needed extraction into a pure transform and stage runner while retaining legacy inclusion lists.
- Options considered:
  - Use executed notebooks in `Executed Notebooks/`
  - Use `Hypercapnia NEW DATA - Medication (CSV Processing).ipynb` (chosen)
- Rationale: The notebook defines the normalized columns and the IP/OP medication code lists expected downstream.
- Consequences: Medication preprocessing drops TriNetX metadata columns, outputs `medication_NEW_####.csv`, and generates `IPmed_list1`–`IPmed_list7` plus `OPmed_list1`–`OPmed_list6` extracts.
- References: `Hypercapnia NEW DATA - Medication (CSV Processing).ipynb:4`, `Hypercapnia NEW DATA - Medication (CSV Processing).ipynb:7`, `Hypercapnia NEW DATA - Medication (CSV Processing).ipynb:22`.

### 2025-02-09 — Canonical procedure processing logic
- Date: 2025-02-09
- Decision: Use `Hypercapnia NEW DATA - Procedure (CSV Processing).ipynb` as the canonical procedure preprocessing source and preserve its code-group extracts.
- Context: Procedure preprocessing needed extraction into a pure transform and stage runner while matching legacy CPT/LOINC/SNOMED filters.
- Options considered:
  - Use executed notebooks in `Executed Notebooks/`
  - Use `Hypercapnia NEW DATA - Procedure (CSV Processing).ipynb` (chosen)
- Rationale: The notebook enumerates the normalized columns and the `HAS_*` outputs used in the legacy workflow.
- Consequences: Procedure preprocessing drops TriNetX metadata columns, outputs `procedure_NEW_####.csv`, and generates `HAS_*.csv` extracts per the notebook code lists.
- References: `Hypercapnia NEW DATA - Procedure (CSV Processing).ipynb:5`, `Hypercapnia NEW DATA - Procedure (CSV Processing).ipynb:8`, `Hypercapnia NEW DATA - Procedure (CSV Processing).ipynb:87`.

### 2025-02-09 — Canonical vital-signs processing logic
- Date: 2025-02-09
- Decision: Use `Hypercapnia NEW DATA - Vital Signs (CSV Processing).ipynb` as the canonical vital-signs preprocessing source and preserve its range filters and temperature conversions.
- Context: Vital-sign preprocessing needed extraction into a pure transform and stage runner while keeping unit conversions and value bounds intact.
- Options considered:
  - Use executed notebooks in `Executed Notebooks/`
  - Use `Hypercapnia NEW DATA - Vital Signs (CSV Processing).ipynb` (chosen)
- Rationale: The notebook defines the normalized columns, code groups, and physiological bounds used by the legacy stage.
- Consequences: Vital-sign preprocessing drops TriNetX metadata columns, outputs `vital_signs_NEW_####.csv`, and generates `value_*.csv` extracts with temperature conversions and range filters matching the notebook.
- References: `Hypercapnia NEW DATA - Vital Signs (CSV Processing).ipynb:5`, `Hypercapnia NEW DATA - Vital Signs (CSV Processing).ipynb:8`, `Hypercapnia NEW DATA - Vital Signs (CSV Processing).ipynb:21`.

### 2025-02-10 — Canonical RFS derivation logic
- Date: 2025-02-10
- Decision: Use `Hypercapnia NEW DATA - RFS Processing.ipynb` as the canonical RFS source and preserve its code lists and thresholds.
- Context: RFS derivation needed extraction into a pure transform and stage runner while matching legacy inclusion logic.
- Options considered:
  - Use executed notebooks in `Executed Notebooks/`
  - Use `Hypercapnia NEW DATA - RFS Processing.ipynb` (chosen)
- Rationale: The notebook enumerates the RFS category code filters and numeric thresholds used for cohort construction.
- Consequences: RFS flags mirror ABG/VBG lab code filters with value bounds, respiratory failure and obesity diagnosis filters, BMI thresholds, ventilation support procedure codes, and predisposition diagnosis patterns.
- References: `Hypercapnia NEW DATA - RFS Processing.ipynb:51`, `Hypercapnia NEW DATA - RFS Processing.ipynb:122`, `Hypercapnia NEW DATA - RFS Processing.ipynb:188`, `Hypercapnia NEW DATA - RFS Processing.ipynb:247`, `Hypercapnia NEW DATA - RFS Processing.ipynb:341`, `Hypercapnia NEW DATA - RFS Processing.ipynb:1928`.

### 2025-02-11 — Emit RFS event extracts for final assembly
- Date: 2025-02-11
- Decision: Persist per-category RFS event extracts (`RFS_<RFS>.csv`) alongside encounter-level flags.
- Context: Final dataset assembly consumes legacy `RFS_<RFS>.csv` files with encounter dates.
- Options considered:
  - Recompute qualifying dates inside final assembly
  - Emit event extracts during the RFS stage (chosen)
- Rationale: Keeps RFS filters centralized and matches notebook outputs.
- Consequences: RFS stage writes `RFS_ABG.csv`, `RFS_VBG.csv`, `RFS_RESPFAIL.csv`, `RFS_OBESITY.csv`, `RFS_VENTSUPPORT.csv`, and `RFS_PREDISPOSITION.csv` with `patient_id`, `encounter_id`, `date`.
- References: `src/trinetx_preprocessing/transform/rfs.py`, `src/trinetx_preprocessing/pipeline/rfs_stage.py`, `Hypercapnia NEW DATA - RFS Processing.ipynb`.

### 2025-02-11 — Canonical final dataset assembly logic
- Date: 2025-02-11
- Decision: Use `Hypercapnia Final Dataset Generation - Master.ipynb` as the canonical source for final dataset assembly; executed notebook variants in `Executed Notebooks/` are treated as derived runs.
- Context: Final dataset assembly needed to be implemented as a pipeline stage while preserving output naming and filters.
- Options considered:
  - Use executed notebook variants (per RFS/setting)
  - Use `Hypercapnia Final Dataset Generation - Master.ipynb` (chosen)
- Rationale: The master notebook defines demographics merges, encounter filtering, RFS/setting naming, and output directories used by the legacy pipeline.
- Consequences: Final assembly uses `RFS_<RFS>.csv` inputs, merges patient demographics, filters to 2022 encounters, excludes `Ex-US`/`Unknown` locations, enforces age 18–109, and writes `RFS_<RFS>_ENC_<SETTING>_{BEFORE,AFTER}.csv` under `output/<SETTING_DIR>/`.
- References: `Hypercapnia Final Dataset Generation - Master.ipynb`.

### 2025-02-11 — Regression hashing normalization strategy
- Date: 2025-02-11
- Decision: Normalize regression tables by sorting columns and rows, then hash a normalized CSV rendering with SHA-256.
- Context: The regression harness needs deterministic hashes independent of row order while avoiding raw data exposure.
- Options considered:
  - Hash raw CSV bytes without normalization
  - Use `pandas.util.hash_pandas_object`
  - Normalize tables (column/row sort) then hash CSV text (chosen)
- Rationale: Sorting columns/rows produces deterministic ordering across pipeline runs, and hashing CSV text avoids version-specific DataFrame hashing.
- Consequences: Regression hashes depend on normalized CSV rendering (with stable float formatting) and are computed after reading CSV values as strings.
- References: `src/trinetx_preprocessing/regression.py:1`.

### 2026-01-01 — Resolve config paths relative to config file
- Date: 2026-01-01
- Decision: Resolve `data_dir`, `work_dir`, and `output_dir` relative to the config file location when not absolute.
- Context: Config files may live outside the repo root; relative paths need deterministic meaning.
- Options considered:
  - Resolve relative to current working directory
  - Resolve relative to the config file (chosen)
- Rationale: Keeps configs portable and avoids reliance on shell working directory.
- Consequences: Users must update config paths if they move the file.
- References: `src/trinetx_preprocessing/config.py:129`.

### 2025-02-05 — Replace split_db.sh with Python splitter
- Date: 2025-02-05
- Decision: Use the `split` CLI backed by `split_csv` to replace `split_db.sh`; chunked outputs include headers, use four-digit zero-padded suffixes, and discovery prefers chunked files when present.
- Context: The shell script is platform-specific and notebooks expect `f"{i:04}"` chunk naming.
- Options considered:
  - Keep `split_db.sh` as-is
  - Python splitter with three-digit suffixes
  - Python splitter with four-digit suffixes (chosen)
- Rationale: Improves portability and aligns chunk naming with notebook expectations.
- Consequences: New chunks are named like `encounter0001.csv` with headers; unchunked files are ignored when chunked files are present.
- References: `src/trinetx_preprocessing/tools/split_csv.py`, `src/trinetx_preprocessing/discovery.py`, `src/trinetx_preprocessing/cli.py`, `docs/ONBOARDING.md`.

### YYYY-MM-DD — Example decision title
- Date: YYYY-MM-DD
- Decision: Use Parquet for intermediate files instead of CSV.
- Context: CSV parsing is slow and memory-heavy.
- Options considered:
  - Keep CSV
  - Parquet (pyarrow)
  - SQLite
- Rationale: Faster reads, compression, stable schemas.
- Consequences: Adds dependency on `pyarrow`; need clear install path.
- References: docs/ARCHITECTURE.md; profiling notes.

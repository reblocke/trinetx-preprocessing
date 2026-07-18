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

### 2026-07-09 — Corrected semantics supersede legacy notebook quirks
- Date: 2026-07-09
- Decision: Post-Milestone 1 releases follow `docs/SPEC.md`, including specimen-specific hypercapnia rules, structured code matching, per-setting event selection, derived diagnosis-or-lab screening, and deterministic feature reductions.
- Context: Milestone 1 established near-exact historical replication and exposed several clinically or analytically incorrect legacy behaviors.
- Options considered:
  - Continue preserving all notebook behavior
  - Patch individual defects without a governing contract
  - Adopt a versioned corrected specification and typed rules (chosen)
- Rationale: A written contract makes intentional divergence reviewable and prevents legacy implementation accidents from remaining requirements.
- Consequences: `refactor-milestone-1` remains the replication fallback; corrected runs require fresh evidence and may change cohort membership while preserving the public final schema.
- References: `docs/SPEC.md`, `src/trinetx_preprocessing/transform`, `src/trinetx_preprocessing/pipeline`.

### 2026-06-08 — Real-data golden master is the final parity gate
- Date: 2026-06-08
- Decision: The refactor requires approved local legacy notebook outputs and
  refactor outputs to be compared by schema, row counts, normalized hashes, and
  documented inclusion logic before signoff.
- Context: Synthetic tests show implementation coverage, but they cannot prove full historical behavior on the real export shape.
- Options considered:
  - Synthetic-only acceptance
  - Code/notebook audit only
  - Real-data golden-master comparison (chosen)
- Rationale: Real-data comparison is the only practical way to detect drift in cohort inclusion and final analytic tables.
- Consequences: Real data and row-level outputs remain local and untracked; only
  private or reviewed aggregate evidence may be used for signoff. Refactor
  Milestone 1 later accepted a documented near-exact row-parity delta rather
  than exact final-file hash equality.
- References: `docs/PLAN.md`, `docs/VALIDATION.md`, `src/trinetx_preprocessing/regression.py`, `src/trinetx_preprocessing/cli.py`.

### 2026-06-08 — Parquet intermediates with legacy final CSV outputs
- Date: 2026-06-08
- Decision: Support Parquet as the preferred internal work-table format while keeping final analytic outputs as historical CSV files.
- Context: Repeated CSV parsing and large intermediate files create avoidable time, disk, and memory pressure on full TriNetX exports.
- Options considered:
  - Keep CSV-only intermediates
  - Use Parquet intermediates (chosen)
  - Use SQLite staging
- Rationale: Parquet improves typed storage and repeated reads with a smaller architecture change than database staging.
- Consequences: `pyarrow` is a dependency; `storage.intermediate_format` controls physical work-table format, and `storage.emit_legacy_csv_intermediates` can be enabled for notebook/debug compatibility.
- References: `src/trinetx_preprocessing/config.py`, `src/trinetx_preprocessing/storage.py`, `config.example.yaml`, `docs/DATA_CONTRACT.md`.

### 2026-06-08 — Memory-aware reads use explicit raw column contracts
- Date: 2026-06-08
- Decision: Stage readers use transform-level raw column contracts as `usecols` when loading raw exports.
- Context: Full TriNetX domain exports may contain columns that are dropped immediately by the legacy logic.
- Options considered:
  - Continue reading all columns
  - Select only documented raw columns (chosen)
- Rationale: Column-limited reads reduce memory and I/O while preserving the exact columns required by the legacy-derived transforms.
- Consequences: Missing required columns fail at read/validation time instead of being silently ignored.
- References: `src/trinetx_preprocessing/pipeline/encounter_stage.py`, `src/trinetx_preprocessing/pipeline/labs_stage.py`, `src/trinetx_preprocessing/pipeline/diagnosis_stage.py`, `src/trinetx_preprocessing/pipeline/medications_stage.py`, `src/trinetx_preprocessing/pipeline/procedure_stage.py`, `src/trinetx_preprocessing/pipeline/vitals_stage.py`.

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

### 2026-06-08 — Use Parquet intermediates for refactor validation
- Date: 2026-06-08
- Decision: Support Parquet work tables via `storage.intermediate_format` while keeping final analytic outputs as CSV.
- Context: The real export must run under severe internal-disk constraints, with most artifacts on `/Volumes/LOCKE STUDY`.
- Options considered:
  - Keep CSV-only intermediates
  - Parquet intermediates with optional CSV companions (chosen)
- Rationale: Parquet reduces repeated CSV parsing and work-table disk footprint while preserving the public final output contract.
- Consequences: Adds `pyarrow`; real-data validation should use `emit_legacy_csv_intermediates: false` unless debugging notebook compatibility.
- References: `src/trinetx_preprocessing/storage.py`, `src/trinetx_preprocessing/config.py`, `docs/CONFIG.md`.

### 2026-06-08 — Hash Parquet using CSV-visible semantics
- Date: 2026-06-08
- Decision: Golden-master hashes compare normalized CSV-visible table contents rather than pandas dtypes or Parquet physical encodings.
- Context: Legacy outputs are CSV, while the refactor may use Parquet intermediates; numeric values such as `55.0` must not mismatch only because Parquet preserves a float dtype.
- Options considered:
  - Hash Parquet typed DataFrames directly
  - Hash Parquet after CSV-visible value normalization (chosen)
- Rationale: Historical parity is about final analytic contents and inclusion logic, not internal storage representation.
- Consequences: Duplicate logical CSV/Parquet companions are allowed only when their normalized hashes match; conflicting duplicates fail fast.
- References: `src/trinetx_preprocessing/regression.py`, `tests/test_regression.py`.

### 2026-06-08 — Prefer chunked stage-local writes
- Date: 2026-06-08
- Decision: Raw-domain stages and RFS derivation should stream chunks into stage-local work tables instead of accumulating full lists of DataFrames when equivalent behavior can be preserved.
- Context: Internal disk and memory are constrained; the restored raw export is expected to live on a slower external drive.
- Options considered:
  - Keep whole-domain in-memory concatenation
  - Stream chunks and write appendable CSV/Parquet work tables (chosen)
- Rationale: Bounded chunk processing lowers peak memory and makes external-drive execution feasible while preserving notebook-derived transforms.
- Consequences: Some stages may reread compact work tables, but parity remains the priority over wall-time optimization.
- References: `src/trinetx_preprocessing/storage.py`, `src/trinetx_preprocessing/pipeline/rfs_stage.py`, `src/trinetx_preprocessing/pipeline/final_assembly.py`.

### 2026-06-23 — Preserve legacy final-feature value quirks for parity
- Date: 2026-06-23
- Decision: Final analytic feature assembly preserves notebook-observed categorical and numeric quirks when they affect output hashes.
- Context: Staged legacy-vs-refactor parity found exact synthetic parity, then a real-data prefix tier exposed mismatches in canonical ethnicity encoding, venous lactate mapping/conversion, potassium boundary inclusion, and `value_New_Temp` float text.
- Options considered:
  - Normalize values into cleaner semantic encodings
  - Preserve notebook-visible values exactly (chosen)
- Rationale: Historical parity is the hard gate; cleaner values are not acceptable if they change final CSV contents.
- Consequences: Canonical ethnicity labels map to the notebook's numeric `0/1/2`, abbreviated synthetic labels remain unchanged, venous lactate uses LOINC `30241-4` with `/ 9.008` plus `2519-7` unchanged, potassium includes the lower bound `1.8`, and `value_New_Temp` applies the notebook's half-precision rounding before output.
- References: `src/trinetx_preprocessing/pipeline/final_assembly.py`, `src/trinetx_preprocessing/transform/vitals.py`, `tests/test_final_assembly.py`, `tests/test_transform_vitals.py`.

### 2026-06-23 — Reduce final lab candidates through scratch buckets
- Date: 2026-06-23
- Decision: Final assembly reduces lab-feature candidates through hidden scratch buckets instead of materializing all matching lab rows in memory.
- Context: Real cohorts can have large lab work tables, and the final assembly previously held all matching rows for every requested lab rule before selecting first/highest values.
- Options considered:
  - Keep list-and-concatenate materialization
  - Use bucketed scratch candidate reduction (chosen)
- Rationale: Chunk-local selection plus scratch-backed per-patient reduction lowers peak memory while preserving the existing first/highest selector semantics.
- Consequences: Final assembly may create temporary `.trinetx-final-labs-*` directories under `work_dir`; cleanup uses strict deletion and raises on real filesystem failures.
- References: `src/trinetx_preprocessing/pipeline/final_assembly.py`, `tests/test_final_assembly.py`.

### 2026-06-08 — Hash final CSVs with chunked external sorting
- Date: 2026-06-08
- Decision: CSV golden-master hashing should preserve normalized sorted-table semantics while sorting rows in bounded chunks and merging temporary sorted chunks from the CSV's filesystem.
- Context: Real final outputs may be too large to read fully on a machine with tight memory and limited internal disk.
- Options considered:
  - Read each CSV fully with pandas before hashing
  - Hash raw ordered CSV bytes
  - Chunk rows, sort chunks, merge sorted chunks, and hash the normalized stream (chosen)
- Rationale: This keeps the parity hash independent of row order while avoiding full-table memory use and avoiding internal-disk spill during external-drive validation.
- Consequences: `hash-outputs` exposes `--hash-chunk-rows`; temporary row-level scratch files are created beside the CSV and removed after hashing.
- References: `src/trinetx_preprocessing/regression.py`, `src/trinetx_preprocessing/cli.py`, `tests/test_regression.py`.

### 2026-06-08 — Cap input inspection during external restore monitoring
- Date: 2026-06-08
- Decision: `inspect-inputs` can cap per-domain matches with `--max-matches`, filter to one or more domains with `--domain`, skip free-space probes with `--skip-space-check`, and isolate domains in subprocesses with `--domain-timeout-seconds` for quick readiness snapshots, while exact discovery remains the default for `validate-config`, `validate-inputs`, and pipeline runs.
- Context: A mounted external restore can make full glob expansion slow or unstable, and readiness checks mostly need to know whether each domain has at least one matching file.
- Options considered:
  - Always enumerate and sort every matching file
  - Use capped inspection only for status snapshots (chosen)
  - For simple `directory/prefix*.csv` patterns, scan the target directory
    directly and stop after the requested cap (chosen)
- Rationale: Capped inspection reduces unnecessary external-drive directory traversal without weakening the strict validation gates.
- Consequences: Capped JSON statuses mark `truncated: true` and `matched_count_exact: false`; skipped space checks report `space_check_skipped: true` and `space_ok: null`; status JSON records search-directory existence, counts, and a bounded path sample rather than unbounded file lists. Use exact validation after all domains are present. Simple shallow patterns avoid full `glob` expansion and per-entry stat calls during capped checks. Timeout-enabled snapshots require `--max-matches`, record `timed_out` domains, send a process-group kill on timeout, perform only a short process-exit check, and do not block trying to drain output from a child stuck in external-volume I/O. They are not sufficient to start a real run.
- References: `src/trinetx_preprocessing/config.py`, `src/trinetx_preprocessing/cli.py`, `docs/VALIDATION.md`.

### 2026-06-08 — Require exact input and free-space status for final validation
- Date: 2026-06-08
- Decision: `validation-status` treats capped or timeout-based `inspect-inputs` JSON as monitoring evidence only; the final input gate requires uncapped match counts, no domain probe timeouts, no probe errors, and successful free-space checks with `min_free_gb >= 100` for `data_dir`, `work_dir`, and `output_dir`.
- Context: Restore monitoring uses `--max-matches`, `--skip-space-check`, and `--domain-timeout-seconds` to avoid hanging on a slow external drive, but those shortcuts cannot prove complete real-data readiness.
- Options considered:
  - Let any `all_present: true` status satisfy the final input gate
  - Require exact uncapped status for the final gate (chosen)
- Rationale: Historical parity must be proven from complete inputs; capped metadata checks are useful for monitoring but are too weak for final validation.
- Consequences: Before profiling or final parity comparison, rerun `inspect-inputs --min-free-gb 100 --json-out ...` without `--max-matches`, `--skip-space-check`, or `--domain-timeout-seconds`, then run `validate-inputs`; exact input snapshots without the threshold cannot pass merge-readiness.
- References: `src/trinetx_preprocessing/cli.py`, `docs/VALIDATION.md`.

### 2026-06-08 — Require current input-status schema for final validation
- Date: 2026-06-08
- Decision: `validation-status` requires `input_status.json` to declare current `inspect-inputs` `schema_version: 1` before it can satisfy the final input gate.
- Context: Input inspection snapshots are metadata-only artifacts that may survive across CLI changes. A stale snapshot could have exact counts and enough free-space evidence but still omit fields that later readiness checks depend on.
- Options considered:
  - Accept any JSON status with passing field values
  - Require the current input-status schema version and keep older snapshots readable only as incomplete evidence (chosen)
- Rationale: Merge-readiness evidence should be regenerated with the same CLI contract that will be reviewed, while old files remain useful for restore monitoring and troubleshooting.
- Consequences: After CLI changes to `inspect-inputs` evidence shape, regenerate `/Volumes/LOCKE STUDY/trinetx-preprocessing-validation/manifests/input_status.json` with the current command before treating `validation-status` as authoritative.
- References: `src/trinetx_preprocessing/cli.py`, `tests/test_cli.py`, `docs/VALIDATION.md`, `docs/REPRODUCIBILITY.md`.

### 2026-06-08 — Write validation evidence artifacts atomically
- Date: 2026-06-08
- Decision: CLI-generated metadata evidence files are written to a hidden temporary file in the target directory and then installed with atomic replacement.
- Context: During external-drive restore monitoring, an interrupted `inspect-inputs --json-out` can otherwise truncate `input_status.json`, leaving `validation-status` with an unparsable evidence file even when a previous complete status existed.
- Options considered:
  - Write status JSON directly to the final path
  - Write temporary file then replace the final path only after the content is complete (chosen)
- Rationale: Final validation depends on small metadata artifacts staying readable even when a slow external-volume probe is interrupted.
- Consequences: `input_status.json`, `validation_status.json`, `validation_status.md`, comparison reports, hash manifests, and profile provenance use atomic text writes. Interrupted writes may leave hidden temp files but should not corrupt the last completed artifact.
- References: `src/trinetx_preprocessing/filesystem.py`, `src/trinetx_preprocessing/cli.py`, `src/trinetx_preprocessing/regression.py`, `src/trinetx_preprocessing/profiling.py`, `tests/test_filesystem.py`.

### 2026-06-08 — Require complete strict profile provenance for merge readiness
- Date: 2026-06-08
- Decision: `validation-status` requires profile provenance to use `schema_version: 2` and include `strict: true`, final-output count, final-output file inventory, total generated path count, wall time, peak RSS, work/output disk footprint, stage timings, start/end timestamps, package/Python metadata, git commit/dirty state, behavior-code dirty state and SHA-256 metadata for `src/`, `pyproject.toml`, and `uv.lock`, and config path/hash metadata.
- Context: The refactor must document performance and memory behavior under external-drive constraints, not just produce output files.
- Options considered:
  - Treat any provenance JSON as sufficient
  - Require the performance fields needed for the final validation record (chosen)
- Rationale: Completion requires exact parity plus documented wall-time, memory, and disk-footprint results that are traceable to the code and config that produced them.
- Consequences: A profile run must use `profile --strict` and write current schema v2 `profile/provenance.json`; incomplete, non-strict, old-schema, stale-code-state, or hand-written provenance does not satisfy merge readiness. `output_files` is regular final CSV files only so it can be compared directly with `hash-outputs --scope final`; work-table evidence is captured through `generated_file_count` and `disk_footprint_bytes.work_dir`.
- References: `src/trinetx_preprocessing/profiling.py`, `src/trinetx_preprocessing/cli.py`, `docs/VALIDATION.md`.

### 2026-06-08 — Bind profile provenance to current behavior code
- Date: 2026-06-08
- Decision: Profile provenance records a deterministic SHA-256 digest over current behavior-affecting code paths (`src/`, `pyproject.toml`, and `uv.lock`), including uncommitted tracked changes and untracked non-ignored files in those paths. `validation-status` recomputes that digest and rejects stale profile provenance when it no longer matches.
- Context: A profile run can be expensive on the external drive. Without a code-state digest, a later validation summary could pair real performance evidence from an older implementation with manifests and docs from the current implementation.
- Options considered:
  - Trust `git_commit` and a dirty boolean
  - Require a current behavior-code state digest while keeping config and output freshness checks separate (chosen)
- Rationale: The digest gives strong metadata-only evidence that the measured run used the implementation under review, while avoiding row-level data reads and avoiding sensitivity to documentation-only edits.
- Consequences: After changing `src/`, `pyproject.toml`, or `uv.lock`, rerun `profile --strict` before treating `validation-status` as merge-ready. Documentation-only edits do not invalidate the code-state digest.
- References: `src/trinetx_preprocessing/profiling.py`, `src/trinetx_preprocessing/cli.py`, `tests/test_cli.py`, `tests/test_profiling_utils.py`, `docs/VALIDATION.md`, `docs/REPRODUCIBILITY.md`.

### 2026-06-08 — Cache final-assembly data checks per setting
- Date: 2026-06-08
- Decision: Final assembly loads each unique setting-level data-check file once into a transient SQLite encounter-id lookup under `work_dir`, and reuses that lookup across all RFS categories for settings that share the file.
- Context: The legacy-shaped output loop writes before/after files for every RFS category and setting. Re-reading the same data-check CSV for each category adds repeated external-drive I/O without changing inclusion logic.
- Options considered:
  - Preserve per-category data-check reads
  - Cache the allowed encounter-id set per setting in Python memory
  - Cache each unique data-check file in a stage-local SQLite lookup on the external work volume (chosen)
- Rationale: This reduces repeated reads on slow mounted volumes without retaining large screening-file encounter-id sets in Python memory and keeps the final output contract unchanged.
- Consequences: Data-check filters are still optional and still applied independently to each final dataset. The stage creates hidden `.trinetx-data-check-ids-*.sqlite` scratch files under `work_dir` and removes them on normal completion; if interrupted, they are private row-level scratch data and should be deleted with other private work artifacts.
- References: `src/trinetx_preprocessing/pipeline/final_assembly.py`, `tests/test_final_assembly.py`.

### 2026-06-08 — Reuse final-assembly setting inputs and RFS events
- Date: 2026-06-08
- Decision: Final assembly prepares the three setting encounter lookups and their optional disk-backed data-check encounter-id lookups once, then processes each per-category `RFS_*` event work table once for reuse across settings.
- Context: The legacy-shaped output grid has every RFS category crossed with every encounter setting. Reading each `RFS_*` event table once per setting creates repeated external-drive I/O without changing inclusion logic.
- Options considered:
  - Keep the setting-first loop and reread each RFS category per setting
  - Read each RFS category once and reuse cached setting inputs while returning paths in the legacy setting/category order (chosen)
- Rationale: This reduces repeated work-table reads on the slow external validation volume while preserving final file names, contents, and returned path order.
- Consequences: The setting/data-check reuse decision still stands, but later hash-bucket changes superseded the original full-category event materialization and SQLite encounter lookup details. Exact real-data parity remains the gate for semantic equivalence.
- References: `src/trinetx_preprocessing/pipeline/final_assembly.py`, `tests/test_final_assembly.py`, `tests/test_pipeline_run.py`.

### 2026-06-08 — Store final demographics on disk
- Date: 2026-06-08
- Decision: Final assembly loads transformed patient demographics into a transient SQLite lookup under `work_dir`, then queries only the patient IDs needed for each RFS/setting merge frame.
- Context: Patient exports can be large, and the previous final-assembly path kept the full transformed demographics table in Python memory for every RFS/setting merge.
- Options considered:
  - Keep the full transformed demographics DataFrame in memory
  - Reread patient CSV chunks for every RFS/setting pair
  - Use a stage-local SQLite demographics lookup on the external work volume (chosen)
- Rationale: SQLite keeps the unique patient demographics table on the configured external work volume, preserves duplicate `patient_id` failure behavior, and lets the existing pandas merge/guardrail logic operate on a small per-output demographics frame.
- Consequences: The stage creates a hidden `.trinetx-demographics-*.sqlite` scratch file under `work_dir` and removes it on normal completion. If interrupted, hidden files may remain as row-level scratch data and should be deleted with other private work artifacts; hash discovery ignores hidden files.
- References: `src/trinetx_preprocessing/pipeline/final_assembly.py`, `tests/test_final_assembly.py`, `docs/VALIDATION.md`.

### 2026-06-08 — Store final setting encounters on disk
- Date: 2026-06-08
- Decision: Final assembly loads each setting encounter work table into a transient SQLite lookup under `work_dir`, then queries only the encounter IDs needed for each RFS/setting merge frame.
- Context: Setting encounter tables can be large, and the previous final-assembly path kept all three setting encounter DataFrames in Python memory for every RFS/setting output.
- Options considered:
  - Keep the three full setting encounter DataFrames in memory
  - Reread setting encounter work tables for every RFS/setting pair
  - Use stage-local SQLite encounter lookups on the external work volume (chosen)
- Rationale: SQLite keeps setting encounter detail on the configured external work volume, preserves duplicate `encounter_id` failure behavior for the merge key, and lets the existing pandas merge/date-filter/guardrail logic operate on a small per-output encounter frame.
- Consequences: This SQLite implementation was superseded on 2026-06-17 by deterministic hash-bucketed `.trinetx-final-encounters-*` scratch directories after real-data profiling exposed external-drive random-I/O stalls.
- References: `src/trinetx_preprocessing/pipeline/final_assembly.py`, `tests/test_final_assembly.py`, `docs/VALIDATION.md`.

### 2026-06-17 — Supersede final encounter SQLite lookup with hash buckets
- Date: 2026-06-17
- Decision: Replace the transient final-assembly setting encounter SQLite lookup with deterministic hash-bucketed scratch CSV directories under `work_dir`.
- Context: After the RFS hash-bucket rerun completed, `run-final-assembly --strict` stalled while creating `.trinetx-final-encounters-*.sqlite` from `AMB_encounters.parquet` on the external validation drive. The lookup file reached about 1.3 GiB with low CPU and no stage progress for roughly 50 minutes, matching the earlier random-I/O failure mode.
- Options considered:
  - Continue the SQLite-backed final assembly attempt
  - Reload full setting encounter DataFrames into Python memory
  - Store setting encounter rows in deterministic encounter-id hash buckets, validate duplicate keys per bucket, and read only matching buckets for each merge (chosen)
- Rationale: All rows for an encounter ID land in one bucket, so duplicate `encounter_id` failure behavior and exact merge membership are preserved while avoiding random SQLite inserts and `IN (...)` probes on the external drive.
- Consequences: Final assembly now creates hidden `.trinetx-final-encounters-*` scratch directories instead of SQLite files and removes them on normal completion. Interrupted attempts remain private row-level scratch and must be cleaned with `clean-scratch --delete` before rerun.
- References: `src/trinetx_preprocessing/pipeline/final_assembly.py`, `tests/test_final_assembly.py`, `docs/VALIDATION.md`.

### 2026-06-17 — Stream final RFS event candidates through hash buckets
- Date: 2026-06-17
- Decision: Final assembly now streams each `RFS_*` event work table in chunks, joins demographics per chunk, writes setting-independent event candidates to encounter-id hash buckets, reduces duplicate encounters, then reduces duplicate patients through patient-id hash buckets before setting-specific encounter merges.
- Context: The patched final encounter lookup completed AMB/EMER/INPAT lookup loading and wrote ABG/VBG outputs, but the run still loaded each complete RFS event table into memory. `RFS_PREDISPOSITION` contains about 100,495,138 rows, making the full-table pandas load inconsistent with the low-memory validation goal.
- Options considered:
  - Continue the partial final assembly run and risk an out-of-memory failure on the largest category
  - Load full RFS categories and rely on available RAM
  - Stream category candidates into deterministic hash buckets and reduce one bucket at a time (chosen)
- Rationale: The final event de-duplication rule is setting-independent until the encounter-table merge. Reducing candidates once per category preserves the qualifying-date/encounter-id ordering rule while avoiding repeated full-category memory loads for each care setting.
- Consequences: Final assembly creates hidden `.trinetx-final-events-*` and `.trinetx-final-patients-*` scratch directories under `work_dir` and removes them on normal completion. `clean-scratch` inventories and deletes both prefixes after interrupted runs. Exact legacy parity remains the hard gate for validating the streamed reducer.
- References: `src/trinetx_preprocessing/pipeline/final_assembly.py`, `src/trinetx_preprocessing/cli.py`, `tests/test_final_assembly.py`.

### 2026-06-08 — Store final data-check membership on disk
- Date: 2026-06-08
- Decision: Final assembly stores optional data-check encounter-id membership in transient SQLite lookups under `work_dir` while building before/after outputs.
- Context: Data-check screening files may contain many encounter IDs. Keeping those IDs as Python sets can create avoidable peak RSS pressure, especially because EMER and INPAT share the same configured input file.
- Options considered:
  - Keep Python `set` membership for data checks
  - Reread data-check CSVs for every before/after filter
  - Use stage-local SQLite membership lookups on the external work volume (chosen)
- Rationale: SQLite is in the Python standard library, keeps high-cardinality membership data on the configured external work volume, and supports exact membership filtering without changing the optional data-check semantics.
- Consequences: The stage creates hidden `.trinetx-data-check-ids-*.sqlite` scratch files under `work_dir` and removes them on normal completion. If interrupted, hidden files may remain as row-level scratch data and should be deleted with other private work artifacts; hash discovery ignores hidden files.
- References: `src/trinetx_preprocessing/pipeline/final_assembly.py`, `tests/test_final_assembly.py`, `docs/VALIDATION.md`.

### 2026-06-08 — Store RFS flag membership on disk
- Date: 2026-06-08
- Status: Superseded on 2026-06-16 by hash-bucketed RFS membership and first-seen encounter scratch directories.
- Decision: The RFS stage stores per-category encounter-id membership in a transient SQLite database under `work_dir` while streaming event extracts, then queries that database chunk-by-chunk while writing `rfs_encounter_flags`.
- Context: The RFS stage can identify many qualifying encounters across lab, diagnosis, procedure, and vitals inputs. Keeping all category membership sets in Python memory creates avoidable peak RSS pressure on the low-memory machine.
- Options considered:
  - Keep Python `set` membership for every RFS category
  - Store only event extracts and reread all RFS event tables repeatedly
  - Use a stage-local SQLite membership store on the external work volume (chosen)
- Rationale: SQLite is in the Python standard library, keeps high-cardinality membership data on the configured external work volume, and supports exact membership checks without changing RFS event extract outputs.
- Consequences: This SQLite implementation was replaced after real-data profiling showed random lookup behavior was not viable on the external drive. Current RFS runs create hidden `.trinetx-rfs-membership-*` and `.trinetx-rfs-encounters-*` scratch directories instead.
- References: `src/trinetx_preprocessing/pipeline/rfs_stage.py`, `tests/test_rfs_stage.py`, `docs/VALIDATION.md`.

### 2026-06-08 — Store encounter-stage reducer state on disk
- Date: 2026-06-08
- Status: Superseded on 2026-06-09 by append-only encounter hash buckets.
- Decision: The encounter stage stores setting-level filtered encounter reducer state in a transient SQLite database under `work_dir` while streaming raw encounter chunks.
- Context: Building `AMB_encounters`, `EMER_encounters`, and `INPAT_encounters` requires keeping the earliest retained row per encounter ID. The prior implementation kept one Python dictionary per setting for the full stage, which can grow with the restored encounter export.
- Options considered:
  - Keep Python dictionaries for all retained encounter IDs
  - Write all filtered rows and run a separate full-table deduplication pass
  - Use a stage-local SQLite reducer keyed by setting and encounter ID (chosen)
- Rationale: SQLite keeps reducer state on the external work volume, preserves the existing earliest-start-date replacement rule, and avoids another full-table pass over filtered encounters.
- Consequences: This SQLite implementation was replaced after external-drive profiling showed random-write and index-build bottlenecks. Current encounter runs create a hidden `.trinetx-encounter-reducer-*` hash-bucket directory instead.
- References: `src/trinetx_preprocessing/pipeline/encounter_stage.py`, `tests/test_encounter_stage.py`, `docs/VALIDATION.md`.

### 2026-06-08 — Bind comparison reports to manifest inputs and contents
- Date: 2026-06-08
- Decision: `validation-status` accepts a final comparison report only when the report uses `schema_version: 1`, the report's recorded `baseline` and `current` paths and manifest SHA-256 digests match the legacy/refactor manifest directories supplied to the status command, and a fresh metadata-only comparison of those current manifests agrees with the report `ok` flag and counts.
- Context: `compare-manifests --report` writes a reusable JSON evidence artifact. A stale report from a different manifest pair, from older `hashes.json` contents in the same manifest directories, or from hand-edited report contents could otherwise make the final parity gate look stronger than the artifacts actually prove.
- Options considered:
  - Trust the report's `ok` flag only
  - Require the report to match the exact manifest paths and manifest file digests being summarized, and recompute the comparison during final status checks (chosen)
- Rationale: Historical parity evidence must be traceable to the specific legacy and refactor manifest contents under review, and the final gate should not trust report fields that are cheap to recompute from metadata.
- Consequences: After regenerating either manifest, rerun `compare-manifests --report ...`; `validation-status` fails old-schema, stale, or internally inconsistent comparison reports even when their own `ok` flag is true and the directory paths are unchanged.
- References: `src/trinetx_preprocessing/cli.py`, `docs/VALIDATION.md`.

### 2026-06-08 — Bind readiness artifacts to one config
- Date: 2026-06-08
- Decision: `validation-status` requires the resolved config path and config SHA-256 in `input_status.json` to match `profile/provenance.json`, and requires that SHA-256 to match the current config file at that path.
- Context: External-drive validation writes several metadata-only artifacts over time. A stale input snapshot from one config, an older version of the same config path, or artifacts generated before a later `config.yaml` edit could otherwise appear together in a passing evidence bundle.
- Options considered:
  - Trust each artifact independently
  - Require cross-artifact config identity and current config-file hash verification (chosen)
- Rationale: Historical parity and performance evidence must describe the same data/work/output configuration and the config file contents currently under review.
- Consequences: After changing or regenerating the external validation config, rerun both `inspect-inputs --json-out ...` and `profile --strict` before treating `validation-status` as merge-ready. `validation-status` reports explicit artifact-consistency blockers for config path mismatches, config SHA-256 mismatches, unavailable config identity, and current config-file hash drift.
- References: `src/trinetx_preprocessing/cli.py`, `docs/VALIDATION.md`, `docs/REPRODUCIBILITY.md`.

### 2026-06-08 — Bind refactor manifests to profiled outputs
- Date: 2026-06-08
- Decision: `validation-status` requires the refactor manifest `source_path` entries and profile provenance final-output inventory to describe the same final CSV file set under the configured `output_dir`, and requires each refactor manifest key to match the `source_path` relative to that configured `output_dir`.
- Context: The golden-master workflow profiles the refactor and then hashes final refactor outputs. The pipeline also writes work-table intermediates, but those should not be compared to a final-output manifest. A stale, hand-copied, or subset refactor manifest could otherwise be compared against legacy outputs while performance provenance came from another run or a larger final output set.
- Options considered:
  - Trust profile provenance and refactor manifest independently
  - Require bidirectional equality between refactor manifest source paths and profile output inventory (chosen)
- Rationale: Parity and performance evidence must refer to the same complete refactor final-output set and the configured output tree under review, while intermediate overhead is tracked through profile disk-footprint metadata. The manifest key is the comparison identity, so it must not hide the file's actual relative path under `output_dir`.
- Consequences: Regenerate the refactor manifest with current `hash-outputs --scope final`; refactor manifests without table `source_path` metadata, from another output tree, outside the configured output tree, with key/source relative-path mismatches, or covering only a subset of profiled outputs cannot satisfy merge readiness.
- References: `src/trinetx_preprocessing/cli.py`, `docs/VALIDATION.md`, `docs/REPRODUCIBILITY.md`.

### 2026-06-08 — Require external-root placement and capacity for final validation
- Date: 2026-06-08
- Decision: `validation-status --required-root PATH` verifies that supplied validation artifact paths, input/profile config paths, configured `data_dir`, `work_dir`, `output_dir`, manifest roots/source paths, and profiled final-output paths resolve under the required root before the final evidence bundle can be ready. With `--required-root-min-free-gb N`, it also records current free-space evidence for that root and fails the root gate below the threshold.
- Context: The real-data validation run must avoid the constrained internal disk and keep raw inputs, intermediates, outputs, profile evidence, and manifests on `/Volumes/LOCKE STUDY`.
- Options considered:
  - Rely on documentation and manual path review
  - Add an optional machine-readable root-placement and capacity gate to the validation summary (chosen)
- Rationale: Root placement and available capacity are cheap to verify from metadata and filesystem stats, and prevent a seemingly complete validation bundle from silently using internal-disk paths or a low-space external root.
- Consequences: External validation status commands should pass `--required-root "/Volumes/LOCKE STUDY" --required-root-min-free-gb 100`. Synthetic/local tests can omit the flags unless they are exercising placement behavior.
- References: `src/trinetx_preprocessing/cli.py`, `tests/test_cli.py`, `README.md`, `docs/VALIDATION.md`, `docs/REPRODUCIBILITY.md`.

### 2026-06-08 — Verify profile output inventory against current files
- Date: 2026-06-08
- Decision: `validation-status` stats each `profile/provenance.json` output file and requires the path to still be a regular `.csv` file with the recorded byte size and mtime.
- Context: The output inventory is written during profiling, while final manifest hashing and readiness summaries may run later. A deleted, overwritten, or hand-edited output tree could otherwise be paired with stale performance provenance.
- Options considered:
  - Trust the historical `exists`, `size_bytes`, and `mtime_ns` fields recorded in profile provenance
  - Verify current file existence, byte size, and mtime without reading row-level contents (chosen)
- Rationale: This keeps readiness checks metadata-only and low-overhead while preventing stale output inventories from satisfying the final evidence bundle.
- Consequences: If profiled final CSV files are moved, deleted, or regenerated, rerun `profile --strict` before treating `validation-status` as merge-ready.
- References: `src/trinetx_preprocessing/cli.py`, `docs/VALIDATION.md`, `docs/REPRODUCIBILITY.md`.

### 2026-06-08 — Require metadata-rich final-scope hash manifests
- Date: 2026-06-08
- Decision: `validation-status` requires legacy and refactor manifests to use `schema_version: 2` with `hash_algorithm: sha256`, include manifest-level `generated_at`, `scope: final`, and `output_dir`, include only final-output `output_dir/` keys ending in `.csv`, per-table nonnegative row counts, column metadata, `physical_format: csv`, and currently existing `.csv` `source_path` files that live under the manifest `output_dir` and whose filenames, byte sizes, and mtimes match manifest metadata before they can satisfy merge readiness.
- Context: The regression loader intentionally keeps reading older hash-only or work-scope manifests for troubleshooting, but historical parity requires final-output schema, row-count evidence, root/scope provenance, the public CSV output contract, and traceability to the current output files under review in addition to normalized hashes.
- Options considered:
  - Accept any manifest whose hashes compare cleanly
  - Require current `hash-outputs --scope final` schema/hash/root metadata, matching CSV filenames and physical format, source-file availability, source-root containment, and source-file stat freshness for final readiness while keeping old manifests loadable (chosen)
- Rationale: Final signoff must prove final CSV schema, row counts, normalized hashes, inclusion logic, and the output root/scope being compared; hash-only, missing-root, work-scope, non-CSV, or stale-source manifests cannot independently document the current final output surface.
- Consequences: Legacy and refactor manifests must be regenerated with current `hash-outputs --scope final`; older string-only, missing-root, non-final-scope, non-CSV, wrong-algorithm, or stale-source manifests remain useful for ad hoc comparisons but `validation-status` reports them as incomplete or stale final evidence. Non-final keys are included in explicit final-scope blocker output so the Markdown handoff identifies the affected keys directly.
- References: `src/trinetx_preprocessing/cli.py`, `tests/test_cli.py`, `docs/VALIDATION.md`, `docs/REPRODUCIBILITY.md`.

### 2026-06-08 — Hash Parquet manifests in bounded batches
- Date: 2026-06-08
- Decision: Parquet manifest hashing reads Parquet files in record batches controlled by `--hash-chunk-rows`, sorts bounded chunks on the source filesystem, and merges those chunks into the same normalized CSV-visible hash stream used for CSV files.
- Context: Parquet intermediates are the preferred refactor storage mode, but loading a full Parquet work table into pandas can exceed the available memory on real TriNetX exports.
- Options considered:
  - Read each Parquet file fully before hashing
  - Stream Parquet batches and reuse the external sorted-chunk hashing path (chosen)
- Rationale: The golden-master workflow must remain usable under severe memory and internal-disk constraints while keeping CSV/Parquet logical comparisons identical.
- Consequences: `--hash-chunk-rows` now bounds both CSV in-memory sort chunks and Parquet record-batch hashing; temporary scratch files are created beside the table being hashed and removed after hashing.
- References: `src/trinetx_preprocessing/regression.py`, `tests/test_regression.py`.

### 2026-06-08 — Ignore hidden filesystem noise in hash discovery
- Date: 2026-06-08
- Decision: Directory-based manifest hashing ignores hidden path components and `__MACOSX` folders while discovering hashable CSV/Parquet outputs.
- Context: External macOS volumes can contain AppleDouble `._*.csv` sidecars, archive folders, or leftover `.trinetx-hash-*` scratch directories after interrupted hashing.
- Options considered:
  - Hash every supported file suffix under work/output
  - Ignore filesystem noise during directory discovery (chosen)
- Rationale: Golden-master manifests should represent pipeline outputs, not OS sidecars or transient row-level scratch files.
- Consequences: Explicitly supplied file paths can still be hashed by lower-level helpers, but `hash-outputs`/directory discovery skip hidden/noise paths.
- References: `src/trinetx_preprocessing/regression.py`, `tests/test_regression.py`, `docs/VALIDATION.md`.

### 2026-06-08 — Stream Parquet work-table reads when chunking is enabled
- Date: 2026-06-08
- Decision: `iter_work_tables` reads Parquet intermediates in record batches when a positive `chunksize` is provided, matching the existing CSV chunking contract.
- Context: Parquet intermediates reduce repeated CSV parsing, but reading a whole Parquet work table into pandas still risks excessive memory use during downstream stages such as RFS derivation.
- Options considered:
  - Keep Parquet reads as full-file pandas reads
  - Honor the configured chunk size for Parquet via pyarrow record batches (chosen)
- Rationale: The existing `chunking.enabled` setting should bound reads for both CSV and Parquet work tables.
- Consequences: Downstream code that uses `iter_work_tables` can process Parquet intermediates in bounded frames; callers that leave `chunksize` unset retain the prior one-frame-per-file behavior.
- References: `src/trinetx_preprocessing/storage.py`, `tests/test_storage.py`.

### 2026-06-08 — Stream final-assembly inputs when chunking is enabled
- Date: 2026-06-08
- Decision: Final assembly reads patient demographics, optional data-check CSVs, setting encounter work tables, and per-category RFS event work tables in `chunking.lines_per_chunk` chunks when chunking is enabled. Patient chunks are transformed into a disk-backed final demographic lookup with duplicate `patient_id` detection across chunks/files; data-check chunks update a disk-backed allowed `encounter_id` lookup used by the legacy filter.
- Context: Patient exports, data-check files, setting encounter work tables, and per-category RFS event work tables can be large, and final assembly previously read these inputs as whole pandas frames before transforming, filtering, or joining.
- Options considered:
  - Keep full raw patient/data-check/work-table accumulation
  - Stream final-assembly CSV and Parquet inputs through the existing chunking setting while preserving global duplicate detection, final demographic output columns, encounter-id filter semantics, and legacy-equivalent joins (chosen)
- Rationale: This reduces avoidable peak memory during final assembly without changing final inclusion logic, allowing duplicate patient IDs that would have failed before, changing which encounters pass data checks, or changing join/filter order.
- Consequences: Later final-event hash-bucket reducers superseded the original per-category RFS event frame materialization. Final assembly now avoids holding the full raw input frames, full transformed demographics table, full setting encounter tables, full data-check membership sets, or full `RFS_*` event category in Python memory. The exact legacy parity gate remains the arbiter for any semantic differences.
- References: `src/trinetx_preprocessing/pipeline/final_assembly.py`, `tests/test_final_assembly.py`, `docs/CONFIG.md`.

### 2026-06-08 — Clean known hidden scratch explicitly
- Date: 2026-06-08
- Decision: Add `clean-scratch` as a dry-run-first CLI command that inventories or deletes known hidden `.trinetx-*` scratch artifacts under an explicit root.
- Context: Memory-bounded hashing and disk-backed stage helpers intentionally write private row-level scratch files beside the table or under configured `work_dir` so they stay on the external validation volume. Normal completion removes them, but interrupted runs can leave stale hidden scratch that consumes external-drive space.
- Options considered:
  - Leave cleanup to manual `find`/`rm` commands
  - Automatically delete hidden scratch during later pipeline commands
  - Provide an explicit cleanup command with dry-run default and `--delete` opt-in (chosen)
- Rationale: The cleanup operation should be reproducible and auditable, but deletion should remain an explicit operator action because these files may contain row-level data and live near final outputs during validation.
- Consequences: `clean-scratch --root PATH` reports matched artifact paths and byte counts, `--json-out` can save a private cleanup inventory, and `--delete` is required before removing anything. The match set is limited to known hidden prefixes created by current hashing and disk-backed stage helpers; public CSV outputs and non-hidden work tables are not targeted.
- References: `src/trinetx_preprocessing/cli.py`, `tests/test_cli.py`, `README.md`, `docs/VALIDATION.md`, `docs/REPRODUCIBILITY.md`.

### 2026-06-08 — Accept observed vitals export spelling
- Date: 2026-06-08
- Decision: Use `Vital Signs/vital*_signs*.csv` as the default vitals input pattern so discovery accepts both historical `vital_signs...` exports and the restored `vitals_signs.csv` spelling observed under `/Volumes/LOCKE STUDY/TriNetX`.
- Context: Legacy notebooks and synthetic fixtures use `vital_signs...`, while the restored real-data tree currently contains `Vital Signs/vitals_signs.csv`. The normalized work-table contract remains `vital_signs_NEW_*.csv`.
- Options considered:
  - Keep only `vital_signs*.csv` and require private config edits for the restored export
  - Broaden the default to the narrow shared shape `vital*_signs*.csv` while preserving downstream output names (chosen)
- Rationale: This keeps `scaffold-validation` usable on the current restored dataset without changing transform behavior, final output names, or historical work-table names.
- Consequences: Input discovery may match either spelling in the `Vital Signs/` folder. The vitals stage still writes `vital_signs_NEW_####.csv`, and historical parity remains the final arbiter for inclusion logic and output contents.
- References: `src/trinetx_preprocessing/cli.py`, `tests/test_config.py`, `tests/test_vitals_stage.py`, `docs/DATA_CONTRACT.md`, `docs/CONFIG.md`.

### 2026-06-08 — Support domain pattern lists for raw inputs
- Date: 2026-06-08
- Decision: Allow a domain to define `patterns:` as a list of glob patterns, and use that for medications by default: `Medications/medication[0-9]*.csv` plus `Medications/medication_ingredient*.csv`.
- Context: The restored medication folder contains raw-looking `medication_ingredient.csv` and generated `medication_NEW_*.csv` files. The previous broad `Medications/medication*.csv` default matched generated intermediates, causing header validation to fail on files that are not raw TriNetX medication exports.
- Options considered:
  - Keep a broad single glob and rely on private config edits
  - Narrow the default to only `medication_ingredient*.csv`
  - Add explicit pattern lists so historical numbered chunks and the restored ingredient export are both accepted while generated intermediates are excluded (chosen)
- Rationale: Pattern lists keep input discovery deterministic and auditable without overmatching files that violate the raw-domain schema.
- Consequences: Existing single-pattern configs remain valid. Generated validation configs now write medication `patterns:` and exact input validation should not treat `medication_NEW_*` as raw medication input.
- References: `src/trinetx_preprocessing/config.py`, `src/trinetx_preprocessing/cli.py`, `tests/test_config.py`, `docs/DATA_CONTRACT.md`, `docs/CONFIG.md`.

### 2026-06-08 — Reduce encounter-stage reducer overhead
- Date: 2026-06-08
- Decision: Filter encounter chunks for all care settings in one pass, batch per-type counts from the combined filtered frame, append reducer candidates sequentially to SQLite, create the reducer lookup index only when final per-setting frames are requested, and stream AMB/EMER/INPAT encounter outputs by scanning that index in key/start-date order.
- Context: A strict real-data profile on the external validation drive spent more than two hours in the first encounter stage on a 36 GiB encounter export without a stage-complete log. A vectorized-upsert restart reached 37.5 million rows quickly but then stalled on the indexed SQLite upsert path. An append-only restart completed the encounter scan (592,125,331 rows read; 381,633,923 normalized) but exposed that AMB alone had 71,474,389 post-filter rows, making full per-setting pandas materialization unsafe. A grouped SQL reducer kept memory low but created large external SQLite temp files and produced no AMB output after several minutes.
- Options considered:
  - Let the existing profile continue indefinitely
  - Revert to full in-memory encounter accumulation
  - Preserve the disk-backed reducer but make writes append-only, build one ordered index, stream that index in Python, and write output batches (chosen)
- Rationale: Historical parity remains the hard gate, so the reducer semantics stay the same: per-setting encounter filtering, earliest `start_date` wins across duplicate `encounter_id` values, equal-date ties keep the first observed candidate row, and invalid LOS rows are still removed. An index-ordered scan avoids per-row indexed upserts, avoids grouped SQL temp tables, and avoids holding a full setting frame in pandas.
- Consequences: The real profile must be restarted to exercise the index-ordered streamed encounter output path. Interrupted hidden reducer scratch is cleaned with `clean-scratch --delete`; partial non-hidden work tables are private generated artifacts and will be overwritten by the restarted profile.
- References: `src/trinetx_preprocessing/transform/encounter.py`, `src/trinetx_preprocessing/pipeline/encounter_stage.py`, `tests/test_transform_encounter.py`, `tests/test_encounter_stage.py`.

### 2026-06-08 — Cover encounter reducer output scans
- Date: 2026-06-08
- Decision: Make the encounter reducer index cover every column needed by the ordered AMB/EMER/INPAT output scan, and log index build start/end.
- Context: The first index-ordered real profile passed the prior grouped-query stall: it completed the 592,125,331-row encounter scan, built the reducer index on the external validation drive, and began writing `AMB_encounters.parquet`. Process sampling then showed output was dominated by SQLite `fetchmany` random reads back into the reducer table because the index provided order but did not cover `patient_id`, `encounter_id`, `end_date_ns`, and `type`.
- Options considered:
  - Let the run continue through slow random table lookups
  - Materialize the full AMB/EMER/INPAT reduced outputs in pandas
  - Add the selected payload columns to the ordered SQLite index so the output scan can be satisfied from the index (chosen)
- Rationale: The covering index preserves the same ordered first-row selection semantics while replacing random table lookups with an index-only scan. This trades some additional external-disk index size for lower read amplification and bounded memory.
- Consequences: The interrupted profile evidence is useful for performance diagnosis but cannot satisfy final readiness. A strict real profile must be rerun after this code change so profile provenance records the current code-state hash.
- References: `src/trinetx_preprocessing/pipeline/encounter_stage.py`, `tests/test_encounter_stage.py`.

### 2026-06-09 — Classify unique codes before group fan-out
- Date: 2026-06-09
- Decision: Diagnosis, medication, and procedure group splitting now evaluates each regex against unique codes within the current chunk, then fans all matching rows out to every matching output group.
- Context: The strict real profile with the covering encounter reducer completed encounter and labs, then spent hours in diagnosis without a completion log. Code inspection showed diagnosis, medications, and procedure all applied every group regex to every normalized row; the same pattern would have affected the much larger medication exports.
- Options considered:
  - Let the run continue and keep row-wise regex scans
  - Replace code groups with hand-coded exact/prefix maps
  - Keep the existing regex definitions but evaluate them once per unique chunk code, preserving overlapping outputs (chosen)
- Rationale: Unique-code classification preserves the legacy regex contract, duplicate row retention, output ordering within each group, and overlapping group behavior while avoiding repeated regex scans across every row in large chunks.
- Consequences: The interrupted profile cannot satisfy final readiness and was stopped deliberately at `status=143`. The next strict real profile must rerun on the current code state after cleaning partial generated work.
- References: `src/trinetx_preprocessing/transform/code_groups.py`, `src/trinetx_preprocessing/transform/diagnosis.py`, `src/trinetx_preprocessing/transform/medications.py`, `src/trinetx_preprocessing/transform/procedure.py`, `tests/test_transform_diagnosis.py`, `tests/test_transform_medications.py`, `tests/test_transform_procedure.py`.

### 2026-06-09 — Replace encounter covering-index reducer with primary-key upserts
- Date: 2026-06-09
- Decision: The encounter reducer stores only the current best row per `(encounter_type, encounter_id)` in a `WITHOUT ROWID` SQLite table keyed by `(encounter_type, encounter_id_key)`. Updates replace an existing row only when the new candidate has an earlier `start_date`, or the same `start_date` with an earlier observed row order.
- Context: The strict real profile after unique-code classification completed the 592,125,331-row encounter scan but then spent about 10 minutes in a single external-disk `CREATE INDEX` over 71,854,804 candidate rows, with large SQLite temp files and no progress to output writing. That late global sort/index was incompatible with the low-overhead external-drive execution goal.
- Options considered:
  - Let the index build continue and accept the external-drive bottleneck
  - Revert to full per-setting pandas materialization
  - Keep a disk-backed reducer but upsert only the current best candidate row per encounter key (chosen)
- Rationale: The chosen reducer preserves the semantic rule encoded by the previous reducer: per-setting filtering, earliest `start_date` wins across duplicate `encounter_id` values, equal-date ties keep the first observed candidate row, missing encounter IDs collapse as pandas `drop_duplicates` would, and invalid LOS rows are removed after reduction. It removes the late global covering-index build and bounds reducer storage to one row per logical encounter/type key.
- Consequences: Encounter output row order is an implementation detail for the normalized golden-master hash; historical inclusion logic and values remain the parity gate. The interrupted profile was stopped at `status=143`, partial generated external work is cleaned, and the strict real profile must be rerun on this reducer implementation.
- References: `src/trinetx_preprocessing/pipeline/encounter_stage.py`, `tests/test_encounter_stage.py`.

### 2026-06-09 — Use append-only encounter hash buckets for external-drive profiling
- Date: 2026-06-09
- Decision: Supersede the primary-key SQLite reducer with append-only hidden CSV hash buckets. The encounter scan writes reducer candidates sequentially into 128 deterministic `encounter_id` buckets, then each bucket is reduced independently in pandas and streamed to AMB/EMER/INPAT outputs.
- Context: The primary-key-upsert profile removed the late covering-index build but became random-write bound as the SQLite key table grew, reaching only 75,000,000 encounter rows after about 6 minutes on the external drive. The original append-only scan was much faster, so the reducer now keeps append-only scan behavior while bounding the later dedupe memory by bucket size.
- Options considered:
  - Continue the primary-key-upsert profile despite worsening random-write behavior
  - Return to append-only SQLite plus global covering index
  - Partition reducer candidates by stable hash bucket, then reduce one bucket at a time (chosen)
- Rationale: All rows for a given `(encounter_type, encounter_id)` key land in the same bucket, so per-bucket sorting by `start_date` and observed row order preserves the same earliest-row/tie-break semantics without a global sort, global index, or full-setting pandas materialization.
- Consequences: The reducer writes private row-level scratch CSVs under a hidden `.trinetx-encounter-reducer-*` directory and removes them on normal completion. Interrupted runs must be cleaned with `clean-scratch --delete` plus removal of generated non-hidden work tables before rerun. Encounter output row order remains non-contractual and is normalized by the golden-master hash.
- References: `src/trinetx_preprocessing/pipeline/encounter_stage.py`, `tests/test_encounter_stage.py`.

### 2026-06-16 — Supersede RFS SQLite membership with hash buckets
- Date: 2026-06-16
- Decision: Replace the transient RFS SQLite membership table with hash-bucketed scratch CSV directories for per-category membership and first-seen encounter rows. The RFS stage writes duplicate-preserving `RFS_*.csv`/Parquet event outputs as before, then builds `rfs_encounter_flags` one bucket at a time.
- Context: The strict real-data profile using SQLite RFS membership completed encounter, labs, diagnosis, medications, procedure, and vitals, but remained in RFS for days. A bounded liveness check on `2026-06-16` showed no log or `rfs_encounter_flags` progress and only tiny SQLite growth, so the profile was stopped cleanly with `status=143`.
- Options considered:
  - Let the multi-day SQLite membership run continue
  - Load all RFS membership sets into Python memory
  - Store membership and encounter candidates in deterministic hash buckets, then process one bucket at a time (chosen)
- Rationale: All rows for an encounter ID land in the same bucket, so category flag checks and first-seen encounter selection remain exact while avoiding random SQLite lookups and full-domain in-memory sets. Event output semantics remain unchanged, including duplicate event rows.
- Consequences: Interrupted RFS runs may leave hidden `.trinetx-rfs-membership-*` or `.trinetx-rfs-encounters-*` scratch directories under `work_dir`; `clean-scratch` inventories and deletes both prefixes. A new strict real profile is required before merge readiness.
- References: `src/trinetx_preprocessing/pipeline/rfs_stage.py`, `src/trinetx_preprocessing/cli.py`, `tests/test_rfs_stage.py`.

### 2026-06-16 — Filter vitals before compact downcast
- Date: 2026-06-16
- Decision: Vital-sign rule application parses values as `float64`, applies unit conversion and min/max filters in that wider dtype, and only then downcasts retained rows to the rule's configured storage dtype.
- Context: The strict real-data profile emitted repeated pandas overflow warnings from `float16` conversion while splitting vitals. Downcasting before filtering can overflow extreme values and can round boundary-adjacent values before inclusion logic is applied.
- Options considered:
  - Keep pre-filter downcast and accept warnings
  - Disable warnings without changing conversion order
  - Filter in wider precision and downcast after inclusion decisions (chosen)
- Rationale: Inclusion logic should be evaluated on parsed numeric values, while compact `float16` remains an internal storage choice for retained rows.
- Consequences: Boundary behavior is now less sensitive to compact storage rounding. Historical parity remains the final arbiter against approved legacy outputs.
- References: `src/trinetx_preprocessing/transform/vitals.py`, `tests/test_transform_vitals.py`.

### 2026-06-16 — Add final-assembly-only resume command
- Date: 2026-06-16
- Decision: Add `run-final-assembly --config CONFIG [--strict]` to build final CSV outputs from existing work-table intermediates without rerunning raw-domain stages.
- Context: Real-data validation can spend many hours producing upstream Parquet work tables. When a downstream stage such as RFS or final assembly is patched, replaying all raw-domain stages wastes external-drive time and increases failure exposure.
- Options considered:
  - Require full `run`/`profile` after every downstream patch
  - Add a final-assembly-only command that reuses existing work tables (chosen)
- Rationale: Resume commands speed debugging while preserving the full `profile --strict` requirement for final merge-readiness provenance.
- Consequences: `run-rfs` plus `run-final-assembly` can validate downstream fixes quickly. A current strict profile is still required before final signoff.
- References: `src/trinetx_preprocessing/cli.py`, `tests/test_cli.py`, `docs/VALIDATION.md`.

### 2026-06-22 — Emit the full legacy final analytic schema
- Date: 2026-06-22
- Decision: Final assembly now emits the full 534-column historical analytic
  CSV schema, using real legacy tier headers as the column-order authority. The
  12-column base cohort output is no longer the final public contract.
- Context: The first complete synthetic legacy-vs-refactor parity run executed
  both pipelines but showed 36/36 schema and hash mismatches. Row counts and
  file sets matched, while legacy outputs contained the full analytic feature
  matrix and the refactor emitted only base cohort columns.
- Options considered:
  - Keep the 12-column output and treat feature assembly as out of scope
  - Require legacy notebooks for final analytic feature creation
  - Build final analytic features from existing refactor work tables while
    preserving the legacy CSV filenames and column order (chosen)
- Rationale: Historical parity requires matching final analytic CSV contents,
  not only cohort membership. Reusing normalized/split work tables keeps the
  implementation resumable and memory bounded, while preserving the notebook
  semantics for demographic recoding, first/highest lab values, vital signs,
  diagnosis/procedure dates, and medication flags.
- Consequences: The current strict real-data profile evidence is stale because
  behavior code changed. Synthetic `tier_00_fixture` now passes exact manifest
  comparison after a full legacy and refactor rerun; `tier_01_prefix` or a fresh
  strict real profile must be run before merge readiness.
- References: `src/trinetx_preprocessing/pipeline/final_assembly.py`,
  `src/trinetx_preprocessing/pipeline/final_output_schema.py`,
  `tests/test_final_assembly.py`,
  `tests/fixtures/final_output_columns.json`.

### 2026-06-23 — Match executed final-notebook value surfaces
- Date: 2026-06-23
- Decision: Final assembly now mirrors the executed legacy notebooks for the
  remaining tier-02 value-surface differences:
  - final schema metadata preserves source column order, so
    `compare-manifests` detects order-only schema drift;
  - `death_year_month` precedes `location` in final outputs, matching real
    tier-01/tier-02 legacy headers;
  - previous Weight/Height/BMI use the executed notebook filter, which merges
    against `master_encounter_df` despite nearby comments saying to exclude
    those encounters, then keeps values only when the selected date is before
    `qualify_date` and writes `int32` values;
  - final lab features reproduce the legacy per-feature CSV round trip by
    applying the notebook's `float16` feature extraction surface, then final
    `float32` output formatting.
- Context: Cached `tier_02_coverage` had exact row-count/schema parity but
  hash mismatches in previous-vital and two lab columns. Aggregate diagnostics
  showed copied legacy notebooks and generated feature work files were the
  authoritative behavior surface.
- Rationale: Historical parity is the hard gate, so implementation follows the
  executed notebooks and their generated feature CSVs rather than comments in
  those notebooks.
- Consequences: The staged ladder now passes through `tier_02_coverage`, but
  the full strict profile remains stale for the current behavior-code hash and
  must be rerun before merge readiness.
- References: `src/trinetx_preprocessing/pipeline/final_assembly.py`,
  `src/trinetx_preprocessing/regression.py`, `tests/test_final_assembly.py`,
  `tests/test_regression.py`.

### 2026-07-08 — Accept Refactor Milestone 1 under near-exact row parity
- Date: 2026-07-08
- Decision: Treat the replication phase as complete for the
  `refactor-milestone-1` repository fallback tag using aggregate row-level
  parity rather than exact final-file hash parity.
- Context: The full BOOK legacy/refactor comparison had 25 content-hash
  mismatches but no missing files, extra files, schema differences, row-count
  differences, legacy-only keys, refactor-only keys, or duplicate-key-mode
  tables. A PHI-safe aggregate audit found `4,412,875 / 4,412,932` exact final
  row matches (`99.998708%`) and `57` mismatched shared-key rows.
- Rationale: The remaining differences are extremely sparse and concentrated in
  Weight/previous-Weight columns. Keeping the milestone as a documented fallback
  point is more useful than continuing to preserve every legacy quirk before
  broader codebase improvement begins.
- Consequences: Exact hash parity remains a diagnostic tool, but it is no
  longer the acceptance blocker for Refactor Milestone 1. Any future change that
  intentionally diverges further from notebook behavior requires separate
  review and validation.
- References: external audit reports under
  `/Volumes/LOCKE BOOK/trinetx-preprocessing-validation/manifests/diagnostics/`;
  reports are private validation artifacts and are not committed.

### 2026-07-08 — Correct post-milestone "last date" and prior-vital semantics
- Date: 2026-07-08
- Decision: After the frozen `refactor-milestone-1` fallback tag, final
  assembly should use corrected analytic semantics for several legacy-compatible
  quirks: prior diagnosis and outpatient medication first/last dates are
  selected only from rows on or before each final row's `qualify_date`,
  `last_date_*` columns select the latest qualifying row, outpatient medication
  last dates are validated independently of first dates, and previous
  Weight/Height/BMI exclude current encounters and select the latest value
  strictly before `qualify_date`.
- Context: Local and GitHub Codex review identified that helper functions named
  for "last" dates could sort ascending and keep the first patient row, causing
  `last_date_*` columns to record earliest rows. The Milestone 1 parity audit
  also showed the remaining accepted residual differences concentrated in
  Weight/previous-Weight columns.
- Rationale: Exact historical mimicry is no longer the active goal after
  Milestone 1. These behaviors are more plausibly legacy bugs than intended
  analytic definitions, and fixing them is preferable before broader
  optimization or maintainability work.
- Consequences: Outputs produced after this decision are post-Milestone 1
  corrected outputs and should not be used to redefine the
  `refactor-milestone-1` replication evidence. Any full real-data evidence
  rerun after this point must be labeled post-milestone.
- References: `src/trinetx_preprocessing/pipeline/final_assembly.py`,
  `tests/test_final_assembly.py`.

### 2026-07-09 — Adopt corrected rules and reusable partitioned analysis indexes
- Date: 2026-07-09
- Decision: Make `docs/SPEC.md` authoritative after Milestone 1, express
  clinical inclusion as immutable typed rules, retain code-system/unit metadata,
  derive diagnosis-or-lab screening, and build compact RFS/feature candidates
  during one streaming pass per domain. Final assembly consumes bounded
  patient-partitioned Parquet indexes shared by all 18 cohorts. A versioned work
  manifest rejects stale or incomplete intermediates.
- Context: The notebook-compatible implementation preserved several incorrect
  gas codes, regex overmatching, cross-setting event suppression, and
  nondeterministic feature reductions. It also repeatedly reread many large
  group tables, producing a 161,763.975-second final-assembly baseline.
- Rationale: Correctness is now governed by an explicit reviewable contract.
  Typed rules make code/system/unit/bound semantics readable, while one-pass
  classification and bounded partitions reduce external-drive I/O without
  requiring full-domain memory.
- Consequences: Existing work tables are incompatible. Complete normalized
  domain tables and legacy group-table emission are opt-in, Milestone 1 remains
  the historical fallback, and release requires corrected staged tests, a fresh
  strict BOOK profile, aggregate-only delta evidence, and performance gates.
- References: `docs/SPEC.md`, `src/trinetx_preprocessing/transform/clinical_rules.py`,
  `src/trinetx_preprocessing/storage.py`,
  `src/trinetx_preprocessing/work_manifest.py`,
  `src/trinetx_preprocessing/pipeline/final_feature_sources.py`.

### 2026-07-10 — Apply data-screen eligibility before patient bucketing
- Date: 2026-07-10
- Decision: Evaluate each category/setting cohort against its encounter-level
  data screen before patient partitioning, store a boolean eligibility column,
  and reuse that boolean when writing `AFTER` outputs.
- Context: A full-scale diagnostic profile showed that encounter IDs within one
  patient bucket hash across many encounter-screen partitions. Querying the
  encounter lookup after enrichment therefore reread much of a 303.5-million-ID
  screen for every cohort group in every patient bucket. First-bucket timings
  projected beyond the final-assembly performance gate.
- Rationale: Screen eligibility depends only on the selected encounter and does
  not depend on analytic feature enrichment. Computing it once before patient
  bucketing preserves output semantics while reducing encounter-screen lookup
  passes by orders of magnitude.
- Consequences: `BEFORE` rows remain unchanged; `AFTER` rows use the same
  encounter membership result without repeated disk lookups. Interrupted-run
  cleanup also recognizes every current partition-store prefix.
- References: `src/trinetx_preprocessing/pipeline/final_assembly.py`,
  `src/trinetx_preprocessing/cli.py`, `tests/test_final_assembly.py`,
  `tests/test_cli.py`.

### 2026-07-10 — Treat legacy data screens as manifest inputs
- Date: 2026-07-10
- Decision: Controlled `data_screen.source: legacy_files` runs require both
  setting-specific screen CSVs before work-manifest initialization. The work
  manifest fingerprints their path, byte size, modification time, and header,
  and rejects missing or changed files.
- Context: GitHub review identified that final assembly could consume edited
  legacy screen files while the manifest still described the same raw inputs
  and configuration.
- Rationale: Screen membership changes final `AFTER` cohorts and is therefore
  an analytic input, not incidental work-directory state.
- Consequences: The work-manifest schema is version `3`; older work manifests
  fail closed. Derived screening remains the corrected default and needs no
  external screen files.
- References: `src/trinetx_preprocessing/work_manifest.py`,
  `tests/test_work_manifest.py`, `tests/test_cli.py`.

### 2026-07-10 — Separate final features by clinical domain
- Date: 2026-07-10
- Decision: Keep final cohort, lookup, screening, and CSV orchestration in
  `final_assembly.py`; move analytic feature enrichment into one small
  orchestrator, shared deterministic reducers, and domain-owned vital, lab,
  diagnosis, procedure, and medication modules.
- Context: Corrected feature logic and bounded reducers had accumulated in a
  single 2,747-line final-assembly module, making independent review and future
  maintenance unnecessarily difficult.
- Rationale: Clinical-domain ownership makes rules and reductions easier to
  locate and test while preserving the existing CLI and compatibility helper
  names.
- Consequences: This extraction intentionally changes no output semantics.
  Existing focused final-assembly tests exercise compatibility aliases, and
  staged/full validation remains required before release.
- References: `src/trinetx_preprocessing/pipeline/final_assembly.py`,
  `src/trinetx_preprocessing/pipeline/final_features.py`,
  `src/trinetx_preprocessing/pipeline/final_feature_common.py`,
  `src/trinetx_preprocessing/pipeline/final_*_features.py`.

### 2026-07-11 — Stream final event partitions into patient cohorts
- Date: 2026-07-11
- Decision: Yield encounter-reduced RFS event partitions directly into setting
  lookups and the patient-partitioned cohort store. Select the global earliest
  `(category, setting, patient)` row inside each patient bucket before feature
  enrichment.
- Context: The first corrected full profile met wall-time targets but reached
  `10,125.734 MB` peak RSS. One-second follow-up sampling showed `6,884.250 MB`
  before feature indexing while the 8.46-million-row predisposition candidate
  frame was concatenated in memory.
- Rationale: Encounter IDs are already deterministically partitioned, and all
  rows for one patient converge in the cohort store. A second stable earliest
  reduction therefore preserves cohort semantics while eliminating the
  full-category concatenation.
- Consequences: Setting lookups and screening remain exact, output filenames
  and schema are unchanged. Reduced event partitions are combined into bounded
  one-million-row join batches to avoid thousands of tiny external lookup
  operations without recreating full-category memory pressure. Full-scale
  validation retains the configured 256 buckets: a 512-bucket diagnostic was
  rejected because doubling simultaneously open Parquet writers raised index
  memory. Feature bucket reads instead retain one generic frame plus source
  row-position arrays and materialize only requested columns on demand.
- References: `src/trinetx_preprocessing/pipeline/cohort.py`,
  `src/trinetx_preprocessing/pipeline/final_assembly.py`,
  `tests/test_final_assembly.py`.

### 2026-07-13 — Partition final feature sources by clinical domain
- Date: 2026-07-13
- Decision: Build independently sealed patient-partitioned stores for vital,
  lab, diagnosis, procedure, and medication feature candidates. Load only the
  active clinical domain for each patient bucket and release each Parquet writer
  as it closes.
- Context: A 256-bucket full diagnostic still reached 10,192.844 MiB because
  the first patient bucket materialized every feature domain in one generic
  frame from an index containing 2.38 billion rows overall. RSS remained above
  the 6,238 MB gate.
- Rationale: Domain-specific stores preserve one scan per compact feature
  source and deterministic row order while bounding bucket memory by the
  largest active domain rather than the sum of all domains.
- Consequences: The review-clean full profile completed all 36 outputs in
  73,589.093 seconds, final assembly in 49,180.54 seconds, and peak RSS at
  6,122.562 MB.
  All 36 output hashes match an independent standalone final-assembly run, and
  recognized scratch is zero. Strict release acceptance remains a separate
  decision because the source contains 286 cross-setting encounter IDs.
- References: `src/trinetx_preprocessing/pipeline/final_feature_sources.py`,
  `src/trinetx_preprocessing/pipeline/final_features.py`,
  `src/trinetx_preprocessing/storage.py`, `tests/test_storage.py`.

### 2026-07-13 — Preserve row alignment and strictness across resume boundaries
- Date: 2026-07-13
- Decision: Sort precomputed data-screen eligibility with its final row before
  writing `AFTER` outputs. Reject `run-final-assembly --strict` when completed
  encounter work includes a non-strict conflict-resolution report.
- Context: GitHub review found that final output sorting could separate a
  positional eligibility mask from its row, and that strict downstream resume
  did not reassert the encounter-stage conflict gate.
- Rationale: Screening is an observation-level property and must follow the
  observation through every reorder. Strictness must apply to prerequisite
  evidence, not only to the currently invoked stage.
- Consequences: The review-clean full profile confirms that six obesity or
  ventilatory-support `AFTER` hashes changed while every schema and row count
  remained stable. Local tests, all three corrected staged tiers, full resource
  gates, and scratch cleanup pass.
- References: `src/trinetx_preprocessing/pipeline/final_assembly.py`,
  `src/trinetx_preprocessing/work_manifest.py`,
  `src/trinetx_preprocessing/cli.py`, `tests/test_final_assembly.py`,
  `tests/test_cli.py`.

### 2026-07-14 — Accept deterministic conflict resolution for Milestone 2
- Date: 2026-07-14
- Decision: Use the completed non-strict full profile as Milestone 2 release
  evidence. Deterministically resolve the 286 source encounter IDs assigned to
  multiple settings by earliest encounter start date and then observed row
  order. Keep strict execution fail-closed on the same conflicts.
- Context: Every corrected semantic, staged, performance, memory, output,
  hygiene, and review gate passed. The source export still assigns 286 encounter
  IDs to more than one setting, and no upstream adjudication is currently
  available.
- Rationale: Deterministic resolution makes the ambiguity explicit and
  reproducible without preventing release of the corrected pipeline. Retaining
  strict failure preserves a stronger acceptance option for analyses that
  require adjudicated source data.
- Consequences: `v0.2.0` and `refactor-milestone-2` may be released from the
  review-clean code state using aggregate conflict evidence. A strict real-data
  run is not claimed to pass, and future upstream adjudication may intentionally
  change affected cohort assignments. This release-specific decision explicitly
  supersedes the 2026-06-08 strict `validation-status` requirement as the
  Milestone 2 release gate only: the command remains unchanged and the current
  bundle is not claimed to report `ready: true`.
- References: `docs/SPEC.md`, `docs/VALIDATION.md`,
  `src/trinetx_preprocessing/pipeline/encounter_stage.py`,
  `src/trinetx_preprocessing/work_manifest.py`.

### 2026-07-14 — Pair supplemental arterial gases to the selected PaCO2
- Date: 2026-07-14
- Decision: Materialize arterial bicarbonate, PaO2, and oxygen saturation from
  versioned LOINC seeds and pair each concept independently to the selected
  first arterial PaCO2 using the existing specimen/panel, exact-time,
  tolerance, and date-only hierarchy. These values do not qualify an encounter.
- Context: The GLP-1 endpoint requires these gas descriptors, but the initial
  implementation exposed permanent null placeholders.
- Rationale: Reusing one pairing table prevents nearby unrelated measurements
  from overriding a better source match and keeps pH and supplemental gas
  provenance deterministic. Explicit unit conversions reject incompatible
  values instead of guessing.
- Consequences: The rule-set version advances to `2026-07-14`. The current
  concepts and broad plausibility bounds are implementation seeds requiring
  investigator review; real-data QA must report unit rejection and concept
  coverage before clinical interpretation.
- References: `config/concept_sets/measurements.csv`,
  `config/glp1_eligibility.yml`,
  `src/trinetx_preprocessing/glp1_eligibility/cohort.py`,
  `tests/test_glp1_foundation.py`, `https://loinc.org/1960-4`,
  `https://loinc.org/2703-7`, `https://loinc.org/2708-6`.

### 2026-07-14 — Retain context flags and configure cleaned-view exclusions
- Date: 2026-07-14
- Decision: Keep all qualifying primary rows in the existing analysis view and
  add `analysis_primary_cleaned_obesity_hypercapnia`, whose exclusions are an
  explicit validated list in configuration. Populate documented context from
  index-encounter codes and source specimen text rather than constant values.
- Context: The endpoint requires context flags without silently deleting rows.
  The initial tables emitted constant false values for several fields and had no
  configurable cleaned view.
- Rationale: Separating retained evidence from exclusion policy preserves audit
  access and permits sensitivity analyses. The first major-trauma seed is
  intentionally narrow because the broad injury chapter includes minor injury,
  poisoning, and procedural complications; a validated trauma algorithm remains
  investigator work.
- Consequences: Positive flags mean documented seed evidence. Negative flags do
  not prove absence. Moderate-sedation CPT `99151`-`99157` and the anesthesia
  service family are treated as index context only when dated no later than the
  selected PaCO2. The default cleaned view excludes all six configured context
  fields, but the unfiltered view and encounter table remain unchanged.
- References: `config/concept_sets/diagnoses.csv`,
  `config/concept_sets/procedures.csv`, `config/glp1_eligibility.yml`,
  `src/trinetx_preprocessing/glp1_eligibility/phenotype_sources.py`,
  `https://www.cms.gov/files/document/02-chapter2-ncci-medicare-policy-manual-2025finalcleanpdf.pdf`,
  `https://www.cdc.gov/nchs/icd/icd-10-cm/index.html`.

### 2026-07-15 — Fail closed on GLP-1 selection and provenance ambiguity
- Date: 2026-07-15
- Decision: Rank the first arterial PaCO2 before validating its value or unit,
  retain unusable first rows with explicit exclusion reasons, and calculate the
  encounter maximum from plausible arterial measurements through discharge.
  Treat the published 50/52 PaCO2 and 27/30/35/40 BMI columns plus arterial
  primary endpoint as fixed contracts; reject configurations that request
  unsupported alternatives. When encounter end is missing, use the existing
  one-day post-start bound for same-encounter BMI fallback as well as gas windows.
- Context: Review found that validity filtering promoted later gas values,
  fixed output columns ignored custom configuration, and the 24-hour table
  understated encounter maxima. A null encounter end also made valid later BMI
  evidence unreachable within the selected encounter.
- Rationale: Selection and validity are distinct operations. Failing closed is
  safer than silently changing the index event or accepting configuration that
  cannot alter the published contract.
- Consequences: The GLP-1 ruleset advances to `2026-07-15`. Unusable first gas
  rows remain auditable but do not enter the strict cohort. Alternate thresholds
  require a future versioned output schema rather than a YAML-only change.
  Open-ended index encounters use `index_date + 1 day` for the configured
  same-encounter BMI fallback.
- References: `src/trinetx_preprocessing/glp1_eligibility/cohort.py`,
  `src/trinetx_preprocessing/glp1_eligibility/config.py`,
  `tests/test_glp1_foundation.py`.

### 2026-07-15 — Separate build identity, evidence, and observability
- Date: 2026-07-15
- Decision: Include parsed concept and phenotype-rule content plus
  package-anchored code content in deterministic build identity. Inventory and
  hash supplied export metadata. Ingest optional medication-ingredient files
  into medication evidence, while computing candidate-patient observability
  from unfiltered raw-domain aggregate scans. Prefer the nearest canonical
  unsplit source family and use headered chunks only as a fallback. When a
  canonical ingredient file exists, ignore a medication chunk family only if
  any chunk, including a one-file chunk family, lacks the required medication
  header fields; retain independently valid medication and ingredient families
  even when optional fields or column order differ. Reject tied nearest export
  roots, ambiguous same-root source families, and cross-domain selections that
  do not share one flat root or recognized sibling domain-folder root before
  inventory or ingestion.
- Context: A changed external concept catalog or code executed from another
  working directory could reuse stale output. Concept-filtered source tables
  also made unmatched history appear absent, and discovered ingredient exports
  were not consumed.
- Rationale: Build identity must describe every behavior-defining input.
  Phenotype evidence depends on approved concepts, whereas data observability
  must not depend on terminology coverage.
- Consequences: Workspace identity schema advances to version 2. Raw
  observability adds bounded sequential aggregate scans but stores no additional
  row-level source copy. Run manifests expose the concept digest and source
  inventory includes metadata files and hashes. Ingredient-only exports are
  valid, and restored roots no longer ingest unsupported headerless medication
  artifacts. Same-size but distinct medication and ingredient domains remain
  discoverable, while neither one logical domain nor a cross-domain selection
  can combine different export roots.
- References: `src/trinetx_preprocessing/glp1_eligibility/concept_sets.py`,
  `builder.py`, `provenance.py`, `discovery.py`, `ingestion.py`, `workspace.py`,
  `tests/test_glp1_foundation.py`.

### 2026-07-15 — Publish complete aggregate flow and protect private outputs
- Date: 2026-07-15
- Decision: Build all 15 contracted cohort-flow rows only after component
  phenotypes and payer routes exist. Use bounded source aggregates for the first
  two stages, one checkpointed domain-wide Space-Saving stream for terminology
  QA, and reject every repository-local output directory regardless of Git
  ignore rules.
- Context: The previous flow stopped after five rows, per-file sketch merges
  lost valid error bounds, and custom repository-local output paths could leave
  confidential databases or staging trees trackable.
- Rationale: Aggregate reports must reconcile the actual endpoint, QA bounds
  must remain truthful, and privacy controls must cover both final and temporary
  output locations. Ignore patterns can contain exceptions and cannot prove that
  every current or future clinical artifact is untrackable.
- Consequences: Cohort flow has exactly 15 ordered rows. The final five are
  parallel BMI-at-least-30 characterizations, not a nested attrition funnel.
  Repository-local roots always fail before staging starts. DuckDB files,
  write-ahead logs, and other generated artifacts remain ignored as defense in
  depth. Existing non-directory output paths fail before Git probing.
  Publication fails closed if a WAL remains after an explicit checkpoint and
  connection close.
- References: `src/trinetx_preprocessing/glp1_eligibility/cohort.py`,
  `ingestion.py`, `provenance.py`, `builder.py`, `.gitignore`,
  `tests/test_glp1_foundation.py`.

### 2026-07-15 — Preserve date-only encounter context
- Date: 2026-07-15
- Decision: Match timestamped diagnosis and procedure context rows against exact
  encounter bounds. When a source date contains no time, match by calendar-date
  overlap after requiring the same patient and encounter identifiers.
- Context: Casting a date-only value to midnight excluded valid same-encounter
  context whenever the encounter began later that day.
- Rationale: Date-only source precision should widen only the temporal boundary,
  not the patient or encounter linkage.
- Consequences: Cardiac arrest, trauma, pneumonia, heart failure, ventilation,
  sedation, and postoperative context remain visible for same-day date-only
  records. The cleaned primary view can therefore apply its configured context
  exclusions consistently.
- References: `src/trinetx_preprocessing/glp1_eligibility/phenotype_sources.py`,
  `tests/test_glp1_foundation.py`.

### 2026-07-16 — Bound DuckDB and hash candidate encounter membership
- Date: 2026-07-16
- Decision: Configure DuckDB with a default 4,096 MiB memory limit and one
  thread, record both settings in run provenance, and retain encounter rows by
  membership in deduplicated candidate-patient and candidate-encounter tables.
- Context: A private full-data build exhausted the former 8 GB DuckDB limit.
  The correlated patient-or-encounter predicate planned as a blockwise nested
  loop over the full encounter export and 2.48 million candidate encounters.
- Rationale: Separate membership predicates use bounded MARK/hash joins while
  preserving the original logical OR and duplicate source rows. Explicit
  runtime settings make the measured resource policy reproducible.
- Consequences: Encounter ingestion no longer uses the pathological nested-loop
  plan. The initial 5,120 MiB/two-thread full benchmark exceeded the 6,238 MiB
  process ceiling by 30.3 MiB during an additional diagnostic aggregation, so
  the approved fallback becomes the production default. A second full-scale
  benchmark must pass before another complete private build is launched.
- References: `config/glp1_eligibility.yml`,
  `src/trinetx_preprocessing/glp1_eligibility/config.py`, `database.py`,
  `ingestion.py`, `tests/test_glp1_foundation.py`.

### 2026-07-16 — Respect source precision and the selected export root
- Date: 2026-07-16
- Decision: Evaluate date-only repeat PaCO2 using inclusive calendar-day
  lookback bounds while retaining exact timestamp bounds for timestamped rows.
  Ignore hidden files only below the input root, not hidden ancestors or a
  caller-selected hidden export root.
- Context: Review found that a date-only elevated repeat on calendar day 14
  could precede a noon timestamp boundary and that absolute-path filtering
  rejected otherwise valid exports staged under a hidden directory.
- Rationale: Temporal comparisons should reflect source precision, and export
  discovery should not reinterpret the caller's chosen root based on ancestors.
- Consequences: Date-only day-14/day-84 repeats remain eligible, timestamped
  events retain exact bounds, and hidden children remain excluded without
  hiding a valid root.
- References: `src/trinetx_preprocessing/glp1_eligibility/cohort.py`,
  `discovery.py`, `tests/test_glp1_foundation.py`.

### 2026-07-17 — Reuse bounded membership and partition vital ingestion
- Date: 2026-07-17
- Decision: Materialize unique gas-candidate patient and encounter identifiers
  once, reuse those tables for every retained-domain scan, and compile validated
  exact, prefix, and regex rules into constant predicates. Exact code sets use
  bounded `IN` hash membership within each normalized code system. Stage
  concept-filtered vital rows in 32 patient-hash Parquet partitions, then append
  each partition after joining only the corresponding candidate-patient bucket.
- Context: The first 4,096 MiB/one-thread full build passed encounter ingestion
  but exhausted DuckDB's internal memory while scanning 852,830,801 vital rows.
  The failed query matched 2.48 million patient/encounter pairs and routed five
  exact vital codes through a generic correlated concept matcher. Compiling the
  rules removed that matcher, but direct table materialization still exhausted
  DuckDB at both 4,096 MiB and 5,120 MiB; the larger trial left insufficient
  process-RSS headroom below the 6,238 MiB release gate.
- Rationale: Unique candidate keys and rule-specific predicates preserve source
  duplicates and overlapping-rule truth values. Partitioned staging scans the
  slow raw source once while bounding each candidate join and persistent-table
  append; the existing 4,096 MiB/one-thread runtime remains unchanged.
- Consequences: Current exact, prefix, and regex plans contain neither blockwise
  nested-loop nor delimiter joins. Vitals require temporary external Parquet
  capacity and strict cleanup. The isolated 852,830,801-row benchmark completed
  in `824.15 s` with `4,248.625 MiB` maximum RSS, retained `178,529,225` rows,
  and left zero scratch and WAL; another complete build may proceed only after
  the focused commit passes CI and review.
- References: `src/trinetx_preprocessing/glp1_eligibility/ingestion.py`,
  `tests/test_glp1_foundation.py`, `docs/GLP1_ELIGIBILITY.md`.

### 2026-07-17 — Bound patient-concept domains and normalize source dates
- Date: 2026-07-17
- Decision: Use the reviewed 32-way patient-hash Parquet ingestion strategy for
  diagnosis, procedure, and medication as well as vitals. Normalize source
  timestamps through one parser that accepts standard timestamp strings,
  compact `YYYYMMDD` dates, and compact `YYYYMMDDHHMMSS` timestamps.
- Context: The next full build passed bounded vitals but exhausted DuckDB's
  4,096 MiB limit during direct diagnosis CTAS. Its preserved database also
  showed that restored TriNetX dates use compact `YYYYMMDD`; generic timestamp
  casts left every retained lab, encounter, vital, and diagnosis event time
  null despite non-null source date strings.
- Rationale: The same bounded data structure should protect every large
  patient-keyed concept source. Temporal cohort and phenotype logic must parse
  the actual export representation rather than silently treating valid dates as
  missing.
- Consequences: Duplicate rows, source-record hashes, public table schemas, and
  ISO fixture behavior remain unchanged. The isolated 1,272,185,090-row
  diagnosis benchmark completed in `1,790.82 s`, retained `86,182,713` rows,
  used `4,417.00 MiB` maximum RSS, and left zero scratch and WAL. Aggregate
  production probes confirm every distinct non-null retained lab, encounter,
  vital, and diagnosis date parses under the shared helper. Another complete
  private build requires clean tests, CI, and review of this checkpoint.
- References: `src/trinetx_preprocessing/glp1_eligibility/ingestion.py`,
  `src/trinetx_preprocessing/cli.py`, `tests/test_glp1_foundation.py`,
  `tests/test_cli.py`, `docs/GLP1_ELIGIBILITY.md`.

### 2026-07-17 — Bound duplicate QA and recognize canonical UCUM gas units
- Date: 2026-07-17
- Decision: Compute exact retained-source duplicate counts while reducing each
  terminology hash partition, persist the five-row aggregate result, and make
  output QA read that summary rather than regrouping all retained domains.
  Recognize lowercase-normalized UCUM `mm[hg]` as mmHg and `[ph]` as pH.
- Context: A review-clean full build completed all `906,193,358` retained source
  rows, terminology QA, core cohort construction, and component phenotypes, then
  exhausted DuckDB's 4,096 MiB limit while grouping source hashes across five
  domains for the HTML report. Aggregate inspection also showed that production
  rows use `mm[Hg]` and `[pH]`; the prior alias lists rejected those rows and
  reduced valid-unit cohort flow to zero.
- Rationale: Per-domain hash partitions preserve the prior exact duplicate
  definition while bounding state. UCUM aliases are semantically identical to
  the already-supported mmHg and pH spellings and belong in normalization, not
  in source-specific preprocessing.
- Consequences: Duplicate QA remains exact, including duplicate null-hash groups,
  and no longer requires a cross-domain source aggregate. Canonical UCUM gas
  rows can enter the intended cohort after the same plausibility and threshold
  checks. Full-scale downstream reconstruction and review are required before
  another complete private build.
- References: `src/trinetx_preprocessing/glp1_eligibility/terminology_qa.py`,
  `src/trinetx_preprocessing/glp1_eligibility/outputs.py`,
  `src/trinetx_preprocessing/glp1_eligibility/cohort.py`,
  `tests/test_glp1_foundation.py`.

### 2026-07-17 — Bound exact terminology coverage reduction
- Date: 2026-07-17
- Decision: Reduce terminology matches one source domain at a time. Domains with
  at most one million retained rows use a direct exact aggregate; larger domains
  stage matches into 32 deterministic source-record-hash Parquet partitions and
  count distinct hashes one partition at a time.
- Context: Full run `7bd772e11f3b00a1d7ee6e81` completed all source ingestion
  and retained `906,193,358` rows, then exhausted DuckDB's 4,096 MiB limit while
  one cross-domain aggregate retained every distinct matched record hash.
- Rationale: All copies of one source-record hash map to the same partition, so
  partition counts sum exactly while bounding each distinct-hash set. Processing
  domains sequentially also releases peak scratch before the next domain. The
  direct small-domain path avoids imposing partition I/O on tests and fixtures.
- Consequences: `concept_match_summary` retains its exact de-duplication and
  overlapping-rule semantics. The read-only full-scale benchmark completed all
  92 concept sets in `812.81 s` with `4,548,182,016` bytes maximum RSS, zero
  required-set warnings, and zero residual terminology scratch.
- References: `src/trinetx_preprocessing/glp1_eligibility/terminology_qa.py`,
  `src/trinetx_preprocessing/glp1_eligibility/builder.py`,
  `src/trinetx_preprocessing/cli.py`, `tests/test_glp1_foundation.py`,
  `tests/test_cli.py`.

### 2026-07-18 — Stream unfiltered observability in bounded record batches
- Date: 2026-07-18
- Decision: Scan each raw observability domain through a separate 512 MiB,
  one-thread DuckDB connection and consume selected analysis-patient rows as
  Arrow record batches capped at one million rows. Reduce each batch against
  the index-event table, then merge only the bounded aggregate state.
- Context: Full build `43ef3d7f4a1441cc4ee5a737` completed all retained source
  rows, terminology QA, and core cohort construction, then exhausted DuckDB's
  4,096 MiB internal buffer while directly joining and grouping the 1.27
  billion-row diagnosis export. Two partitioned Parquet variants also exhausted
  that buffer during their 22 GB selected-row materialization.
- Rationale: Observability must include unmapped raw events, preserve duplicate
  row counts, and support multiple index dates per patient. Streaming the
  existing DuckDB CSV parser retains its `null_padding` input behavior while
  eliminating both the unbounded aggregate and row-level materialization.
- Consequences: The production diagnosis benchmark completed in `427.76 s`,
  produced `59,596` index summaries and `12,334,864` qualifying lookback events,
  used `465,829,888` bytes maximum RSS, and left no row-level scratch. The scan
  connection's temporary directory is still cleaned strictly and is recognized
  by `clean-scratch` after interrupted runs.
- References: `src/trinetx_preprocessing/glp1_eligibility/ingestion.py`,
  `src/trinetx_preprocessing/cli.py`, `tests/test_glp1_foundation.py`,
  `tests/test_cli.py`.

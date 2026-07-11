# Architecture

## Design goals
- Implement the corrected analytic contract in `docs/SPEC.md`.
- Provide a single, documented entrypoint (CLI).
- Keep the computational core pure and testable.
- Isolate I/O, configuration, and orchestration.
- Support low-overhead intermediates without changing final CSV outputs.

## Legacy components (historical references)
- Large raw exports were split manually before notebook execution.
- Preprocessing notebooks: encounter, diagnosis (prior/current), lab results, medication, procedure, vital signs.
- `Hypercapnia NEW DATA - RFS Processing.ipynb` — derives RFS cohorts.
- `Hypercapnia Final Dataset Generation - Master.ipynb` — builds final datasets per RFS/setting.
- `Hypercapnia Data Checks.ipynb` — data quality encounter lists.
- `Hypercapnia Master.ipynb` — orchestration via `nbconvert`.

## Current `src/` mapping (legacy → module)
- Raw CSV splitting → `src/trinetx_preprocessing/tools/split_csv.py` + CLI `split` command.
- `Hypercapnia NEW DATA - Encounter (CSV Processing).ipynb` → `transform/encounter.py` + `pipeline/encounter_stage.py`.
- `Hypercapnia NEW DATA - Prior Diagnosis (CSV Processing).ipynb` + `Hypercapnia NEW DATA - Current Diagnosis (CSV Processing).ipynb` → `transform/diagnosis.py` + `pipeline/diagnosis_stage.py`.
- `Hypercapnia NEW DATA - Lab Results (CSV Processing).ipynb` → `transform/labs.py` + `pipeline/labs_stage.py`.
- `Hypercapnia NEW DATA - Medication (CSV Processing).ipynb` → `transform/medications.py` + `pipeline/medications_stage.py`.
- `Hypercapnia NEW DATA - Procedure (CSV Processing).ipynb` → `transform/procedure.py` + `pipeline/procedure_stage.py`.
- `Hypercapnia NEW DATA - Vital Signs (CSV Processing).ipynb` → `transform/vitals.py` + `pipeline/vitals_stage.py`.
- `Hypercapnia NEW DATA - RFS Processing.ipynb` → `transform/rfs.py` + `pipeline/rfs_stage.py`.
- `Hypercapnia Final Dataset Generation - Master.ipynb` → cohort and I/O
  orchestration in `pipeline/final_assembly.py`, feature orchestration in
  `pipeline/final_features.py`, shared reducers in
  `pipeline/final_feature_common.py`, and domain feature modules named
  `pipeline/final_*_features.py`.
- `Hypercapnia Data Checks.ipynb` → diagnosis-or-lab encounter availability
  derived from normalized work tables; legacy files remain an explicit
  compatibility source.
- `Hypercapnia Master.ipynb` → `pipeline/run.py` + `cli.py` (config-driven orchestration).

## Current data flow
1. Discover inputs from config and validate paths.
2. Initialize the versioned work manifest and fail closed on stale inputs,
   configuration, rules, package state, or incomplete dependencies.
3. Stream and normalize encounter data, resolving cross-setting conflicts and
   emitting AMB/EMER/INPAT tables through bounded Parquet partitions.
4. Stream each clinical domain once. Classify typed code rules once per chunk
   and write compact RFS and feature candidate indexes.
5. Derive RFS events and flags from compact indexes.
6. Build all 18 category/setting cohorts, derive diagnosis-or-lab screening,
   attach encounter-screen eligibility once per cohort, and then partition
   final candidates by patient.
7. Build patient-partitioned feature/history indexes once, reuse each bucket
   across all cohorts, apply the precomputed eligibility flag to `AFTER` rows,
   and stream the 36 final CSVs.

Work tables are addressed by legacy logical CSV names, but
`storage.intermediate_format` controls whether physical intermediates are CSV or
Parquet. Final analytic outputs remain CSV for public compatibility. Legacy
complete normalized `*_NEW_*` domain tables are opt-in through
`storage.emit_normalized_domain_tables: true`. Legacy
`HAS_*`, `IPmed_*`, `OPmed_*`, and `value_*` group tables are emitted only when
`storage.emit_legacy_group_tables: true`.

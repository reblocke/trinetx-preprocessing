# Architecture

For the delivered/pending boundary, see `CURRENT_STATE.md`.

## Design goals
- Implement the corrected analytic contract in `docs/SPEC.md`.
- Provide a single, documented entrypoint (CLI).
- Keep the computational core pure and testable.
- Isolate I/O, configuration, and orchestration.
- Build one canonical preprocessed database while preserving exact final CSV
  compatibility.

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
3. Stream labs first to identify additive source-element candidates, then
   stream and normalize encounter data, resolving cross-setting conflicts and
   emitting AMB/EMER/INPAT tables through bounded Parquet partitions.
4. Stream each clinical domain once. Classify typed code rules once per chunk
   and write compact RFS and feature candidate indexes.
5. Derive RFS events and flags from compact indexes.
6. Combine encounter-reduced event partitions into bounded one-million-row
   batches, stream them through each setting lookup, attach diagnosis-or-lab
   eligibility, and partition candidates by patient. Within each patient
   bucket, reduce to the global earliest event for every category/setting
   before feature enrichment.
7. Build patient-partitioned feature/history indexes once, reuse each bucket
   across all cohorts through source row-position views, materialize only the
   requested domain columns, apply the precomputed eligibility flag to `AFTER`
   rows, and stream the 36 final CSVs.
8. Materialize `trinetx_preprocessed.duckdb` from those historical observations
   and the source-faithful domain capture tables. Add catalog, rule,
   membership, observability, provenance, quality, and compatibility-manifest
   tables.
9. Regenerate the 36 CSVs from database views and require their normalized
   hashes to equal the pipeline-generated files before atomic publication.

Work tables are addressed by legacy logical CSV names, but
`storage.intermediate_format` controls whether physical intermediates are CSV or
Parquet. The DuckDB database is canonical; final analytic CSVs remain public
compatibility exports. Legacy
complete normalized `*_NEW_*` domain tables are opt-in through
`storage.emit_normalized_domain_tables: true`. Legacy
`HAS_*`, `IPmed_*`, `OPmed_*`, and `value_*` group tables are emitted only when
`storage.emit_legacy_group_tables: true`.

Study-specific GLP-1 eligibility, phenotype, and analysis logic remains
downstream. `combined_preprocessing/glp1_adapter.py` is the tested boundary from
the canonical source tables to that derivation. See
`docs/UNIFIED_PREPROCESSING.md`.

## Cohort-source boundary

The permanent architecture is one preprocessing and cohort workflow with a
single catalog that contains GLP-1 and typed traditional source candidates.
`element_membership` records code-rule matches only; value, time, index,
phenotype, exclusion, and cohort decisions remain downstream. The read-only,
manifest-bound consumer surface is defined in `UNIFIED_PREPROCESSING.md`.

The GLP-1 adapter and standalone raw ingestion are migration references, not a
second product architecture. Current synthetic tests establish adapter parity
on fixtures, but the new exact-head private full-data parity run is still
pending. Cohort-layer import is also paused until the downstream cohort
repository publishes a stable refactor behavior head.

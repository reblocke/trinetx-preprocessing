# Unified Preprocessing Stage 1

## Endpoint

Stage 1 establishes one canonical Python preprocessing product,
`trinetx_preprocessed.duckdb`. It contains all historical 534-column
observations plus the source-faithful elements required by the GLP-1 pipeline.
The 36 historical CSVs are generated compatibility exports, not a parallel
preprocessed product. Study-specific GLP-1 eligibility and the future Stata
migration remain downstream.

## Implemented

1. A versioned combined database contract with exact 36-output/534-column
   compatibility views.
2. Bounded source capture for labs, vitals, diagnoses, procedures,
   medications, encounters, and patients, preserving duplicate rows and source
   provenance.
3. A unified element catalog, matching-rule table, source membership,
   observability, RFS membership, encounter availability, provenance,
   data-dictionary, and quality-summary tables.
4. Atomic combined builds with fail-closed code/config/source/catalog identity,
   database validation, and exact compatibility-export hash checks.
5. CLI support for build, status, inspection, validation, and compatibility
   export.
6. A synthetic adapter gate comparing current downstream GLP-1 source and
   analytic tables from raw ingestion versus the combined database.
7. Aggregate-only scripts for historical baseline capture, compatibility
   parity, element completeness, and resource benchmarking.

## Remaining acceptance work

1. Run all local gates and the full synthetic combined build at the final branch
   head.
2. Capture an approved aggregate historical baseline for the 36 CSV outputs.
3. Run a fresh full combined build on the private external volume.
4. Require exact ordered-schema, row-count, and normalized-hash equality for
   all 36 compatibility exports.
5. Record additive element rule coverage, observed-match coverage, wall time,
   peak RSS, database/work/output footprints, and final free space.
6. Complete holistic local and GitHub review before merging Stage 1.

## Deferred

- Migrating `trinetx-hypercapnia-code/stata/do/10_preprocessing.do`.
- Changing GLP-1 cohort, phenotype, imputation, propensity, or analysis
  semantics.
- Expanding clinical terminology beyond the current versioned element catalog.

Those changes require separate branches and their own parity/correction gates.

## Acceptance

Stage 1 is complete when the unified database validates, all 36 compatibility
files match the approved baseline exactly, the combined GLP-1 adapter gate
passes, resource constraints are met, aggregate evidence is complete, and no
private or generated validation artifact is tracked.

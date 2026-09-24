# Unified Preprocessing Roadmap

## Endpoint

Stage 1 establishes one canonical Python preprocessing product,
`trinetx_preprocessed.duckdb`. It contains all historical 534-column
observations plus the source-faithful elements required by the GLP-1 pipeline.
The 36 historical CSVs are generated compatibility exports, not a parallel
preprocessed product. Study-specific cohort and GLP-1 eligibility derivations
remain downstream. See `CURRENT_STATE.md` for the current handoff boundary.

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

## Stage 1 acceptance — complete

1. The final behavior head passed all local gates and the full synthetic
   combined build.
2. The approved aggregate corrected baseline covers all 36 compatibility
   outputs.
3. A fresh full combined build atomically published exactly 38 files on the
   private external volume.
4. All 36 exports and all 6,949,511 rows matched by ordered schema, row count,
   and normalized SHA-256.
5. Aggregate evidence records all 534 historical elements, 92 additive source
   elements, all 118 included rules, wall time, a 4,503.531 MiB peak RSS below
   the 6,238 MiB gate, storage footprints, and final free space.
6. Database, adapter, strict fail-closed, scratch-hygiene, local-test, CI, and
   exact-head review gates passed. The detailed aggregate record is in
   `docs/VALIDATION.md`; private and row-level evidence remains external.

## Cohort-source foundation — complete

1. The source catalog now unions current GLP-1 requirements and typed
   traditional Hypercapnia/RFS extraction rules.
2. The versioned, manifest-bound, read-only DuckDB API and CLI validator are
   implemented. The 36 CSVs remain the legacy bridge; no cohort, index,
   phenotype, imputation, or analysis decision was added.
3. The traditional reference repository exposes reproducible `FULL_DATA` and
   `AFTER_EXCLUSION` variants for later migration parity, merged in
   `trinetx-hypercapnia-code` PR #4 at
   `0584b0e13fe547f4a67b7d05e00aa40c0e95fa94` with green post-merge CI.
4. Code/API review and synthetic CI are accepted. Private GLP-1 source-mode
   equivalence passed at behavior head `9fe392b`; `GLP1_SOURCE_ACCEPTANCE.md` records the scope.
   Broader retained-source completeness and current-schema all-36-file
   certification remain separate upstream release gates.

## Encounter interface: current refactor

The owner approved extraction from downstream stable head 5ada7194d40f.
The implementation now provides both original encounter populations and
traditional/GLP-1 source features through `build-encounters`. The preserved
study package and configuration are downstream. See
ENCOUNTER_PREPROCESSING.md and CONTINUITY.md for validation/landing status.

## Subsequent work

1. Continue neutral measurement and data-quality work here.
2. Correct GLP-1 indication/prevalence definitions and implement encounter-based
   study analyses downstream, using explicit study-specific denominators.
3. Review terminology and optional-domain availability where the proposed
   analysis needs stronger clinical ascertainment.
4. Keep the CSV/DTA reference route available until its consumers migrate.

No new study estimand, indication correction or reporting is part of this
refactor. Historical acceptance evidence below retains its original scope.

## Evidence boundary

Stage 1 was accepted because the unified database validates, all 36
compatibility files match the approved baseline exactly, the combined GLP-1
adapter gate passes, resource constraints are met, aggregate evidence is
complete, and no private or generated validation artifact is tracked.
That historical acceptance does not establish full-data parity for the expanded
traditional catalog or authorize retirement of the standalone GLP-1 raw scan;
those are later exact-head gates.

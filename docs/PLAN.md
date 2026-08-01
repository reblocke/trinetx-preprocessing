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

## Next phases

1. **Land PR #8.** Reconcile the fresh whole-PR review and exact-head CI. The PR
   remains draft until an explicit ready/merge decision.
2. **Create an immutable unified-product release checkpoint.** Choose the next
   package version and tag after merge, point package metadata at the canonical
   README, update the changelog, and normalize Milestone 2/Unified Stage 1
   terminology. The version is `UNCONFIRMED`.
3. **Cut over GLP-1 ingestion in a separate PR.** Add a manifest-bound
   unified-database source to the production GLP-1 CLI, preserve the standalone
   raw builder as the reference, and require full-data adapter-versus-reference
   parity before deprecating the second raw scan.
4. **Reconcile GLP-1 issue #6.** Separate completed software/evidence work from
   the remaining investigator terminology and private record-level review.
5. **Migrate the Stata consumer in its own repository and branch.** Freeze its
   current aggregate/output baseline, define the Python/Stata boundary, and
   replace preprocessing incrementally while retaining the 36-file contract
   until exact private full-data parity passes.
6. **Finish onboarding and legacy cleanup.** Keep notebooks as reference-only
   material, move them under `notebooks/legacy/` only in a dedicated cleanup,
   and deprecate compatibility paths only after all downstream consumers have
   migrated.

## Deferred

- Migrating `trinetx-hypercapnia-code/stata/do/10_preprocessing.do`.
- Changing GLP-1 cohort, phenotype, imputation, propensity, or analysis
  semantics.
- Expanding clinical terminology beyond the current versioned element catalog.

Those changes require separate branches, explicit clinical decisions where
applicable, and their own parity/correction gates.

## Acceptance

Stage 1 was accepted because the unified database validates, all 36
compatibility files match the approved baseline exactly, the combined GLP-1
adapter gate passes, resource constraints are met, aggregate evidence is
complete, and no private or generated validation artifact is tracked.

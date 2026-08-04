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
4. Code/API review and synthetic CI are accepted. A fresh private full-data
   source-completeness and GLP-1 adapter-versus-reference run at the exact
   current head remains pending.

## Next phases

1. **Wait for the downstream refactor boundary.** Freeze the stable behavior
   head of the cohort-creation repository once its current refactor completes.
   Do not import from a moving target.
2. **Import cohort construction into the primary workflow.** Port the
   Hypercapnia derivations and selections incrementally under the shared cohort
   layer, consuming only the cohort-source contract while the Stata/CSV route
   remains the exact private reference. Bring GLP-1 source elements and later
   derivations into that same registry and workflow; do not create a permanent
   standalone GLP-1 product or second preprocessing path.
3. **Use the GLP-1 adapter only for migration parity.** Add a manifest-bound
   unified-database source to the current reference CLI, preserve standalone
   raw ingestion until full-data adapter-versus-reference parity passes, then
   absorb the validated GLP-1 path into the shared workflow and retire the
   second raw scan.
4. **Reconcile GLP-1 issue #6.** Update its stale checklist to separate the
   delivered standalone CLI, eight-file contract, synthetic acceptance, and
   behavior-head-scoped aggregate full-data reference evidence from the
   remaining literal scope: ingest optional high-value domains when present;
   complete and clinically review the versioned concept catalogs; move
   remaining phenotype/label/payer policy into versioned configuration; add the
   required smoke-query SQL/script and expand `summarize` to emit the specified
   aggregate prevalence, indication-burden, treatment-gap, and missingness
   results; refresh full-data evidence at the final exact catalog/rule head;
   and complete investigator terminology and private record-level review. Keep
   the issue open until every retained acceptance criterion has evidence.
5. **Finish onboarding and legacy cleanup.** Keep notebooks as reference-only
   material, move them under `notebooks/legacy/` only in a dedicated cleanup,
   and deprecate compatibility paths only after all downstream consumers have
   migrated.

## Deferred

- Importing cohort logic before the downstream repository refactor provides a
  stable, reviewable behavior head.
- Changing GLP-1 cohort, phenotype, imputation, propensity, or analysis
  semantics.
- Expanding clinical terminology beyond the current versioned element catalog.

Those changes require separate branches, explicit clinical decisions where
applicable, and their own parity/correction gates.

## Evidence boundary

Stage 1 was accepted because the unified database validates, all 36
compatibility files match the approved baseline exactly, the combined GLP-1
adapter gate passes, resource constraints are met, aggregate evidence is
complete, and no private or generated validation artifact is tracked.
That historical acceptance does not establish full-data parity for the expanded
traditional catalog or authorize retirement of the standalone GLP-1 raw scan;
those are later exact-head gates.

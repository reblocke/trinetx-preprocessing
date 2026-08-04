# CONTINUITY

## Goal (incl. success criteria)
- Deliver a cohort-neutral unified source contract and reproducible Hypercapnia
  reference baseline so later cohort code can be imported without reopening raw
  TriNetX exports.
- Preserve the exact 36-file historical compatibility contract; do not import
  or change cohort, phenotype, imputation, or analysis logic in this milestone.

## Constraints/Assumptions
- Raw TriNetX data, row-level outputs, logs, manifests, profiles, and
  validation artifacts remain private, external, and untracked.
- The stable consumer surface is DuckDB plus the existing 36-CSV bridge.
- Standalone raw ingestion remains the reference until a frozen-head full-data
  source/parity/resource gate passes.
- The original worktree's uncommitted recovery ledger remains user-owned and
  untouched; this work is isolated from merged `origin/main`.
- No full-data or other expensive pipeline process is active; do not interrupt
  unrelated drive interrogation.
- Merge authority for any new PR remains separate from implementation.

## Key decisions
- `trinetx-hypercapnia-code` is the authoritative source reference and emits
  both `FULL_DATA` and `AFTER_EXCLUSION` variants.
- The source catalog unions the existing GLP-1 catalog and typed traditional
  extraction/RFS rules, while source candidacy remains distinct from cohort
  inclusion.
- GLP-1 keeps its own catalog fingerprint so the existing adapter stays bound
  to exactly its eligibility semantics after the catalog grows.
- The adapter is a migration-only parity bridge. The permanent design brings
  GLP-1 elements and later cohort derivations into the same primary workflow
  and shared cohort-source contract as the legacy elements, not a separate
  GLP-1 product.

## State
- Preprocessing branch: `codex/cohort-source-contract` from
  `149a65a` (`origin/main`).
- Reference PR: `reblocke/trinetx-hypercapnia-code#4`, exact head `7d4e387`.
  It is draft. Review found two source-reference defects: direct `10` must
  load/validate the configured raw root, and frozen-reference tests must stop
  repeatedly extracting full ~1.3-GB trees on hosted CI. Fixes are in progress.
- Contract PR: `reblocke/trinetx-preprocessing#9`, published through
  `e90d936`; local fixes are not yet committed. Review confirmed that the
  GLP-1 adapter must filter source rows by active GLP-1 membership after the
  catalog gains traditional candidates.

## Done
- PR #8 merged at `149a65a`; exact-head CI passed and all review threads are
  resolved.
- Reference baseline now supports both preprocessing variants and an external
  raw-data compatibility root; focused static tests pass. No private-data Stata
  run has been attempted.
- The preprocessing branch now has an expanded source catalog, a versioned
  read-only cohort-source API/CLI, explicit schema/catalog provenance, and a
  GLP-1-only adapter fingerprint. Focused catalog, consumer, CLI, and GLP-1
  adapter parity tests pass.
- The API spill-location guard was added locally with focused regression tests;
  it closes the direct-API counterpart to the existing CLI guard.
- Cross-repo audit confirmed coverage of core RFS, diagnosis, procedure, lab,
  vital, and existing medication rule families. The Stata outpatient-MAT
  annotation is retained as a separately marked source candidate without
  changing legacy outputs or cohort logic.

## Now
- Apply the active-GLP-1 membership filters to all adapter clinical source
  domains, with traditional-only candidate rows in the synthetic parity test.
- Commit/push the safe-spill and adapter fixes, then reconcile fresh exact-head
  review and CI for both draft PRs.

## Next
- Run final complete synthetic checks subject to available scratch space, then
  reconcile CI/review feedback for the frozen branch heads.
- Freeze accepted heads and retain private aggregate source/reference evidence
  before importing downstream cohort code. The separate production GLP-1
  unified-source CLI and its adapter-versus-raw full-data runner are not yet
  implemented, so that specific cutover gate is not currently runnable.

## Open questions (UNCONFIRMED if needed)
- Formal package release/tag is UNCONFIRMED and outside this milestone.
- Availability/timing of the private full-data gate is UNCONFIRMED.
- The original TriNetX query/export must adjudicate the three Stata-annotated
  outpatient-MAT codes (`3304`, `236913`, `28863`) before a cohort treats the
  retained source candidate as a clinical definition.

## Working set (files/ids/commands)
- `src/trinetx_preprocessing/combined_preprocessing/{traditional_catalog,elements,database,contract,cohort_source,cohort_source_contract,glp1_adapter}.py`
- `tests/test_{traditional_catalog,combined_preprocessing,cohort_source}.py`
- `README.md`, `docs/{DECISIONS,PLAN,UNIFIED_PREPROCESSING,GLP1_ELIGIBILITY}.md`
- Source reference: `/Users/reblocke/Research/trinetx-hypercapnia-code-cohort-reference`, commit `5d86ef4`
- `uv run pytest -q`, `uv run ruff check .`, `uv run ruff format --check .`, `uv lock --check`, `git diff --check`

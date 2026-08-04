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

## State
- Preprocessing branch: `codex/cohort-source-contract` from
  `149a65a` (`origin/main`).
- Reference PR: `reblocke/trinetx-hypercapnia-code#4`, exact head `b379177`.
  It is draft and under CI; merge authority remains separate.
- Contract implementation is assembled through `999954c`; documentation,
  branch-level review, and frozen-head evidence remain pending.

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
- Cross-repo audit confirmed coverage of core RFS, diagnosis, procedure, lab,
  vital, and existing medication rule families. The Stata outpatient-MAT
  annotation is retained as a separately marked source candidate without
  changing legacy outputs or cohort logic.

## Now
- Finish documentation/verification, push the exact preprocessing head, and
  request/reconcile holistic review for both draft PRs.

## Next
- Run final complete synthetic checks subject to available scratch space, then
  reconcile CI/review feedback for the frozen branch heads.
- With an accepted reviewed head, run the fresh external full-data source/parity
  and resource gate before importing downstream cohort code.

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

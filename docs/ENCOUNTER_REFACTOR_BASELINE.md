# Prior continuity checkpoint

# CONTINUITY

## Goal (incl. success criteria)
- Keep the public unified-preprocessing handoff concise, current, and free of
  machine-specific or private validation details.
- Prepare a future GLP-1 source cutover that preserves the accepted cohort,
  phenotype, inclusion, and output contracts and proves exact adapter/reference
  parity before either reference path is retired.

## Constraints/Assumptions
- Raw TriNetX data, row-level outputs, databases, logs, manifests, profiles,
  process details, and private validation artifacts remain external and
  untracked.
- Source-catalog membership is candidacy, not cohort inclusion; clinical
  semantics and the 36-file compatibility contract remain unchanged.
- Static and synthetic validation do not replace the approved private-data and
  licensed-runtime gates required for release acceptance.
- This documentation update does not tag a release, change package versions,
  alter repository settings, or claim completion of the private gates.

## Key decisions
- Adapter membership filters use uncorrelated semijoins to avoid the large
  delimiter-join intermediate that exhausted memory at private scale. This
  preserves source multiplicity, catalog membership, and clinical definitions.
- A comparison failure may borrow both completed builds only after independently
  checking their producing code, dependencies, configuration, catalog, source
  identity and output provenance. Hash partitions preserve full-value equality
  and duplicate multiplicity; hashes only route rows.
- A completed raw reference may be borrowed after a canonical-build failure
  only with unchanged raw-producing code, dependencies, configuration, catalog
  and source identity. Reuse records both producer revisions and retains the
  exact comparison gate; it does not rewrite historical provenance.
- The unified DuckDB/catalog contract is the permanent source interface for
  traditional and GLP-1 workflows.
- Database-backed GLP-1 processing is accepted at behavior head `9fe392b`.
  Preserve raw-reference ingestion for reproduction and retain the explicit
  precision-repair provenance with the original producer receipts.
- Canonical preprocessing owns reusable source-file audit evidence. The
  reference GLP-1 consumer may read that evidence and the validated shared
  tables, but may not rescan raw exports in database mode.
- The future cutover is an orchestration change: existing cohort, phenotype,
  flow, evidence, and output logic must run unchanged after source materialization.
- Public continuity records durable product decisions and validation boundaries,
  not local paths, process identifiers, transient resource observations, or
  private run inventories.

## State
- `main` includes merged cohort-source PR #9 and the subsequent repository
  overview update.
- PR #9 provides the unified catalog, manifest-bound read-only cohort-source
  API/CLI, safe DuckDB spill handling, and synthetic adapter parity across all
  five clinical domains.
- The merged Stata reference is provenance-bound in the catalog, and the final
  PR #9 head passed its documented local and GitHub checks.
- Importing downstream cohort construction remains paused until that codebase
  exposes a named stable behavior head.
- The active GLP-1 source-contract branch adds canonical source audit tables,
  raw-free database consumption, exact GLP output comparison, and a sequential
  private acceptance launcher. The launcher now proves targeted scientific
  equivalence through exact raw-versus-database GLP-1 outputs; all-36-file
  compatibility and exhaustive retained-source membership checks remain a
  separate upstream preprocessing release gate.
- The bounded validator keeps all 64 partition outputs open while writing.
  DuckDB's 100-file default caused excessive partition-file churn at private
  scale; the matching open-file setting preserves the same exact audit with bounded
  memory and substantially less filesystem overhead for future runs.

## Done
- Added change-based `verify-update` planning/execution, provenance-checked
  staged-product promotion through existing publication locks, and bounded
  exact GLP-1 comparison with private aggregate receipts. Private acceptance
  is recorded at `9fe392b`; promotion alone did not close that gate.
- Unified preprocessing and source-catalog interfaces are public and merged.
- Human- and machine-facing documentation records the privacy, provenance,
  compatibility, and downstream-migration boundaries.
- The prior machine-specific operational ledger was retained locally and is
  intentionally excluded from the public repository.

## Now
- Private source-mode equivalence is accepted at `9fe392b` through composed
  full-data evidence: the complete 24-table comparison, exact confirmation of
  two repaired encounter-precision projections, corrected-package readback,
  regenerated Parquet comparison and baseline fingerprints. See
  `docs/GLP1_SOURCE_ACCEPTANCE.md` for the precise producer and repair boundaries.
- Database-backed GLP-1 processing is the production route for this validated
  contract. Retain explicit raw-reference mode for reproduction.

## Next
- Finish publication and remove owned temporary packages after evidence sealing.
- Use change-based verification against the accepted private baseline for future
  updates. Broader cohort import and traditional source certification stay separate.

## Open questions (UNCONFIRMED if needed)
- The stable downstream cohort-refactor behavior head is UNCONFIRMED.
- Availability and timing of the private full-data and licensed-runtime gates
  are UNCONFIRMED.
- A formal package version or release tag remains outside this work.

## Working set (files/ids/commands)
- `README.md`, `AGENTS.md`, `llms.txt`, `CONTINUITY.md`, and active `docs/`
- `git diff --check`, privacy/restricted-artifact scan, and documentation review
- GitHub PR #9 and the merged Stata reference provenance recorded in the catalog

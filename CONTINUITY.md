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
- The GLP-1 adapter and standalone raw ingestion remain migration references
  until frozen-head parity is demonstrated on approved inputs.
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
- The bounded validator keeps all 256 partition outputs open while writing.
  DuckDB's 100-file default caused excessive partition-file churn at private
  scale; the 256-file setting preserves the same exact audit with bounded
  memory and substantially less filesystem overhead for future runs.

## Done
- Added change-based `verify-update` planning/execution, provenance-checked
  staged-product promotion through existing publication locks, and bounded
  exact GLP-1 comparison with private aggregate receipts. Private acceptance
  remains pending; promotion alone does not close that gate.
- Unified preprocessing and source-catalog interfaces are public and merged.
- Human- and machine-facing documentation records the privacy, provenance,
  compatibility, and downstream-migration boundaries.
- The prior machine-specific operational ledger was retained locally and is
  intentionally excluded from the public repository.

## Now
- Full private comparison completed at `5ebf82f`: 22 of 24 database tables
  and all six Parquet-to-database checks matched. Two encounter tables differed.
  Aggregate diagnosis locates the differences at missing encounter-end precision:
  reference ingestion emits `timestamp`, whereas canonical capture retains NULL.
  The adapter now uses the unchanged reference classifier on the retained raw
  end-date field. Targeted full-row confirmation remains pending; do not accept
  source cutover or discard either completed output package yet.
- Both private GLP-1 builds completed. The subsequent monolithic comparison
  exhausted its configured memory limit. Recover using exact full-value hash
  partitions and provenance-checked reuse of both completed output packages;
  do not rebuild them solely to retry comparison. Full-data equivalence and
  source adoption remain pending until that comparison passes.
- A bounded external-drive benchmark identified partition-buffer spill and
  filesystem overhead. The GLP-1 comparator uses 64 partitions and larger row
  groups; exact equality, schemas and duplicate multiplicities are unchanged.
- Complete reviewable synthetic and private-data gates for canonical-source
  GLP-1 reference consumption; keep the shared source product canonical.

## Next
- Identify the stable downstream cohort behavior head.
- Finish the active frozen-head private GLP-1 scientific-equivalence sequence:
  build from raw reference and from the validated canonical database, then
  compare their contracted outputs exactly. Schedule broader upstream source
  certification independently when it is needed for that release decision.

## Open questions (UNCONFIRMED if needed)
- The stable downstream cohort-refactor behavior head is UNCONFIRMED.
- Availability and timing of the private full-data and licensed-runtime gates
  are UNCONFIRMED.
- A formal package version or release tag remains outside this work.

## Working set (files/ids/commands)
- `README.md`, `AGENTS.md`, `llms.txt`, `CONTINUITY.md`, and active `docs/`
- `git diff --check`, privacy/restricted-artifact scan, and documentation review
- GitHub PR #9 and the merged Stata reference provenance recorded in the catalog

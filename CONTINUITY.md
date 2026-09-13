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
  private acceptance launcher. The launcher now requires aggregate 36-file
  baseline parity and shared-element completeness evidence before it can write
  a completed acceptance receipt.
- Full-scale source-membership referential integrity is validated through
  bounded hash partitions and temporary local spill storage; it must remain an
  exact check rather than being relaxed for large products.

## Done
- Unified preprocessing and source-catalog interfaces are public and merged.
- Human- and machine-facing documentation records the privacy, provenance,
  compatibility, and downstream-migration boundaries.
- The prior machine-specific operational ledger was retained locally and is
  intentionally excluded from the public repository.

## Now
- Complete reviewable synthetic and private-data gates for canonical-source
  GLP-1 reference consumption; keep the shared source product canonical.

## Next
- Identify the stable downstream cohort behavior head.
- Finish the active frozen-head private full-data acceptance sequence: validate
  the canonical product, compare its 36 compatibility projections with the
  approved aggregate baseline, record shared-element completeness, and compare
  raw-reference with database-backed GLP-1 outputs.

## Open questions (UNCONFIRMED if needed)
- The stable downstream cohort-refactor behavior head is UNCONFIRMED.
- Availability and timing of the private full-data and licensed-runtime gates
  are UNCONFIRMED.
- A formal package version or release tag remains outside this work.

## Working set (files/ids/commands)
- `README.md`, `AGENTS.md`, `llms.txt`, `CONTINUITY.md`, and active `docs/`
- `git diff --check`, privacy/restricted-artifact scan, and documentation review
- GitHub PR #9 and the merged Stata reference provenance recorded in the catalog

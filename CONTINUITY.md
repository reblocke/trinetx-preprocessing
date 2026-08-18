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

## Done
- Unified preprocessing and source-catalog interfaces are public and merged.
- Human- and machine-facing documentation records the privacy, provenance,
  compatibility, and downstream-migration boundaries.
- The prior machine-specific operational ledger was retained locally and is
  intentionally excluded from the public repository.

## Now
- Publish this sanitized continuity update as a documentation-only draft PR.

## Next
- Identify the stable downstream cohort behavior head.
- Implement the GLP-1 cutover as a separate reviewed change with exact contract
  tests, synthetic parity, and explicit private-data/licensed-runtime gates.

## Open questions (UNCONFIRMED if needed)
- The stable downstream cohort-refactor behavior head is UNCONFIRMED.
- Availability and timing of the private full-data and licensed-runtime gates
  are UNCONFIRMED.
- A formal package version or release tag remains outside this work.

## Working set (files/ids/commands)
- `README.md`, `AGENTS.md`, `llms.txt`, `CONTINUITY.md`, and active `docs/`
- `git diff --check`, privacy/restricted-artifact scan, and documentation review
- GitHub PR #9 and the merged Stata reference provenance recorded in the catalog

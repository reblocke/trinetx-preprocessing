# Refactor Finalization Plan

This plan replaces the initial milestone scaffold for `refactor-pipeline`.
The replication phase is complete for Refactor Milestone 1. The accepted
milestone evidence is near-exact row parity against full legacy outputs:
`4,412,875 / 4,412,932` final analytic rows matched exactly (`99.998708%`),
with no schema, row-count, or key-set differences and `57` documented
Weight/previous-Weight residual row differences.

## Completion principle
- Preserve historical inclusion logic and final analytic CSV contents first.
- Use Parquet for internal intermediates to reduce repeated CSV parsing and disk
  overhead, while preserving legacy final CSV output names and layout.
- Treat performance work as valid only when it preserves golden-master parity.

## Final milestones
1. Planning and contract cleanup.
   - Keep this plan, `docs/VALIDATION.md`, `docs/DATA_CONTRACT.md`,
     `docs/REPRODUCIBILITY.md`, and `docs/DECISIONS.md` current.
   - Reconcile `main` documentation/readiness notes into this branch.
2. Golden-master parity gate.
   - Run the historical notebook pipeline on approved local data.
   - Keep real-data artifacts under
     `/Volumes/LOCKE STUDY/trinetx-preprocessing-validation` on low-space
     machines.
   - Hash legacy and refactor final outputs with `hash-outputs --scope final`.
   - Compare existing manifests with `compare-manifests` so a slow external run
     is not repeated only for comparison.
   - Document every mismatch before changing behavior.
3. Parquet intermediate hardening.
   - Use `storage.intermediate_format: parquet` for refactor work tables.
   - Keep final outputs as CSV.
   - Emit legacy CSV intermediates only when explicitly configured.
4. Performance and memory pass.
   - Profile current and final runs with `profile`.
   - Use explicit columns, explicit dtypes, stage-local writes, chunking, and
     appendable work-table writers.
   - Record wall time, peak RSS, row counts, and disk footprint.
5. Merge readiness.
   - Remove accidental metadata/noise changes.
   - Keep legacy notebooks as references unless an intentional notebook change is
     documented.
   - Require Ruff, pytest, CLI smoke checks, and golden-master signoff.

## Definition of done
- Synthetic tests pass in default CSV mode and chunked Parquet intermediate mode.
- Real-data golden-master comparison passes or has approved documented deltas;
  for Refactor Milestone 1, the approved delta is the aggregate row-parity audit
  showing `99.998708%` exact row agreement and `57` residual Weight-related row
  differences.
- Profiling artifacts show no unexplained performance or memory regression.
- Documentation states how to reproduce the parity and performance gates without
  committing raw data or row-level outputs.

## Current milestone state
- `legacy-pre-refactor` will mark the branch-point fallback before refactor work.
- `refactor-milestone-1` will mark the reviewed current implementation.
- Future work should start from a new post-milestone branch and may improve or
  intentionally diverge from exact notebook quirks only after separate review.

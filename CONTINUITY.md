# CONTINUITY

## Goal (incl. success criteria)
- Finish the whole-PR #8 holistic review, integrate every confirmed finding,
  and reconcile the final exact head with local tests, GitHub CI/review, and
  zero unresolved threads.
- Preserve the accepted unified preprocessing product and exact 36-file
  compatibility contract while documenting the remaining overall refactor
  roadmap.

## Constraints/Assumptions
- Raw TriNetX data, row-level outputs, databases, logs, manifests, profiles,
  and validation artifacts remain private, external, and untracked.
- The accepted full-data product must remain unchanged unless a confirmed fix
  changes product semantics. This review round currently changes only guards,
  validation, recovery, standalone export publication, and documentation.
- Peak RSS remains capped at 6,238 MiB and private validation roots retain at
  least 100 GiB free.
- PR #8 remains draft until the user separately authorizes ready/merge.
- Expensive PID 80692 exited naturally during the recovered run and was never
  interrupted.

## Key decisions
- Behavior head `c96dc40` produced the accepted product; `f3c1b03` changed only
  bounded read-only completeness evidence; `d6a70d2` recorded final Step 2
  evidence.
- Milestone 2 accepts deterministic non-strict resolution for 286 documented
  encounter-setting conflicts. Strict execution remains a separate fail-closed
  adjudication proof.
- The canonical product is one DuckDB plus its manifest and 36 generated CSVs.
  GLP-1 eligibility and the future Stata migration remain downstream phases.
- Standalone `export-legacy` publishes only to a separate external,
  compatibility-only tree; it never mutates the canonical product in place.

## State
- Branch: `codex/unified-preprocessing-v1`.
- Integrated review-reconciliation head:
  `75805d20411a6f177126b9750c286f4591a22b22`.
- Exact-head CI run `30712167025` passed in 6m16s. The fresh whole-PR Codex
  review found one P3 stale 462-versus-463 test-count statement in thread
  `PRRT_kwDOLtXliM6VqEpq`; the final reconciliation change set corrects it.
- Documentation reconciliation head
  `14b8fb758281df1787f577081170bd084b21717b` passed CI run `30712522979`
  in 7m18s.
- The requested holistic GitHub review found one P2 recovery issue in thread
  `PRRT_kwDOLtXliM6VpRQI`; parallel whole-diff audits found and rechecked the
  related path, lock, scratch, export, validation, and documentation issues.
- Its final exact-head review found a third P2: the sidecar rename was not
  directory-fsynced before validation state in thread `PRRT_kwDOLtXliM6VqWae`.
  The missing durability barrier and regression are now committed; exact-head
  CI run `30714776156` passed in 6m05s and the thread is resolved.
- The subsequent exact-head review found one P2 in thread
  `PRRT_kwDOLtXliM6VqeGE`: standalone `validate-preprocessed` does not reject
  repository-local database or compatibility roots even though validation may
  create DuckDB spill and CSV hash scratch beside those inputs.
- The current local change set guards both validation scratch roots before any
  scan. An independent diff audit then found that a setting-directory symlink
  could redirect compatibility hash scratch back into the repository despite a
  safe top-level root; the current change set also guards every distinct
  contract CSV parent and adds a symlink regression. All four focused tests and
  the complete 468-test suite pass.
- Commit `75805d2` is pushed; the latest P2 has an exact-fix reply and is
  resolved. Exact-head CI run `30715666488` passed in 6m25s; holistic review
  request `issuecomment-5153140607` completed as review `4835619937` and found
  one additional P2 in thread `PRRT_kwDOLtXliM6VqoE6`: baseline/parity evidence
  hashing does not guard compatibility roots or contract CSV parents before
  creating adjacent hash scratch.
- The earlier four P2 threads and the P3 thread are resolved.
- The current local fix centralizes root/contract-parent hash guards, applies
  them before combined evidence hashing, and also guards the database spill
  roots used by parity and element-completeness evidence. Generic pre-existing
  `hash-outputs` remains outside this combined-evidence review finding. An
  independent callsite audit found no other unguarded new combined-product hash
  path; builder, validation, export, and benchmark routes use guarded staging.
  All nine focused validation/evidence regressions and the complete 473-test
  suite pass.

## Done
- Step 2 acceptance completed: atomic 38-file publication; exact 36/36 parity
  across 6,949,511 rows; 4,503.531 MiB peak RSS; 534 historical elements, 92
  source elements, and 118/118 included rules; both adapter cases; strict
  286-conflict no-write proof; 430-test/Ruff/diff gate; clean scratch/product
  hygiene; clean exact-head CI/review.
- Triggered a fresh whole-PR GitHub review against `main` and audited the
  roadmap, privacy boundary, and integrated local diff in parallel.
- Implemented early rejection of equal/nested combined work/output roots.
- Added aggregate per-domain validation that every retained clinical source
  row has an included source-concept membership.
- Hardened `export-legacy` with symlink/unmanaged-tree rejection, manifest-bound
  verification, explicit replacement, locks, durable staging, rollback, and
  atomic whole-tree publication.
- Added a durability barrier before the pre-database checkpoint and automatic
  rebuild of stale interrupted pre-database staging.
- Updated the plan, onboarding, strict-mode guidance, and changelog for the
  accepted unified-product state and next phases; package README metadata is a
  future release-checkpoint task.
- Clarified that output-neutral lifecycle/validation hardening may reuse an
  unchanged accepted product only behind focused, bounded, CI, and review
  gates, and that production GLP-1 CLI cutover is still a separate phase.
- Corrected the roadmap for stale open issue #6: substantial standalone GLP-1
  software/evidence is delivered, but optional-domain ingestion, catalog and
  config completion, smoke-query/summary completion, and clinical/private
  validation remain literal issue scope.
- Scoped standalone GLP-1 full-data evidence to behavior head `459cbda`; the
  later semantics-preserving procedure-regex rewrite changed catalog identity,
  so issue #6 also needs fresh evidence at its final catalog/rule head.
- Fixed the second review P2 by coercing malformed timestamps only in the
  complete combined encounter-flow universe while preserving strict parsing in
  legacy/domain transforms. The exact CSV/Parquet adapter regression plus
  encounter-stage/transform tests pass 18/18.
- Hardened case-insensitive containment, stable lock/publication identity,
  no-follow lock opening, terminal/exact-cardinality compatibility export,
  staging-routed spill, live-destination revalidation, unowned-state
  preservation, and canonical/standalone scratch recovery.
- The exact current worktree passes all 473 tests in 171.34 seconds using the
  external validation temp/cache. Repository-wide Ruff, touched-file format,
  `git diff --check`, and `uv lock --check` also pass after the evidence-scratch
  fix.
- A bounded read-only check against the unchanged accepted database reports
  zero retained rows missing an included source-concept membership across all
  five clinical domains and zero included memberships with a wrong catalog
  domain. The 4,479.62-second pass peaked at 3,953.656 MiB RSS; its 39.95-second
  complement peaked at 1,609.391 MiB. Database size/mtime remained unchanged
  and all spill was cleaned.

## Now
- Commit/push the evidence-scratch fix, reconcile its thread, and repeat
  exact-head CI/review, unresolved-thread, PR-state, privacy, and clean-worktree
  checks.

## Next
- Require final exact-head CI, clean GitHub review, zero unresolved threads,
  clean worktree, and no tracked private/generated artifacts.
- Report the prioritized roadmap: land/release PR #8; GLP-1 production cutover;
  issue #6 software/evidence/clinical reconciliation; separate Stata migration;
  then legacy onboarding/deprecation cleanup.

## Open questions (UNCONFIRMED if needed)
- Marking PR #8 ready or merging it remains `UNCONFIRMED` and requires explicit
  user authorization.
- The next release version/tag is `UNCONFIRMED`.
- The exact Stata migration boundary and timing remain `UNCONFIRMED`.

## Working set (files/ids/commands)
- `src/trinetx_preprocessing/combined_preprocessing/{builder,database,validation}.py`
- `src/trinetx_preprocessing/{config,cli,regression}.py`
- `tests/test_{config,cli,combined_preprocessing}.py`
- `docs/{PLAN,ONBOARDING,UNIFIED_PREPROCESSING,VALIDATION,GLP1_ELIGIBILITY}.md`
- `README.md`, `CHANGELOG.md`, `llms.txt`, `pyproject.toml`
- PR #8; initial holistic comment `issuecomment-5152163533`; exact-head review
  comments `issuecomment-5152599268` and `issuecomment-5152752637`; resolved P2
  threads `PRRT_kwDOLtXliM6VpRQI`, `PRRT_kwDOLtXliM6Vp6VT`, and
  `PRRT_kwDOLtXliM6VqWae`; P3 thread `PRRT_kwDOLtXliM6VqEpq`; resolved P2
  thread `PRRT_kwDOLtXliM6VqeGE`; exact-head review request
  `issuecomment-5153140607`; review `4835619937`; open P2 thread
  `PRRT_kwDOLtXliM6VqoE6`; CI runs `30710776011`, `30712167025`,
  `30712522979`, `30714776156`, and `30715666488`
- `git diff --check`; `ruff check .`; external-TMP `pytest -q`

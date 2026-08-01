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
- Pushed review-request head: `d895a814c2647a955a5d52876e064e51a0eed5b1`.
- CI run `30706764612` passed at that head.
- The requested holistic GitHub review found one P2 recovery issue in thread
  `PRRT_kwDOLtXliM6VpRQI`; parallel whole-diff audits found and rechecked the
  related path, lock, scratch, export, validation, and documentation issues.
- The worktree contains the integrated fixes and documentation updates but is
  not yet committed or pushed.

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
- Hardened case-insensitive containment, stable lock/publication identity,
  no-follow lock opening, terminal/exact-cardinality compatibility export,
  staging-routed spill, live-destination revalidation, unowned-state
  preservation, and canonical/standalone scratch recovery.
- The exact current worktree passes all 462 tests in 1,194.09 seconds using the
  external validation temp/cache. All focused regressions and three independent
  read-only re-audits pass with no remaining confirmed implementation issue.
  Repository Ruff, touched-file format, `git diff --check`, and
  `uv lock --check` pass.
- A bounded read-only check against the unchanged accepted database reports
  zero retained rows missing an included source-concept membership across all
  five clinical domains and zero included memberships with a wrong catalog
  domain. The 4,479.62-second pass peaked at 3,953.656 MiB RSS; its 39.95-second
  complement peaked at 1,609.391 MiB. Database size/mtime remained unchanged
  and all spill was cleaned.

## Now
- Commit and push the integrated hardening and evidence.
- Commit/push the integrated review fixes, reply to and resolve the P2 thread,
  then request exact-head re-review.

## Next
- Require final exact-head CI, clean GitHub review, zero unresolved threads,
  clean worktree, and no tracked private/generated artifacts.
- Report the prioritized roadmap: land/release PR #8; GLP-1 production cutover;
  issue #6 clinical reconciliation; separate Stata migration; then legacy
  onboarding/deprecation cleanup.

## Open questions (UNCONFIRMED if needed)
- Marking PR #8 ready or merging it remains `UNCONFIRMED` and requires explicit
  user authorization.
- The next release version/tag is `UNCONFIRMED`.
- The exact Stata migration boundary and timing remain `UNCONFIRMED`.

## Working set (files/ids/commands)
- `src/trinetx_preprocessing/combined_preprocessing/{builder,database,validation}.py`
- `src/trinetx_preprocessing/{config,cli,regression}.py`
- `tests/test_{config,cli,combined_preprocessing}.py`
- `docs/{PLAN,ONBOARDING,UNIFIED_PREPROCESSING,VALIDATION}.md`
- `README.md`, `CHANGELOG.md`, `llms.txt`, `pyproject.toml`
- PR #8; holistic comment `issuecomment-5152163533`; P2 thread
  `PRRT_kwDOLtXliM6VpRQI`; CI run `30706764612`
- `git diff --check`; `ruff check .`; external-TMP `pytest -q`

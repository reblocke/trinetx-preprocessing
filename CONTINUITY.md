# CONTINUITY

## Goal (incl. success criteria)
- Make the cohort-source and Stata-reference PRs documentation-complete, merge
  reference PR #4 first, then merge preprocessing PR #9, and verify both
  default branches after merge.
- Leave both repositories ready to resume one shared cohort-workflow migration
  when the downstream cohort refactor reaches a stable behavior head.

## Constraints/Assumptions
- Raw TriNetX data, row-level outputs, logs, manifests, profiles, and private
  validation artifacts remain external and untracked.
- This release train changes documentation and merge state only; it does not
  import cohort logic, alter clinical semantics, run restricted data, tag a
  release, delete branches, or clean worktrees.
- The original worktree's user-owned `CONTINUITY.md` edit remains untouched;
  all work occurs in isolated PR worktrees.
- Standalone Stata and GLP-1 raw ingestion remain references until their
  frozen-head private parity gates pass.

## Key decisions
- Update active human and machine documentation in both repositories; retain
  historical prompts, notebooks, archives, and frozen evidence as references.
- Use merge commits and expected-head protection, matching repository history.
- Merge `trinetx-hypercapnia-code#4` into `master` before
  `trinetx-preprocessing#9` into `main`, then bind preprocessing documentation
  to the exact merged reference commit.
- GLP-1 and traditional elements belong to one permanent source catalog and
  workflow. Element membership is source candidacy, not cohort inclusion; the
  GLP-1 adapter is a migration-only bridge.
- A reviewer service rate limit is not itself a correctness finding. If it
  persists, require clean independent read-only reviews plus zero unresolved
  GitHub threads before merge.

## State
- Reference PR #4 merged into `trinetx-hypercapnia-code/master` as
  `0584b0e13fe547f4a67b7d05e00aa40c0e95fa94`; exact-head CI and post-merge
  `master` CI run `30936293016` passed.
- Cohort-source PR #9 starts from
  `360eabdbb520a691d42844a1a2045cd788a15e68`; its prior exact-head CI passed
  with 500 tests passed and 7 skipped, and GitHub reports CLEAN.
- The user explicitly authorized documentation completion, ready-for-review
  promotion, and merge for both PRs on 2026-08-04; GitHub is authoritative for
  PR #9's live draft/ready state.
- The documentation-complete PR #9 content passes local diff, Ruff check,
  Ruff format, lockfile, CLI-help, and full pytest gates (507 passed). After
  publication, GitHub is the source of truth for its exact head and live gates.
- Importing downstream cohort construction is paused because that codebase is
  being refactored; the stable restart commit is UNCONFIRMED.

## Done
- PR #8 merged at `149a65a`; exact-head and post-merge CI passed and all review
  threads were resolved.
- PR #4 merged deterministic `FULL_DATA` and `AFTER_EXCLUSION` reference
  variants with disk-bounded synthetic tests and reconciled active docs.
- PR #9 provides the unified catalog, manifest-bound read-only cohort-source
  API/CLI, safe DuckDB spill handling, and synthetic adapter parity across all
  five clinical domains.
- Independent implementation and architecture reviews found no remaining
  P1/P2 code issue at the starting heads.
- Preprocessing machine guidance (`AGENTS.md`, `llms.txt`, the code-agent
  workflow, and repository inventory) now records the unified-product,
  consumer-interface, privacy, evidence, and downstream-blocker invariants.
- Active human documentation now records the same boundary, current API/CLI,
  temporary adapter role, unadjudicated source candidates, and pending private
  parity gate; the exact merged Stata reference commit is bound into PR #9.

## Now
- If the documentation-bound changes are still local, publish them. If PR #9
  remains open, merge only after live exact-head CI, reconciled P1/P2 review,
  zero unresolved threads, and clean expected-head mergeability. If merged,
  verify post-merge `main` CI and final repository topology.

## Next
- Merge PR #9 with expected-head protection, verify post-merge `main` CI, and
  confirm both repositories' final topology and preserved local worktrees.

## Open questions (UNCONFIRMED if needed)
- The stable downstream cohort-refactor behavior head is UNCONFIRMED.
- Availability and timing of the private full-data/Stata gates are UNCONFIRMED.
- Formal package version or release tag is outside this merge train.

## Working set (files/ids/commands)
- `/Users/reblocke/Research/trinetx-hypercapnia-code-cohort-reference`
- `/Users/reblocke/Research/trinetx-preprocessing-cohort-source-contract`
- GitHub PRs `reblocke/trinetx-hypercapnia-code#4` and
  `reblocke/trinetx-preprocessing#9`
- `README.md`, `AGENTS.md`, `llms.txt`, `CONTINUITY.md`, and active `docs/`
- `git diff --check`, Ruff check/format, `uv lock --check`, `pytest -q`, and
  exact-head/default-branch GitHub Actions

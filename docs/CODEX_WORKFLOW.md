# Code-Agent Workflow

This workflow applies to Codex and other code agents. No particular model,
reasoning tier, or autonomous prompt chain is part of the repository contract.
Files under `docs/prompts/` document the historical refactor sequence; do not
replay them as current work instructions.

## Start every task

1. Read `AGENTS.md`, `CONTINUITY.md`, and `docs/CURRENT_STATE.md`.
2. Inspect the exact branch, commit, working-tree diff, and relevant tests before
   accepting older status claims.
3. Preserve unrelated or user-owned edits. Use an isolated worktree when the
   active checkout is dirty or when release evidence must stay frozen.
4. Update `CONTINUITY.md` with facts only when the goal, constraints, state, or
   evidence changes.

## Architectural invariants

- The manifest-bound `trinetx_preprocessed.duckdb` is the canonical source
  product. The 36 historical CSVs are its Stata compatibility bridge.
- Traditional and GLP-1 source candidates share one permanent catalog and
  workflow. `element_membership` is source candidacy, not cohort inclusion.
- Downstream code consumes the read-only source through
  `open_cohort_source()`, `validate_cohort_source()`, or
  `validate-cohort-source`; it must validate schema/catalog provenance and
  required elements first.
- `glp1_adapter.py`, standalone GLP-1 ingestion, and Stata are migration or
  reference implementations. Do not create a permanent parallel GLP-1 product.
- Cohort construction has not been imported. Its migration remains paused
  until the downstream cohort repository identifies a stable behavior head.
- Synthetic adapter parity is implementation evidence only. Private frozen-head
  GLP-1/full-data and Stata parity gates remain pending.

## Implementation and data safety

- Keep changes narrow and put new runtime logic under `src/`; retain notebooks
  and historical prompts as references.
- Use Python, `uv`, pytest, and Ruff. Do not add another environment manager,
  formatter, or orchestration framework.
- Use only synthetic/de-identified test fixtures. Never inspect, copy, commit,
  or quote raw clinical rows or private validation artifacts.
- Keep real databases, compatibility exports, manifests, logs, profiles, and
  DuckDB spill outside the repository. Preserve non-symlink safe-location
  checks, bounded memory, and cleanup limited to tool-owned scratch prefixes.
- Treat schema/catalog fingerprints, source provenance, the 36-file bridge, and
  final CSV behavior as compatibility surfaces. Record intentional semantic or
  contract changes in `docs/DECISIONS.md`.

## Completion evidence

Run focused tests while developing, then the repository gate before publishing:

```bash
git diff --check
uv run ruff check .
uv run ruff format --check .
uv lock --check
uv run pytest -q
```

Before merge, also confirm exact-head CI, review reconciliation, zero unresolved
threads, clean mergeability, privacy-safe tracked files, and post-merge default-
branch CI. State explicitly when private-data parity was not run; prior or
synthetic evidence must not be promoted to a private full-data result.

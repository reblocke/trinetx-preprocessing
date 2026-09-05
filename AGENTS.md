# AGENTS.md

## Scope and data boundaries
- Python-first TriNetX preprocessing. Preserve outputs and inclusion logic during refactoring; use `src/` and CLI entry points for new reusable logic. Do not introduce a different implementation language unless requested.
- Treat this repository as public. Never commit raw TriNetX exports, PHI, row-level products, credentials, private drafts, publisher text, private manifests, or DuckDB spill artifacts. Generated validation artifacts require explicit review before publication. No manuscript version is expected here.
- Raw inputs are immutable. Real export inputs may use ignored `data/` paths; databases, spill, manifests, logs, and row-level products from real runs follow the external-location requirements below.
- Tests use synthetic or approved de-identified fixtures under `tests/fixtures/`. Preserve legacy notebooks by archiving them under `notebooks/legacy/` if a requested move is needed.

## Current architecture and migration invariants
- Read `docs/CURRENT_STATE.md` before changing architecture, public interfaces,
  migration status, or validation claims.
- The canonical reusable source product is the manifest-bound
  `trinetx_preprocessed.duckdb`. The 36 historical CSVs remain a compatibility
  bridge for the frozen Stata reference, not a second canonical product.
- GLP-1 and traditional elements belong to one permanent catalog and one
  preprocessing workflow. A row in `element_membership` records source
  candidacy; it does **not** establish cohort inclusion or clinical eligibility.
- Current downstream consumer surfaces are the read-only Python
  `open_cohort_source()` / `validate_cohort_source()` API and the
  `validate-cohort-source` CLI. Consumers must validate manifest, schema, and
  catalog provenance before reading rows.
- `src/trinetx_preprocessing/combined_preprocessing/glp1_adapter.py`, the standalone GLP-1 ingestion
  path, and the Stata pipeline are migration/reference paths. Do not turn the
  GLP-1 adapter into a permanent parallel product.
- Cohort-construction code has not been imported into this repository. Its
  migration is paused until the downstream cohort repository exposes a stable
  behavior head; never infer cohort semantics from the source catalog.
- Synthetic adapter tests are not private full-data evidence. Standalone
  ingestion and Stata remain references until frozen-head private full-data
  parity gates pass.
- DuckDB databases, temporary spill, manifests, logs, and row-level outputs
  from real data must live outside the repository in validated, non-symlinked
  locations. Preserve the existing safe-location checks and clean only
  tool-owned scratch prefixes.
- Preserve the 36-file Stata compatibility contract until the private reference parity gate authorizes retirement.
- Preserve cohort-source schema and catalog fingerprints at the consumer boundary; incompatible changes require an explicit schema-version decision.

## Context and scientific decisions
- Use `README.md` for entry points, `docs/TESTING.md` for check selection, and `docs/SPEC.md` / `docs/DATA_CONTRACT.md` for affected data behavior.
- Study requirements and approved specifications take precedence over implementation. A discrepancy affecting definitions, inclusion, or accepted outputs needs an explicit scientific decision before changing that behavior. Record authorized divergences in `docs/DECISIONS.md`; do not infer cohort semantics or adjust expected results to obtain a pass.

## Continuity
- Read the local `CONTINUITY.md` when resuming work or when the task depends on prior decisions, checkpoints, or handoff state.
- Update it at meaningful decisions, validated checkpoints, scope changes, or handoff. Keep the existing headings and mark uncertain facts `UNCONFIRMED`.
- Reconcile stale ledger entries with the current user request and observed files. Routine turns and typo fixes do not require ledger edits or a ledger snapshot in the response.

## Implementation and verification
An implementation request covers the necessary local edits, applicable safe checks, and fixes for regressions caused by the change. Continue through verification within that scope. Ask only for unresolved decisions that affect scientific meaning, authorized data access, external cost, publication, deployment, or the requested scope. Preserve unrelated work; a dirty checkout alone is not a reason to stop.

- Use the pinned Python environment, `uv`, `pyproject.toml`, and `uv.lock`. Keep dependency changes and the lockfile together; Ruff is the only formatter/linter.
- Keep transformations in importable code and I/O at explicit boundaries; use `pathlib.Path`, configurable paths, and no `os.chdir` in committed code. Validate schemas, units, ranges, and missingness. Report notebooks must run from a clean session.
- For documentation-only changes, check affected references and `git diff --check`; validate `CITATION.cff` only if its metadata changes.
- For Python behavior changes, run affected tests with `uv run pytest -q <test-path>` and Ruff checks on touched code. Add a regression test when it can catch the failure. Broaden checks for shared interfaces or unresolved failures; repeat only as needed after changes.
- For performance work, measure before/after and preserve exact output behavior. Small synthetic checks do not satisfy frozen-head private full-data parity.
- Recheck affected public documentation and artifact claims. Report commands actually run and any remaining restricted-data or runtime gates; do not regenerate real-data products merely to validate a prose edit.

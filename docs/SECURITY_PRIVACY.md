# Security and Privacy

## Non-negotiables
- Do not commit raw TriNetX exports, row-level patient data, or derived row-level outputs.
- Store real data under `data/` (git-ignored).
- Use only synthetic or de-identified fixtures in `tests/fixtures/`.
- Keep regression artifacts from real data local only (hash manifests in `artifacts/` must not be committed).
- Keep canonical DuckDB products, adjacent manifests, compatibility exports,
  and cohort-source consumer spill outside every Git worktree. Git ignore rules
  are not an adequate boundary for row-level artifacts.

## Logging
- Logs must not print patient identifiers.
- Prefer aggregate counts and high-level summaries.

## Sharing
- If you need to share an error case, reduce it to a synthetic reproducer.
- If a schema sample is needed, redact and minimize.
- Share cohort-source validation metadata only after confirming it is aggregate
  and identifier-free; do not share source-table query results.

## Cohort-source consumers

- Use `open_cohort_source()` so the product is contract-validated before a
  read-only DuckDB connection is exposed and its owned spill is cleaned.
- Put any explicit `spill_root` on the approved external private volume. The API
  rejects repository-local database parents and spill roots even when ignored.
- Required element IDs and catalog fingerprints establish compatibility, not
  authorization to export row-level data or proof of clinical cohort validity.

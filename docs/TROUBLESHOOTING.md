# Troubleshooting

## Common issues

### File not found
- Confirm `data_dir` in config points to the correct location.
- Confirm expected subfolders exist (Encounter, Diagnosis, etc.).
- Prefer glob patterns over hard-coded filenames.

### Memory errors
- Process in chunks; avoid concatenating all chunks into one DataFrame.
- Drop unused columns early.
- Use Parquet intermediates and the default bounded analysis partitions.

### CSV parse issues
- Use explicit dtypes where possible.
- Log the chunk filename being processed for quick isolation.

### Output row-count explosions
- Check join keys and join type (inner vs left).
- Add assertions on expected row grain after merges.

### Cohort-source validation fails

- Confirm the database is a regular file with an adjacent
  `trinetx_preprocessed_manifest.json` sidecar and one terminal `complete`
  embedded manifest row.
- Treat a schema, sidecar, run-ID, required-element, or catalog-digest mismatch
  as an incompatible product; do not bypass it. Rebuild or select the exact
  product the consumer was written against.
- The CLI supports only `--database`, repeatable `--require-element`, and
  `--json`. Use the Python `validate_cohort_source()` result for detailed
  catalog-pin or spill-root diagnostics.

### Cohort-source database or spill location is rejected

- Move the database and explicit `spill_root` outside every Git worktree. An
  ignored repository path is still rejected because it can expose confidential
  row-level data.
- Ensure the external location exists on the intended private volume and has
  sufficient space for bounded DuckDB spill. Do not redirect spill to a local
  repository cache.

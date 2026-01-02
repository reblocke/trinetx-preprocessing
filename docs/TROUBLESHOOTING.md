# Troubleshooting

## Common issues

### File not found
- Confirm `data_dir` in config points to the correct location.
- Confirm expected subfolders exist (Encounter, Diagnosis, etc.).
- Prefer glob patterns over hard-coded filenames.

### Memory errors
- Process in chunks; avoid concatenating all chunks into one DataFrame.
- Drop unused columns early.
- Consider Parquet or SQLite for intermediate storage.

### CSV parse issues
- Use explicit dtypes where possible.
- Log the chunk filename being processed for quick isolation.

### Output row-count explosions
- Check join keys and join type (inner vs left).
- Add assertions on expected row grain after merges.

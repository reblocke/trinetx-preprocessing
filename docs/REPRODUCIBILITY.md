# Reproducibility

## Environment
- Use `uv` to manage dependencies.
- Commit `pyproject.toml` and `uv.lock`.

## Determinism
- Avoid implicit working-directory dependence.
- Make all I/O paths explicit via config.
- If randomness exists (bootstraps, sampling), use `np.random.default_rng(seed)` and pass `rng`.

## Provenance
For each pipeline run, record:
- git commit hash
- config file used
- package versions (from lockfile)
- start/end timestamps
- row counts per stage

Store provenance in an output-sidecar file (e.g. `Output/provenance.json`).

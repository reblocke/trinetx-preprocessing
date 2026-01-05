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
- stage wall times

Store provenance in an output-sidecar file (e.g. `Output/provenance.json`).

## Profiling
Use the profiling harness to capture performance data without changing outputs:
```bash
./.venv/bin/python -m trinetx_preprocessing profile --config config.yaml \
  --out artifacts/profile
```
The command writes:
- `profile.pstats` and `profile.txt` for cProfile output
- `provenance.json` with stage timings and run timestamps

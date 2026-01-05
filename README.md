# TriNetX Preprocessing Pipeline

This repository refactors the TriNetX hypercapnia preprocessing notebooks into a
deterministic, CLI-driven pipeline. The CLI reads exported CSVs, normalizes each
domain, derives RFS cohorts, and assembles final encounter-level datasets for the
2022 analysis window.

## Quickstart (synthetic fixtures)
```bash
mkdir -p .uv_cache
export UV_CACHE_DIR="$PWD/.uv_cache"
uv sync

cp config.example.yaml config.yaml
mkdir -p artifacts/synthetic_example/work artifacts/synthetic_example/output
./.venv/bin/python -m trinetx_preprocessing validate-config --config config.yaml
./.venv/bin/python -m trinetx_preprocessing run --config config.yaml
```

Or run the helper script that builds a config for you:
```bash
./.venv/bin/python scripts/run_synthetic_example.py --output-root artifacts/synthetic_example
```

Outputs land under `artifacts/synthetic_example/output/`.

## Real data placement (do not commit)
Put raw TriNetX exports under `data/` (git-ignored) and update `config.yaml`:
```
data/
  Encounter/
  Diagnosis/
  Lab Results/
  Medications/
  Procedure/
  Vital Signs/
  Patient/
```
Adjust domain patterns in `config.yaml` if your filenames differ.

## CLI basics
```bash
./.venv/bin/python -m trinetx_preprocessing --help
./.venv/bin/python -m trinetx_preprocessing validate-inputs --config config.yaml
./.venv/bin/python -m trinetx_preprocessing run --config config.yaml
```

## Performance
Profile the pipeline with cProfile and stage timers:
```bash
./.venv/bin/python -m trinetx_preprocessing profile --config config.yaml \
  --out artifacts/profile
```
Use `--strict` with `run` or `profile` to enable guardrail checks for joins and
required identifiers.

## Tests + quality checks
```bash
./.venv/bin/ruff format .
./.venv/bin/ruff check .
./.venv/bin/python -m pytest -q
```

## More docs
- `docs/ONBOARDING.md`: step-by-step setup + legacy notebook notes
- `docs/CONFIG.md`: config file details
- `docs/DATA_CONTRACT.md`: inputs, outputs, and required columns
- `docs/ARCHITECTURE.md`: pipeline structure

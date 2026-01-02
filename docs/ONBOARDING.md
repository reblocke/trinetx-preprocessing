# Onboarding

This guide is for a new collaborator who wants to run the pipeline end-to-end.

## What you need
- Python >= 3.11
- `uv` for dependency management
- Sufficient disk and RAM for your cohort size

## Quickstart (developer)
```bash
uv sync
ruff format
ruff check
pytest -q
```

## Running the pipeline
The long-term goal is a CLI entrypoint, e.g.

```bash
python -m trinetx_preprocessing run --config config.yaml
```

Until the CLI exists, document the current canonical run path here:
- which notebooks or scripts to run
- required order
- expected outputs

## Data placement
- Put real TriNetX exports under `data/` (ignored by git).
- Do not rename columns unless the spec says so.

## First-success checklist
- [ ] You can run tests without `data/`.
- [ ] You can run a small synthetic example end-to-end.
- [ ] You can reproduce baseline outputs on the fixture dataset.

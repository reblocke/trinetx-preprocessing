# SKILL: TriNetX Preprocessing Refactor

## Context
This repository contains a legacy TriNetX preprocessing pipeline (notebook-heavy).
The refactor will produce a Python package + CLI, preserving outputs while improving usability.

## Priorities (in order)
1. Ease of use by others (onboarding, single entrypoint, clear config)
2. Reproducibility (uv lockfile, deterministic runs, provenance)
3. Runtime efficiency (only after profiling; avoid premature optimization)
4. Modularity (extract shared logic; reduce notebook duplication)

## Non-negotiables
- Do not commit raw TriNetX data or row-level extracts.
- Tests must run without `data/`.
- Preserve output semantics; behavior changes require explicit documentation and validation.

## Target end state
- `src/` package with:
  - pure transforms
  - I/O adapters for TriNetX domain tables
  - a CLI entrypoint driven by a config file
- `tests/` with unit + regression coverage
- `docs/` that enables new collaborators to run the pipeline reliably

## Commands
- Format: `ruff format`
- Lint: `ruff check`
- Tests: `pytest -q`

## Canonical docs
- `AGENTS.md`
- `CONTINUITY.md`
- `docs/ARCHITECTURE.md`
- `docs/DATA_CONTRACT.md`
- `docs/DECISIONS.md`

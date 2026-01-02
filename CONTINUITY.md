# CONTINUITY

This file is the compaction-safe continuity ledger for the refactor work.
Keep it short. Facts only. Mark uncertainty as `UNCONFIRMED`.

## Goal (incl. success criteria)
- Refactor the TriNetX preprocessing pipeline into a Python package + CLI while preserving outputs.
- Success means:
  - `pytest` passes
  - regression outputs match baseline on a small synthetic fixture
  - onboarding docs enable a new user to run the pipeline without editing code

## Constraints/Assumptions
- Data exports from TriNetX contain sensitive information and must not be committed.
- Real inputs live under `data/` (git-ignored).
- Use `uv` for dependencies (`pyproject.toml` + `uv.lock`).
- Ruff is the only linter/formatter.

## Key decisions
- UNCONFIRMED: package name (`trinetx_preprocessing` is the default suggestion)
- UNCONFIRMED: primary intermediate format (CSV vs Parquet vs SQLite)

## State
- Done:
- Now:
- Next:

## Open questions
- UNCONFIRMED: exact required output schema(s) for final datasets
- UNCONFIRMED: which legacy notebooks are canonical for ground truth

## Working set (files/ids/commands)
- AGENTS.md
- docs/*

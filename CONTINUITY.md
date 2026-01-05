# CONTINUITY

This file is the compaction-safe continuity ledger for the refactor work.
Keep it short. Facts only. Mark uncertainty as `UNCONFIRMED`.

## Goal (incl. success criteria)
- Milestone 014: profiling harness + performance guardrails (no semantic change).
- Success: profiling command exists, guardrails implemented + tested, docs updated.

## Constraints/Assumptions
- Data exports from TriNetX contain sensitive information and must not be committed.
- Real inputs live under `data/` (git-ignored).
- Use `uv` for dependencies (`pyproject.toml` + `uv.lock`).
- Ruff is the only linter/formatter.
- Do not run on real `data/` unless explicitly required.

## Key decisions
- Package name set to `trinetx_preprocessing` (per milestone prompt).
- UNCONFIRMED: primary intermediate format (CSV vs Parquet vs SQLite)

## State
- Done:
  - Milestone 004: splitter + discovery utilities with tests and docs updates.
  - Milestone 005: chunked CSV I/O helpers + schema validation + CLI header checks.
  - Milestone 006: encounter transforms + stage runner + CLI + tests + docs updates.
  - Milestone 007: lab-results transforms + stage runner + CLI + tests + docs updates.
  - Milestone 008: diagnosis transforms + stage runner + CLI + tests + docs updates.
  - Milestone 009: meds/procedure/vitals transforms + stage runners + CLI + tests + docs updates.
  - Milestone 010: RFS transforms + stage runner + CLI + tests + docs updates.
  - Ruff import ordering fixes applied; `ruff format` clean.
  - Implemented final assembly stage + full `run` orchestration.
  - Added per-category `RFS_<RFS>.csv` outputs in RFS stage.
  - Added end-to-end synthetic `run` pytest coverage.
  - Updated `docs/ONBOARDING.md`, `docs/DATA_CONTRACT.md`, `docs/DECISIONS.md`.
  - Added regression hashing utilities and hash manifest helpers.
  - Added CLI `baseline` and `compare` commands.
  - Updated regression workflow docs and privacy warning.
  - Added regression hashing unit tests.
  - Added `README.md` quickstart and refreshed `README.txt` legacy note.
  - Added synthetic example script under `scripts/`.
  - Updated `docs/ONBOARDING.md`, `docs/CONFIG.md`, `docs/ARCHITECTURE.md`, `docs/DATA_CONTRACT.md`.
  - Updated `config.example.yaml` for synthetic artifacts output.
  - Expanded CLI help text + examples.
  - `uv sync` failed (uv panic: system-configuration NULL object).
  - `./.venv/bin/ruff format .` completed.
  - `./.venv/bin/ruff check .` passed.
  - `./.venv/bin/python -m pytest -q` passed (39 tests).
  - `./.venv/bin/python -m trinetx_preprocessing --help` succeeded.
  - Milestone 014: profiling harness + guardrails + docs + tests.
  - `uv sync` failed (uv panic: system-configuration NULL object).
  - `./.venv/bin/ruff format .` completed.
  - `./.venv/bin/ruff check .` passed.
  - `./.venv/bin/python -m pytest -q` passed (45 tests).
  - `./.venv/bin/python -m trinetx_preprocessing profile --help` succeeded.
- Now: milestone 014 complete.
- Next: (end)

## Open questions
- UNCONFIRMED: exact required output schema(s) for final datasets.
- UNCONFIRMED: raw filename mismatch for labs/meds (`lab_result.csv` vs `lab_results*.csv`, `medication_ingredient.csv` vs `medication*.csv`).
- UNCONFIRMED: output directory casing (`Output` in README vs `output` in notebooks).
- UNCONFIRMED: when data checks should run relative to final dataset generation.

## Working set (files/ids/commands)
- `src/trinetx_preprocessing/profiling.py`
- `src/trinetx_preprocessing/guardrails.py`
- `src/trinetx_preprocessing/pipeline/run.py`
- `src/trinetx_preprocessing/pipeline/final_assembly.py`
- `src/trinetx_preprocessing/cli.py`
- `docs/REPRODUCIBILITY.md`
- `docs/DECISIONS.md`
- `README.md`

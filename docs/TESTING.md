# Testing

## Goals
- Make correctness cheap to verify.
- Guard against silent behavior change during refactor.
- Keep tests free of confidential data.

## Test tiers
1. Unit tests: pure transforms
2. Regression tests: fixture-based output equivalence
3. (Optional) Integration tests: end-to-end on synthetic mini-cohort

## Commands
```bash
ruff format
ruff check
pytest -q
python -m trinetx_preprocessing --help
```

## Fixtures
- Put only synthetic or de-identified fixtures under `tests/fixtures/`.
- Prefer tiny tables that still exercise edge cases (missing values, duplicates, etc.).

## Regression strategy (recommended)
- Snapshot key outputs (or hashes) from the legacy pipeline on a fixture dataset.
- In CI/local runs, regenerate outputs from the refactored pipeline and compare.

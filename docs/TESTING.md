# Testing

## Goals
- Make correctness cheap to verify.
- Guard against silent behavior change during refactor.
- Keep tests free of confidential data.

## Test tiers
1. Unit tests: pure transforms
2. Regression tests: fixture-based output equivalence
3. Integration tests: end-to-end on synthetic mini-cohort in default CSV mode
   and chunked Parquet intermediate mode, including `run`, `baseline`,
   `compare`, and `profile` command paths

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
- For real-data golden-master validation, hash approved local legacy outputs with
  `hash-outputs --scope final --hash-chunk-rows 100000`, hash refactor outputs
  the same way, and compare with `compare-manifests --report`. Summarize the
  gate with `validation-status` and save JSON/Markdown reports under the
  private external validation root. Do not commit row-level outputs or
  unreviewed manifests.
- `validation-status` remains the strict historical-parity gate. Milestone 2's
  corrected release evidence is the explicit exception documented in
  `docs/VALIDATION.md`; it does not claim a ready strict status while source
  encounter-setting conflicts remain unadjudicated.

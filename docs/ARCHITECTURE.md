# Architecture

## Design goals
- Preserve semantics of the legacy pipeline.
- Provide a single, documented entrypoint (CLI).
- Keep the computational core pure and testable.
- Isolate I/O, configuration, and orchestration.

## Proposed structure
- `src/trinetx_preprocessing/`
  - `config.py` (load/validate config)
  - `io/` (read/write TriNetX domain files)
  - `transform/` (pure transforms; pandas-in, pandas-out)
  - `pipeline/` (orchestration: stage execution, caching)
  - `cli.py` (argument parsing, logging)
- `tests/`
  - unit tests for transforms
  - regression tests for output equivalence on synthetic fixtures
- `notebooks/legacy/` (archived, canonical references)

## Pipeline stages (conceptual)
1. Ingest / discover input files
2. Split or stream-read large CSVs
3. Domain transforms (encounter, diagnosis, labs, meds, procedures, vitals)
4. RFS derivation (reasons-for-suspicion)
5. Final dataset assembly and export
6. Validation summaries

## Observability
- Use structured logging.
- Emit per-stage row counts and key integrity checks.

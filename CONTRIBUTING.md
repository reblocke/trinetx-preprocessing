# Contributing

## Ground rules
- Follow `AGENTS.md` (style, tools, reproducibility, testing).
- Do **not** commit raw TriNetX exports or row-level patient data.
- Prefer small, reviewable pull requests.

## Development setup
1. Install `uv` (Python package manager).
2. Create and sync the environment:
   ```bash
   uv sync
   ```
3. Run checks:
   ```bash
   ruff format
   ruff check
   pytest -q
   ```

## Branching and commits
- Branch from `main` (or a designated refactor branch).
- One logical change per commit.
- Commit messages should describe the user-visible intent.

## Testing expectations
- Unit tests for all new/changed functions.
- Regression tests guard “no behavior change” for core pipeline outputs.
- Tests must run without access to `data/` (use `tests/fixtures/`).

## Documentation expectations
- If behavior changes, update `docs/SPEC.md` and record rationale in `docs/DECISIONS.md`.

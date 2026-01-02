# AGENTS.md

## Project overview
- This repository is a **Python-first** project for statistical programming, experimental analysis, and scientific computing.
- The primary language is **Python**. Do not propose implementations in R, Julia, or SQL unless explicitly asked.
- Priorities (in order):
  1) **Human time**: readability, maintainability, debuggability
  2) **Reproducibility**: deterministic runs, stable environments
  3) **Performance**: only when needed and measured

## Project-specific overlays: TriNetX preprocessing
- The pipeline may touch **confidential clinical export data**. Treat all raw TriNetX exports as sensitive:
  - Never commit raw data or row-level extracts.
  - Keep all real inputs under `data/` (git-ignored).
  - Tests must use **synthetic** or de-identified fixtures under `tests/fixtures/`.
- Primary refactor goal: preserve **outputs and inclusion logic** while improving:
  - onboarding and ease-of-use (first)
  - reproducibility (second)
  - performance (third, only when measured)
  - modularity (fourth)
- Preserve legacy notebooks by moving them (if needed) to `notebooks/legacy/` rather than deleting.
  New logic should live under `src/` and be callable from a CLI.


## Continuity Ledger (compaction-safe; recommended)
Maintain a single Continuity Ledger for this workspace in `CONTINUITY.md` (or `http://CONTINUITY.md` if your environment uses that mapping).

The ledger is the canonical session briefing designed to survive context compaction; do not rely on earlier chat text unless it’s reflected in the ledger.

### How it works
- At the start of every assistant turn: read `http://CONTINUITY.md`, update it to reflect the latest goal/constraints/decisions/state, then proceed.
- Update `http://CONTINUITY.md` again whenever any of these change: goal, constraints/assumptions, key decisions, progress state (Done/Now/Next), or important tool outcomes.
- Keep it short and stable: facts only, no transcripts. Prefer bullets.
- Mark uncertainty as `UNCONFIRMED` (never guess).

### `functions.update_plan` vs the Ledger
- Use `functions.update_plan` only for short-term execution scaffolding (a small 3–7 step plan).
- Use `http://CONTINUITY.md` for long-running continuity across compaction (the “what/why/current state”), not a step-by-step task list.

### In replies
- Begin with a brief **Ledger Snapshot** (Goal + Now/Next + Open Questions).
- Print the full ledger only when it materially changes or when the user asks.

### `http://CONTINUITY.md` format (keep headings)
- Goal (incl. success criteria):
- Constraints/Assumptions:
- Key decisions:
- State:
- Done:
- Now:
- Next:
- Open questions (UNCONFIRMED if needed):
- Working set (files/ids/commands):

## Authority hierarchy (resolve conflicts in this order)
1) The study protocol / analysis plan / primary papers and domain requirements (if applicable)
2) Repository docs: `README.md`, `docs/SPEC.md`, `docs/DECISIONS.md`, and this `AGENTS.md`
3) Existing code and notebooks (reference only)

When lower-level code conflicts with higher-level requirements:
- implement the higher-level requirement,
- document the divergence (and why) in `docs/DECISIONS.md` with file/line references.

## Non-negotiables (keep updated)
Use this section to list hard constraints the assistant must not violate (and update it as the project evolves). Examples:
- fixed dataset contract (required columns, units, and encoding)
- required reporting conventions (tables, figures, rounding, labels)
- approved modeling approach(es) and diagnostics
- performance or memory ceilings in production

If this section is empty or ambiguous, default to: correctness → clarity → reproducibility → measured optimization.

## Environment
- Python ≥ 3.11 on macOS/Linux (use the repo’s pinned version if specified in `pyproject.toml`).
- Dependency management uses **uv** (`pyproject.toml` + `uv.lock`).
  - Commit `pyproject.toml` and `uv.lock`.
  - Do **not** add `pip install ...` / `conda install ...` commands to committed code (scripts, modules, notebooks).
  - If dependencies must change, propose the `pyproject.toml` edits and the corresponding uv workflow needed to update the lockfile.
- Code quality uses **Ruff only**:
  - Formatting: `ruff format`
  - Linting: `ruff check` (use `--fix` when appropriate)
  - Do not introduce Black, isort, flake8, pylint, or additional formatters/linters.
- Jupyter is allowed.

## Repository structure and design
- Prefer a **src layout** for importable code:
  - `src/<package_name>/...`
  - `tests/...`
  - optional: `notebooks/`, `scripts/`, `docs/`, `artifacts/`
- Keep the computational core **pure** (no I/O, no hidden state). Isolate I/O in dedicated modules (e.g., `io.py`, `data.py`).
- Follow “functional core, imperative shell”:
  - pure functions for transforms/statistics/models
  - thin orchestration layer for reading/writing, CLI, notebook glue

## Coding style (human-centered)
- **Clarity beats cleverness.** Optimize for the next reader (often future-you).
- Prefer **deep modules** over shallow wrappers:
  - simple interface (few arguments, sensible defaults)
  - hide complexity behind well-named functions/classes
- Avoid deep nesting:
  - use guard clauses / early returns
  - keep control flow flat and readable
- Use meaningful names:
  - descriptive is good (even if long)
  - avoid single-letter names outside tight mathematical contexts
- Limit function arguments:
  - if a function needs >5 parameters, consider:
    - a dataclass/typed config object
    - grouping related parameters into a single structure
    - splitting responsibilities
- Prefer explicit data flow:
  - no hidden global state
  - no reliance on implicit working directory
  - pass dependencies explicitly
- Imports:
  - avoid `from x import *`
  - avoid heavy imports inside tight loops unless profiling supports it
  - standard library first; third-party next; local imports last
- Use docstrings for public functions/classes:
  - what the function does
  - inputs/outputs (units, shapes, dtypes)
  - important assumptions and edge cases
- Use type hints for public APIs and cross-module boundaries.

## Code delivery in assistant responses
- Provide **paste-ready** code blocks: complete imports, functions, and example usage.
- Prefer stable, widely used packages over custom implementations of standard methods.
- If changes span multiple files, show a clear file-by-file patch or the full new file contents.
- If you’re unsure about a project choice, make the smallest safe assumption and flag it explicitly as `UNCONFIRMED`.

## Data manipulation and I/O
- Use `pandas` for tabular work, `numpy` for arrays, and `scipy` where appropriate.
- Prefer vectorized operations over row-wise Python loops.
  - Avoid `df.apply(..., axis=1)` and `iterrows()` unless there is a clear, documented need.
- Avoid chained assignment in pandas; use `.loc[...]`.
- Use `pathlib.Path` for paths.
  - Never hard-code absolute paths.
  - Do not change the global working directory in committed code (`os.chdir`).
- Validate inputs at boundaries:
  - schema/columns, dtypes, ranges, units
  - fail fast with informative error messages
- Prefer stable intermediate data formats for derived artifacts (often Parquet for tables) when appropriate.

## Reproducibility
- All examples must run from a fresh Python session.
- Always show required imports in examples.
- Randomness:
  - Prefer `rng = np.random.default_rng(1234)` and pass `rng` explicitly.
  - For libraries with their own RNG controls, set seeds explicitly and document where.
- Avoid manual, non-reproducible steps. If something changes data, it should be executable code.

## Notebooks and Quarto
- Jupyter notebooks (`.ipynb`) are allowed for exploration and reporting.
- Notebooks should be restartable and deterministic:
  - “Restart & Run All” should succeed without hidden state.
  - move heavy logic into importable modules under `src/`.
- If Quarto (`.qmd`) is used:
  - label chunks clearly
  - keep reports narrative; keep heavy lifting in modules

## Modeling
Choose tools that match the inferential goal:
- Classical/statistical inference: `statsmodels` (including formula interfaces when helpful)
- Predictive modeling / ML: `scikit-learn` (pipelines, CV, proper train/test splits)
- Bayesian modeling: **PyMC + ArviZ**

General modeling expectations:
- State the estimand and assumptions.
- Include basic diagnostics appropriate to the model class.
  - e.g., residual checks, convergence checks, calibration/leakage checks
- Prefer returning tidy/tabular outputs (`pandas.DataFrame`) with clear column names and metadata.

## Visualization
- Prefer `matplotlib` for publication-quality plots.
- Every plot should:
  - label axes and units
  - include a clear title/caption
  - avoid misleading scales
  - be generated from deterministic code

## Performance and optimization
- Default stance: **do not optimize prematurely**. Write correct, clear code first.
- If performance matters:
  - profile to find bottlenecks
  - optimize the bottleneck (not everything)
  - benchmark before/after to confirm improvement
  - stop when it’s “fast enough” (avoid over-optimization)
- Prefer algorithmic and data-structure improvements over micro-optimizations.
- Use vectorization and compiled backends (NumPy/SciPy) where appropriate.
- Consider parallelization only when tasks are independent and I/O won’t bottleneck.
- Introduce heavier tools (Numba/Cython/custom C/C++) only after profiling and with tests.

## Tests and checks
- Use `pytest` for unit tests under `tests/`.
- When creating/modifying functions, add or update tests and state how to run them (e.g., `pytest -q`).
- Use small, de-identified fixtures (or synthetic data) under `tests/fixtures/`.

## Milestone discipline and definition of done (recommended)
Every milestone should end with:
- tests passing locally (`pytest`)
- artifacts updated under `artifacts/` (small tables/figures/markdown summaries), if outputs changed
- documentation updated (`README.md` / `docs/DECISIONS.md`) if behavior or assumptions changed
- a commit with a clear message is ready to be made

## What not to do
- Do not add interactive-only calls to pipelines (`breakpoint()`, `pdb.set_trace()`, `input()`).
- Do not introduce hidden global state or non-determinism without clear explanation.
- Do not restructure the project into new orchestration frameworks (Kedro/Dagster/Prefect/etc.) unless explicitly asked.
- Do not commit secrets, credentials, patient identifiers, or large raw extracts.

# Repository Inventory

Use this inventory to distinguish current contracts and runtime code from
migration references and historical refactor material. Start with
`docs/CURRENT_STATE.md` for the current delivery and blocker status.

## Top-level control surfaces

- `README.md` — primary human overview, quickstart, and supported commands.
- `AGENTS.md` — authoritative contributor/agent guardrails and current
  architecture invariants.
- `CONTINUITY.md` — short-lived, compaction-safe ledger for the active task; it
  is not a product contract or permanent evidence record.
- `llms.txt` — compact public orientation for machine readers; it supplements,
  but never replaces, `AGENTS.md`.
- `config.example.yaml` — public synthetic configuration example. Local
  `config.yaml` is ignored.
- `pyproject.toml` and `uv.lock` — package metadata and reproducible dependency
  lock.

## Current runtime implementation

- `src/trinetx_preprocessing/cli.py` — CLI for config/input validation, staged
  and full preprocessing, canonical database publication/inspection,
  compatibility export, cohort-source validation, profiling, comparison, and
  cleanup.
- `src/trinetx_preprocessing/config.py`, `storage.py`, `work_manifest.py`,
  `filesystem.py`, `guardrails.py`, and `validation.py` — configuration,
  bounded CSV/Parquet storage, resumability/provenance, safe publication and
  cleanup, join guardrails, and schema checks.
- `src/trinetx_preprocessing/pipeline/` — shared domain transforms, RFS logic,
  historical Hypercapnia-compatible assembly, and 36-file CSV payload used by
  the canonical build and Stata bridge.
- `src/trinetx_preprocessing/transform/` and `io/` — pure transformations and
  bounded I/O primitives.
- `src/trinetx_preprocessing/regression.py` and `profiling.py` — normalized
  output manifests, comparisons, resource profiles, and PHI-safe provenance.

## Canonical combined product and consumer contract

- `src/trinetx_preprocessing/combined_preprocessing/builder.py` — atomic
  orchestration/publication of the canonical manifest-bound
  `trinetx_preprocessed.duckdb` and optional 36-CSV compatibility bridge.
- `src/trinetx_preprocessing/combined_preprocessing/traditional_catalog.py` and
  `elements.py` — one catalog joining traditional and GLP-1 source candidates.
  Membership denotes source candidacy, never cohort inclusion.
- `src/trinetx_preprocessing/combined_preprocessing/cohort_source_contract.py`
  — versioned public table schemas and schema fingerprint.
- `src/trinetx_preprocessing/combined_preprocessing/cohort_source.py` — current
  read-only consumer API: `validate_cohort_source()` and
  `open_cohort_source()`.
- `src/trinetx_preprocessing/combined_preprocessing/database.py` and
  `contract.py` — bounded DuckDB sessions, manifest/catalog binding, product
  metadata, and database contract.
- `src/trinetx_preprocessing/combined_preprocessing/validation.py`,
  `evidence.py`, and `scratch.py` — product validation, aggregate evidence, and
  owned-scratch lifecycle.
- `src/trinetx_preprocessing/combined_preprocessing/glp1_adapter.py` —
  migration-only adapter used to compare the canonical source with the
  standalone GLP-1 path. It is not the intended permanent GLP-1 workflow.

The source contract intentionally stops before cohort construction. No
downstream cohort-selection, phenotype, imputation, or analysis code has been
imported yet.

## Migration and historical references

- `src/trinetx_preprocessing/glp1_eligibility/` — standalone GLP-1 ingestion,
  cohort, phenotype, evidence, and output implementation retained as a parity
  reference while migration is incomplete; it is not a second canonical source
  product.
- `Hypercapnia*.ipynb` and `Executed Notebooks/` — historical notebooks kept for
  provenance and behavior comparison, not current implementation guidance.
- `README.txt` — legacy pipeline notes retained for historical context.
- `docs/prompts/` — archived task prompts that explain the refactor sequence;
  they must not be replayed as current machine instructions.

## Active documentation roles

- `docs/CURRENT_STATE.md` — delivered/reference/pending/blocked status and the
  restart criteria for downstream cohort migration.
- `docs/SPEC.md` — authoritative corrected analytic contract.
- `docs/ARCHITECTURE.md`, `docs/UNIFIED_PREPROCESSING.md`, and
  `docs/DATA_CONTRACT.md` — architecture, canonical product, table grain, and
  data contracts.
- `docs/VALIDATION.md`, `docs/REPRODUCIBILITY.md`, and `docs/TESTING.md` —
  evidence classes, parity gates, reproducible runs, and test expectations.
- `docs/GLP1_DATA_CONTRACT.md`, `docs/GLP1_ELIGIBILITY.md`,
  `docs/GLP1_MIGRATION.md`, and `docs/GLP1_PHENOTYPES.md` — active GLP-1
  reference contracts and migration boundary; they do not make the standalone
  package permanent.
- `docs/CONFIG.md`, `docs/ONBOARDING.md`, `docs/SECURITY_PRIVACY.md`,
  `docs/TROUBLESHOOTING.md`, and `docs/GLOSSARY.md` — operational guidance.
- `docs/DECISIONS.md` — durable architecture/semantic decisions and accepted
  divergences. `docs/PLAN.md` is the roadmap, not proof of completion.
- `docs/CODEX_WORKFLOW.md` — model-agnostic code-agent execution and evidence
  rules.

## Tests and validation boundary

- `tests/test_*.py` — pytest coverage for CLI/config, transforms and stages,
  storage/lifecycle safety, combined publication, unified catalog behavior,
  cohort-source validation, and synthetic GLP-1 adapter parity.
- `tests/fixtures/` — synthetic/de-identified fixtures only.
- Repository gate: `git diff --check`, `uv run ruff check .`,
  `uv run ruff format --check .`, `uv lock --check`, and `uv run pytest -q`.

Passing public tests does not establish private full-data Stata or standalone-
adapter parity. Those frozen-head gates remain external and pending.

## Private and generated-data boundary

Raw TriNetX exports, real-data DuckDB/CSV products, row-level extracts, logs,
manifests, profiles, and spill must remain untracked and outside the repository.
Repository-local and symlinked output/spill locations are unsafe. Cleanup must
remain restricted to explicitly owned scratch prefixes; never recursively
remove an unmanaged path.

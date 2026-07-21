# Repo Inventory

## Top-level layout
- `README.md` - primary user-facing quickstart, validation, and testing guide.
- `AGENTS.md` - contributor and agent guardrails for public, clinical-data-safe work.
- `CONTINUITY.md` - compaction-safe ledger for the current refactor effort.
- `llms.txt` - compact public index for LLM/code-agent readers; reviewed as documentation, not as a replacement for `AGENTS.md`.
- `config.example.yaml` - synthetic/example config; local `config.yaml` is ignored.
- `pyproject.toml` and `uv.lock` - Python package metadata and locked dependencies.
- `README.txt` - legacy pipeline notes, updated to route splitting through the supported Python CLI.
- `Hypercapnia*.ipynb` and `Executed Notebooks/` - historical notebooks retained as canonical references.

## Refactor implementation
- `src/trinetx_preprocessing/cli.py` - CLI entrypoint for validation, stage runs, profiling, hashing, comparison, and cleanup.
- `src/trinetx_preprocessing/config.py` - YAML config loading, validation, and input-domain inspection.
- `src/trinetx_preprocessing/storage.py` - CSV/Parquet work-table helpers and bounded partition stores.
- `src/trinetx_preprocessing/work_manifest.py` - fail-closed intermediate compatibility and stage-completion manifest.
- `src/trinetx_preprocessing/regression.py` - normalized hashing, manifests, and manifest comparison.
- `src/trinetx_preprocessing/profiling.py` - strict profile runner and provenance writer.
- `src/trinetx_preprocessing/pipeline/` - stage orchestration for raw domains, RFS, final assembly, and full pipeline runs.
- `src/trinetx_preprocessing/transform/` - pure transform logic and shared code-group splitting.
- `src/trinetx_preprocessing/io/`, `tools/`, `filesystem.py`, `guardrails.py`, and `validation.py` - bounded I/O, utility commands, strict cleanup, join guardrails, and schema checks.

## Tests and fixtures
- `tests/test_*.py` - pytest coverage for config, CLI workflows, transforms, stages, storage, hashing, profiling, and guardrails.
- `tests/fixtures/` - synthetic/de-identified fixtures only.
- Full local gate: `git diff --check`, `./.venv/bin/ruff check .`, and `./.venv/bin/python -m pytest -q`.

## Documentation
- `docs/PLAN.md` - final refactor completion plan.
- `docs/VALIDATION.md` - golden-master parity workflow and current validation status.
- `docs/DATA_CONTRACT.md` - configured inputs, intermediate contracts, and final output layout.
- `docs/REPRODUCIBILITY.md` - environment, profile, manifest, and evidence requirements.
- `docs/DECISIONS.md` - historical and refactor implementation decisions.
- `docs/CONFIG.md`, `docs/ONBOARDING.md`, `docs/TESTING.md`, `docs/ARCHITECTURE.md`, `docs/SECURITY_PRIVACY.md`, `docs/TROUBLESHOOTING.md`, and `docs/GLOSSARY.md` - supporting operational docs.
- `docs/prompts/` - historical Codex prompt scaffolding; not runtime implementation.

## Private and generated data boundaries
- Raw TriNetX exports, real-data work/output trees, logs, manifests, profile outputs, and row-level extracts must remain untracked.
- Real-data validation currently belongs under `/Volumes/LOCKE BOOK/trinetx-preprocessing-validation`, not the repository.
- Known local/generated artifacts are ignored, including `.DS_Store`, AppleDouble sidecars, `config.yaml`, `artifacts/`, `logs/`, `profile/`, `manifests/`, `work/`, `output/`, and generated zip archives.

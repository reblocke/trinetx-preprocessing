# CONTINUITY

## Goal (incl. success criteria)
- Deliver post-Milestone 1 package `0.2.0` with corrected cohort and feature semantics, bounded external-memory execution, and substantially faster final assembly.
- Success requires the corrected clinical invariants, 36-file/534-column public output contract, local and staged tests, a fresh strict BOOK profile, aggregate-only delta evidence, and clean review/release gates.

## Constraints/Assumptions
- `refactor-milestone-1` is immutable and remains the historical-replication fallback.
- Raw TriNetX data, row-level extracts, logs, manifests, profiles, and validation outputs remain external and untracked.
- Full evidence uses `/Volumes/LOCKE BOOK/trinetx-preprocessing-validation`; keep at least 100 GiB free and peak RSS at or below 6,238 MB.
- Corrected behavior supersedes known notebook quirks. The final CSV names and 534-column schema remain stable.
- Python, `uv`, Ruff, pytest, Parquet intermediates, and external-drive scratch remain the supported toolchain.

## Key decisions
- ABG is arterial LOINC `2019-8`/`32771-8`; VBG is venous LOINC `2021-4`; both require `45 < PCO2 < 200` mmHg after recognized unit conversion.
- Specimen-unspecified `11557-6` and total CO2 `2026-3` do not define ABG/VBG cohorts.
- Cohort events are selected independently per RFS category, setting, and patient.
- `AFTER` requires encounter-level diagnosis or lab availability derived by the pipeline.
- Code matching uses typed exact/prefix rules. Numeric inclusion uses `float64` before output downcasts.
- Existing work tables are not reusable after the corrected intermediate schema is introduced.

## State
- Branch: `codex/refactor-post-milestone-1`; review candidate `a96c899` is pushed on PR #5.
- Baseline BOOK profile: final assembly `161,763.975 s`, total `281,840.675 s`, peak RSS `6,238.062 MB`.
- Milestone 1 evidence remains external; post-Milestone 1 semantic date fixes have 203 passing tests and a clean Codex review.
- Corrected behavior is implemented through typed rules, retained metadata, deterministic reducers, derived data screening, encounter-conflict handling, partitioned Parquet stores, fail-closed work manifests, and bucket-oriented final assembly.
- Compact RFS and lab-feature indexes are built during domain streaming. The manifest now records runtime versions, row counts, artifact fingerprints, and running/completed state.
- Full local gate passes: `git diff --check`, Ruff, and `226` pytest tests.
- Corrected external tiers 00, 01, and 02 pass all 36-file/534-column, identifier, age/date, screening, and compact-index invariants under `corrected_v0.2.0/`.
- Tier-02 final assembly improved from `66.405 s` to `31.787 s` after removing redundant bucket-local scratch; peak RSS was `219.188 MB`.

## Done
- Historical replication accepted at `99.998708%` aggregate exact-row parity and tagged `refactor-milestone-1`.
- Corrected post-milestone prior-date, procedure first/last, and previous-vital fixes are committed and reviewed.
- Legacy audit identified gas-code/threshold, predisposition-regex, setting-selection, data-screen, J46, TTE, numeric-boundary, encounter-conflict, and nondeterministic feature-reduction defects.

## Now
- Package version is being finalized at `0.2.0`; GitHub Codex review is requested and pending.

## Next
- Run the fresh full BOOK profile and aggregate Milestone 1 delta audit.
- Address any GitHub review findings, then publish `v0.2.0`.

## Open questions (UNCONFIRMED if needed)
- None blocking; the approved implementation plan locks defaults.

## Working set (files/ids/commands)
- `docs/SPEC.md`, `docs/DECISIONS.md`, `config.example.yaml`
- `src/trinetx_preprocessing/config.py`, `transform/`, `pipeline/`, `storage.py`, `work_manifest.py`
- `git diff --check`; `./.venv/bin/ruff check .`; external-TMP full `pytest -q`
- `/Volumes/LOCKE BOOK/trinetx-preprocessing-validation/profile/provenance.json`

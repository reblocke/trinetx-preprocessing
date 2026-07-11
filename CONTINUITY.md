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
- Branch: `codex/refactor-post-milestone-1`; screening-performance fix `b5ebc38` is pushed on PR #5.
- Baseline BOOK profile: final assembly `161,763.975 s`, total `281,840.675 s`, peak RSS `6,238.062 MB`.
- Milestone 1 evidence remains external; post-Milestone 1 semantic date fixes have 203 passing tests and a clean Codex review.
- Corrected behavior is implemented through typed rules, retained metadata, deterministic reducers, derived data screening, encounter-conflict handling, partitioned Parquet stores, fail-closed work manifests, and bucket-oriented final assembly.
- Compact RFS and lab-feature indexes are built during domain streaming. The manifest now records runtime versions, row counts, artifact fingerprints, and running/completed state.
- Full local gate passes: `git diff --check`, Ruff, and `228` pytest tests.
- Corrected external tiers 00, 01, and 02 pass all 36-file/534-column, identifier, age/date, screening, and compact-index invariants under `corrected_v0.2.0/`.
- Tier-02 final assembly improved from `66.405 s` to `31.787 s` after removing redundant bucket-local scratch; peak RSS was `219.188 MB`.
- The first full corrected profile attempt read `592,125,331` encounter rows in about 17 minutes, then exposed an unbounded Python-callback cost in encounter conflict summarization and was stopped cleanly before downstream stages.
- The vectorized replacement summarized all 128 retained full-scale encounter partitions in `87.526 s` and found `286` cross-setting encounter IDs (`275` EMER+IMP, `8` AMB+IMP, `3` AMB+EMER).
- The second full attempt completed encounter in `1,499.39 s`, then exposed lab classification repeating precision/string conversion over every chunk once per feature rule; it was stopped early in labs.
- On a real 250,000-row lab chunk, match-first classification reduced runtime from `3.166 s` to `0.200 s` (`15.84x`) with exact feature-frame equality.
- Corrected tiers 00, 01, and 02 pass again after the lab optimization with unchanged before/after row contracts and peak RSS at or below `223 MB`.
- The third full attempt reached labs after a `1,415.21 s` encounter stage, then confirmed complete normalized domain copies were still written despite compact-index execution; it was stopped before further redundant I/O.
- Intermediate schema `5` makes complete normalized domain tables opt-in. Tiers 00, 01, and 02 pass with unchanged final row contracts, no `*_NEW_*` work files, and peak RSS below `220 MB`.
- Full profile attempt four completed every raw-domain scan exactly once and completed RFS, then exposed repeated encounter-screen partition reads inside patient-bucket final enrichment. The run was stopped with `SIGTERM` after the first bucket established a projected final-assembly miss; completed work tables and diagnostic evidence were preserved.
- Data-screen eligibility is now computed once per category/setting before patient bucketing and reused during `AFTER` writes. Focused tests and Ruff pass.
- `clean-scratch` now recognizes all current partition-store prefixes. It inventoried and deleted seven attempt-four final-assembly scratch roots totaling `35,650,393,292` bytes, then rechecked clean.
- Full local gates pass with `233` tests. Corrected tiers 00, 01, and 02 pass from work-manifest schema `3` with unchanged 36-file/534-column contracts and before/after row counts; tier-02 final assembly completed in `34.969 s` with `218.422 MB` peak RSS.
- The standalone full-scale final-assembly benchmark from `b5ebc38` indexed `2,375,800,669` compact feature rows once and reused precomputed screening across all 18 cohort/setting outputs.
- The standalone benchmark completed all `256` patient buckets and `36` outputs in about `21,445 s` (`5h57m`), an `86.7%` reduction from the `161,763.975 s` baseline; it left zero recognized scratch roots.
- GitHub PR #5 review found one current provenance gap: legacy data-screen CSVs were not manifest inputs. Commit `632bba1` requires and fingerprints both files under work-manifest schema `3`; all five review threads are resolved.
- Final feature logic is now decomposed into a 167-line orchestrator, a shared reducer module, and dedicated vital/lab/diagnosis/procedure/medication modules; the 1,408-line final assembly retains cohort, lookup, screening, and output responsibilities. Focused tests pass without output-semantic changes.
- Full local gates pass after the module extraction. Corrected tiers 00, 01, and 02 pass; tier 02 retained 36 tables and 51/51 rows with `37.877 s` final assembly and `218.047 MB` peak RSS.

## Done
- Historical replication accepted at `99.998708%` aggregate exact-row parity and tagged `refactor-milestone-1`.
- Corrected post-milestone prior-date, procedure first/last, and previous-vital fixes are committed and reviewed.
- Legacy audit identified gas-code/threshold, predisposition-regex, setting-selection, data-screen, J46, TTE, numeric-boundary, encounter-conflict, and nondeterministic feature-reduction defects.

## Now
- Archive the completed standalone diagnostic evidence and launch a clean full corrected profile from source commit `e51e743`.

## Next
- Run a fresh full profile from the reviewed code state using the external aggregate-only monitor.
- Validate the completed 36-file/534-column output contract, provenance, scratch cleanup, resource use, and compact-index scan evidence.
- Produce the external aggregate-only delta report, run a holistic local review, and refresh documentation/release readiness. Strict acceptance remains blocked by `286` source encounter-setting conflicts; fresh GitHub Codex review is blocked by the current account review quota.

## Open questions (UNCONFIRMED if needed)
- Whether release acceptance may use the documented deterministic non-strict resolution for the `286` source conflicts, or requires upstream conflict adjudication before a strict profile can pass.

## Working set (files/ids/commands)
- `docs/SPEC.md`, `docs/DECISIONS.md`, `config.example.yaml`
- `src/trinetx_preprocessing/config.py`, `transform/`, `pipeline/`, `storage.py`, `work_manifest.py`
- `git diff --check`; `./.venv/bin/ruff check .`; external-TMP full `pytest -q`
- `/Volumes/LOCKE BOOK/trinetx-preprocessing-validation/profile/provenance.json`

# CONTINUITY

## Goal (incl. success criteria)
- Publish the reviewed corrected pipeline as immutable `refactor-milestone-2` / `v0.2.0`, then begin the supplied GLP-1 implementation ticket on a new post-milestone branch.
- Milestone 2 success requires the corrected clinical invariants, 36-file/534-column public output contract, local and staged tests, fresh BOOK profile, aggregate-only delta evidence, explicit conflict policy, clean review, tags, and GitHub release.
- GLP-1 work must augment the existing database creation only; existing outputs and behavior remain intact unless the ticket explicitly adds versioned fields or artifacts.
- Current turn: implement all 13 release-relevant GLP-1 findings, verify them locally and synthetically, then obtain clean PR review before any private full build.

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
- Milestone 2 accepts deterministic non-strict resolution for the 286 source encounter-setting conflicts; strict execution remains fail-closed.
- `refactor-milestone-1` remains unchanged, and GLP-1 work starts only after the Milestone 2 fallback is durable on GitHub.

## State
- Branch: `codex/glp1-augmentation`, created from Milestone 2 merge commit `e3d62de`; it tracks `origin/codex/glp1-augmentation`.
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
- The first clean full corrected profile completed in `54,513.44 s`; final assembly took `29,459.945 s`, all 36 outputs were written, and scratch cleaned to zero. Time gates passed, but provenance peak RSS was `10,125.734 MB`, above the `6,238 MB` gate.
- One-second 512-bucket follow-up sampling isolated a `6,884.250 MB` pre-feature peak from concatenating all `8,456,198` predisposition event candidates. The failed diagnostic was stopped cleanly and seven scratch roots (`13.44 GB`) were inventoried/deleted.
- Final event partitions now stream into the patient cohort index, with global earliest-patient reduction inside each bucket. Full local gates pass with `234` tests; tiers 00/01/02 pass unchanged with peak RSS at or below `219.031 MB`.
- The first unbatched streaming diagnostic held peak RSS to `2,849.906 MB` but remained in ABG after 90 minutes because each reduced partition triggered separate setting joins; it was stopped cleanly and its scratch removed.
- Reduced event partitions now form bounded one-million-row setting-join batches. Full local gates pass with `235` tests; tiers 00/01/02 pass unchanged, with tier-02 final assembly `33.725 s` and `219.000 MB` peak RSS.
- The batched 512-bucket diagnostic restored cohort throughput and held cohort peak RSS below `3,490 MB`, but feature indexing reached `7,017.828 MB` because open Parquet-writer memory scales with bucket count. It was stopped and cleaned; 512 buckets are rejected.
- At 256 buckets, `FinalFeatureBucket` now retains one generic partition plus source position arrays and materializes requested columns on demand. Full local gates pass with `236` tests; tiers 00/01/02 pass unchanged, with tier-02 final assembly `30.510 s` and `218.266 MB` peak RSS.
- The run was not blocked on an older process. It completed feature indexing, but the monitor recorded a `10,192.844 MiB` RSS peak while loading the first combined feature bucket and RSS remained above the gate during later buckets; the diagnostic was stopped cleanly once the failure was conclusive.
- Aggregate logs/status were preserved under `corrected_v0.2.0/diagnostics/final_assembly_256_bounded_20260712`. Seven recognized scratch roots totaling `35,739,521,967` bytes were inventoried, deleted, and rechecked at zero.
- Feature sources are now partitioned into independently sealed vital, lab, diagnosis, procedure, and medication stores. A patient bucket loads only its active domain, and diagnosis reductions are adjacent so each domain is consumed once per cohort group.
- `PartitionedParquetStore.seal()` releases each writer as it closes instead of retaining every closed writer until all buckets are sealed.
- Full local gates pass with `237` tests. Corrected tiers 00/01/02 pass with unchanged 36-file row contracts; tier-02 final assembly completed in `31.176 s` with `205.562 MB` peak RSS.
- GitHub PR #5 has no newly returned actionable review. The most recent review request remains blocked by the account code-review quota; prior threads are resolved.
- Commit `0ba7ded` partitions final feature sources by domain and is pushed on PR #5.
- The full standalone 256-bucket domain-partitioned final assembly completed in `39,249.45 s` (`10h54m`) with `5,972.828 MiB` observed peak RSS, 36 outputs, and zero scratch roots. It passes the `80,882 s` and `6,238 MB` gates.
- Current output hashes match the prior 256-bucket output exactly across all 36 tables: zero hash, schema, row-count, missing, or extra differences. Evidence is under `manifests/full_256_domain_final`, `manifests/full_256_domain_comparison.json`, and `diagnostics/final_assembly_256_domain_20260712`.
- The fresh full non-strict profile from commit `3b87b83` completed all 36 outputs in `73,993.53 s`; final assembly took `49,153.049 s`, profiled peak RSS was `5,896.062 MB`, work footprint was `15,894,947,783` bytes, output footprint was `7,898,119,999` bytes, and recognized scratch was zero.
- Fresh full output hashes exactly match the independent standalone bounded run across all 36 tables. The PHI-safe aggregate delta reports `4,412,932` Milestone 1 rows, `6,949,511` corrected rows, `3,466,002` shared keys, `946,930` Milestone-only keys, and `3,483,509` corrected-only keys.
- GitHub review of `a98142b` found two actionable issues: eligibility could become positionally misaligned after final sorting, and strict final-assembly resumes accepted conflict-resolved non-strict encounter work. Both fixes pass `238` tests and corrected tiers 00/01/02 with unchanged row contracts.
- The alignment fix is behavior-changing, so the `3b87b83` full profile, hashes, and Milestone 1 delta are stale for release even though they remain useful performance diagnostics.
- Commit `b134f70` fixes both findings, is pushed, and received a clean GitHub Codex re-review with all threads resolved.
- The review-clean full non-strict profile from commit `1112963` completed all 36 outputs in `73,589.093 s`; final assembly took `49,180.54 s`, profiled peak RSS was `6,122.562 MB`, work footprint was `15,894,947,783` bytes, output footprint was `7,898,323,229` bytes, and recognized scratch was zero.
- The alignment fix changed six obesity/ventilatory-support `AFTER` hashes with no schema or row-count changes. The final aggregate delta reports `3,471,448` shared keys, `941,484` Milestone-only keys, and `3,478,063` corrected-only keys.
- The explicit strict resume check exits `2` before final assembly with `286` deterministically resolved conflicts, confirming the review-clean fail-closed behavior without changing current outputs.
- Final GitHub review of release commit `73e49bf` found that the non-strict Milestone 2 policy conflicted with the unchanged strict `validation-status` gate. Release docs now explicitly scope that command to historical/strict merge readiness and do not claim `ready: true`; corrected Milestone 2 acceptance uses the documented evidence checklist and aggregate conflict policy.
- GitHub issue #6 now preserves the recovered GLP-1 endpoint ticket. No prior pipeline process is active or blocking implementation.
- The additive GLP-1 foundation includes typed config, versioned concept-set validation, split/unsplit export discovery, PHI-safe header validation, and atomic run-status monitoring.
- Deterministic input inventory, resumable build staging, atomic publication, DuckDB metadata/catalog tables, and concept-filtered core source ingestion are implemented. `2026-3` remains retained evidence but cannot create a gas candidate. Existing pipeline modules and outputs are unchanged; local gates pass with `249` tests.
- The production GLP-1 `build`, `summarize`, and `status` commands now generate/reuse the core DuckDB/Parquet output contract. First-available arterial PaCO2, hierarchical pH pairing, sensitivity cohorts, persistent arterial follow-up, and measured/calculated BMI are covered by synthetic tests.
- Full local gates pass with `251` tests. Draft PR #7 is open against `refactor-pipeline`.
- No legacy, profile, DuckDB build, or prior pipeline process is active; implementation is not blocked on an older run. The existing GLP-1 `status` command provides aggregate monitoring for future long builds.
- GitHub Codex review of `b0f6f74` returned two P2 findings: persistent hypercapnia can miss a later elevated repeat after an earlier normal repeat, and the disabled VBG sensitivity switch is not honored by cohort admission.
- Both PR #7 findings are fixed with focused regression coverage: persistence selects the earliest elevated repeat, and VBG-only candidates are admitted only when the sensitivity switch is enabled.
- Diagnosis, procedure, lab, blood-pressure, and medication component sources now feed temporal phenotype statuses, indication tiers, payer-route modeling, and GLP-1 order/exposure fields in the production build.
- Full local gates passed with `252` tests at the component checkpoint; no production run is active.
- PR #7 review of `dcebd2a` identified unreachable weight-label-only routing and missing non-diagnosis evidence. Local fixes make weight/no-route branches reachable and publish source plus derived evidence across all component domains.
- MASH staging, index-context separation, observability fields, six analysis views, aggregate `status --watch`, and the committed 20-case synthetic acceptance fixture are implemented locally.
- Long-form evidence now covers diagnosis, procedure, lab, blood pressure, medication, derived status, and every non-null indication. Retained-source date coverage, nonblank data-dictionary descriptions, and expanded aggregate QA are included without another raw-data scan.
- The final local gate passes: `git diff --check`, Ruff, and `257` pytest tests. The production CLI completed the 20-case fixture in `0.56 s` with about `347 MiB` maximum RSS, producing 19 encounter candidates, 17 patient index events, 14 primary obesity-hypercapnia rows, and 651 evidence rows.
- Fresh and reused build results now report the same eight public files, including DuckDB and excluding internal workspace/AppleDouble metadata.
- Pre-full-run audit identified four local gaps: dirty-tree code was not part of run identity, required concept sets lacked no-match warnings, output toggles were ignored, and no CI workflow exercised the synthetic suite. These are being fixed before any private build.
- Commit `73c3c3f` is pushed with the GLP-1 evidence contract, 20-case acceptance fixture, analysis views, monitoring, and publication contract. GitHub Codex review returned three P2 findings: unspecified PCO2 entered the VBG sensitivity cohort, diagnosis/procedure history ignored `study.lookback_days`, and open-ended baseline medications ignored `medication_lookback_days`.
- No legacy pipeline, profile, DuckDB build, or prior pytest process is active. The current gate is code review and local verification, not a running historical process.
- Local fixes for all three PR findings pass focused tests. The validation-gap checkpoint also fingerprints dirty source content, warns on required concept sets with no retained matches, honors optional output switches, and adds locked Python 3.11 CI.
- Full local gates pass with `259` tests. A fresh 20-case production CLI smoke completed in `0.59 s` with `383,795,200` bytes maximum RSS, `0` warnings, `19` candidate encounters, `17` patient index events, `14` primary obesity-hypercapnia rows, and `651` evidence rows; `status --watch` exited normally on completion.
- The first GitHub CI run exposed a Python 3.11-only portability defect in the `remove_tree_strict` monkeypatch test, not production cleanup. The test now dispatches to `onerror` or `onexc` according to the runtime and passes under Python 3.11.11 and 3.12.11; CI no longer duplicates feature-branch runs for both push and pull-request events.
- Follow-up commit `17da0d2` is pushed. The single Linux CI job passes all `259` tests, all seven PR threads are resolved, and a fresh Codex review is requested but has not yet returned.
- A read-only issue #6 acceptance audit found three pre-private-run gaps: supplemental `abg_hco3`/`abg_po2`/`abg_sao2` fields remain null placeholders, several context/exclusion flags remain constant false, and QA does not yet report high-frequency unmapped source codes. Versioned concept sets remain documented seed definitions requiring investigator review.
- GitHub Codex review of `17da0d2` returned one P2 finding: baseline lab phenotypes used the 730-day general history instead of the 365-day measurement window. The source evidence boundary now applies `measurement_lookback_days`; focused stale A1c/eGFR/AHI/LVEF/fibrosis regression coverage and the full `259`-test suite pass.
- Commit `f2f58ab` is pushed, its Linux CI job passes all `259` tests, and no legacy, profile, DuckDB build, pytest worker, or prior pipeline process is active.
- GitHub Codex review of `f2f58ab` returned two P2 findings: code-only HFpEF can unlock routes documented as requiring strict measurement evidence, and same-timestamp latest lab rows lack a deterministic source-record tie-breaker.
- `LOCKE BOOK` has about `8.2 TiB` free. The future private build is not blocked by storage or an older process; the existing GLP-1 `status --watch` command is the selected aggregate monitor.
- Both `f2f58ab` review findings are fixed locally: HFpEF-derived strict/bridge routes require strict measurement certainty, and latest lab reductions order by timestamp then source-record hash. Focused tests and the full local gate pass with `260` tests.
- Review fixes are pushed as `b30345b`; both PR threads are resolved and a fresh Codex review is pending.
- Supplemental arterial bicarbonate, PaO2, and oxygen saturation now use versioned LOINC seeds, explicit unit/range validation, and the same deterministic pairing hierarchy as arterial pH. Focused GLP-1 tests pass.
- The supplemental-gas checkpoint passes `git diff --check`, Ruff, and the full `260`-test suite.
- Context flags now derive from documented index-encounter arrest, narrow trauma, anesthesia/sedation, postoperative, and specimen evidence. A configurable cleaned primary view excludes selected flags without deleting unfiltered candidates; focused tests pass.
- Live status check on 2026-07-14 found no legacy, profile, GLP-1 build, DuckDB, notebook, or pytest worker. `/Volumes/LOCKE BOOK` has about `8.2 TiB` free, so execution is not blocked by an older run or storage.
- Supplemental arterial gases are pushed at `c5c85d8`; context/exclusion and one-pass bounded unmapped-code QA changes are local and under verification.
- Merge-base review against `8a6e90360718b26595ec60c4eafb59e5d5839b8e` completed with clean `git diff --check`, clean Ruff, and `264` passing tests; semantic review still found release-relevant GLP-1 provenance, cohort-selection, observability, ingredient-ingestion, cohort-flow, and artifact-safety defects plus several configuration/QA edge cases.
- All seven P1 and six P2 GLP-1 review findings are fixed locally with focused regression coverage: first-gas ordering, concept/code identity, ingredient ingestion, raw observability, output safety, complete cohort flow, sketch bounds, fixed configuration contracts, encounter maxima, and metadata inventory.
- The committed 20-case production fixture completes in `0.66 s` with `378,355,712` bytes maximum RSS, 19 candidate encounters, 17 patient index events, 14 primary obesity-hypercapnia rows, 651 evidence rows, eight public files, and 15 cohort-flow rows.
- A header-only BOOK preflight exposed canonical source files mixed with legacy headerless split artifacts. Discovery now selects one nearest canonical family, permits ingredient-only medication exports, and suppresses the exact duplicate medication alias; the repeated BOOK `validate-export` reports 0 errors and 0 warnings across seven clinical files plus 12 metadata files.
- No private build has started. The final review-fix gate passes `git diff --check`, Ruff, and all `283` tests. A fresh production CLI smoke completed in `1.36 s` with `379,027,456` bytes maximum RSS, 19 candidate encounters, 17 patient index events, 14 primary obesity-hypercapnia rows, 651 evidence rows, zero warnings, eight public files, and all 15 cohort-flow rows.
- The staging audit caught and fixed an overbroad output ignore that also matched the Python package; repository-local generated outputs remain protected, and a regression test now proves source files are not hidden.
- Commit `be64733` is pushed on PR #7, GitHub CI passes all `283` tests, and the fresh Codex review returned one P2 boundary finding: ingredient-only exports could pass validation without fields required by ingestion.
- Ingredient-only exports now require `patient_id`, `code_system`, `code`, and `start_date` at header validation. Ruff, diff checks, `45` focused tests, and all `284` tests pass; the header-only BOOK preflight remains valid with 0 errors and 0 warnings.
- Running pytest temporary files directly on the ExFAT validation volume was pathologically metadata-bound (`5` tests in `450 s`); the complete synthetic suite therefore used a bounded `/tmp` basetemp while retaining the uv cache externally.

## Done
- Historical replication accepted at `99.998708%` aggregate exact-row parity and tagged `refactor-milestone-1`.
- Corrected post-milestone prior-date, procedure first/last, and previous-vital fixes are committed and reviewed.
- Legacy audit identified gas-code/threshold, predisposition-regex, setting-selection, data-screen, J46, TTE, numeric-boundary, encounter-conflict, and nondeterministic feature-reduction defects.
- PR #5 merged cleanly into `refactor-pipeline` at `e3d62de`; annotated tags `refactor-milestone-2` and `v0.2.0` and both GitHub releases are published without changing Milestone 1.

## Now
- Commit and push the verified medication-ingredient header-contract correction.

## Next
- Push the focused correction, resolve the PR thread, request a final Codex review, then decide whether the monitored private full build is unblocked.

## Open questions (UNCONFIRMED if needed)
- UNCONFIRMED: which expanded terminology rows the investigator will approve for the first private build. The recovered ticket is pinned as GitHub issue #6 and remains authoritative.

## Working set (files/ids/commands)
- `docs/SPEC.md`, `docs/DECISIONS.md`, `config.example.yaml`
- `src/trinetx_preprocessing/config.py`, `transform/`, `pipeline/`, `storage.py`, `work_manifest.py`
- `git diff --check`; `./.venv/bin/ruff check .`; external-TMP full `pytest -q`
- `/Volumes/LOCKE BOOK/trinetx-preprocessing-validation/profile/provenance.json`
- `/Volumes/LOCKE BOOK/trinetx-preprocessing-validation/corrected_v0.2.0/tools/monitor_pipeline.py`
- `/Volumes/LOCKE BOOK/trinetx-preprocessing-validation/corrected_v0.2.0/full/monitor_256_bounded_status.json`
- `/Volumes/LOCKE BOOK/trinetx-preprocessing-validation/corrected_v0.2.0/full/final_assembly_256_bounded.log`
- GitHub issue #6: `https://github.com/reblocke/trinetx-preprocessing/issues/6`
- Draft PR #7: `https://github.com/reblocke/trinetx-preprocessing/pull/7`
- Branch: `codex/glp1-augmentation` at pushed checkpoint `be64733`; PR #7 has one focused follow-up ready to commit.

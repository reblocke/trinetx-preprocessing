# Changelog

All notable changes to this project will be documented in this file.

The format is based on Keep a Changelog, and this project aims to follow Semantic Versioning.

## [Unreleased]
### Added
- Added an independent, versioned GLP-1 eligibility database build that leaves
  the Milestone 2 pipeline and its 36 final CSV outputs unchanged.
- Added first-available arterial PaCO2 selection, unit-aware pH pairing,
  persistent-hypercapnia and VBG sensitivity cohorts, measured/calculated BMI,
  temporal component phenotypes, indication tiers, payer-route modeling, and
  GLP-1 order history.
- Added unit-normalized arterial bicarbonate, PaO2, and oxygen-saturation
  values paired to the selected PaCO2 through the same deterministic hierarchy.
- Added documented cardiac-arrest, narrow major-trauma, anesthesia/sedation,
  postoperative, and probable-venous context flags plus a configurable cleaned
  primary-cohort view that leaves unfiltered candidates intact.
- Added source and derived long-form evidence, six study analysis views, atomic
  aggregate run monitoring with `status --watch`, and a committed 20-case
  synthetic acceptance fixture.
- Added a locked GitHub Actions gate that runs Ruff and the complete synthetic
  pytest suite on Python 3.11.

### Fixed
- Ranked the first arterial PaCO2 before unit and plausibility filtering so a
  later valid result cannot replace an earlier unusable result; encounter
  maxima now cover valid arterial measurements through encounter discharge.
- Included concept-set contents and package-anchored code content in build
  identity, and inventoried supplied export metadata so changed rules, code, or
  metadata cannot silently reuse stale outputs.
- Ingested optional medication-ingredient exports and separated raw-domain
  observability counts from concept matching so incomplete seed terminology is
  not reported as absent patient history. Discovery now prefers the nearest
  canonical unsplit source, falls back to supported split files, and ignores
  medication chunks, including one-file chunk families, that lack required
  header fields beside a canonical ingredient file while allowing valid
  column-order differences. Discovery now rejects tied nearest export roots,
  ambiguous source families, and selected clinical domains that do not share
  one flat root or recognized sibling domain-folder root instead of merging
  separate exports silently.
- Required ingredient-only exports to expose `patient_id`, `code_system`,
  `code`, and `start_date`, so malformed medication sources fail during header
  validation instead of later ingestion.
- Published all 15 contracted cohort-flow stages after phenotype and payer-route
  derivation, with source-patient and adult-encounter counts computed from the
  unfiltered export.
- Made multi-file unmapped-code sketches preserve their error bounds by using a
  single checkpointed domain stream, and rejected unsupported custom threshold
  and arterial-specimen configurations instead of silently ignoring them.
- Applied the existing one-day open-encounter bound to same-encounter BMI
  fallback, so a missing encounter end does not discard later valid BMI evidence.
- Rejected every repository-local confidential output root regardless of Git
  ignore rules, and added format-specific defense-in-depth protection for
  DuckDB artifacts, write-ahead logs, and the sibling run-state filename.
  Existing non-directory output paths also fail before Git probing. Builds now
  checkpoint DuckDB and fail before publication if a WAL remains.
- Matched date-only diagnosis and procedure context rows by encounter calendar
  date while retaining exact encounter-bound checks for timestamped rows.
- Excluded specimen-unspecified PCO2 from the VBG-only sensitivity cohort while
  retaining it as non-qualifying source evidence.
- Applied configured lookback windows to baseline diagnosis, procedure, and
  medication evidence, including open-ended active medication records, and
  applied the measurement-specific window to every baseline lab phenotype.
- Included dirty tracked and untracked source content in the deterministic run
  identity so locally modified builds cannot reuse clean-code outputs.
- Honored the Parquet and HTML output switches and emitted aggregate warnings
  when required concept sets match no retained source rows.
- Selected the earliest elevated repeat PaCO2 in the configured persistence
  window so an earlier normal repeat cannot hide later persistent hypercapnia.
- Reused deduplicated gas-candidate keys across source domains, compiled concept
  rules into bounded exact/prefix/regex predicates, and staged full-scale vital
  ingestion through 32 patient-hash Parquet partitions before bounded appends.
- Honored the VBG sensitivity switch during cohort admission.
- Made weight-label-only and no-documented-route payer branches reachable when
  disease-specific and Bridge criteria do not apply.
- Published evidence rows for lab, vital, procedure, medication, status, and
  indication rules rather than diagnosis evidence alone.

## [0.2.0] - 2026-07-14
### Added
- Added the corrected `docs/SPEC.md` analytic contract, immutable typed clinical
  rules, aggregate gas-rule rejection audits, encounter-setting conflict
  reporting, and a fail-closed versioned work manifest.
- Added bounded Parquet partition stores and compact RFS/feature indexes built
  during each domain's streaming pass.

### Changed
- Complete normalized `*_NEW_*` domain tables are now opt-in through
  `storage.emit_normalized_domain_tables`; corrected execution writes compact
  analysis indexes by default.
- Post-Milestone 1 final assembly now treats selected legacy quirks as bugs
  rather than replication targets when computing prior/latest analytic dates.
- Final assembly now reuses patient-partitioned feature/history buckets across
  all category/setting cohorts instead of repeatedly scanning group tables.
- `AFTER` screening is derived from diagnosis-or-lab encounter availability.
- Legacy domain group tables are opt-in through
  `storage.emit_legacy_group_tables`.
- Final analytic feature logic is separated into small domain-owned vital, lab,
  diagnosis, procedure, and medication modules, leaving final assembly focused
  on cohort, lookup, screening, and output orchestration.
- Final cohort construction streams encounter-reduced event partitions into the
  patient-partitioned cohort index in bounded one-million-row join batches and
  performs the global earliest-patient reduction inside each patient bucket
  instead of concatenating a full RFS category in memory.
- Final feature sources are partitioned independently by clinical domain.
  Patient buckets load only the active vital, lab, diagnosis, procedure, or
  medication domain instead of materializing all feature rows together.
- Full corrected profiling completed all 36 outputs in 73,589.093 seconds with
  6,122.562 MB peak RSS; final assembly completed in 49,180.54 seconds.
- Release evidence accepts deterministic non-strict resolution for the 286
  source encounter IDs assigned to multiple settings. Strict execution remains
  fail-closed so unresolved source conflicts cannot be overlooked.

### Fixed
- Kept precomputed `AFTER` eligibility aligned with final row sorting so mixed
  eligible/ineligible rows cannot receive one another's screen result.
- Made strict final-assembly resumes reject encounter work that contains a
  non-strict conflict-resolution report.
- Included compact analysis indexes in stage output inventories so work
  manifests and callers track the artifacts consumed downstream.
- Replaced per-encounter Python conflict aggregation with a bounded vectorized
  reduction, preserving the same conflict counts and setting combinations on
  full-scale encounter partitions.
- Limited lab feature precision conversion and CSV-visible rounding to rows
  matching each clinical code rule instead of repeating those operations over
  every raw lab row for every rule.
- Corrected final analytic `last_date_*` selection for prior diagnosis,
  procedure-style encounter features, and outpatient medications so "last"
  dates use the latest qualifying row instead of the earliest row.
- Corrected prior diagnosis and outpatient medication first/last date assembly
  to filter rows to each final row's `qualify_date` before reducing, so future
  rows cannot hide earlier qualifying history.
- Corrected previous Weight/Height/BMI assembly to exclude current encounters
  and choose the latest strictly prior value before each final row's
  `qualify_date`.
- Corrected ABG/VBG codes, specimen and unit handling, gas thresholds,
  predisposition prefix matching, J46/TTE code sets, setting-specific event
  selection, numeric boundary filtering, and deterministic feature reductions.
- Precomputed encounter-level `AFTER` eligibility before patient bucketing so
  final assembly no longer rereads large encounter-screen partitions for every
  category/setting group in every patient bucket.
- Extended `clean-scratch` to inventory and safely remove all current final
  cohort, feature-source, lab, and previous-vital partition stores.
- Fingerprinted both legacy data-screen CSVs in the work manifest and require
  them before controlled `legacy_files` runs, so changed screen inputs fail
  stale-work validation instead of silently changing `AFTER` cohorts.

### Removed
- Removed the obsolete `split_db.sh`; the portable Python `split` command is the
  supported splitter.

## [refactor-milestone-1] - 2026-07-08
### Added
- Refactored the legacy TriNetX hypercapnia preprocessing notebooks into a
  deterministic Python CLI with stage commands, strict profiling provenance,
  memory-bounded hashing/comparison, Parquet intermediates, and final legacy CSV
  output preservation.
- Added synthetic tests, staged legacy-vs-refactor validation tooling, and
  external-drive validation workflows for confidential real-data runs.

### Changed
- Completed the replication phase under near-exact row parity evidence:
  `4,412,875 / 4,412,932` final analytic rows match exactly (`99.998708%`).
- Documented the remaining `57` shared-key row differences as residual
  Weight/previous-Weight legacy quirks for the milestone fallback point.

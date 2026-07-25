# Changelog

All notable changes to this project will be documented in this file.

The format is based on Keep a Changelog, and this project aims to follow Semantic Versioning.

## [Unreleased]
### Added
- Added one canonical `trinetx_preprocessed.duckdb` containing the historical
  534-column observations, source-faithful additive elements, catalog/rule
  membership, observability, provenance, quality summaries, and 36 exact
  compatibility views.
- Added combined-product build, status, inspection, validation, and legacy
  export commands plus aggregate-only parity, completeness, and benchmark
  scripts.
- Added the versioned standalone GLP-1 eligibility build now retained as the
  downstream derivation and validation reference for unified preprocessing.
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

### Changed
- Unified historical and GLP-1 source preprocessing behind one manifest-bound
  raw-data pass; the existing GLP-1 cohort/phenotype implementation remains a
  downstream reference rather than a second canonical preprocessor.
- Medication-ingredient exports now enter the unified source-element table
  without entering historical medication feature reduction.
- Completed-output reuse now validates the exact configured GLP-1 public file
  set, rejects empty artifacts, and confirms the DuckDB run identity/status
  before reporting success.
- Work-manifest schema 4 binds resumable corrected-pipeline intermediates to the
  current behavior-code fingerprint, including a source-hash fallback when Git
  metadata is unavailable.
- `status --watch` now exits nonzero when a build reports failure or its local
  worker disappears before completion, allowing wrappers to propagate failed
  and killed builds correctly.
- Completed the exact behavior-head full-data GLP-1 build from commit
  `459cbda` in 20,941.55 seconds with 5,635,293,184 bytes maximum RSS, below
  the 6,238 MiB gate. The build atomically published exactly the eight
  contracted analytic files with zero warnings, errors, WAL files, recognized
  scratch artifacts, hidden workspaces, or residual AppleDouble sidecars.
- Matched the reviewed `e7bf01a` parent build exactly across all 59,954
  analysis rows, 1,320,409 candidate encounters, and 12,028,276 evidence rows:
  schemas, key sets, table counts, non-provenance analysis values, and all
  three order-independent semantic fingerprints are unchanged.
- Preserved all 59,954 index-event keys, 1,320,409 candidate encounters, 9,527
  strict primary rows, payer-route counts, and cohort-flow counts relative to
  the reviewed `71ef56f` baseline. The corrected all-history cirrhosis rule
  changed 191 analysis rows; corrected evidence retention added 9,193 diagnosis
  rows and removed 2,612,789 post-index non-GLP-1 medication rows.
- The earlier provisional-to-reviewed aggregate comparison preserves all 59,954 index-event keys,
  1,320,409 hypercapnia candidate encounters, and 9,527 strict primary rows.
  Corrected phenotype windows, date precision, code-only obesity, blood-pressure
  units, and source-traceable gas evidence intentionally change downstream
  phenotype and evidence values.

### Fixed
- Made combined-product replacement transactional across the DuckDB, sidecar,
  and all 36 compatibility CSVs, with rollback on publication failure.
- Enforced identical typed source-table contracts for CSV and Parquet work,
  source-faithful patient strings, and `include: true` source retention.
- Aligned medication-ingredient preflight validation with ingestion, ignored
  confidential CSV intermediates, and made the synthetic example rerunnable.
- Preserved a complete compact encounter-flow inventory so downstream GLP-1
  source-denominator counts include pre-2022 non-gas-candidate encounters.
- Removed the internal build-workspace manifest before atomic publication while
  restoring it if publication fails, so completed builds contain exactly the
  eight contracted public files without weakening resumability.
- Excluded source modification times from deterministic input identity while
  retaining them in the provenance inventory, so byte-identical copied or
  restored exports reuse the same run without hiding source metadata.
- Pinned the primary PaCO2 threshold to 45 mm Hg because the public endpoint,
  analysis columns, and cohort-flow labels are explicitly fixed as `gt45`.
- Evaluated cirrhosis over all available pre-index diagnosis history so remote
  cirrhosis cannot be misclassified as noncirrhotic MASH after the general
  diagnosis lookback expires.
- Scoped candidate-flow counting, encounter de-duplication, first gas
  selection, and encounter PaCO2 maxima by both patient and encounter so reused
  encounter identifiers cannot mix or undercount clinical rows across patients.
- Excluded post-index non-GLP-1 orders from baseline medication components and
  source evidence while retaining precision-aware GLP-1 follow-up orders.
- Treated same-calendar-day timestamped anesthesia/sedation procedures as
  at-or-before a date-only selected ABG while retaining exact ordering for
  timestamped ABGs.
- Preserved low-eGFR source precision when testing CKD persistence: timestamped
  measurements require at least 90 elapsed days, while a date-only endpoint
  uses the inclusive 90-calendar-day boundary.
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
  date while retaining exact encounter-bound checks for timestamped rows,
  including compact `YYYYMMDD` and `YYYYMMDDHHMMSS` source representations.
- Bounded vital, diagnosis, procedure, and medication ingestion with reusable
  patient-hash Parquet partitions, and normalized compact TriNetX `YYYYMMDD`
  dates before temporal cohort and phenotype logic.
- Bounded exact terminology-match counts with domain-sequential record-hash
  partitions, preventing full-scale QA from retaining every matched hash in one
  cross-domain aggregate.
- Reduced exact duplicate-source counts through the same bounded per-domain
  hash partitions, and taught gas normalization to recognize canonical UCUM
  `mm[Hg]` and `[pH]` spellings present in production TriNetX exports.
- Streamed unfiltered observability through a bounded DuckDB Arrow reader and
  million-row partial reductions, avoiding a full-domain join/group and large
  row-level scratch while preserving duplicate event counts and index-specific
  lookback windows.
- Excluded specimen-unspecified PCO2 from the VBG-only sensitivity cohort while
  retaining it as non-qualifying source evidence.
- Applied phenotype-specific temporal windows: all available pre-index history
  for MI, stroke, PAD, revascularization, bariatric and liver-staging history;
  five years for AHI/REI; the general history window for kidney and cardiac
  measurements; and all prior structured fibrosis staging. Pre-index GLP-1
  order history is no longer truncated by the active-medication window.
- Represented diagnosis-only obesity as `code_only` without promoting it into
  measured BMI threshold views, normalized blood pressure only from recognized
  pressure units, and preserved raw gas and blood-pressure values and units in
  long-form evidence.
- Preserved date-only encounter-end precision for inclusive same-day bounds,
  published the paired arterial pH source row required for strict hypercapnia,
  and applied configured history windows with exact bounds for timestamped
  rows and calendar-day bounds for date-only diagnosis, procedure, laboratory,
  BMI, blood pressure, medication, and observability rows. Date-only medication
  ends remain active through their complete calendar day, and GLP-1 follow-up
  flags use exact starts/endpoints for timestamped orders and inclusive
  calendar dates for date-only orders.
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
- Applied the combined-product DuckDB memory, thread, and external-spill policy
  to compatibility export, provenance refresh, inspection, evidence, and
  validation instead of limiting only database creation.
- Removed macOS AppleDouble metadata files from the staging tree immediately
  before atomic publication so the canonical product contains only contracted
  outputs.
- Replaced global all-domain source-integrity validation with equivalent
  domain-local orphan and duplicate checks plus explicit logical-domain and
  cross-domain source-file guards.
- Disabled insertion-order preservation for read-only combined-product
  sessions so large exact validation aggregates can spill within the configured
  memory limit; canonical database creation retains ordered insertion.
- Replaced full-domain duplicate source-ID aggregation with an exact 64-way
  Parquet reduction so validation remains bounded on production-sized domains.
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

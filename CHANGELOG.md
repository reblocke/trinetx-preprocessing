# Changelog

All notable changes to this project will be documented in this file.

The format is based on Keep a Changelog, and this project aims to follow Semantic Versioning.

## [0.2.0] - 2026-07-09
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

### Fixed
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

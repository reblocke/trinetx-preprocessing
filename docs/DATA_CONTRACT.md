# Data Contract

This document defines pipeline boundaries and storage grain. Corrected clinical
semantics live in `docs/SPEC.md`.

## Private inputs

The configured raw root contains Encounter, Diagnosis, Lab Results,
Medications, Procedure, Vital Signs, and Patient exports. Raw exports and all
row-level derivatives are confidential and must remain untracked.

Required identifiers:

- Every domain: `patient_id`.
- Encounter-linked domains: `encounter_id`.
- Encounter: identifiers, start/end dates, and setting type.
- Diagnosis: code system, code, date, and diagnosis indicators.
- Labs: code system, code, date, numeric value, and units.
- Medications: the historical medication schema, or `patient_id`, `code_system`,
  `code`, and `start_date` for recognized `medication_ingredient*.csv` exports.
- Procedure: code system, code, and date.
- Vitals: code system, code, date, numeric value, and units.
- Patient: sex, race, ethnicity, birth year, regional location, and death month.

`validate-inputs` checks configured source headers without scanning row data.

## Normalized intermediates

Logical `*_NEW_####` tables preserve patient/encounter IDs and domain dates.
Clinical normalized tables also retain `code_system`; lab and vital tables
retain `units_of_measure`. Numeric rule eligibility is evaluated in `float64`.

Encounter normalization emits AMB, EMER, and INPAT tables with start/end dates,
type, and length of stay. Cross-setting encounter-ID conflicts fail strict runs
and produce aggregate-only diagnostics in non-strict runs.

Physical work tables are CSV or Parquet according to
`storage.intermediate_format`. Final CSV format is unaffected.

## Compact analysis indexes

During each domain's single raw scan, the pipeline writes only rows needed for:

- RFS event candidates;
- current-encounter analytic features;
- patient-history features; and
- diagnosis-or-lab encounter availability.

Complete normalized `*_NEW_*` domain tables are optional compatibility
artifacts controlled by `storage.emit_normalized_domain_tables`; they are not
written by default or consumed by corrected RFS/final assembly.

Feature candidates carry a logical `source_name`; RFS candidates carry an RFS
category. Final assembly repartitions candidates by patient, while encounter
reducers partition by encounter. The default is 256 bounded Parquet buckets
with Snappy compression and 250,000-row groups.

Historical `HAS_*`, `IPmed_*`, `OPmed_*`, and `value_*` group tables are not
required. They are emitted only when `storage.emit_legacy_group_tables: true`.

`pipeline_work_manifest.json` records the intermediate schema version, ruleset,
configuration hash, source metadata fingerprints, package versions, row counts,
and stage completion. Resume commands fail closed when work is incompatible.

## RFS and screening tables

- `RFS_<CATEGORY>` contains event-level `patient_id`, `encounter_id`, and date.
- `rfs_encounter_flags` contains one retained AMB/EMER/INPAT encounter row and
  category flags; historical normalized encounter tables remain a read fallback.
- Corrected RFS codes, systems, units, conversions, and thresholds are defined
  in `docs/SPEC.md` and immutable typed rules.
- `AFTER` eligibility is derived from at least one normalized diagnosis or lab
  row on the selected encounter.

## Canonical combined output

`trinetx_preprocessed.duckdb` is the authoritative preprocessing product. It
contains the historical observation payload, typed source tables, element
catalog and rules, source-element memberships, observability, provenance,
quality summaries, and compatibility-output metadata described in
`docs/UNIFIED_PREPROCESSING.md`.

The source tables retain row provenance, duplicate source records, raw and
normalized codes/units, parsed dates, source timestamp precision, and
source-faithful patient strings. Clinical rows are retained only when at least
one matching element rule has `include: true`; exclude-only matches do not enter
the canonical source tables. They are the shared input boundary for downstream
studies; downstream cohort and phenotype decisions are not preprocessing
elements.

`source_encounter_flow` is the compact exception to concept-filtered clinical
retention. It stores the four fields needed to reconstruct complete encounter
flow denominators, including pre-2022 encounters outside the historical final
output window.

## Public compatibility outputs

The pipeline always writes:

```text
output/
  AMBULATORY/
  EMERGENCY/
  INPATIENT/
```

For six RFS categories and three settings, each directory contains paired
`RFS_<RFS>_ENC_<SETTING>_BEFORE.csv` and `..._AFTER.csv` files: 36 total.

- Every file uses the exact ordered 534-column schema in
  `pipeline/final_output_schema.py`, including empty outputs.
- Row grain is one selected encounter per `(RFS category, setting, patient)`.
- Selection, age, location, event-in-encounter, screening, and feature-reducer
  semantics follow `docs/SPEC.md`.
- Final names and CSV format are stable public compatibility contracts.
- Each file is generated from its database compatibility view. The database
  stores the expected normalized SHA-256, row count, and ordered columns, and
  validation rejects any divergent export.

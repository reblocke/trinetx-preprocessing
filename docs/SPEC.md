# Corrected Analytic Pipeline Specification

This document is the behavior authority for post-Milestone 1 releases. Legacy
notebooks remain historical references, but known notebook defects do not
override this contract.

## Specification boundary

This specification governs the historical/corrected Hypercapnia compatibility
outputs. The canonical DuckDB now exposes one cohort-source catalog containing
GLP-1 and traditional source candidates, but source `element_membership` does
not apply any analytic rule in this specification. Cohort import has not yet
occurred and is paused until the downstream repository refactor exposes a stable
behavior head. The GLP-1 adapter and standalone raw ingestion remain temporary
parity references; see `CURRENT_STATE.md` and `GLP1_PHENOTYPES.md`.

Codes `3304`, `236913`, and `28863` are retained only as unadjudicated
Stata-annotated outpatient-MAT source candidates. They do not change the
medication features or cohort semantics below and require original-query/export
review before clinical inclusion.

## Public output contract

- The pipeline writes 36 final CSV files: six respiratory-failure syndrome
  (RFS) categories by three settings, each with `BEFORE` and `AFTER` variants.
- Every final CSV uses the ordered 534-column schema in
  `pipeline/final_output_schema.py`, including empty outputs.
- One patient may appear once in each RFS/setting output. The selected event is
  the earliest qualifying event for that patient within that setting.

## RFS definitions

- **ABG:** LOINC `2019-8` or `32771-8`, arterial PCO2, after conversion to
  mmHg, with `45 < value < 200`.
- **VBG:** LOINC `2021-4`, venous PCO2, after conversion to mmHg, with
  `45 < value < 200`.
- LOINC `11557-6` is specimen-unspecified PCO2 and does not define ABG or VBG.
- LOINC `2026-3` is total arterial CO2 and does not define ABG.
- Respiratory failure, obesity, ventilation support, and predisposition use
  version-controlled exact-code or prefix rules. Regex metacharacters are not
  code-list syntax.
- Numeric eligibility is evaluated in `float64`. Storage downcasts cannot alter
  cohort inclusion.

## Encounter and screening semantics

- Eligible encounters start on or after `2022-01-01`, use AMB, EMER, or IMP,
  and have positive length of stay after the documented end-date fill.
- An encounter ID assigned to multiple settings is invalid. Strict runs fail;
  non-strict runs report aggregate conflicts and choose earliest start date,
  then observed row order.
- An RFS event must occur within the selected encounter interval.
- `AFTER` includes a `BEFORE` row when the selected encounter has at least one
  normalized diagnosis or lab record. Screening is derived by the pipeline;
  missing derived screening evidence is an error in strict mode.

## Feature reduction semantics

- Current-encounter diagnosis flags mean any matching row. Diagnosis date is
  the earliest matching date.
- Principal diagnosis indicators reduce by `P`, then `S`, then `U`.
- Admitting and reason-for-visit indicators reduce positive (`Y`/`T`), then
  negative (`N`/`F`), then unknown (`U`), with observed order breaking ties.
- Inpatient medication date is the earliest matching start date in the current
  encounter.
- Prior diagnosis and outpatient medication rows must be on or before the
  final row's qualify date. Previous vitals must be strictly earlier.
- `HAS_J46` includes `J45.42`. `HAS_TTE` is limited to `93303`, `93304`,
  `93306`, `93307`, `93308`, and `93356`.

## Internal data and reproducibility

- Normalized clinical tables retain code system and units when present.
- Known unit conversions are explicit; incompatible or missing units are
  excluded from unit-sensitive rules and counted in aggregate provenance.
- Intermediate schema, ruleset, configuration, inputs, and stage completion
  are recorded in an untracked work manifest. Stale work is not reused.
- Real data and row-level generated artifacts remain external and untracked.

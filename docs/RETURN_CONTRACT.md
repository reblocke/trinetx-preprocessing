# Return outcomes contract (proposed v1; private acceptance BLOCKED)

This is an opt-in, separate outcome product. It does not alter encounter
features, compatibility CSVs, cohort selection, or study analyses. The input
population is every original `(patient_id, encounter_id)` key in each accepted
encounter variant, independently. A row in `element_membership` supplies source
candidacy, never outcome eligibility by itself.

## Sources and identity

The accepted, manifest-bound `trinetx_preprocessed.duckdb` supplies
`source_encounter`, `source_diagnosis`, `source_lab_measurement`,
`element_membership`, `source_patient`, and observability. The accepted encounter
bundle supplies only original index keys and its parent manifest identity. The
build validates both products before reading clinical rows and publishes to a
new external directory. Neither `source_encounter_flow` (no end field) nor
compatibility/RFS selection, legacy filled end dates, or baseline lookbacks is
a discharge or return source. Repeated source records retain source IDs. Keys
are paired strings, never a concatenated or variant-encoded patient key.

## Episode and time rules

An episode is the composite source `(patient_id, encounter_id)`. Multiple
source rows with the same pair are mapped to that episode; an ED and inpatient
row sharing that pair is one evidenced ED-to-inpatient continuation and one
acute-care event. Distinct encounter IDs are never merged merely because their
dates overlap or are within 24 hours. Such overlaps and uncertain same-day
order are reported. This conservative rule does not assert that every transfer
has a shared ID. Source types `EMER` and `IMP` identify ED and inpatient in the
accepted exports; unrecognized types are retained as unknown, not reclassified.

Index follow-up starts at the *source episode end*, requiring an observed,
non-derived end and a valid start/end order. Missing, conflicting, or derived
ends make the outcome unavailable. A derived return start cannot establish
post-index order. A timestamp-precision end/start pair permits
within-day ordering. Date-only values are calendar-day observations: a
same-day distinct-ID event has uncertain order and is not a confirmed return.
Confirmed returns start in `(index end, index end + N days]`, for N = 30, 90,
and 365 by default. A return with a missing start is undated evidence and
cannot enter a window. End dates and linked diagnosis/lab dates are not filled.

An inpatient episode after an inpatient index is a readmission. After an
ED-only index it is an admission. ED-only returns, any ED presentation, and
acute-care union are separately reported. An evidenced ED-to-inpatient episode
counts once in the union and once in the inpatient category; it is not ED-only.
Recurrent episodes remain distinct. Observed follow-up and coarse death month
are separate fields; neither censors at last visit nor proves complete capture.
Conflicting recorded death months remain unknown.

## Return evidence

Only an ICD-10-CM diagnosis linked to a return episode can satisfy the exact
set `J96.02`, `J96.12`, `J96.22`, `J96.92`, `E66.2`. Broad J96 and historical
diagnoses do not qualify. Source code, date, record ID, and rejection reason
remain in evidence.

Gas evidence uses return-episode source rows in the arterial or venous PCO2
catalog sets. A contradictory specimen, missing/nonpositive/nonfinite numeric
value, unsupported unit, missing date, or out-of-episode date is rejected with
a reason. Accepted `mmHg`, `mm Hg`, `mm_hg`, `mm[Hg]`, and `Torr` are unchanged;
`kPa` is multiplied by 7.5006168270417. Unspecified-blood PCO2 is retained
but cannot establish ABG or VBG. Any usable measurement in the episode can
establish a threshold. ABG and VBG each have separate `>45`, `>50`, `>=45`,
and `>=50` flags, plus explicitly named any-gas unions. These are not legacy
mean or first-day flags and do not require pH or a particular index route.
Gas threshold flags use three states: `true` (positive), `false` (usable gas
tested without the threshold), and `null` (unknown). No usable gas is unknown,
never a negative test. Testing counts are separate.
The named `any_hypercapnia` union is the exact ICD set, ABG PCO2 `>=45`, or
VBG PCO2 `>=50`; the other named threshold unions remain separately available.

## Product and acceptance

The versioned bundle contains a typed dictionary, episode/source mapping,
diagnosis and gas evidence, unique index-to-return links, one summary per
original key per variant (including unavailable and not-applicable rows),
validation report, and a manifest hashing all artifacts. Every category and
evidence criterion has independently computed counts, flags, first dates, and
first precise timestamps at each horizon. Fields are labeled **outcomes** and
must not be used as baseline predictors. A complete build is engineering
evidence only; private acceptance additionally binds source, parent bundle,
code, configuration, contract, validator and all required comparison gates.

Private profiling of composite-key conflicts, end derivation/precision,
settings, linkage, forward coverage, and transfer documentation is a required
pre-build gate. An unsupported source fact stays unknown; a failed gate blocks
acceptance rather than changing this contract silently.

The CLI entry points are `python -m trinetx_preprocessing build-returns` and
`python -m trinetx_preprocessing validate-returns`. Both require the canonical
database, accepted parent bundle, and external work/output paths. The build
also requires a patient partition count (default 32); `--resume` verifies the
source, parent, code and partition identity and every completed part hash.
The validator requires a new external report path and independently reconciles
summary keys, return links, counts, flags, first dates/timestamps, uncertainty,
typed schemas and artifact hashes. These commands are not a private acceptance
seal.

## Current gate status

The accepted canonical diagnosis catalog does not retain the four required
`J96.02/J96.12/J96.22/J96.92` source codes. Its concept-filtered diagnosis
table therefore cannot support the exact return ICD outcome. The build
preflight raises an error before publication. The source and parent manifest
hashes, aggregate encounter profiling, and missing-code list are recorded in
an external private receipt; no row-level data or private paths are in this
document. The source has date-only encounter start/end observations and some
index keys have missing or conflicting ends. Same-day order and those index
anchors remain unavailable under this contract.

To unblock, approve and validate a canonical diagnosis capture containing all
five exact ICD-10-CM codes, establish its source acceptance and linkage to the
accepted parent keys, and re-profile episode end/forward coverage and transfer
evidence. Then run the resource pilot, one locked two-variant outcomes-only
build, independent validation, and external acceptance seal. Do not substitute
the compatibility CSVs, a broad J96 rule, or a raw export rescan.

# Proposed independent GLP-1 encounter population interface

Status: design proposal. No source cutover or scientific estimate is approved.

The accepted encounter bundle's two variants inherit the authenticated legacy
36-file compatibility population. The separately accepted historical GLP-1
patient-index table was constructed from the manifest-bound canonical source.
A bounded private aggregate comparison on 2026-09-24 found that neither bundle
variant covers all historical patients or exact index encounters, although
every historical index key exists in that same canonical encounter source.
The audit did not choose a replacement index, compute a phenotype, or publish
restricted counts. Its source identities and aggregate receipts remain private.
The historical GLP-1 source acceptance at `9fe392b` establishes canonical/raw
source interchangeability for its validated contract. Retain it as evidence;
it does not accept this new population interface or the original abstract's
index membership, exact timing, and clinical estimates.

This population-interface problem remains separate from the accepted
[calendar-date revision](GLP1_TIMESTAMP_SOURCE_GAP.md). The new D/D+1 gas rule
does not make either existing compatibility-backed variant represent the
historical patient/index population. A population interface still requires
its own independent acceptance and downstream reconciliation.
The draft source-capability audit in `cohort_source_capability_audit.py`
provides aggregate timing and medication-field capture counts for a validated
canonical source. It does not select a population or make a new source
acceptable for the original abstract.
The separate `audit_calendar_source_sizing()` scans all source encounter and
patient rows to count key, date, encounter-type and birth-year field coverage.
It reports approximate distinct-key values solely to size a bounded full-source
projection. It retains duplicates in row counts and does not apply age,
encounter-type, context or clinical inclusion rules. Its approximate key
values are not patient denominators or source-acceptance evidence.
An owner-only source-wide run completed in 2.57 minutes with stable canonical
input identity, empty DuckDB spill and mode-0600 receipt read-back. All
observed encounter starts were date-only and parseable by the candidate date
parser. A small minority of raw encounter rows carried an `EMER` or `IMP`
type hint, making a narrowly staged candidate-key path worth testing before
materializing every encounter key. The approximate all-key estimate exceeded
the raw row count, illustrating why that estimate must never be used as an
exact key count or study denominator. This audit did not verify one-record-per-
patient selection, context exclusions, clinical evidence or source acceptance.
The separate `cohort_source_gas_policy_audit.py` candidate counts fixed
categories for catalog-matched arterial PaCO2 and pH rows: source-key and
date completeness, raw numeric screening ranges, normalized unit classes,
specimen-label classes, and same-day specimen/panel group multiplicity. It emits no source
labels or row identifiers. These counts support clinical review of a future
versioned mapping policy; they do not approve unit conversion, specimen
semantics, plausibility limits, or sample linkage.
The audit materializes only catalog-matched candidate rows in temporary
read-only-connection tables, then reuses that set for all fixed-category and
linkage counts. It drops those tables on success or failure. This avoids
repeating the full canonical-source join for each count.
An owner-only candidate run at `f598ab6` completed in 1,394.25 seconds with
stable source identity and an owner-only receipt read-back. It found that the
catalog-matched arterial candidates have no populated specimen or specimen/panel
link identifiers on this snapshot; same-day pH therefore cannot be called a
linked sample. Its first date-validity result was invalidated by the draft
parser accepting only hyphenated dates, while the source stores observed
compact `YYYYMMDD` dates. The parser, batch start check and fixed-category
date audit now accept both compact and hyphenated observed date-only forms.
The audit also adds fixed hints for common unit-label variants, including
UCUM `mm[Hg]` and `[pH]`, while leaving clinical conversion and specimen
meaning unapproved. The corrected owner-only aggregate rerun at `3844ea0`
found no invalid candidate dates, confirmed absent specimen/sample-link IDs,
and passed stable source-identity and private receipt read-back checks. A
separate owner-only fixed-category lineage check found exact configured
arterial LOINC membership and source-code agreement for every candidate.
Another fixed-category probe found UCUM `[pH]` on all source-code pH rows in
this snapshot. These probes inform clinical policy review; none accepts the
population source or clinically validates the gas phenotype.

## Proposed upstream product

Create a separately named and versioned encounter/evidence product from an
approved manifest-bound TriNetX source. Preserve original `patient_id` and
`encounter_id`, encounter type, raw start/end values and precision, source/HCO
provenance, duplicate source records, stable source-record identity, and linked
clinical evidence. Keep source catalog membership distinct from study inclusion:
the upstream product must not select one patient index, apply GLP-1 exclusions,
or decide medication activity. The downstream study owns those decisions.

The candidate `build_calendar_candidate_fields()` projects every valid exact
source encounter key to a temporary relation with observed date-only start,
normalized encounter type and numeric birth year only where source records
agree. It retains duplicate-source-row counts and separate invalid/missing or
conflicting field indicators; invalid encounter keys are reported in aggregate
QA. It does not filter adult or emergency/inpatient candidates, derive exact
age from birth year, apply context exclusions or choose an index. This makes
source uncertainty visible before downstream study rules are applied.
Synthetic read-only, ambiguity, empty-population and prior-output-preservation
fixtures pass. The full private source and scope gates remain open.
For a bounded full-source engineering path, `stage_calendar_type_hint_keys()`
temporarily groups exact keys that have at least one raw `EMER` or `IMP` type
hint. The caller must then rejoin **all** raw encounter rows for those keys
before running the existing field projection, so an out-of-scope or conflicting
type row at a hinted key cannot disappear. This stages potential keys only; it
does not approve encounter eligibility, omit unresolved context evidence, or
choose a patient index. Synthetic duplicate, mixed-type, empty and read-only
checks pass. A private type-hinted projection audit remains an engineering
feasibility gate, not independent source acceptance. An owner-only full-source
scoped run completed in 5.13 minutes, including hint-key staging and the
all-row field projection. Exact hint-key and projected-key counts reconciled;
the projected source-row count retained the hinted rows. Stable input identity,
empty scratch and mode-0600 receipt read-back passed. The projection exposed
nonzero duplicate-source and conflicting-start categories across the broader
source population. Those uncertain starts cannot silently become index dates.
The audit produced no patient-level output and did not accept a cohort, context
order or source policy.
The packaged `build_calendar_type_hint_candidate_fields()` now performs the
type-hint stage, all-row rejoin and exact-key field projection without a
caller-authored source view. It checks hinted/projected key counts and source
row retention before replacing its temporary output, and removes its temporary
key/view stages on success or failure. The underlying generic field builder
accepts a named source relation for this bounded path; its audit counts refer
to that relation's scope. Sixteen affected synthetic/read-only tests pass,
including mixed-type preservation and rollback of a prior output. This remains
a candidate API requiring a trusted read-only source and an independent
population receipt.
An owner-only full-source run of that packaged API completed in 5.69 minutes.
Every aggregate hinted-key and projected-field QA value matched the prior
manual scoped run exactly; canonical input identity was stable, temporary
scratch was empty after close, and the mode-0600 private receipt passed
read-back. These are separate runs, so the elapsed times do not establish a
speed improvement. The audit compares aggregate QA, not every projected row,
and does not issue source acceptance or a patient-level denominator.
An owner-only cross-repository aggregate coverage audit then compared the
authenticated historical one-index-per-patient keys with the packaged
type-hint key relation. Every historical exact index key was present in that
candidate scope. The run completed in 1.43 minutes with stable canonical and
historical input identities, empty scratch and mode-0600 receipt read-back.
This verifies historical-key retention by the type hint; it does not compare
new patient indexes, extra source patients, exclusions, gas eligibility or
independent source acceptance.
A separate owner-only fixed-category audit reconciled the conflicting-start
total to that projection in 3.39 minutes, with stable source identity, empty
scratch and a mode-0600 receipt read-back. Conflicts span one day through more
than a month, with a longer tail; many keys have more than two raw rows. Each
conflicted key had one observed `source_id` value in this snapshot. That field
pattern does not identify the correct start, and no earliest, latest or
majority-date rule is approved. An unresolved candidate date must stay visible
to downstream index selection and population reconciliation.
An owner-only aggregate audit used the historical patient IDs as a bounded
scope for this projection. A separate exact-index read-back found every
historical index key in that candidate source and agreement of observed
calendar date, encounter type and the historical birth-year age proxy at
those keys. Age-18 boundary cases remain. Both audits passed stable source
identity and private receipt read-back checks. They do not test the extra
source population, context exclusions, clinical gas qualification or a new
patient index and cannot accept this independent interface.

The existing read-only `open_cohort_source()` / `validate_cohort_source()`
boundary already exposes versioned canonical source tables with manifest,
schema and catalog checks. Reuse that boundary where it can support the scope:
a new study-facing acceptance policy and receipt may bind an immutable
canonical database and explicit source views in place instead of copying the
entire source database. This is an explicit new accepted interface, not a
silent fallback from a failed encounter-bundle read. The receipt must bind the
exact database identity/bytes, source manifest and schema/catalog revision,
and the installed consumer must verify that trusted identity before opening
rows. Preserve the accepted date-only database and its existing bundle.

The draft `verify_accepted_cohort_source()` and
`open_accepted_cohort_source()` implement this trust boundary without issuing
an acceptance. They require a caller-supplied receipt SHA-256, exact database
and adjacent sidecar SHA-256/size, matching embedded metadata and catalog,
required element IDs, and passing provenance, source-scope and historical-index
coverage gates in the trusted receipt. The open function reuses the existing
read-only cohort-source API and checks file identity across the read. A
synthetic receipt and database exercise positive and tamper rejection paths;
they do not pass the private gates or authorize downstream adoption. Hashing
the full database is an intentional once-per-open cost to bind exact bytes.
An owner-only standalone read-only SHA-256 pass over the 167.3 GiB canonical
database took 924.88 seconds with stable identities and receipt read-back.
That measures the digest alone, not a complete accepted-source open or report.

The candidate `project_calendar_encounter_evidence()` reads one original
patient/encounter key from a caller-opened validated source. It requires
observed date-only raw starts and arterial lab dates, rejects conflicting
starts and duplicate source-record keys, and uses catalog membership with
duplicate memberships collapsed. It returns raw numeric values, units,
specimen and panel fields without classifying the gas. Synthetic exact-key,
precision and ambiguity fixtures pass. This per-encounter projection is a
validation bridge, not a measured bulk report path or evidence of source
acceptance. Clinical specimen, unit, plausibility and linkage policies remain
downstream decisions.

The candidate `iter_calendar_population_evidence()` accepts a caller-owned
one-row-per-patient exact-key index relation and streams raw arterial candidates
through read-only temporary tables. It validates original VARCHAR keys,
observed date-only starts and ambiguous source records, scans gas membership
once for the selected keys, and removes temporary tables on normal completion,
early close or error. The projection preserves each candidate's normalized
source code system and code alongside catalog membership for downstream
provenance review. It never chooses the index or classifies a gas. A
200-encounter/100,200-membership-row synthetic comparison returned identical
per-encounter results in 0.020 seconds versus 1.846 seconds for repeated
single-key projection, excluding source verification and trust hashing. This
one-run fixture does not measure the private population or establish source
acceptance; the full-source batch path still needs private runtime validation.

Candidate selection needs encounter-grain gas evidence before the patient
index is chosen. The companion `iter_calendar_encounter_evidence()` uses the
same bulk source scan for a caller-owned relation with unique original
patient/encounter pairs while allowing repeated patients. It returns every
candidate encounter with its raw date-only gas evidence, including encounters
with no catalog-matched gas, so downstream rules can classify encounters
before applying the explicit context-exclusion/index order. Synthetic
repeated-encounter and duplicate-pair fixtures pass. This does not define the
adult emergency/inpatient candidate pool or approve an arterial policy.

The draft `audit_candidate_population()` compares an authenticated historical
patient/index key table supplied by the caller against the unfiltered canonical
`source_encounter` table. It returns aggregate exact-key, patient-present but
index-missing, and patient-absent categories, plus duplicate-start conflicts
and start-precision counts for exact keys. It rejects duplicate, null or
non-string historical keys, leaves all source rows in place, and selects no new
index. A missing start alongside an observed start for the same original key
counts as a conflict. Hand-counted synthetic cases and a read-only
cohort-source integration case exercise the audit. Complete key coverage would
support only one part of the private population gate; source scope and
longitudinal evidence still need
review.

An owner-only candidate run at draft audit revision `92fc880` on the accepted
canonical snapshot passed complete historical patient/index key coverage and
reproduced the prior independent aggregate linkage and conflicting-start
categories. Input identities remained stable; the bounded run took 164 seconds
and peaked at approximately 3.51 GB resident memory. Its restricted receipt is
retained outside Git. This verifies the candidate audit and key coverage only;
it does not approve source scope, issue a population acceptance receipt, or
recover time-of-day precision.

The null-aware conflict correction at `9e92e1f` was rerun on the same accepted
inputs. The exact historical key categories still matched the independent
audit, and the corrected conflicting-start count did not change. Input
identities remained stable; the owner-only, path-free receipt is mode 0600
outside Git. This checks the affected audit behavior, not source acceptance.

The draft `audit_candidate_source_scope()` inventories the historical patient
set through the canonical `source_patient`, `patient_observability`, and
`source_file_inventory` tables. For each clinical domain it reports how many
historical patients have observed records, aggregate event counts, observed
first/last event times, and export-file counts. It includes the raw `meds`
inventory alias for the canonical `medications` domain. These are transfer and
capture diagnostics: a patient without a record is not a clinical negative,
and the first/last observed event does not prove continuous history. Synthetic
and read-only source tests pass; private source-scope review remains pending.
The audit now fails before totaling history if observability has duplicate
patient/domain keys, blank patient IDs, or reversed observed spans.
The presence of medication records also does not establish order activity:
the accepted medication export has no end or status fields, and the canonical
columns contain no populated values for them. The original no-active-order
denominator therefore needs separate source evidence or an approved
unavailability decision.

An owner-only candidate inventory at `4ab72db` passed its structural checks
with stable input identities. Every historical patient had a canonical patient
record; each of the five clinical domains had source files and some observed
records among historical patients. The run took 7.61 seconds and peaked at
approximately 520 MB resident memory. Its path-free, mode-0600 aggregate
receipt remains outside Git. This confirms observable source capture for this
snapshot, not uninterrupted lookback, complete clinical ascertainment, or
source-scope acceptance.
An owner-only rerun at `f89f1d9` passed the stronger structural checks with
stable input identities and the same aggregate inventory. Its corrected,
path-free mode-0600 receipt remains outside Git; source-scope acceptance is
still pending.

A read-only metadata/schema validation of the accepted canonical snapshot on
2026-09-24 passed the existing cohort-source API at schema version `1.0` with
its source-work-manifest binding present. That verifies this reuse path can
open the current source; it does not validate a new receipt, population scope,
timed fields, or the original abstract phenotype.

Define the candidate source scope explicitly before building. It must cover
all encounters and longitudinal evidence needed for the original study and
demonstrate complete coverage of the accepted historical patient/index keys
without deriving its population by filtering to that historical output. Include
ambulatory history even if the primary index later uses emergency/inpatient
encounters. Avoid changing the existing accepted variants or their receipt.

## Acceptance and downstream adoption gates

1. Bind raw export identity, canonical-source manifest, catalog, code revision,
   source scope, and every produced artifact in a new immutable manifest.
   Keep restricted paths and rows outside Git.
2. Validate original key preservation, duplicate/conflicting starts, source
   coverage, event precision, companion evidence, units, and missingness. Report
   aggregate historical key coverage; classify missing patients separately
   from patients present with a different or missing index encounter.
3. Review the candidate source scope and full private reconciliation before
   accepting a new interface. Do not force parity by dropping records or
   relaxing clinical criteria. Record intended source-coverage changes and
   unexplained differences separately.
4. Issue a new private acceptance receipt and pin the versioned upstream
   product in the downstream installed consumer. If the interface references
   canonical tables in place, verify their database identity and provenance
   through the existing read-only source API as part of that boundary. The
   study adapter must never silently fall back from an accepted bundle.
5. Reconstruct the approved patient-index cohort downstream, then compare
   patient membership, index events, context exclusions, recorded medication
   history,
   and named denominators with the historical route. Evaluate intentional
   calendar-date phenotype changes separately from source-coverage changes;
   source-specific arterial, pH and date-boundary validation remains required.

Until these gates pass, the existing accepted encounter bundle remains an
engineering product for its stated compatibility population. The historical
canonical workflow remains a comparison/reproduction path. No report should
label either current variant as the original abstract population.

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

This is a population-interface problem separate from the
[timestamp source gate](GLP1_TIMESTAMP_SOURCE_GAP.md). A new timed export alone
does not make either existing compatibility-backed variant represent the
original patient-level cohort. A new population interface alone does not
restore the original first-24-hour phenotype from date-only events.

## Proposed upstream product

Create a separately named and versioned encounter/evidence product from an
approved manifest-bound TriNetX source. Preserve original `patient_id` and
`encounter_id`, encounter type, raw start/end values and precision, source/HCO
provenance, duplicate source records, stable source-record identity, and linked
clinical evidence. Keep source catalog membership distinct from study inclusion:
the upstream product must not select one patient index, apply GLP-1 exclusions,
or decide medication activity. The downstream study owns those decisions.

The existing read-only `open_cohort_source()` / `validate_cohort_source()`
boundary already exposes versioned canonical source tables with manifest,
schema and catalog checks. Reuse that boundary where it can support the scope:
a new study-facing acceptance policy and receipt may bind an immutable
canonical database and explicit source views in place instead of copying the
entire source database. This is an explicit new accepted interface, not a
silent fallback from a failed encounter-bundle read. The receipt must bind the
exact database identity/bytes, source manifest and schema/catalog revision,
and the installed consumer must verify that trusted identity before opening
rows. A future timed export requires a new immutable canonical product; never
rewrite the accepted date-only database or its existing bundle.

The draft `verify_accepted_cohort_source()` and
`open_accepted_cohort_source()` implement this trust boundary without issuing
an acceptance. They require a caller-supplied receipt SHA-256, exact database
and adjacent sidecar SHA-256/size, matching embedded metadata and catalog,
required element IDs, and passing provenance, source-scope and historical-index
coverage gates in the trusted receipt. The open function reuses the existing
read-only cohort-source API and checks file identity across the read. A
synthetic receipt and database exercise positive and tamper rejection paths;
they do not pass the private gates or authorize downstream adoption. Hashing
the full database is an intentional once-per-open cost to bind exact bytes;
its private runtime is still unmeasured.

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

The draft `audit_candidate_source_scope()` inventories the historical patient
set through the canonical `source_patient`, `patient_observability`, and
`source_file_inventory` tables. For each clinical domain it reports how many
historical patients have observed records, aggregate event counts, observed
first/last event times, and export-file counts. It includes the raw `meds`
inventory alias for the canonical `medications` domain. These are transfer and
capture diagnostics: a patient without a record is not a clinical negative,
and the first/last observed event does not prove continuous history. Synthetic
and read-only source tests pass; private source-scope review remains pending.
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
   patient membership, index events, context exclusions, medication states,
   and named denominators with the historical route. The original first-24-hour
   result additionally requires a timestamp-capable approved source and its
   own temporal/pH-pairing validation.

Until these gates pass, the existing accepted encounter bundle remains an
engineering product for its stated compatibility population. The historical
canonical workflow remains a comparison/reproduction path. No report should
label either current variant as the original abstract population.

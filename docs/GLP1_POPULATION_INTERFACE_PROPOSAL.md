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
   product in the downstream installed consumer. The study adapter must read
   through that trusted boundary; no silent canonical/raw fallback is allowed.
5. Reconstruct the approved patient-index cohort downstream, then compare
   patient membership, index events, context exclusions, medication states,
   and named denominators with the historical route. The original first-24-hour
   result additionally requires a timestamp-capable approved source and its
   own temporal/pH-pairing validation.

Until these gates pass, the existing accepted encounter bundle remains an
engineering product for its stated compatibility population. The historical
canonical workflow remains a comparison/reproduction path. No report should
label either current variant as the original abstract population.

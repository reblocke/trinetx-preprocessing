# Continuity

## Goal (incl. success criteria)
Complete postmerge encounter validation and shared acceptance hardening for the
downstream GLP-1 consumer while preserving the accepted reference behavior.

## Constraints/Assumptions
Preserve FULL_DATA and AFTER_EXCLUSION membership, timing, repeated encounters,
and measurement imputation. No propensity models upstream. Private outputs remain
external. Execute on the Mac mini without changing drive state.

## Key decisions
Reuse accepted transformations; reconcile incompatible source projections before
another private build. Owner approved the one-time authenticated companion import
and targeted audit gates on 2026-09-20. See NEXT_STEPS.md. Publish two
encounter-grain Parquet products with evidence, dictionary, manifest and QA.
Move study analysis without claiming its known scientific defects are repaired.

## State
The encounter split is merged: upstream `main` is at `4bbe8cf`, and downstream
`master` is at `d5d2691`. Postmerge work is in an isolated RESEARCH FAST
worktree; the historical private bundle remains in its existing location.

## Done
Implementation, 10 focused encounter checks, relocated GLP-1 fixtures, bounded
review, lint/format and layout checks complete. All 92 extracted legacy
function/class ASTs match their accepted originals. Reference port untouched.

## Now
All pre-enrichment gates passed. Both legacy variants match authenticated
references across the complete 33/534-field contracts, with zero membership and
missingness differences. Canonical patient/composite-encounter linkage covers
every encounter, with zero demographic or anchor-day disagreements. Corrected
coverage recognizes both medication export families and distinguishes observed
spans from incomplete capture; observed spans do not prove continuous history.
The corrected private build completed both independent variants: FULL_DATA
2,662,675 and AFTER_EXCLUSION 833,476 encounter rows. It used a provenance-bound
recovery cache after earlier memory and file-proliferation failures; all failed
attempts and their artifacts remain preserved. Source/element joins, availability
and the wide output use bounded partitions without changing output semantics.
The full retained-reference comparison passed exact membership and all 33/534
field checks; the separate validator passed all bundle artifacts, schema, source
coverage, inventories and manifest hashes. Peak whole-process RSS was measured
at 7,404,158,976 bytes. The historical private receipt records the earlier
installed pair and gates; it predates the new shared acceptance contract and
cannot authorize the strengthened production reader without revalidation.
Parquet row order is unspecified; consumers explicitly sort by original keys.
Preserve all failed/superseded artifacts, older branches and dirty instructions.

## Next
Version-1.0 shared acceptance verification and validator report binding have
focused synthetic real-Parquet tests passing. Table-specific schema, QA null,
catalogue source-count, coverage/inventory availability, and enumerated
HBA1c/BMI raw-triplet checks have mutation tests. Versioned linkage policies
and cache content fingerprints also have focused tests. The existing private
bundle is being revalidated under the shared private build lock, with scratch
on encrypted RESEARCH FAST; its result is not yet known. Compose a new integrated
receipt through the trusted private process only after all gates pass; merge
upstream before changing the downstream immutable pin and running hosted
installed-pair CI.

## Open questions
Canonical source validated: 837 catalog elements including 303 source concepts.
Canonical compatibility capture uses corrected_v1 and earliest_per_setting;
its encounter population differs from the retained accepted reference.
The authenticated compatibility companion remains the population authority;
independent canonical-projection reconciliation is a separate gate. No new
scientific acceptance is claimed.

## Working set
`encounters/acceptance.py`, validator report, focused acceptance tests and the
postmerge companion ticket; downstream reader and installed-pair gate.

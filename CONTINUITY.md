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
For the original abstract, seek an approved timestamp-capable TriNetX extract;
do not reinterpret its first-24-hour rule from date-only fields.

## State
The encounter split is merged: upstream `main` includes postmerge validation
hardening at `cae58a2`, and downstream `master` includes strict consumer merge
`c2302cb`.
RESEARCH FAST was physically absent at the last disk check; private work uses
an encrypted fallback volume. The historical private bundle remains immutable.

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
catalogue source-count, coverage/inventory availability, enumerated HBA1c/BMI
raw-triplet checks, linkage policies and cache fingerprints have mutation tests.
Fresh complete-linkage coverage and stronger private artifact validation passed
for both variants at merged upstream revision `cae58a2`. Downstream pins that
immutable revision. Its full and installed-pair CI passed, then a private
identity-bound engineering receipt and isolated installed production read
passed for both variants and companion evidence. Downstream PR #18 merged as
`c2302cb` with a Git tree identical to its tested head, and the installed read
passed again through a trust record bound to that merge. None of these gates
establishes the original GLP-1 scientific report.

## Open questions
The accepted source snapshot has date-only encounter starts and clinical events
across the preserved domains. A new approved source export is needed if clinical
event times are available; its feasibility and time-zone semantics are
UNCONFIRMED. See
docs/GLP1_TIMESTAMP_SOURCE_GAP.md. The current bundle remains immutable.
Canonical source validated: 837 catalog elements including 303 source concepts.
Canonical compatibility capture uses corrected_v1 and earliest_per_setting;
its encounter population differs from the retained accepted reference.
The authenticated compatibility companion remains the population authority;
independent canonical-projection reconciliation is a separate gate. No new
scientific acceptance is claimed.
Draft upstream PR #21 proposes a separately accepted GLP-1 population
interface, potentially using the existing versioned read-only cohort-source
API without duplicating the canonical database. Its acceptance, source scope,
and any timed export remain UNCONFIRMED.
The draft now has a caller-trusted receipt verifier and read-only open boundary
that bind exact canonical database and sidecar bytes, metadata, required
elements and declared population gates. Its synthetic tamper test passed. No
private population receipt has been issued or accepted.
An aggregate candidate-population audit now classifies historical patient/index
key coverage, conflicting source start dates and start precision without
selecting an index or returning keys. Synthetic and read-only source tests pass;
the private acceptance gates remain open.
The existing `validate_cohort_source()` API passed a metadata/schema check on
the accepted snapshot at schema `1.0`; this is not a new population or timing
acceptance.

## Working set
`encounters/acceptance.py`, validator report, focused acceptance tests and the
postmerge companion ticket; downstream reader and installed-pair gate.

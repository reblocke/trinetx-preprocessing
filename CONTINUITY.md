# Continuity

## Goal (incl. success criteria)
Implement the approved combined readmissions execution redesign and strict
return-summary consumer, then complete one final private acceptance and ordered
upstream/downstream rollout. Preserve calendar-day contract 2.0, both original
variants, original keys and missingness. The 4–5 hour objective is measured;
all correctness gates and demonstrated runtime improvement remain mandatory.

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
2026-09-29: the owner authorized the combined implementation, private acceptance
and ordered merges, superseding the earlier integration-only session limit.
Isolated branches start at upstream `d81a22b` and downstream `4a57843`.
Failure-first execution/consumer expectations are recorded upstream in
`docs/RETURN_EXECUTION_DESIGN.md`. Both pinned development environments are
ready. Implementation and bounded profiling are active; no redesigned product
is accepted and no final private run has started. Execute at High effort.

Current implementation checkpoint: strict return acceptance/schema/key verification,
bounded downstream reads, exact parent joins and aggregate reporting are implemented.
Synthetic reader/report E2E passes with corruption rejections and explicit nullable
state denominators. Source staging preserves exact typed rows; direct/staged six-table
comparisons pass. Real synthetic source and v2 parent validation, cold/warm
prerequisites, interrupted/resumed production, one/two workers and signed validation
checkpoint reuse pass together. Existing clinical partition E2E and 67 affected
return/parent regressions pass. These are development checks, not installed/private
acceptance. Noneditable installed reader, execution and full producer/consumer
E2Es now pass outside both checkouts on downstream's pinned Python, with retained
artifact readback. The existing installed encounter checks pass. Controller
publication/recovery E2E passes; full regression checks and the bounded staged
resource pilot are active. Private timings remain external. The final private
run has not started. Remaining: review, final installed candidate wheels, pilot
forecast, CI, final private acceptance and ordered rollout.

The following entries are historical checkpoints, not current release claims:

2026-09-29 bounded readmissions integration: base `c81650b`, accepted branch
`82d3bd5`, separate integration checkout. Current main encounter APIs, shared
receipt contract, coverage rules and cache format are preserved. Return parent
validation is isolated in its own module, with its existing failure fixtures.
The original sealed code and runtime remain available. Integration creates a
new package identity; original private acceptance does not transfer to it.
Public verification passed at integration commit `99b2a3a`: 492 pytest cases,
Ruff, format, lock and diff checks; both retained E2E runners and artifact
readback; noneditable wheel and existing consumer API/CLI smoke checks without
PYTHONPATH. All 19 upstream-added regressions ran. Documentation-only updates
follow that frozen source. Hosted CI is separate and is reported on the draft
PR. No private job is authorized in this session. See
docs/RETURN_INTEGRATION.md and docs/RETURN_ACCEPTANCE.md.

Historical merged-encounter checkpoint (predates return integration):
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
Review the integration draft and required CI. After reorganization, complete
fresh private acceptance, the downstream return reader and its retained E2E,
then merge and update the immutable downstream pin. Preserve the original
accepted bundle and runtime throughout. The bounded session starts no recurring
monitor or unattended continuation.

Historical merged-encounter follow-up:
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

## Working set
`encounters/acceptance.py`, validator report, focused acceptance tests and the
postmerge companion ticket; downstream reader and installed-pair gate.

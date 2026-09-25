# Continuity

## Goal (incl. success criteria)
Implement the owner-approved encounter preprocessing split: reusable traditional
and GLP-1 data creation upstream, study analysis downstream, reference port preserved.

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
The approved encounter implementation is merged upstream at `4bbe8cfee3dad3b7c07fb8c42d7217804150b650` and downstream at `d5d269168eafc7905c9238a5486fc03a62b55ec3`. Both required hosted CI checks passed. The current checkout started clean at the upstream merge head; this ticket's edits are local and uncommitted.

## Done
Implementation, 10 focused encounter checks, relocated GLP-1 fixtures, bounded
review, lint/format and layout checks complete. All 92 extracted legacy
function/class ASTs match their accepted originals. Reference port untouched.

## Now
The opt-in return-outcome contract and separate build/validation commands are
implemented locally in isolated worktree `codex/readmissions-20260924`.
C0 copied the uncommitted encounter hardening baseline without changing the
original checkout; its 109 encounter tests passed. The accepted parent manifest
and canonical source sidecar hashes agree. A locked aggregate profile found
date-only encounter starts/ends, missing/conflicting index episode ends, and
shared ED/inpatient source IDs. A source-catalog preflight found that the
accepted catalog lacked ICD-10-CM-specific exact rules for four J96 codes.
A follow-up aggregate query found rows for all five exact codes in the canonical
diagnosis table; the four J96 codes have exact wildcard code-system rules that
capture ICD-10-CM rows. The source-capability check was corrected and now
passes. No private row-level return product has been published.
The locked C1 forward-coverage profile has now completed for both variants.
It reconciles to 2,662,675 FULL_DATA and 833,476 AFTER_EXCLUSION original
keys, records unavailable index anchors separately, and shows that last
observed events often precede the 365-day horizon. The aggregate receipt is
external; it does not establish continuous follow-up or complete capture.
The canonical database's full byte SHA-256 baseline was recorded externally
before any outcomes pilot or build, with unchanged source/parent manifest
identities. Fourteen focused return tests pass on the current code. The full
suite passed 516 tests on the immediately preceding validator revision; a
final full run remains due after the episode/source mapping check. Ruff, lock,
non-editable wheel, and installed CLI/legacy-consumer smokes passed on earlier
revisions and must be rerun as applicable before acceptance. An earlier full run had one intermittent
combined compatibility-export worker failure; that test passed in isolation
and in a later unchanged full run. These checks do not satisfy the missing
resource pilot or C4 acceptance seal. The return validator now independently
recomputes episode/source mapping, link times and categories, link flags from
diagnosis/gas evidence, and summaries; synthetic tampering checks include an
uncertain link omitted from summaries.

This ticket adds versioned per-table Parquet evidence contracts, independent
feature-missingness and source-coverage reconciliations, explicit strict versus
permitted-incomplete linkage policy, manifest-bound validation reports and
receipt verification helpers, and deterministic duplicate-preserving content
fingerprints for reusable stage tables. The follow-up fixes let the validator
read older policy-free bundles without modifying them, recompute linkage and
baseline eligibility from Parquet, and reject incomplete report/receipt
identities. The full encounter suite passed 109 tests; the focused validation
and coverage suite passed 62 tests. Ruff, `git diff --check`, and affected
local Markdown link checks passed. Verification used the pinned uv environment
with an external temporary cache and `uv run --offline --no-sync`. No
encounter membership, retained value, timing rule, or evidence content changed.
The earlier 24-test run with pytest scratch on RESEARCH FAST and 33-test focused
rerun remain historical evidence for the preceding hardening pass; its task-owned
scratch was removed. RESEARCH FAST is not currently mounted.

The historical handoff reports that all pre-enrichment gates passed. Both legacy variants match authenticated
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
at 7,404,158,976 bytes. The prior continuity note reports a private acceptance
receipt and exact installed-pair evidence, but the receipt was not found in a
bounded search of currently accessible external volumes; its identity and
current gate state remain UNCONFIRMED here. No new private data scan or build
was run. Upstream PR14 and downstream PR15 are now verified merged with passing
required CI, correcting the old active instructions below.
Parquet row order is unspecified; consumers explicitly sort by original keys.
Preserve all failed/superseded artifacts, older branches and dirty instructions.

## Next
For return outcomes, use the documented absence of transfer and discharge
fields in source_encounter_flow and perform a resource pilot, then one locked
private outcomes-only build with
independent validation, byte-unchanged input proof, and an external acceptance
seal. Recheck the exact source/parent identities before the private run.

In the Mini private handoff, use the existing shared lock to
revalidate the immutable accepted bundle, run downstream comparator and installed
consumer readback, and verify the trusted receipt against exact manifest/report
identities. Do not rebuild unless a concrete data-affecting discrepancy requires
it. See [docs/ENCOUNTER_RELEASE.md](docs/ENCOUNTER_RELEASE.md).

## Open questions
Canonical source validated: 837 catalog elements including 303 source concepts.
Canonical compatibility capture uses corrected_v1 and earliest_per_setting;
its encounter population differs from the retained accepted reference.
The source/input boundary needs reconciliation; no scientific acceptance claimed.

## Working set
Encounter builder and relocated GLP-1 modules; focused pytest, Ruff,
source/output comparison and normal repository checks.

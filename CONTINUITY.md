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
identities. On the preceding return code at `e21c6ed`, sixteen focused tests
and the full suite passed 520 tests with 238 existing performance warnings.
Ruff check and format, `uv lock --check --offline`, `git diff --check`, and
non-editable wheel installation all passed. The installed wheel's code identity
matches the checkout; the new return commands and old cohort-source consumer
smokes passed without `PYTHONPATH`. Earlier full runs on changing code and an
intermittent compatibility-export worker failure remain historical evidence;
the frozen pass supersedes them. These checks do not satisfy the unfinished
resource pilot or C4 acceptance seal. The return validator now independently
recomputes episode/source mapping, link times and categories, link flags from
diagnosis/gas evidence, and summaries; synthetic tampering checks include an
uncertain link omitted from summaries.
An initial pilot launcher was stopped before pilot output because an external
helper named `profile.py` shadowed Python's standard module and started an
unintended read-only aggregate query. Its evidence was preserved externally.
The corrected 32-partition resource pilot completed one entire patient bucket
in each variant. Its external receipt passed source/parent identity,
summary-key, artifact-hash, and free-space checks. The first full outcomes-only
build stopped during required parent-bundle validation, before any return
partition, with DuckDB out of memory at the validator's fixed 1 GiB limit.
Its external receipt, log, and work are preserved. The encounter validator
now accepts an optional memory cap while keeping its old 1 GiB default;
opt-in return validation requests 4 GiB. No retry or acceptance is claimed. Independent
return validation, post-build source byte comparison, and the external
acceptance seal remain pending.
The final bounded-validator code passed 71 affected tests and 522 full-suite
tests with 238 existing performance warnings. Ruff check and format, offline
lock check, non-editable wheel installation, and isolated old/new consumer
smokes also passed; an external C3 receipt binds those checks to code identity
`63ecb329b10d902acfa925e2bfdb28aa65eb6f2df1f2b4f09316a41924b66b17`.
A separate 4 GiB parent preflight also failed at the same exact distinct
aggregation. The opt-in validator now writes two complete, hash-partitioned
scratch projections and sums exact per-partition distinct counts; default
encounter validation remains unchanged. Seventy-one affected tests pass.
The locked full-scale bounded preflight passed that memory stage, then found
the accepted schema 2.0 parent bundle lacks `event_datetime_precision` in
diagnosis, procedure, and medication evidence for both variants. All other
required columns were present in the schema audit. The producer retains raw
`date` and `event_datetime` in those tables but does not emit the required
precision field. No full return product or seal exists. This is BLOCKED on an
explicit owner schema-version decision; do not waive the validator or rebuild
the accepted parent under this ticket.

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
For return outcomes, obtain an explicit schema-version decision for the
accepted parent evidence gap. A new accepted parent bundle with explicit
precision, or an approved versioned rule proving equivalent precision from
retained source fields, must then pass the complete parent validator. Only
after that gate and refreshed C3 checks may a new external full-build attempt
run; preserve all failed receipts and work. On terminal completion,
independently validate the separate bundle, prove accepted source/parent
artifacts byte-unchanged, and write the external acceptance seal. Cross-ID
continuations remain unconfirmed because the flow table has no transfer or
discharge authority.

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

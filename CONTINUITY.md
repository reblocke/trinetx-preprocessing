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
Implementation in isolated worktrees from verified merged source heads.

## Done
Implementation, 10 focused encounter checks, relocated GLP-1 fixtures, bounded
review, lint/format and layout checks complete. All 92 extracted legacy
function/class ASTs match their accepted originals. Reference port untouched.

## Now
Both corrected private legacy bases passed the complete retained-reference gate:
FULL_DATA 2,662,675 encounters and 33 fields; AFTER_EXCLUSION 833,476 encounters
and 534 fields. Membership and missingness differences are zero; all retained
values satisfy their declared exact/continuous rules. Both variants are unique
by original composite key. Reference identity and immutability checks passed.
Canonical patient/encounter linkage, demographics and anchor-day agreement
passed for every encounter. A medication source-file audit alias mismatch made
the first history report label available medication data unavailable; that
report is preserved but superseded. Coverage now recognizes both canonical
medication export families and rejects unexplained audit/observability conflicts.
Rerun coverage before enrichment; no clinical enrichment has started. All failed attempts and reference
implementations remain preserved. Final source pin, installed-pair checks,
private enriched-artifact acceptance and coordinated merges remain pending.

## Next
Pass canonical source linkage/history coverage, then build and validate
clinical enrichment. Bind private acceptance to the exact
source pair and producers, verify the installed downstream pin and final CI,
and merge UP14 before DOWN15.

## Open questions
Canonical source validated: 837 catalog elements including 303 source concepts.
Canonical compatibility capture uses corrected_v1 and earliest_per_setting;
its encounter population differs from the retained accepted reference.
The source/input boundary needs reconciliation; no scientific acceptance claimed.

## Working set
Encounter builder and relocated GLP-1 modules; focused pytest, Ruff,
source/output comparison and normal repository checks.

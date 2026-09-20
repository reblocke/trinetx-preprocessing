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
Both independent private legacy bases completed at producer ba7470b:
FULL_DATA 2,662,675 encounters; AFTER_EXCLUSION 833,476. All 36 partitions were
read and cleaned, with peak whole-process RSS 8,577,777,664 bytes. The retained
reference comparator is running; matching counts alone do not establish parity.
Bounded reader allocations and wide publication use the existing enrichment SQL
cap after pandas release. The actual output volume creates AppleDouble metadata
companions; future inventories now exclude those companions without deleting
them. Eight affected adapter, coverage and validation tests and Ruff pass.
The existing legacy bundle and its producer identity remain unchanged.
No clinical enrichment has started. All failed stagings, the older branch and
dirty instructions remain preserved.

## Next
Pass the complete retained-field comparison and source linkage/history coverage,
then build and validate clinical enrichment. Bind private acceptance to the exact
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

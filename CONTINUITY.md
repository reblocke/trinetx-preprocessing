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
The authenticated import passed exact text-frame parity for all 36 partitions.
Bounded ordinal reads, preallocated columns and equal-string sharing preserve
accepted frames; all four adapter regressions pass. The latest private attempt
read and cleaned every FULL_DATA partition and wrote its intermediate, then
failed during wide joined Parquet publication at the 512 MiB ingestion cap.
Publication now uses the existing 2816 MiB enrichment cap after pandas frames
are released. Metadata is checkpointed before publication. Validate that exact
boundary on a copy of the preserved intermediate before another complete run.
Private membership acceptance remains pending; no clinical enrichment started.
All failed stagings, the older branch and dirty instructions are preserved.

## Next
Pass the full-data publication probe, rebuild and compare both independent
legacy bases, then pass
source linkage/history coverage before clinical enrichment. Validate all
artifacts, bind private acceptance to the source pair and final producer,
verify installed downstream pin and final CI, and merge UP14 before DOWN15.

## Open questions
Canonical source validated: 837 catalog elements including 303 source concepts.
Canonical compatibility capture uses corrected_v1 and earliest_per_setting;
its encounter population differs from the retained accepted reference.
The source/input boundary needs reconciliation; no scientific acceptance claimed.

## Working set
Encounter builder and relocated GLP-1 modules; focused pytest, Ruff,
source/output comparison and normal repository checks.

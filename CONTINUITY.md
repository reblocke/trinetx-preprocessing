# Continuity

## Goal (incl. success criteria)
Implement the owner-approved encounter preprocessing split: reusable traditional
and GLP-1 data creation upstream, study analysis downstream, reference port preserved.

## Constraints/Assumptions
Preserve FULL_DATA and AFTER_EXCLUSION membership, timing, repeated encounters,
and measurement imputation. No propensity models upstream. Private outputs remain
external. Execute on the Mac mini without changing drive state.

## Key decisions
Reuse accepted transformations and canonical source projections. Publish two
encounter-grain Parquet products with evidence, dictionary, manifest and QA.
Move study analysis without claiming its known scientific defects are repaired.

## State
Implementation in isolated worktrees from verified merged source heads.

## Done
Reference checkouts preserved; pure transformation extraction started.

## Now
Implement source-projection input, GLP-1 enrichment and safe publication.

## Next
Focused tests, one private integrated build/comparison, bounded review and CI.

## Open questions
None on the approved scope. Private source coverage remains to be checked.

## Working set
Encounter builder and relocated GLP-1 modules; focused pytest, Ruff,
source/output comparison and normal repository checks.

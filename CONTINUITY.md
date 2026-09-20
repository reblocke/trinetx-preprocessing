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
Private build failed at encounter-context deduplication under the 2816-MiB
DuckDB cap; retained intermediates remain external. The focused query-width/
key-scope repair at 8b19b7f passed targeted checks and CI, but not a private build.
Early FULL_DATA membership comparison also failed; investigate source compatibility
before restarting expensive enrichment or merging.

## Next
Continue from NEXT_STEPS.md on the Mini: repair both input/key adapters and the
comparator contract/authentication; pass legacy and independent enrichment
coverage gates before the private build. Bind acceptance to the source pair and
bundle, then test the installed pinned pair and final CI.
Merge upstream first and then downstream only after those checks pass.

## Open questions
Canonical source validated: 837 catalog elements including 303 source concepts.
Canonical compatibility capture uses corrected_v1 and earliest_per_setting;
its encounter population differs from the retained accepted reference.
The source/input boundary needs reconciliation; no scientific acceptance claimed.

## Working set
Encounter builder and relocated GLP-1 modules; focused pytest, Ruff,
source/output comparison and normal repository checks.

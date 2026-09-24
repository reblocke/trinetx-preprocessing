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
at 7,404,158,976 bytes. The private acceptance receipt and linked PRs record
the exact installed-pair, hosted-check and merge state separately.
Parquet row order is unspecified; consumers explicitly sort by original keys.
Preserve all failed/superseded artifacts, older branches and dirty instructions.

## Next
For release, verify the final installed downstream pin, hosted checks and private
acceptance bound to the source pair and producers. Merge UP14 before DOWN15.

## Open questions
Canonical source validated: 837 catalog elements including 303 source concepts.
Canonical compatibility capture uses corrected_v1 and earliest_per_setting;
its encounter population differs from the retained accepted reference.
The source/input boundary needs reconciliation; no scientific acceptance claimed.

## Working set
Encounter builder and relocated GLP-1 modules; focused pytest, Ruff,
source/output comparison and normal repository checks.

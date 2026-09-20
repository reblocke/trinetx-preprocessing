# Current repository state

Updated 2026-09-19. Python encounter preprocessing is implemented here; validation
and publication status are recorded in CONTINUITY.md and the linked PR.
See [ENCOUNTER_PREPROCESSING.md](ENCOUNTER_PREPROCESSING.md) for the command,
products, timing, identifiers, missingness and verification boundary.
The initial private build failed, and its legacy population differs from the
accepted reference. The interface is not yet privately validated. Follow
[NEXT_STEPS.md](../NEXT_STEPS.md) before another build or merge.

The manifest-bound DuckDB remains the canonical captured source. Its existing
compatibility projections feed the extracted accepted Python transformations
in memory. Both encounter variants retain repeated encounters and their
original rules. The 36-file CSV/DTA workflows remain available through the
preserved reference implementation.

GLP-1 study cohort/eligibility/prevalence code and configuration have moved to
trinetx-hypercapnia-code. Shared source normalization and terminology remain here.
Historical source acceptance at 9fe392b and the frozen Stata reference remain
unchanged; they are not receipts for this new encounter interface.
Historical details remain in VALIDATION.md and GLP1_SOURCE_ACCEPTANCE.md.

The owner-approved extraction uses downstream merged source 5ada7194d40f.
The earlier pause awaiting a stable cohort head is superseded by this explicit
refactor. Unadjudicated Stata outpatient-MAT source codes remain candidates,
not a validated medication-assisted-treatment phenotype.

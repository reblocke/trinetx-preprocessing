# Current repository state

Updated 2026-09-25. Python encounter preprocessing is implemented and merged.
Public merge and hosted CI state, historical private-run reports, unverified
private gates, and the supported revalidation/build workflows are summarized in
[ENCOUNTER_RELEASE.md](ENCOUNTER_RELEASE.md). Product definitions and commands
remain in [ENCOUNTER_PREPROCESSING.md](ENCOUNTER_PREPROCESSING.md).

The manifest-bound DuckDB remains the canonical captured source. An authenticated DuckDB companion now supplies the original
compatibility snapshot to the accepted Python transformations; canonical
clinical tables supply enrichment. The owner authorized this one-time import
on 2026-09-20 to preserve legacy membership. Both sources remain read-only. Both encounter variants retain repeated encounters and their
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

An opt-in, separate return-outcome interface is implemented for review in
[RETURN_CONTRACT.md](RETURN_CONTRACT.md). Exact wildcard catalog rules retain
the required J96 diagnosis rows; the initial source-capability check was too
narrow and has been corrected. An earlier v1 resource pilot completed, but its
full build stopped during parent validation. The [return audit](RETURN_AUDIT.md) identifies
an inherited producer/validator precision-schema mismatch and additional return
implementation defects. The owner resumed C0–C4 on 2026-09-25 after the E2E-first testing cleanup;
see [the testing review](testing_review.md). The accepted [calendar-day v2
contract](RETURN_CONTRACT.md) governs the implemented opt-in v2 builder and
validator. Its public and synthetic checks pass; full accepted-parent
validation passed on the preceding code after exact bounded-memory and
producer-count repairs. The opt-in v2 builder now uses a 4 GiB DuckDB cap; v1
remains at 1 GiB. A final-code resource pilot passed both variants with
independent partition validation and external hash receipts. Fresh parent
validation is running for the current code identity. C3 private proof and C4
remain gated by that result. Existing
encounter products and cohort-source interfaces are preserved.

# Current repository state

Updated 2026-09-29. Python encounter preprocessing is implemented and merged.
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

The separate, opt-in [calendar-day v2 return contract](RETURN_CONTRACT.md) now
has C0–C4 engineering acceptance. A current-code exact accepted-parent check,
two-variant resource pilot, one locked outcomes-only build, independent full
validation and terminal seal audit passed. The accepted build completed both
variants across 64 patient partitions; all output hashes, schemas, original
keys, evidence and summaries were checked, and canonical-source and parent
bytes were unchanged. The synthetic E2E also covers same-ID ED/inpatient
progression and an unlinked possible transfer across distinct IDs. See the
[return acceptance record](RETURN_ACCEPTANCE.md) for evidence identities,
commands and scientific limits. Earlier failed or rejected builds and the
[2026-09-25 return audit](RETURN_AUDIT.md) remain historical evidence. The
opt-in v2 builder uses a 4 GiB DuckDB cap; v1 remains at 1 GiB. Existing
encounter products, the 36-file bridge and cohort-source interfaces remain
unchanged.

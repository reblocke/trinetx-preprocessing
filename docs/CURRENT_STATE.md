# Current repository state

Updated 2026-09-24. Python encounter preprocessing is implemented here. The
original split merged at upstream `4bbe8cf` and downstream `d5d2691`;
postmerge validator hardening is on upstream `main` at `cae58a2` and the strict
downstream consumer merged as `c2302cb`. This is the current public status
summary; private source, bundle and receipt
identities remain in the owner-only release record.
See [ENCOUNTER_PREPROCESSING.md](ENCOUNTER_PREPROCESSING.md) for the command,
products, timing, identifiers, missingness and verification boundary.
The authenticated companion route passed the complete legacy population/value
and canonical linkage/coverage gates. A corrected private build completed both
independent variants. The full retained-reference comparison passed. Fresh
complete-linkage coverage and stronger artifact validation passed at the merged
upstream revision. A private identity-bound engineering receipt and an isolated
installed production read passed for both variants and companion evidence;
downstream full and installed-pair CI passed at the immutable merged pin. The
downstream merge tree matches the tested consumer head. Scientific acceptance
for the original patient-level GLP-1 abstract remains separate; see
[NEXT_STEPS.md](../NEXT_STEPS.md).
Aggregate source audits found that this accepted snapshot preserves only
date-level encounter starts, arterial gas events, and other clinical-domain
events. The original abstract's
first-24-hour gas rule requires a new approved timestamp-capable source; see
[the timestamp source gate](GLP1_TIMESTAMP_SOURCE_GAP.md).
The accepted medication export also lacks end and status fields, leaving the
original documented no-active-order denominator unavailable from this source.
Draft source-capability auditing can now summarize parsed versus date-only
event precision across encounter starts, labs, catalog-matched arterial PaCO2
and pH candidates, and medication starts, plus medication end/status capture and raw-header field
presence, without returning rows or paths. It is a candidate-source screen;
the accepted source limitation and scientific report gate are unchanged.
The read-only `audit-cohort-source-capabilities` command exposes this screen
through a validated canonical source and labels both acceptance and abstract
report readiness false.
A separate `screen-glp1-export-headers` command accepts explicitly listed
proposed encounter, lab and medication CSVs and reads their headers only. It
reports fixed aggregate field-presence counts without paths, raw header names
or clinical rows. It is a pre-build triage aid, not precision or source
acceptance; see the timestamp source gate.
An owner-only accepted-snapshot CLI run at `ab77abd` reproduced the date-only
and absent medication end/status findings with stable source identity; its
restricted aggregate receipt remains outside Git.
An owner-only header screen of two archived 2022 raw export layouts found the
same date-field pattern without separate time-of-day or medication end/status
columns. It did not inspect values or rule out a current alternative extract.
Draft population-interface work has a trusted canonical-source verifier and an
aggregate historical-key audit. An owner-only candidate run at `92fc880`
reproduced independent key-coverage categories with stable input identities;
this is not a new accepted source population or a timed extract. See the
[population interface proposal](GLP1_POPULATION_INTERFACE_PROPOSAL.md).
An additional owner-only candidate inventory found canonical patient records
for the historical population and observed records plus source files in all
five clinical domains. It does not establish continuous history or clinical
ascertainment; the source-scope acceptance gate remains open.
The draft scope audit now rejects duplicate observability keys, blank patient
IDs, and reversed event spans before inventory totals. Its affected private
rerun preserved the prior aggregate inventory and input identities; this is
still structural evidence only.

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

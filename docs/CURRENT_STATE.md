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
events. The owner accepted a revised patient-level calendar-date gas phenotype using
the first arterial testing date on D or D+1; see the
[precision audit and decision](GLP1_TIMESTAMP_SOURCE_GAP.md). The historical
elapsed first-24-hour rule remains unavailable from this snapshot.
The accepted medication export also lacks end and status fields, leaving the
original documented no-active-order denominator unavailable from this source.
The downstream historical-scope audit found GLP-1 catalog matches only in the
ingredient-named export family, so confirmed recorded orders are also
unavailable. The owner approved a separately labeled coded source-family
descriptor on 2026-09-25; event role and terminology review still gate its
actual exhibit. No email or new timestamp acquisition is authorized.
Draft source-capability auditing can now summarize parsed versus date-only
event precision across encounter starts, labs, catalog-matched arterial PaCO2
and pH candidates, and medication starts, plus medication end/status capture and raw-header field
presence, without returning rows or paths. It is a candidate-source screen;
the accepted source limitation and scientific report gate are unchanged.
It now also inventories arterial numeric values, mmHg unit labels, specimen
and panel identifiers, and same-day groups containing both arterial elements.
Those aggregate groups do not establish that panel IDs mean one specimen.
The read-only `audit-cohort-source-capabilities` command exposes this screen
through a validated canonical source and labels both acceptance and abstract
report readiness false.
The candidate bulk calendar gas projection now reads caller-supplied exact
patient/encounter keys through temporary read-only tables. Its original
one-index-per-patient route remains available, and a separate encounter-grain
route allows repeated candidate encounters for a patient before index
selection. Both stream one raw evidence result per exact encounter and clean
temporary tables on exit. Each candidate now retains its normalized source
code system and code as well as catalog membership, so a downstream
missing-specimen policy can check the actual record. Synthetic
repeated-encounter, parity and cleanup
tests pass; private population-scale runtime and clinical mapping remain
unvalidated.
A separate read-only vital projection accepts one exact selected index per
patient and an explicit vital catalog element ID. It streams all matched raw
vital rows across that patient's encounters, preserves source dates, precision,
values, units and record keys, and emits an empty marker for patients without
matches. This prepares a BMI evidence review without choosing a measurement,
normalizing units or treating index-day BMI as pre-presentation evidence.
Synthetic exact-key, duplicate-membership, absence and duplicate-key checks
pass; source hierarchy and clinical BMI policy remain unresolved.
A separate read-only diagnosis/lab/procedure history projection now takes one exact
selected index per patient, an explicit catalog element and its domain. It
streams all matched source rows across encounters with raw date, precision,
code, value, unit and source-file fields, and marks patients with no match.
An explicit multi-element route unions declared catalog concepts in one source
scan and emits each raw record once even when it matches several concepts.
Every requested concept must be present in the declared domain; this enables
the preserved broad NIV/IMV and separate CPAP code sets to be projected without
using the narrow CPT-only GLP-1 seed as their replacement.
It does not call a missing match negative, apply the D-1 history cutoff, or
classify T2D; source roles, terminology, capture and clinical rules still need
review. A procedure candidate retains its original code and date; it does not
implement the broader legacy NIV/IMV definitions. Synthetic cross-encounter,
duplicate-membership, union, absence and key tests
pass.
An owner-only full-source gas-policy audit completed with stable source
identity but revealed a candidate parser mismatch: observed compact date-only
strings were counted as invalid by an ISO-only draft check. The candidate
parser and batch projection now handle both observed date forms. The audit's
field-capture categories show absent specimen and specimen/panel link IDs in
these catalog-matched candidates. The corrected owner-only audit at `3844ea0`
found no invalid candidate dates and passed stable source-identity and private
receipt read-back checks. Separate owner-only fixed-category checks found
exact configured arterial LOINC code lineage and UCUM `[pH]` on source-code
pH rows. Clinical source-policy review remains required before a phenotype
estimate; absent sample links cannot support a paired-pH claim.
An additional candidate audit now counts fixed categories for arterial unit,
specimen, numeric, date and same-day linkage evidence without releasing raw
labels or source keys. It has no CLI yet. Its results inform a future reviewed
clinical mapping policy; they do not accept one.
Its fixed unit hints now include UCUM `[pH]` as a separately counted category.
A separate `screen-glp1-export-headers` command accepts explicitly listed
proposed encounter, lab and medication CSVs and reads their headers only. It
reports fixed aggregate field-presence counts without paths, raw header names
or clinical rows. It is a historical diagnostic aid, not precision or source
acceptance; see the precision audit.
An owner-only accepted-snapshot CLI run at `ab77abd` reproduced the date-only
and absent medication end/status findings with stable source identity; its
restricted aggregate receipt remains outside Git.
An owner-only header screen of two archived 2022 raw export layouts found the
same date-field pattern without separate time-of-day or medication end/status
columns. It did not inspect values or establish source-specific clinical timing.
Draft population-interface work has a trusted canonical-source verifier and an
aggregate historical-key audit. An owner-only candidate run at `92fc880`
reproduced independent key-coverage categories with stable input identities;
this is not a new accepted source population or a timed extract. See the
[population interface proposal](GLP1_POPULATION_INTERFACE_PROPOSAL.md).
A separate candidate source-wide sizing audit counts encounter and patient
rows, key/date/type/birth-year field coverage, and approximate distinct keys
without selecting a cohort. Approximate key values guide engineering capacity
only; they cannot serve as a denominator or establish source acceptance.
An owner-only source-wide run completed with stable source identity and private
receipt read-back in 2.57 minutes. The date parser covered all observed
date-only encounter starts; only a minority of raw rows had an in-scope type
hint. The full-source distinct-key estimate overran the raw row count, so it
remains a coarse capacity signal. No full population was staged or accepted.
A candidate read-only calendar field projection now groups raw encounter
records at exact patient/encounter grain and joins patient birth-year evidence.
It exposes observed start date, normalized encounter type and birth year only
when the corresponding source rows agree, with separate missing/conflict QA.
Invalid source keys are counted, not silently incorporated. Synthetic
read-only, duplicate, conflict, empty and rollback checks pass. It does not
apply adult/type/context eligibility or select the study population.
A separate type-hint helper stages exact keys with any raw `EMER` or `IMP`
record. A scoped field projection rejoins all encounter rows for each hinted
key, preserving conflicting type evidence. Synthetic mixed-type and read-only
checks pass; the hint is a capacity tactic and no eligibility rule is approved.
An owner-only full-source scoped projection completed in 5.13 minutes with
reconciled exact hint/projected keys, stable source identity, empty scratch and
private receipt read-back. It surfaced nonzero duplicate-record and conflicting
start-date categories outside the historical patient scope. This remains
engineering feasibility evidence; the unresolved starts need explicit handling
before a new patient index can be selected.
A packaged type-hint candidate helper now composes key staging, all-record
rejoin and field consensus with scoped count checks and temporary-stage
cleanup. Synthetic mixed-type, read-only and prior-output rollback fixtures
pass. It still only exposes candidate fields and cannot accept a population.
An owner-only packaged-API full-source run completed in 5.69 minutes and
matched every aggregate QA field from the prior manual scoped projection.
Source identity, private receipt read-back and scratch cleanup passed. This
is aggregate API parity, not full row parity or source acceptance.
An owner-only cross-repository aggregate check found every authenticated
historical exact index key in the packaged type-hint scope, with stable input
identities and private receipt read-back. New patient/index membership,
exclusions and clinical qualification remain unreconciled.
An owner-only aggregate conflict-pattern follow-up reconciled exactly to the
scoped projection with stable identity and private receipt read-back. The
conflicts span multiple calendar-day ranges and often involve more than two
raw rows. A single observed `source_id` value within each conflicting key did
not resolve its start date. No source-date tie or correction policy is approved.
Owner-only aggregate checks on the historical patient scope found complete
exact historical index-key presence and date/type/historical-age-proxy
agreement at those keys, with age-18 boundary uncertainty still present.
Source identities and private receipt read-backs passed. This does not
accept the independent source population or a revised patient index.
The candidate per-encounter calendar projection preserves exact original
keys, raw observed dates, units and sample identifiers. It fails on
conflicting starts or undated arterial candidates; synthetic tests pass.
It is not a bulk clinical adapter or an accepted-source estimate.
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

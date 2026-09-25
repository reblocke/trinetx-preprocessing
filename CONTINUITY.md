# Continuity

## Goal (incl. success criteria)
Complete postmerge encounter validation and shared acceptance hardening for the
downstream GLP-1 consumer while preserving the accepted reference behavior.

## Constraints/Assumptions
Preserve FULL_DATA and AFTER_EXCLUSION membership, timing, repeated encounters,
and measurement imputation. No propensity models upstream. Private outputs remain
external. Execute on the Mac mini without changing drive state.

## Key decisions
The owner accepted a calendar-date GLP-1 abstract phenotype and prohibited
all email sending. A new read-only candidate source projection keeps raw
arterial values, units and linkage identifiers at the exact original
patient/encounter key; it fails on conflicting date-only starts or undated
arterial candidates. Synthetic tests pass. It does not accept a population,
normalize clinical gas values, or produce a report.
A bulk candidate projection now takes a caller-selected one-index-per-patient
relation, validates exact keys and source starts, scans gas membership once,
streams raw encounter candidates and drops temporary tables on exit. Eighteen
focused single/bulk tests pass. A one-run 200-index/100,200-membership-row
synthetic comparison matched the single-key results in 0.020 versus 1.846
seconds; it excludes trust hashing and is not private-scale validation.
The same bulk core now exposes an encounter-grain route for repeated candidate
encounters before choosing one patient index. It requires unique exact
patient/encounter pairs but does not require patient uniqueness; the original
selected-index route still does. Synthetic repeated-patient, duplicate-pair
and cleanup fixtures pass. Neither route chooses the clinical candidate pool
or accepts the source.
A separate candidate calendar-field projection now builds one temporary row
per valid original encounter key from all source encounter rows, joins
patient birth-year evidence, and records missing or conflicting starts,
encounter types and birth years without choosing a value arbitrarily.
It counts invalid encounter-key rows and returns aggregate QA. Synthetic
read-only, conflict, empty and rollback checks pass. Adult/type/context
eligibility and age interpretation remain downstream study decisions.
A one-run 200,000-encounter/100,000-patient in-memory synthetic build under a
512 MB DuckDB limit took 0.127 seconds; this excludes canonical-source
verification and is not a private runtime measurement.
Two owner-only aggregate historical-patient-scope audits completed in 3.6 and
3.9 minutes. The second independently reproduced the first source-field and
descriptor categories, found every historical exact index key present, and
found concordant source date, encounter type and historical age proxy at those
keys. Age-18 boundary cases were present. Both runs used the same stable
source identities and mode-0600 receipt read-back. They do not cover extra
source patients, clinical gas qualification or new patient-index selection.
A separate source-wide aggregate sizing audit completed in 2.57 minutes on the
canonical encounter and patient tables, with stable source identity, no
remaining scratch and mode-0600 private receipt read-back. All observed
encounter starts were parseable date-only values; a minority of raw rows had
an in-scope type hint. Its approximate all-key estimate exceeded the raw row
count and is only an engineering capacity hint. Test scoped candidate staging
before full-source materialization; no cohort or source has been accepted.
A candidate type-hint key staging helper now preserves exact hinted keys and
requires rejoining all their source encounter rows before field consensus.
Synthetic mixed-type and read-only checks pass. An owner-only full-source
scoped projection completed in 5.13 minutes with reconciled exact hinted and
projected keys, stable input identity, empty scratch and mode-0600 private
receipt read-back. Duplicate rows and nonzero conflicting start dates were
surfaced in the broader source population. Do not select an index from an
unresolved start; no type, adult or context rule has been approved.
A separate owner-only aggregate start-conflict audit reconciled exactly to the
scoped projection in 3.39 minutes, with stable source identity, empty scratch
and mode-0600 receipt read-back. Conflicting starts span several day ranges,
often with more than two source rows, and each conflicting key had one observed
`source_id` value. This does not identify a correct start; retain uncertainty
until an explicit scientific source/index policy is approved.
The aggregate candidate capability audit now also reports arterial numeric,
unit, specimen and panel-field capture plus same-day linkage groups. These are
source-mapping diagnostics, not clinically validated gas pairs.
A separate fixed-category gas-policy audit now inventories catalog-matched
arterial key/date completeness, normalized unit and specimen classes, numeric
ranges and same-day specimen/panel group multiplicity. Focused synthetic tests
pass. It returns no raw labels or keys and does not approve clinical mapping.
An owner-only first attempt exceeded a 3 GiB DuckDB query limit. A bounded
6 GiB retry revealed repeated large source joins and was stopped before it
produced a receipt. The audit now materializes the matched candidate set once
in temporary tables and cleans them on exit. An owner-only run at `f598ab6`
then completed in 1,394.25 seconds
with stable input identities and mode-0600 read-back. It exposed the draft
ISO-only date-check error against observed compact `YYYYMMDD` source dates;
specimen and specimen/panel link IDs were absent in the catalog-matched
candidates. The parser, batch start check and audit now accept both observed
date-only forms. Fixed unit-label hints include UCUM `mm[Hg]` and `[pH]`.
A corrected owner-only audit at `3844ea0` found no invalid candidate dates,
confirmed absent specimen/sample-link IDs, and passed stable source identity
and mode-0600 receipt read-back. Separate owner-only fixed-category checks
found exact configured arterial LOINC membership with source-code agreement
for every candidate and UCUM `[pH]` on all source-code pH rows. These are
review inputs, not source or clinical-policy acceptance; no linked-pH or
report claim follows.
Owner decision on 2026-09-24 supersedes the earlier timestamp-acquisition
plan: day precision is fixed, the missing times cannot be obtained, and email
contact is prohibited. The downstream patient-level abstract now uses the
accepted D/D+1 first-testing-date PaCO2 rule, with pH separately labeled and
recorded prior orders descriptive. Earlier source-contact and timestamp-source
notes below are historical. Population/source and report-science acceptance
remain open.

Reuse accepted transformations; reconcile incompatible source projections before
another private build. Owner approved the one-time authenticated companion import
and targeted audit gates on 2026-09-20. See NEXT_STEPS.md. Publish two
encounter-grain Parquet products with evidence, dictionary, manifest and QA.
Move study analysis without claiming its known scientific defects are repaired.
For the revised patient-level abstract, use the owner-approved D/D+1
calendar-date rule and retain the historical timed selector only for
reproduction. The source-population interface remains a separate gate.

## State
The encounter split is merged: upstream `main` includes postmerge validation
hardening at `cae58a2`, and downstream `master` includes strict consumer merge
`c2302cb`.
RESEARCH FAST was physically absent at the last disk check; private work uses
an encrypted fallback volume. The historical private bundle remains immutable.

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
at 7,404,158,976 bytes. The historical private receipt records the earlier
installed pair and gates; it predates the new shared acceptance contract and
cannot authorize the strengthened production reader without revalidation.
Parquet row order is unspecified; consumers explicitly sort by original keys.
Preserve all failed/superseded artifacts, older branches and dirty instructions.

## Next
Version-1.0 shared acceptance verification and validator report binding have
focused synthetic real-Parquet tests passing. Table-specific schema, QA null,
catalogue source-count, coverage/inventory availability, enumerated HBA1c/BMI
raw-triplet checks, linkage policies and cache fingerprints have mutation tests.
Fresh complete-linkage coverage and stronger private artifact validation passed
for both variants at merged upstream revision `cae58a2`. Downstream pins that
immutable revision. Its full and installed-pair CI passed, then a private
identity-bound engineering receipt and isolated installed production read
passed for both variants and companion evidence. Downstream PR #18 merged as
`c2302cb` with a Git tree identical to its tested head, and the installed read
passed again through a trust record bound to that merge. None of these gates
establishes the original GLP-1 scientific report.

## Open questions
The accepted source snapshot has date-only encounter starts and clinical events
across the preserved domains. The owner-approved D/D+1 revision supersedes the
previous timestamp-source search. No email contact is authorized. See
docs/GLP1_TIMESTAMP_SOURCE_GAP.md. The accepted bundle remains immutable.
An owner-only, path-free aggregate medication audit found that the accepted
raw export lacks order end and status fields, and the corresponding canonical
columns have no populated values. The source identity remained stable; its
mode-0600 receipt is outside Git. This separately blocks the original
documented no-active-order denominator from this snapshot.
Canonical source validated: 837 catalog elements including 303 source concepts.
Canonical compatibility capture uses corrected_v1 and earliest_per_setting;
its encounter population differs from the retained accepted reference.
The authenticated compatibility companion remains the population authority;
independent canonical-projection reconciliation is a separate gate. No new
scientific acceptance is claimed.
Draft upstream PR #21 proposes a separately accepted GLP-1 population
interface, potentially using the existing versioned read-only cohort-source
API without duplicating the canonical database. Its acceptance, source scope,
and any timed export remain UNCONFIRMED.
The draft now has a caller-trusted receipt verifier and read-only open boundary
that bind exact canonical database and sidecar bytes, metadata, required
elements and declared population gates. Its synthetic tamper test passed. No
private population receipt has been issued or accepted.
An aggregate candidate-population audit now classifies historical patient/index
key coverage, conflicting source start dates and start precision without
selecting an index or returning keys. Synthetic and read-only source tests pass;
the private acceptance gates remain open.
An owner-only run at audit revision `92fc880` passed historical key coverage,
matched the prior independent aggregate categories and kept input identities
stable. It took 164 seconds with approximately 3.51 GB peak RSS; the receipt
is mode 0600 and path-free. Source-scope and timing acceptance remain open.
The draft conflict audit now counts a missing start alongside an observed start
for the same original key as a conflict. The prior private conflict receipt was
made before this correction. An affected private aggregate rerun at `9e92e1f`
passed with stable input identities and unchanged conflict count. Its path-free
mode-0600 receipt is outside Git; source-scope, timing and scientific acceptance
remain open.
The draft source-scope inventory now summarizes canonical demographic presence,
five-domain observed records, event counts, observed spans and export-file
counts for the historical patient set. Synthetic and read-only source tests
pass. It does not establish continuous history or clinical negatives.
An owner-only scope inventory at `4ab72db` passed structural checks with stable
inputs: all historical patients have a canonical patient record, and all five
clinical domains have files and observed records. It took 7.61 seconds with
approximately 520 MB peak RSS. The receipt is path-free and mode 0600. Full
source-scope review, timing and scientific acceptance remain open.
The scope audit now fails on duplicate patient/domain observability, blank
patient keys, and reversed observed spans. At `f89f1d9`, an affected owner-only
rerun passed with stable input identities and unchanged aggregate inventory.
The first comparison script wrote a failed receipt because it compared a Python
tuple with a JSON list; its failed receipt is preserved. The corrected rerun
normalizes the aggregate representation, passed, and wrote a separate path-free
mode-0600 receipt outside Git. This remains structural evidence, not acceptance.
The existing `validate_cohort_source()` API passed a metadata/schema check on
the accepted snapshot at schema `1.0`; this is not a new population or timing
acceptance.
The draft source-capability audit now counts encounter-start, lab-event and
medication-start precision, parsed versus unparsed timestamp-labeled rows,
populated medication end/status fields and raw-header field presence from a
validated canonical connection. Thirteen focused capability/scope/population
tests plus Ruff pass. The owner closed timestamp-source acquisition;
calendar-date arterial provenance and clinical acceptance remain open.
The candidate capability audit is now available as a read-only CLI command
against a validated canonical product. It emits aggregate JSON only and marks
source acceptance and abstract readiness false. A command test uses
a synthetic canonical build. An owner-only accepted-snapshot run at `ab77abd`
completed in 162 seconds, with stable source identity, clean spill storage,
mode-0600 path-free receipt and date-only/absent medication-field findings
matching prior independent audits. The receipt remains outside Git. Neither
source nor scientific/report acceptance is established.
A path-free, mode-0600 header-only receipt now records two archived 2022 raw
TriNetX layouts. Encounter, lab and medication headers have date fields but no
separate time-of-day or medication end/status fields. No clinical values were
read, so this is historical source-layout context, not a current-source or
phenotype acceptance decision. No time-source acquisition is planned.
Earlier public-product and inquiry research is superseded by the owner's
fixed day-resolution decision. No emails may be sent. Historical source
capability screens remain evidence of the accepted snapshot only.
Draft header-only proposed-export triage now takes explicit encounter, lab and
medication CSV paths, reads only their headers, and returns path-free aggregate
field-presence counts with source/report acceptance false. Synthetic CLI tests
cover fixed output and path-free errors. This does not prove that any new
source contains actual clinical timestamps or order history.
The validated canonical-source capability audit now also separates included
catalog-matched arterial PaCO2 and pH candidate precision from all labs. It
counts each source record once even if membership has duplicate rows and does
not establish arterial provenance, index linkage or first-gas/pH pairing.
The audit fails closed if either arterial catalog element is absent; zero
observed candidates now means the catalog element was available to search.

## Working set
`encounters/acceptance.py`, validator report, focused acceptance tests and the
postmerge companion ticket; downstream reader and installed-pair gate.

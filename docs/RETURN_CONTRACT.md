# Return outcomes contract (calendar-day v2)

The owner accepted D1–D6 as the implementation basis and explicitly resumed the readmissions goal on 2026-09-25. This is the frozen scientific contract for the opt-in return product; the original v1 text is retained in [RETURN_CONTRACT_V1.md](RETURN_CONTRACT_V1.md). C0–C4 acceptance gates remain binding. Parent bundle schema 2.0 and cohort-source schema/catalog fingerprints remain unchanged. Parent validator compatibility has its own version. All private inputs and outputs remain external.

## 1. Population and source boundaries

Retain exactly one summary per original composite key in each parent variant,
independently, including unavailable and not-applicable outcomes. Preserve
recurrent index encounters. Use the validated canonical source for all available
encounter, diagnosis and gas history of these patients, including return
encounters that never qualified for the original cohort.

Inputs are immutable. All private work, spill, row products, logs and acceptance
receipts remain external. The 36-file compatibility contract, legacy values,
inclusion rules, dependencies and downstream files remain unchanged.

## 2. Dates, anchors and windows

The primary time scale is **calendar days**. An observed date is represented as
a date, not an inferred instant at midnight. Retain raw source values and original
precision as provenance when available. This product does not require hours,
minutes or within-day order. Timestamp-valued source observations, if encountered,
use their recorded calendar date under this explicitly day-based contract;
original timestamps remain evidence and do not rescue same-day ordering.

Let `D0` be the observed, non-derived, nonconflicting index episode end date.
Let `Dr` be an observed, non-derived, nonconflicting return start date.
Define `days_after_index_end = Dr - D0` using integer calendar-day subtraction.

| Observation | Primary result |
|---|---|
| `1 <= days_after_index_end <= 30` | In 30-, 90- and 365-day windows |
| `31 <= days_after_index_end <= 90` | In 90- and 365-day windows |
| `91 <= days_after_index_end <= 365` | In 365-day window |
| Distinct encounter starts on `D0` | Same-day uncertain; not a confirmed return |
| Encounter overlaps the index episode end | Overlap/possible continuation; not a confirmed return |
| Unknown, invalid, derived or conflicting relevant date | Explicit unavailable/uncertain reason |
| Known start more than 365 days later | Outside the outcome horizon |

For example, with an index end of January 2, January 3 is day 1 and February 1
is day 30. A January 2 presentation has uncertain order. This is a calendar-day
endpoint; it does not claim exactly 720 elapsed hours for a 30-day window.

Compute each criterion's first qualifying **date** independently within each
window. Provide integer days to that event. Do not present a midnight timestamp
as a measured first-event time; any retained compatibility timestamp field must
be NULL for this day-based result and documented accordingly.

Missing/derived index ends produce unavailable outcomes for that index. They
do not exclude the summary row and are not filled from legacy variables, later
encounters, last observations or the flow table. NULL or mixed precision must
not be promoted to known precision. A validated raw-date proof can establish
day resolution where a legacy precision metadata field is absent.

## 3. Episode and category rules

The composite `(patient_id, encounter_id)` is the source encounter identity.
Preserve every source row and its multiplicity. Use a versioned, explicit setting
mapping. Unknown types cannot establish an acute return.

Same-ID continuation rule: after allowing duplicate source rows, each
setting component has one distinct observed start/end pair, with valid order.
An ED/inpatient progression requires
`ED start <= inpatient start <= ED end <= inpatient end`, evaluated as dates.
It uses the ED start and inpatient end as episode boundaries. Other arrangements
remain conflicting or unsupported until an additional rule is approved. This
allows differing component dates without waiving contradictions merely because
both types are present. Exact expected cases must accompany implementation.

Do not merge distinct IDs solely because dates overlap or are adjacent. Without
authoritative cross-ID transfer linkage, retain that uncertainty. Do not infer
a discharge or transfer from `source_encounter_flow`.

Report inpatient, ED-only, any ED and acute-care union separately. An ED/inpatient
episode appears once in the acute-care union, belongs to inpatient and any ED,
and is not ED-only. Recurrent episodes remain separate.

Applicability: inpatient returns after inpatient indexes are readmissions;
inpatient returns after ED-only indexes are admissions. Known nonacute index keys
remain present with `not_applicable` primary return outcomes. An unknown setting
has unavailable applicability, with a distinct reason. Any desired generic
post-outpatient admission endpoint would need its own explicit definition.

## 4. Diagnosis and gas qualification

Preserve exact ICD-10-CM `J96.02`, `J96.12`, `J96.22`, `J96.92`, `E66.2`
qualification on the return episode. Historical or broad J96 diagnoses do not
qualify. Retain all candidate evidence and rejection reasons.

Retain the explicit specimen catalog, unit conversions, raw/converted values,
source identifiers and multiplicity. Any usable return-episode measurement can
qualify; there is no pH requirement or index-route restriction. Do not add a
new physiological plausibility cutoff without a separate scientific decision.

Clinical evidence date rule: require episode linkage and an event
date inside an observed, coherent episode interval, inclusively by date. If the
return end is missing, derived or conflicting, the all-cause event can still
qualify from its valid start, but the interval-dependent phenotype is unavailable;
retain its linked evidence with the reason. A future rule accepting encounter-ID
linkage alone for phenotype qualification would need a separate decision.

For each specimen and each threshold, `true` means at least one usable positive
measurement; `false` means at least one usable measurement and none positive;
NULL means no usable measurement. Rejected rows and measurements of the other
specimen cannot turn NULL into false.

Retain separate ABG/VBG >45, >50, >=45 and >=50 fields, with explicit units.
Add unambiguous paired gas unions:

- `gas_abg_gt45_or_vbg_gt50`;
- `gas_abg_ge45_or_vbg_ge50`.

Keep any same-cutoff unions only with explicit names and definitions. Define
separate ICD-or-gas composites for strict and inclusive thresholds. The inclusive
composite is exact qualifying ICD OR ABG >=45 OR VBG >=50. An ICD-positive episode
can establish that composite without a gas. Absence of a qualifying ICD is an
absence of qualifying recorded evidence, not proof of clinical absence.

For a gas-only union, true means any usable included specimen meets its threshold;
false means at least one included specimen was usable and no measured specimen
met its threshold; NULL means neither specimen was usable. An unmeasured second
specimen does not erase a negative observation in the measured specimen, and is
still NULL in its own specimen-specific result. For ICD-or-gas composites, a
qualifying ICD establishes true; otherwise use that gas-union three-state result.

## 5. Counts, flags, uncertainty and follow-up

Counts describe **confirmed observed events**, not complete capture of all events.
For an applicable, evaluable index, zero confirmed events is a valid observed
count. For an unavailable or not-applicable index, primary counts, flags and first
dates are NULL; preserve a separate reason. Do not encode unavailable as zero.

Expose counts for every temporal state and relevant reason, including same-day,
overlap, missing start, derived start, conflicting start, unknown precision and
invalid order. Record these by category/window when the date permits assignment;
undated uncertainty stays separate and must not be assigned an invented window.
For conflicting dates spanning a boundary, preserve possible-window membership
without arbitrarily selecting a single date to decide eligibility.

Horizon flag rule: positive if at least one confirmed qualifying event
exists; otherwise NULL if unresolved candidate timing could change the result.
A negative flag must be defined as no qualifying event in the evaluable observed
set, never as complete ascertainment. Supply confirmed counts alongside that flag.
Known day-zero and known pre-end overlapping starts are outside the day-1-through-N
endpoint by definition; retain their uncertainty counts, but they alone do not
make that endpoint's flag NULL. Undated/conflicting candidates whose possible
start could fall in the window can change an otherwise false flag to NULL.

For gas-related horizon flags, a positive measurement establishes true. With no
positive result, retain NULL if any relevant confirmed return lacks usable testing
or interval eligibility. False requires at least one relevant return and all such
returns to be evaluable and negative for that criterion. No usable gas stays NULL.
Publish tested, untested and phenotype-unavailable return counts so this rule can
be audited. This explicitly resolves the current normal-plus-untested ambiguity.

Keep last observed event, observation relative to each horizon, and recorded death
month separate. Neither last observation nor death month supplies an exact censor
date. Do not claim continuous coverage, unplanned readmission, causation or complete
capture. Label the entire product as outcomes, not baseline predictors.

## 6. Parent precision compatibility proof

Introduce an explicitly versioned parent-validation rule for the recognized
schema 2.0/feature-contract 1.0 producer representation. Its scope is the six
diagnosis/procedure/medication component artifacts lacking the explicit field.

1. Validate parent/source provenance, artifact hashes, required original fields
   and types. Unexpected missing columns or representations still fail.
2. For diagnosis/procedure use retained raw `date`; for medication use `start_date`.
   Require supported date-only syntax, a real parseable calendar date, nonmissing
   values when an event is present, agreement with parsed `event_datetime`, and
   no contradictory parsed time of day for this legacy day-only proof.
3. Project proven `date_only` precision in a validation view or ephemeral external
   derived table. Never rewrite accepted Parquet or its manifest. Preserve row
   multiplicity and reconcile row totals, including typed empty domains.
4. If an explicit precision field is present, check its consistency; do not
   silently override it. Unrecognized/mixed representations fail this compatibility
   proof and require an applicable versioned rule or an explicit decision.
5. Retain every other parent validation gate and issue a report stating which
   representation was validated. Acceptance-receipt readers must recognize and
   verify the new validation-contract version explicitly.

This corrects a representation mismatch while requiring equivalent information.
It does not authorize a blanket assumption that every timestamp is date-only,
or a generic exemption from missing-column validation. No parent schema/catalog
fingerprint is changed.

## 7. Repair and acceptance sequence

| Stage | Work | Exit gate |
|---|---|---|
| A. Agree definitions | Adopt day windows, applicability, episode coherence, evidence eligibility, threshold unions and NULL rules; record the decision | Versioned contract and hand-authored expected fixtures |
| B. Repair implementation | Fix F1–F7, complete dictionary, fresh scratch for resume, symmetric path checks | Actual producer/validator integration; day-boundary, null, rejected-gas and real-resume regressions |
| C. Strengthen proof | Independent source/evidence/link/summary reconstruction with bounded partitions | Both-direction multiset comparisons; every adversarial corruption rejected; fresh/resumed/partitioned full artifacts agree |
| D. Establish readiness | Cheap full schema/capability checks, complete immutable-parent validation, trusted parent receipt, frozen code checks, refreshed installed runner and resource evidence | Every pre-build gate passes on the exact code/config/contract; no truncation or exception-by-test-edit |
| E. Execute C4 | One locked full outcomes-only build of both variants, then full validation and byte comparisons | External seal binds source, parent, output, producer, validator, configuration, contracts and all required gates |

Re-run affected tests during repairs, then the full suite, Ruff, lock and installed
wheel/old-consumer checks on the frozen candidate. Keep old tolerances and fixture
expectations unchanged. Pilot the validator as well as the builder at realistic
scale. Previous failed attempts remain preserved; changed code cannot resume
old return partitions under a different identity.

Unknown outcomes for individual rows are valid contract results. A failed identity,
compatibility proof, completeness check, runtime gate or unresolved scientific
definition blocks acceptance of the bundle. **DONE still requires C0–C4.**

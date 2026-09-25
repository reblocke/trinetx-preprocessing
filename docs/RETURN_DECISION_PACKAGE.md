# Return outcomes: decisions and completion plan

Status: **proposed; D1–D6 await the owner's decisions; goal remains BLOCKED**.
Prepared 2026-09-25 from the [audit](RETURN_AUDIT.md) and
[calendar-day proposal](RETURN_DAY_RESOLUTION_PROPOSAL.md). No runtime changes
or private builds are authorized by this document itself. Existing C4
authorization remains conditional on its gates; the owner has requested this
decision package before unblocking the goal.

## Decisions for the owner

The choices below affect scientific meaning. The software defects in the next
section have concrete repairs and do not require choosing whether to fix them.

| ID | Decision | Recommendation | Alternative and consequence |
|---|---|---|---|
| D1 | What time scale defines a return? | Calendar-day difference 1–30, 1–90 or 1–365 from observed index episode end. Keep day-zero events as same-day uncertainty. Use dates and integer days for first events. | A hybrid rule could use actual within-day timestamps when available. It would create different same-day eligibility by source precision and offers no benefit for the profiled day-only encounters. |
| D2 | When do same-ID ED/inpatient records form one episode? | Require coherent component dates, allowing duplicate records. Each setting has one distinct valid observed interval; require ED start <= inpatient start <= ED end <= inpatient end. Otherwise retain conflict/unsupported status. | Grouping solely by shared ID and taking min/max retains more episodes but can conceal contradictory records. No automatic cross-ID merging under either choice. |
| D3 | Which index settings have applicable return outcomes? | Inpatient index -> inpatient readmission; ED-only index -> inpatient admission. Known nonacute indexes have not-applicable primary outcomes; unknown settings have unavailable applicability. Retain every original row with the distinct reason. | A generic post-outpatient admission endpoint could include other known index settings, but would broaden the outcome definition and require separate names. |
| D4 | Can a return with an unusable end date establish a phenotype? | A valid observed start can establish an all-cause return, provided chronology is not invalid. Require a coherent observed start/end interval for diagnosis/gas qualification; otherwise the phenotype is unavailable and evidence remains retained. | Encounter ID plus a dated event after the return start could establish the phenotype without a known end. This retains more evidence but cannot enforce an observed discharge boundary. |
| D5 | How should counts, flags and timing uncertainty relate? | Counts are confirmed observed events. Unavailable/not-applicable indexes have NULL primary counts/flags. For valid indexes: positive if a confirmed event exists; otherwise unknown if unresolved candidate timing could place an event in the window; otherwise false for the observed window. Preserve all uncertainty reasons separately. | Setting every evaluable zero count's flag to false is simpler, but loses the distinction between no confirmed event and unresolved window membership unless users always consult the uncertainty fields. |
| D6 | How should mixed tested/untested returns affect a gas phenotype over a window? | Any qualifying positive establishes true. Without a positive, use unknown if any relevant return is untested or otherwise unevaluable. False requires at least one relevant return and all such returns evaluated and negative. Publish positive, tested, untested and unavailable counts. | A tested-only flag would be false when the measured subset is normal, even if another return is untested. That answers a narrower question and must be named as such. |

Recommended package: adopt all six recommendations. D4 and D6 most directly
trade evaluability for conservative phenotype qualification. D2 may also mark
additional source episodes unavailable. These changes affect the new return
product; they do not remove original index rows or change legacy outcomes.

### Clarifying D5: day zero versus unknown window membership

Under D1, a known same-day start is excluded from the day-1-through-N endpoint
by definition. It still contributes to the same-day uncertainty count, since
within-day order is unknown. It does not alone make the day-1-through-N flag
NULL. Similarly, a known pre-end overlapping start is outside that endpoint.

An undated start or conflicting possible starts that could land inside the
window can make an otherwise zero-event flag NULL. Counts still report zero
confirmed observed events. Unknown individual outcomes are legitimate results;
failure to preserve or validate them is an acceptance failure.

### Clarifying D6 with examples

Assume a valid applicable index and no unresolved timing that could affect the
specified window. Examples below use ABG >=45 mmHg:

| Observed confirmed returns | Positive count | ABG phenotype flag |
|---|---:|---|
| One return with usable ABG 40 | 0 | false |
| One return with ABG 40; another without usable ABG | 0 | NULL |
| One return with ABG 50; another without usable ABG | 1 | true |
| Only rejected ABG measurements | 0 | NULL |
| No confirmed returns | 0 | NULL, with separate no-return/testing state |
| Index anchor unavailable | NULL | NULL |

A gas-only ABG/VBG union is evaluated from the usable specimens: a positive in
either establishes true; at least one usable specimen with neither positive
establishes false; neither usable gives NULL. Specimen-specific results retain
their own missingness. A qualifying exact ICD can establish an ICD-or-gas
composite even without a gas. Without a qualifying ICD, use the gas-union state.
An unavailable diagnosis/gas episode interval under D4 remains an explicit
phenotype-availability limitation.

## Requirements already settled by the goal

Retain exact ICD-10-CM J96.02/J96.12/J96.22/J96.92/E66.2 qualification. Publish
strict ABG >45 OR VBG >50 and inclusive ABG >=45 OR VBG >=50 gas unions, and
their explicitly named ICD-or-gas counterparts. Preserve all requested individual
threshold flags. The preprocessing product need not choose a study's primary
threshold; downstream analysis can select among these documented outcomes.

Keep all original keys independently in both variants, recurrent events and
the inpatient/ED-only/any-ED/acute-union categories. Preserve the canonical source,
parent bytes, 36-file compatibility contract, legacy behavior and dependency
pins. Do not infer transfer linkage, exact death dates, continuous capture or
unplanned readmission. Real products and receipts remain external. These are
existing constraints, not choices to relax to obtain a pass.

## Repair strategy

| Audit finding | Implementation strategy | Required evidence |
|---|---|---|
| F1: parent precision mismatch | Recognize the actual schema-2.0 producer representation through a new validation-contract version. Prove precision from raw date/start_date in a read-only projection; leave parent files unchanged. Require parseability, agreement with parsed dates, no contradictory time, expected types and complete row counts. | Actual producer output passes; malformed/missing raw dates, contradictory precision, unexpected missing fields and altered hashes fail. Complete private parent validation still required. |
| F2: NULL precision fall-through | Handle NULL explicitly and preserve mixed/unknown component precision. Permit only the documented proof to recover a known date. | Hand-authored known/NULL/mixed/invalid precision cases; no unsupported precision becomes available or confirmed. |
| F3: false gas flags | Compute usable testing availability before thresholds. Apply D4/D6 and explicit gas-union truth tables. | No gas, rejected-only, other-specimen-only, exact boundary, converted unit, normal-plus-untested and positive-plus-untested cases. |
| F4: missing links pass | Independently derive the complete expected candidate-link set from index anchors and episodes. Compare missing and extra rows, including duplicate multiplicity and uncertain candidates. Prove source-to-episode coverage as well. | Deleting a link and consistently changing its summary/hashes fails; added/duplicated/cross-patient links and consistently omitted source episodes fail. |
| F5: invalid evidence passes | Recompute normalization, specimen/ICD qualification and date eligibility from source-bound evidence; independently check anchor, death and observability fields. | Raw 450 mmHg with normalized 45 fails; changing rejection labels, source fields, eligibility, multiplicity or anchors cannot pass via rehashing. |
| F6: resume scratch collision | Allocate fresh attempt-scoped validation scratch, preserve old failures, enforce output/work separation in both directions and non-symlinked locations. | Interrupt/resume using the real parent validator; fresh/resumed results agree across every table; changed input/code/configuration and unsafe paths fail. |
| F7: lost summary uncertainty | Enumerate every temporal state and account for each candidate, including uncertain window membership. Complete the typed dictionary with units, applicability and NULL meanings. | State totals and each criterion's counts/flags/first dates reconcile independently; no rejected or ambiguous candidate disappears silently. |

Use hand-authored expected fixtures and independently written validation logic;
do not construct all expected values from the builder's formulas. Include a
small complete source -> parent -> returns -> validation integration path with
real manifests, rather than stubbing the affected boundaries.

Make validation operate on bounded patient partitions. Check partition ownership,
key uniqueness and totals across the full bundle. Run inexpensive schema and
capability gates before large aggregations. Measure resource use without reducing
rows or changing exact comparisons. Keep existing default interfaces and legacy
expectations unchanged; version new return semantics explicitly.

## Path to completion after the owner unblocks the goal

| Checkpoint | Work | Exit evidence |
|---|---|---|
| C0: re-establish baseline | Verify worktree/input identities and recover the trusted parent acceptance receipt through bounded searches of documented handoff locations. Check its report/manifest/reference bindings. Preserve original checkout and failed attempts. | Baseline identities and acceptance provenance established; missing proof is reported BLOCKED. A complete manifest alone is insufficient. |
| C1: freeze the agreed contract | Record the owner's D1–D6 choices in DECISIONS.md; finalize return v2, dictionary and exact expected examples. Bind the parent compatibility-validation version separately. | Reviewable specification and fixtures with no remaining definition ambiguity. No private parent schema change. |
| C2: implement repairs | Fix F1–F7 in reviewable commits, retaining legacy APIs/defaults and all original keys. | Targeted regression and real-boundary integration checks pass. |
| C3: establish proof | Run adversarial validation, complete-table fresh/resume/partition equivalence, unchanged legacy fixtures, full pytest, Ruff, lock check, non-editable wheel and isolated old/new consumer smokes. | Evidence tied to frozen source/code/configuration/contract. Prior 522-test receipts are historical, not substitutes. |
| C4 readiness | Complete read-only parent/source validation under the shared lock. Refresh private runner/receipt versions. Pilot both builder and validator on the final code with realistic partitions and adequate free space. | All input, scientific, correctness and resource gates pass before a full outcome build starts. |
| C4 execution and acceptance | One locked, complete, outcomes-only build of both variants; no row truncation. Independently validate outputs, hashes, schemas and keys, compare immutable input bytes, and seal the evidence externally. | Complete build AND full validation AND unchanged-input proof AND provenance-bound acceptance seal. Only then mark DONE. |

Acceptance provenance is a factual gate, not a vote to deem a receipt valid.
If the historical parent receipt cannot be recovered and validated, report the
exact missing evidence. Any replacement acceptance process must establish the
required proof on the immutable bundle; do not fabricate a historical receipt
or rebuild the private baseline under this goal.

The earlier pilot implies about **38 hours for the old builder alone** by linear
extrapolation, plus validation and byte comparisons. This is not a completed-run
measurement or a promise for repaired code. Re-estimate using the final pilot;
avoid broad performance refactoring unless a measured resource gate requires it.

On any failed gate, preserve the attempt, record the reason, diagnose before
retry, and remain BLOCKED if resolution requires missing data or an owner
decision. Do not relax comparisons, modify expected legacy results, or declare
completion from build status alone. Unblocking starts this sequence; it does not
skip directly to the long private build.

# Return implementation audit — 2026-09-25

Historical audit of an earlier revision. The repaired calendar-day v2 build
passed C0–C4 engineering acceptance on 2026-09-29; see the current
[return acceptance record](RETURN_ACCEPTANCE.md). The status and next actions
below describe the audited revision, not the current accepted build.

Status: **C2/C3 require repairs; C4 remains BLOCKED.** This audit reviews
`a5338f5` on `codex/readmissions-20260924`, whose package code identity is
`63ecb329b10d902acfa925e2bfdb28aa65eb6f2df1f2b4f09316a41924b66b17`.
It covers the new return builder, validator, CLI, tests and the inherited
encounter-validator contract that stopped the private run. It does not apply
new scientific rules or change the accepted input products.

## What the precision block means

The existing [return contract](RETURN_CONTRACT.md) already supports calendar
dates. Its timestamp branch is conditional on timestamps actually being known;
the absence of hours/minutes is not itself a reason to reject day-only returns.

The immediate exception is a producer/validator schema mismatch. The inherited
hardening requires `event_datetime_precision` in diagnosis, procedure and
medication component evidence. The unchanged producer emits the raw date and
parsed `event_datetime`, but does not add that column. Both encounter variants
therefore fail the new validation requirement. The parent still declares
schema 2.0 and feature contract 1.0; the hardening did not introduce a producer
schema transition for those fields.

This is metadata about precision, not a demand for finer timestamps. For
example, raw `20240105` establishes the calendar date 2024-01-05. A parsed
timestamp stored at midnight does not establish that the event occurred at
midnight. A `date_only` label can be proven from the retained raw value without
inventing a time of day.

External read-only aggregate receipts cover all six affected artifacts. They
report date-only raw representations, successful calendar-date parsing, and
agreement with parsed dates, without parsed time-of-day values. They support
a narrowly versioned compatibility proof. They do not establish complete
follow-up, clinical eligibility, or acceptance of a return bundle. Exact private
identities, counts and receipt paths remain outside this repository.

The affected files are **baseline component evidence in the parent**. The return
builder uses that parent for index keys and provenance, and obtains new encounter,
diagnosis and gas history from the canonical database. Its encounter source
already has start/end precision fields. Requiring a parent rebuild solely to
populate redundant metadata is unnecessary if a versioned validator can prove
the same information from the immutable legacy representation.

## Work implemented

- An isolated worktree preserves the original checkout's uncommitted hardening.
- `build-returns` and `validate-returns` are opt-in CLI entry points. The output
  is a separate bundle with independent FULL_DATA and AFTER_EXCLUSION keys.
- The builder produces episode/source mapping, episodes, diagnosis evidence,
  gas evidence, index-to-return links, summaries, a typed dictionary, progress
  checkpoints and artifact hashes. It partitions by patient.
- Implemented rules include recurrent returns, same-ID ED/inpatient aggregation,
  separate acute-care categories, exact ICD matching, explicit gas unit conversion,
  threshold variants, same-day/overlap states, observed follow-up and coarse death.
- Resume checks bind source/parent/code/configuration and completed artifact hashes.
  The validator checks artifact identities, keys and several internal reconciliations.
- A private resource pilot completed one patient bucket in both variants. The full
  build attempt failed before producing return partitions. Exact parent distinct
  counting was subsequently partitioned to get past the first memory failure.

The existing record contains 71 affected tests and 522 full-suite tests passing,
plus Ruff, lock, wheel and isolated consumer checks. Those are useful historical
checks of this revision. The new adversarial findings below mean **C3 is not
complete**. The new return diff does not change the legacy transformations,
cohort-source API, dependency declarations or lockfile; the inherited validator
regression still needs repair to preserve compatibility.

## Confirmed defects and reproducible gaps

Priorities: P1 must be resolved before private acceptance; P2 must be resolved
before relying on the affected interface. Locations refer to the audited revision.

### F1 — P1: validator rejects the unchanged producer's evidence schema

Locations: [validation.py](../src/trinetx_preprocessing/encounters/validation.py),
lines 50–136 and 929–930;
[feature_sources.py](../src/trinetx_preprocessing/encounters/feature_sources.py),
lines 103–111, 156–164 and 651–659.

A synthetic call to the actual diagnosis evidence producer produces a table
missing exactly `event_datetime_precision` from the validator's required set.
This reproduces the private failure without private data. Validator fixtures
are generated from `EVIDENCE_CONTRACTS`, so they supply the field the real
producer omits. Rebuilding with the unchanged producer would reproduce the gap.

Repair: define and test the existing schema 2.0 representation, add a versioned
raw-date precision proof for these legacy tables, and retain every other schema,
type, identity, linkage and reconciliation check. Test actual producer output
against the validator. Do not remove the precision assurance or modify the parent.

### F2 — P1: NULL precision can become an available anchor or confirmed return

Locations: [returns.py](../src/trinetx_preprocessing/encounters/returns.py),
lines 136–139, 179–181 and 207–218;
[return_validation.py](../src/trinetx_preprocessing/encounters/return_validation.py),
lines 177–188.

SQL `NULL NOT IN (...)` is NULL, so the CASE skips the intended unknown state.
A synthetic index with NULL end precision remained `available`; a return with
NULL start precision became `confirmed`. Also, `count(DISTINCT precision)` ignores
NULLs, so combining known and unknown source rows can incorrectly yield a known
episode precision. The validator repeats this logic.

Repair: handle NULL explicitly; define aggregation of mixed or missing precision;
use a separate expected-result oracle. Unknown precision must remain unknown
unless a validated raw-date proof establishes the applicable date rule.

### F3 — P1: rejected or other-specimen gas rows produce false link flags

Location: [returns.py](../src/trinetx_preprocessing/encounters/returns.py),
lines 349–369; the same expression is repeated in the validator, lines 122–138.

For an episode whose gas rows are all rejected, the link has
`abg_tested=false` and `abg_gt45=false` instead of a NULL threshold result.
The same problem affects an unmeasured specimen when only the other specimen is
present. The summary can correctly be NULL while its underlying link says false.

Repair: first determine whether each specimen has any usable measurement, then
emit a threshold flag only when it was tested. Specify how untested episodes
affect a horizon-level flag when another episode has a normal gas. Add named
specimen-specific combined thresholds rather than relying on ambiguous unions.

### F4 — P1: validation checks present links but does not prove link completeness

Location: [return_validation.py](../src/trinetx_preprocessing/encounters/return_validation.py),
lines 234–237 and 474–556.

The geometry query starts from existing links. It never compares the full
expected candidate-link set against the actual set. A synthetic same-day link
was removed, its summary uncertainty count was changed to zero, and all artifact
hashes/receipts were refreshed. The full internal return validator still passed.
The retained episode/source tables still contained the omitted event.

Repair: independently generate expected links from the validated index anchors
and complete episode table; compare both directions, including uncertainty and
duplicates. Prove source encounter/evidence completeness against canonical
source projections, not solely internal consistency among output artifacts.

### F5 — P1: evidence normalization and rejection labels are trusted

Location: [return_validation.py](../src/trinetx_preprocessing/encounters/return_validation.py),
lines 120–166 and 506–526.

Changing a synthetic gas row to raw **450 mmHg** while leaving its normalized
value **45 mmHg**, refreshing its hashes, and retaining existing outcomes still
passes the internal return validator. It aggregates stored `value_mmhg` and
`rejection_reason`; it does not independently recompute conversion, specimen
eligibility, exact ICD qualification or date eligibility from retained fields.
Index anchor state, death and observability fields also lack complete independent
reconciliation against their authoritative sources.

Repair: recompute clinical qualification and conversions independently, verify
the source-row multiset and multiplicity, then validate links and summaries.
Keep hashing as an identity check; it cannot certify the correctness of a
self-consistent but incorrectly generated bundle.

### F6 — P2: advertised resume fails with the original work directory

Locations: [returns.py](../src/trinetx_preprocessing/encounters/returns.py),
lines 592–597, before the resume branch at 633–638;
[validation.py](../src/trinetx_preprocessing/encounters/validation.py), line 788.

Every build invokes parent validation in `work_dir/parent-validation`, which is
created with `exist_ok=False`. A second call with that directory raises
`FileExistsError` before resume logic. The existing resume test replaces parent
validation with a stub and therefore misses this failure. Repeated real parent
validation against a valid synthetic parent reproduced it.

Repair: allocate fresh, tool-owned validation scratch per attempt while retaining
previous failure evidence. Add an interrupted/resumed integration test using the
real parent validator. Work inside the output directory must also be rejected;
the current overlap check only rejects the opposite nesting direction.

### F7 — P2: some uncertainty disappears from summaries

Location: [returns.py](../src/trinetx_preprocessing/encounters/returns.py),
lines 203–218 and 411–421.

`conflicting_return_start` and `unknown_return_precision` are link states, but
have no corresponding summary uncertainty fields. A synthetic conflicting-start
return was excluded from outcomes with no summary indication of that exclusion.
Candidate filtering can also omit ambiguous records when their chosen start
falls outside the window; the day contract must specify such boundary cases.

Repair: enumerate all temporal states, retain counts for every excluded/uncertain
reason, and independently reconcile their totals. Distinguish a count of confirmed
observed events from an assertion that no event occurred.

## Decisions and operational work still needed

1. **Applicability and missingness.** A synthetic nonacute index currently has
   `inpatient_event_term=not_applicable` while its inpatient outcome is positive.
   An unavailable anchor has zero counts but NULL flags. These combinations
   require explicit definitions; they are not resolved by date granularity.
2. **Threshold union names.** Current `any_gas_gt45` uses the same cutoff for
   ABG and VBG, as does `any_gas_gt50`. There is no gas-only field explicitly
   named for ABG >45 OR VBG >50, nor its inclusive counterpart. The goal's
   paired-threshold wording needs explicit names and expected fixtures.
3. **Episode authority.** Same-ID ED/inpatient records bypass conflicting-start
   and conflicting-end checks. Specify which component differences establish
   a coherent continuation and which remain conflicts. Cross-ID transfer
   identity remains unsupported. Missing or derived return ends also need
   an explicit rule for diagnosis/gas episode eligibility.
4. **Scale.** The output validator reads all partitions together with a 1 GiB
   DuckDB cap. Full-scale success is unproven. Make semantic validation bounded
   by patient partition, and run cheap complete schema checks before expensive
   distinct aggregations. The prior memory repair passed the distinct-count
   stage, not the entire parent validator.
5. **Acceptance provenance.** The current continuity ledger does not identify
   a verified trusted parent acceptance receipt. Resolve that gate independently
   of the precision fix. The existing private acceptance runner references an
   older C3 receipt and fixed test count; refresh it against the final code,
   contract and required named gates before any new run.
6. **Documentation.** v1 says the validation report is inside the bundle, while
   the CLI writes it externally. The acceptance seal should bind that external
   report. The dictionary currently lists types and an `outcome` role without
   full field definitions, units, null semantics or applicability.

## Audit evidence and limits

Eight targeted synthetic probes reproduced the seven defects above plus the
applicability inconsistency. They exercised the real diagnosis producer, return
builder expressions, full internal return-artifact validator, and real parent
validator scratch behavior. The two adversarial full return-validator probes
stubbed **only** external parent/source validation, as the existing synthetic
bundle test does. Their results are not end-to-end private acceptance.

The script, synthetic artifacts and machine-readable findings are saved outside
Git. This audit read existing private aggregate receipts; it did not rescan raw
exports or regenerate private products. No runtime repair is included in this
audit revision. The reviewable next contract is
[RETURN_DAY_RESOLUTION_PROPOSAL.md](RETURN_DAY_RESOLUTION_PROPOSAL.md).

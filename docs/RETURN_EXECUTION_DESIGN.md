# Return execution and consumer acceptance

Status: implementation in progress; no new private acceptance or release claimed.

## Approved objective

Preserve calendar-day return contract 2.0 and the independent original encounter
variants while reducing repeated source scans, reusing verified prerequisites,
recovering interrupted validation, and supporting a strict downstream reader.
The existing v1 defaults, encounter acceptance API, and accepted products remain
supported. Production evidence and profiling artifacts stay external.

## Failure model and independent expectations (written before implementation)

Existing partition E2Es prove clinical decisions but do not exercise a persisted
source stage, dependency-specific receipts, installed summary consumption, or
recovery of partition validation. Extend retained E2Es to cover these boundaries;
do not replace the independent clinical oracle with producer-derived expectations.

| Failure | Independent expected result |
| --- | --- |
| A missing component start with another component beyond day 365 | Unknown horizon flags under the existing approved decision table |
| Day 0/30/90/365, strict/inclusive gas threshold, normal/absent/rejected gas | Existing hand-authored fixture values and three-state semantics remain exact |
| Source staging drops, duplicates, changes, or misroutes a row | Exact typed multiset reconciliation fails, even if total row counts match |
| FULL_DATA membership is substituted for AFTER_EXCLUSION | Original per-variant key comparison fails |
| Parent/source bytes, catalog, dependency or applicable contract changes | Bound prerequisite or checkpoint is rejected |
| A documentation-only change | Computational identity remains unchanged |
| Outcome-validator change with unchanged producer | Build may be reused; old validation checkpoints are invalidated |
| Unknown source-code dependency change | Conservatively invalidate potentially affected evidence |
| Receipt says pass but has wrong scope, missing evidence, or wrong trusted digest | Reject before exposing rows or accepting reuse |
| Interrupted file write or receipt publication | Retain incomplete evidence; never mark the partition complete |
| Interrupted validation after a completed partition | Reverify matching completed outputs; repeat only uncompleted or invalidated work |
| Competing controllers | Existing shared lock rejects the second controller |
| Missing/extra/duplicate/null/wrong composite key | Exact original-key proof fails; no implicit inner join or population change |
| Wrong receipt/report/parent or unsupported contract | Downstream open fails without development/raw fallback |
| File changes during reading | Read fails; no report is published as complete |
| Nullable booleans/integers are converted to clinical negatives | E2E comparison fails; preserve nullable types and missingness |
| All summary columns are requested | Bounded batches; full DataFrame requires explicit projection |
| Fresh/resumed, direct/staged, one/multiple worker execution differ | Exact rows, schemas, keys and multiplicity comparison fails |
| Aggregate report chooses a threshold/window/population | Reject the report; enumerate every existing alternative and denominator |
| Candidate code is merged with materially different dependencies | Prior acceptance cannot certify the changed dependency identity |

## Execution design

Use one controller and one immutable run configuration. Shared prerequisite
receipts bind source/parent bytes, schema/catalog, environment and dependency
closures. Input bytes are checked at run boundaries. Unknown dependency changes
invalidate broadly; historical receipts and producer manifests are never rewritten.

Create minimal raw-history projections for the union of index patients while
retaining separate original variant keys. Independently prove source-stage
coverage using complete typed rows with duplicate multiplicity. Each clinical
partition consumes its shard; the validator derives its own expected outcomes.
Materialize repeated validator intermediates once per partition.

Atomic validation receipts bind the exact source stage, parent, output artifacts,
validator and contracts. Final global reconciliation and input-byte checks remain
mandatory. Existing filesystem and advisory-lock helpers supply durable writes
and single-controller ownership. A quiet process is not progress evidence.

Profile before selecting storage/concurrency. Start with one worker and 32
partitions; benchmark two only within measured process-family memory headroom.
Retain cold preparation and warm reuse timings separately, including proof costs.
Publish a resource-pilot forecast before a full private run.

## Consumer contract

Return acceptance is distinct from encounter acceptance. Version the return
acceptance/report metadata separately from the unchanged scientific/data contract.
Bind producer/validator, source/parent, inventory, schema, validation report and
independently verified original-key digests. Freeze the consumer schema from the
approved contract and accepted artifact schema; never trust a self-declared schema.

Downstream open requires explicit bundle, variant, receipt path, externally trusted
receipt SHA-256 and validation-report path. Expose bounded Arrow batches and an
explicitly projected DataFrame; projections include patient_id, encounter_id and
index_event_id. Join parent pat_enc_hash to index_event_id together with both
original identifiers after parent-manifest and exact-key reconciliation.

The downstream quality report covers both variants, all existing windows,
settings and phenotype alternatives. Preserve unknown/unavailable/not-applicable
states and explicit denominators. No endpoint selection, cohort adaptation,
censoring change, intraday ordering or complete-capture claim is authorized.

## Required proof and rollout

Record failure expectations before each implementation change. Retain installed
noneditable upstream/downstream E2E artifacts outside checkouts with PYTHONPATH
removed. Exercise real source/parent validation, corruptions, recovery, joins,
missingness and independently expected report aggregates. Public proofs do not
substitute for private full-data acceptance.

After public checks and the measured pilot, freeze both candidates and run one
locked full build/validation, exact reference comparison and unchanged-input
proof. Seal the upstream product, verify the installed consumer and report, then
compose release evidence. Merge upstream first, update the immutable downstream
pin and lockfile, repeat affected installed/private checks, then merge downstream.
Record tested producers and actual merge revisions separately. Runtime improvement
is required; the requested runtime target is an objective, not a relaxed gate.

### Process-lock failure fixture

A short synthetic clinical partition cannot deterministically hold a worker open
while its controller dies. The retained subprocess workflow therefore also
exercises the actual worker dispatcher with a bounded blocking job: after the
controller terminates, a second lock owner must still be rejected until the
active worker finishes. It uses real processes, descriptor transfer and flock;
no mocked bookkeeping can establish this property. This expectation precedes
the worker lock-lifetime implementation.

### Controller publication recovery expectations

The retained full synthetic workflow also runs the actual locked controller CLI.
A completed run resumed with the identical configuration must reverify its
authenticated receipt and actual artifacts and return the same accepted receipt.
An interrupted draft seal must remain preserved and must not prevent a new,
independently verified seal. Completed receipts are immutable. Missing or altered
receipt/report evidence must fail closed. These recovery cases were recorded
before changing controller publication and draft naming.

### Membership staging cost experiment

The initial private profile identified the broad catalog-membership join as a
preparation bottleneck. Both the preserved producer and independent validator
read exactly the arterial, venous and unspecified blood PCO2 source elements.
Stage those required membership elements only, retaining true, false and null
inclusion values and duplicate multiplicity. This pushes an existing source
predicate earlier; it does not select patients, encounters or clinical outcomes.
The independent canonical comparison must cover every required complete row.
The E2E fixture includes unrelated memberships, repeated required memberships,
and false/null inclusion values, and must preserve exact direct/staged outputs.

Computational identity discovery must also invalidate on unknown Python code
under the packaged catalog directory. Only its non-code resources are excluded
because the actual return catalog is bound through the canonical source.
The source proof must reject a staged column type changed with equal-looking
values even when the staged schema and hashes are rebound. Compare actual types
directly with canonical source types before SQL multiset comparison, which can
otherwise coerce unequal types into a common type.

### Full-size membership routing recovery

The first full candidate failed before staging history: its distinct routing
table covered every laboratory record for original patients, although only the
three required membership elements consume that table. The smaller pilot did
not expose this memory failure. Keep the memory limit unchanged. Restrict only
membership routing to records having at least one required element; keep all
laboratory history in the staged laboratory relation.

Before implementation, extend the retained execution E2E with unrelated laboratory
records, required memberships that are solely false or null, duplicate laboratory
and membership rows, and a source record associated with multiple original
patients. Independently compare staged membership rows and routing against the
original unrestricted laboratory mapping, including exact duplicate multiplicity.
Require all unrelated laboratory rows to remain staged, and preserve the existing
direct/staged six-table comparisons and independent clinical validation.

Failure cases are lost false/null memberships, extra copies caused by joining
membership duplicates into routing, collapsed patient buckets, missing unrelated
laboratory history, and a proof sharing the same filtering mistake as production.
Synthetic success is insufficient for the observed scale failure: full-size
routing must finish under the unchanged resource limit before a revised resource
receipt or another frozen acceptance attempt can be considered. Preserve the
failed attempt, its prerequisite receipt, and its original forecast.

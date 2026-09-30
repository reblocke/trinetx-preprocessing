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

The first restricted routing query also failed at full scale. Its query plan
decorrelated `EXISTS` through a large delimiter join; a direct semi-join rewrite
still planned a hash build from the broad laboratory side. Materialize distinct
required membership record IDs first, then join laboratory rows to that compact
relation. This gives the optimizer actual intermediate cardinality and avoids
the correlated-query delimiter table. Reuse the independent unrestricted oracle
and all existing failure fixtures. No resource-limit increase or successful
private feasibility claim follows from query-plan inspection alone.

### Source partition write repair: expectations before implementation

The prior writer materialized each source relation and requested a filtered
COPY and a separate count for every one of 32 buckets. The existing three-bucket
synthetic workflow did not establish the full-size write cost. Operational
measurements and stopped-attempt evidence remain external. A completed Parquet
footer does not establish scientific or release acceptance.

Before changing the writer, extend the retained execution E2E with a 32-bucket
stage from the same independently specified fixture. For all six relations,
require exactly 32 files and the original canonical field order and SQL types,
including valid typed Parquet files for empty buckets. Compare each manifest
row count to that file's completed Parquet metadata, and independently reconcile
all typed rows, nulls, duplicates and routing against the canonical database.
All required gas memberships, including false and null inclusion, and all
unrelated laboratory history must remain present. A source record associated
with several original patients may route membership rows to several distinct
buckets; compare that relation to an independent canonical routing oracle at
each partition count rather than assuming its row total is constant across
different partition counts. A stage is not published until every relation and
the independent proof pass.

A single-thread native partition writer may emit only one piece per occupied
bucket, so the ordinary E2E cannot reliably trigger the multiple-piece path.
Within the same retained workflow, split a known source fixture into two Parquet
pieces and require the bounded consolidation step to reconstruct its exact typed
multiset and metadata row count. This focused fixture catches a real writer
failure otherwise absent from the E2E; it does not replace full stage proof.
Also require a durable completion event for each final file and a relation-level
write result. An absent or altered file, extra piece, wrong bucket, changed type,
truncated file or interrupted publication must fail the independent proof or
inventory gate even if counts and local hashes are rebound.

For the first full-size repaired measurement, use the separately recorded private
diagnostic budget and stop conditions. Record actual query, normalization,
metadata, flush, hash and independent proof times and storage headroom outside
the repository. A timeout is incomplete, not a passing pilot. Reuse a fully
verified stage only with authenticated matching producer, validator, input,
configuration, environment and artifact identities. Do not publish another
full-run forecast until complete full-size staging and independent canonical
reconciliation pass.

### Explicit prerequisite reuse across corrected candidates

A corrected source-stage identity requires a new frozen controller configuration;
the failed run's configuration-bound checkpoint cannot simply be rewritten.
Allow the new configuration to name an explicit prerequisite receipt and an
externally trusted SHA-256 together. Reuse must rehash all current input bytes
and require identical source/parent validator, environment, contract and catalog
dependencies through the existing prerequisite verifier. Preserve the old
receipt and issue a new receipt binding its digest. A missing digest, wrong
digest or changed dependency must fail before source staging; there is no cold
fallback after rejected explicit reuse.

Extend the installed product E2E before implementing this interface: complete a
new controller run using the independently produced prerequisite receipt, prove
the new receipt records its exact predecessor, and reject incomplete trust,
incorrect digest and a rebound receipt with mismatched validator dependency.
Retain the existing fresh-run and interrupted/resumed execution coverage.

Runtime evidence for explicit cross-candidate reuse must identify it as reuse,
not cold prerequisite execution. It includes recovery downtime within the new
run, but excludes prior candidate time; retain and report that earlier time
separately. The product E2E must inspect the emitted runtime receipt for these
distinctions before any acceptance record is described as a cold measurement.

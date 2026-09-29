# Return outcomes acceptance

Status (2026-09-29): **C0–C4 engineering acceptance passed for the opt-in
calendar-day v2 return bundle**. The locked r4 outcomes-only build completed
both independent variants on code identity
`de9d4268bb64ffa47411f019d42c7e3f1abd76a8935bd96d285d7081ba752d88`.
Its independent full validator passed all 64 patient partitions and verified
every original index key, source episode, evidence row, link, phenotype,
summary rule, schema and output hash. The external acceptance seal passed,
with SHA-256
`683e882935bab49302b72378e58da03ac2c6065ee3cdd8b3a161093d99e5de4c`.
A second, terminal auditor independently rehashed the canonical database,
all 44 accepted-parent files and all 386 output artifacts, checked the seal's
gate bindings and confirmed pre/post input byte equality. Its report SHA-256
is `51aef498874bfa0bf19cfe6a2e897e37392a4ff0b5a6fb6476ae4b98bfe8757d`.
The output manifest and independent validation report SHA-256 values are
`f346f5b347ecf7dbaa86a7a60fd7c043bcd2af40b4fa5a440b39efc359b7b69a`
and `317de5c6b741fcb9e031f68587cdeed75259c6428c2d8165c951ed08765ce086`.
Private row-level data, manifests, logs and receipts remain outside Git.

The current-code C0 provenance, exact accepted-parent validation and final
resource pilot passed with external receipt SHA-256 values
`5aefcd5c0fefdb7e59a3f564ea787f2a32a382204fb365554a31af189ccebef9`,
`c733f7976dc9fd7a4f04800edcdc988717b620f4d31a3d417b689218f09c9155`
and `143aea8c583cc064c78a95aecef2ddada3616d020d2b5fc05069b2b106543cec`.
The 32-partition pilot's independent artifact audit passed. C3 passed full
pytest (464 cases), Ruff, offline lock, five legacy E2Es, a noneditable wheel
and installed old-consumer API/CLI checks. Its public proof SHA-256 is
`2ee5dda936a2ee84db74b972b1b7ef6be07672c95c817b2fcedf9ddc91e0a40c`.
The source-to-output v2 E2E, wrapper resume/collision/tamper E2E and private
source/parent gates supply complementary evidence. An additional readback-verified
source-to-output E2E for same-ID progression and unlinked cross-ID possible
transfer passed after the seal, with receipt SHA-256
`634469d1d9ba8884085687765f72f6c5f42e1fd74c10c3fddfa1cba85335bbb2`.
It changed only the synthetic E2E script, leaving the sealed package code and
contract identities unchanged.

This is an engineering acceptance of observed calendar-day outcomes. It does
not establish complete return capture, exact intraday ordering, planned status,
causality or clinical eligibility. The preexisting encounter products, 36-file
compatibility bridge and old cohort-source consumer remain the supported
unchanged interfaces.

This page tracks private acceptance for the opt-in v2
return bundle. The executable rules are in [RETURN_CONTRACT.md](RETURN_CONTRACT.md).
The [2026-09-25 audit](RETURN_AUDIT.md) records defects at an earlier revision;
its earlier blocked status is historical.
The owner explicitly resumed the goal under the calendar-day v2 contract.
Historical v1 text remains in [RETURN_CONTRACT_V1.md](RETURN_CONTRACT_V1.md).

## Historical repair and retry record

The dated findings below describe earlier rejected runs and checkpoints. Their
"pending" statements apply to those snapshots; the 2026-09-29 status above
governs the accepted r4 build.

The locked r3 C4 build on LOCKE STATION completed all 64 partitions and
published a complete manifest for both variants. During independent validation,
an additional hand-authored synthetic E2E found that a same-ID ED/inpatient
return with an unknown ED start and an observed inpatient start on day 366 was
reported as negative for every horizon. Under the approved contract, its start
could be in each window, so those flags must remain unknown. The validator
repeated the producer's possible-window formula and could not catch the error.
The r3 worker was terminated after this scientific gate failure; both runner
processes exited, no return-validation report or acceptance seal exists, and
all r3 outputs and scratch remain external and unaccepted. The external failure
receipt SHA-256 is
`010966fc8aef1ed1a3487737ed47da6c599701b9153959b24f699d3250fa501a`;
the terminal rejection receipt SHA-256 is
`9b19ac4d294137592459db92d494d661adc01249ea99f9bf03f7fa48d3f177d5`.
The public E2E was extended before the code repair and failed on the old result.
The repaired E2E now passes six independent partial-start cases, a forged
provenance rejection, and one-versus-three partition equivalence. Its external
receipt SHA-256 is
`d28bfe6d0c8afdd93b85946a60e8326207dcc305a842275f19531bf4bd03366c`.
This code and contract change invalidates the prior code-bound public, parent,
pilot and C4 receipts. A fresh locked build and all C3/C4 gates are required.
On repaired code identity
`de9d4268bb64ffa47411f019d42c7e3f1abd76a8935bd96d285d7081ba752d88`,
the full pytest suite passed 464 cases with 238 existing warnings. Ruff check
and format, offline lock, five legacy E2E workflows with readback-verified
manifest SHA-256
`61f8f8e8555dc003eb9256623d047b67d5785b434c40c21c787aecb13c6f7c4e`,
and a fresh noneditable wheel with installed old-consumer API/CLI smoke checks
passed. The synthetic wrapper E2E passed fresh, resumed and partitioned output
multisets, collision and wrong-receipt checks; its independent readback receipt
SHA-256 is
`dc9c7af94c2647bc1591f3b415f9a82ac1f68439955d7ac3a6e5d2cdd7271126`.
That wrapper stubs upstream validation. The accepted-parent validation and
resource pilot must be repeated on this code before another private build.

On the preceding code, the r6 accepted-parent validation passed FULL_DATA (2,662,675)
and AFTER_EXCLUSION (833,476) with receipt SHA-256
`c075bcfe2fc7b595723e5ba0c4d12219e50643c8ff5be10aeac7c7bf6a2098b0`.
The first C4 build on LOCKE BOOK failed on ExFAT AppleDouble scratch files.
The diagnosed APFS retry passed launch gates and began writing return
partitions; its last verified checkpoint had 25 FULL_DATA partitions. A later
write failed with an I/O error and RESEARCH FAST disappeared, so the runner
could not produce a failure receipt. Its independent observation receipt is
external (SHA-256
`61e7e1f2f817a98f126bbd5b27ec7626eb3f38065aa21c7769e0f7ab9feefbf5`).
At the handoff, the enclosure and NVMe controller are visible, but the
controller reports a write-command timeout and exposes no disk. The actual
completed count at failure is UNCONFIRMED. No complete C4 product,
post-build input hash comparison, independent full return validation, or
acceptance seal exists. Restore the same volume and audit its checkpoint and
completed file hashes before any resume decision.
A separate LOCKE STATION APFS volume passed read-only filesystem verification
and a 4 GiB write/fsync/readback probe. A locked two-variant, 32-partition
pilot passed with 82,928 FULL_DATA and 25,969 AFTER_EXCLUSION bucket keys;
all 12 artifact hashes were independently verified. Its receipt SHA-256 is
`4897d6574f93aa704c3d7133d8205357e4ca752de156ee9795bf2a751f4f73df`.
A later C4 attempt used it; that r3 attempt was rejected as described above.
The full C4 acceptance gates remain unchanged.

The preceding calendar-day v2 build and independent validator were checked on code
identity `c16ef758b1d5506343d4de0d1a20b19b4ed704f93556de4fd1e710710dade2cf`.
The frozen suite passed 464 cases (238 existing performance warnings); Ruff
check/format, `uv lock --check --offline`, `git diff --check`, noneditable wheel
installation with matching code identity, and the installed old cohort-source
consumer passed. The five legacy E2Es passed with a readback-verified manifest
SHA-256 `130fc5fefe18aee5854092796d0fe81eadd668313c5544d3d6ceeac44b9f3ec3`.
The v2 partition E2E passed hand-authored boundaries, independent reconciliation,
adversarial corruption and one-versus-three partition equivalence; its receipt
SHA-256 is `9ba678adccf2b11386506b1e50338e4b3062507de80346e6fd8bd4b982932103`.
A separate synthetic wrapper check passed fresh/resumed/partitioned full-artifact
multisets, output collision and wrong receipt checks; its receipt SHA-256 is
`5353682be0759cb89aca6466e51c334a60f3d7758918a75c221eb52c4ae84a48`.
That check explicitly stubs upstream parent/source validation, so these passes
do not close the real input boundary or C4 acceptance.

The first versioned parent precision preflight rejected all full-data diagnosis
rows because its proof recognized ISO dates but not the producer's eight-digit
`YYYYMMDD` representation. Both representations are now checked. A second
locked preflight reached exact element-by-history availability reconciliation
and failed at the 4 GiB DuckDB limit; the same unchanged query failed at 8 GiB
in isolation. Both failed receipts and work remain external. The opt-in bounded
path now partitions evidence by stable index ID, proves projected and joined
row multiplicity, and sums exact distinct counts across disjoint partitions.
Its synthetic positive and missing/duplicate coverage checks pass. The next
locked full parent validation found 1,389 FULL_DATA hba1c count differences;
an exact aggregate showed every difference was a stored NULL on an index with
no element evidence, versus the validator's expected zero. The accepted
producer left-joins a summary only for indexes with element evidence, so NULL,
zero, and positive counts have distinct meanings. The validator now checks
those three states exactly; a full-file correction query found zero hba1c
differences, and a repeatable synthetic E2E rejects all three count
corruptions. The locked r4 full parent validation passed both variants on code
identity `e74ef7d9a5f6930e9da1772c3cbff66315207ef41a85e0f8bc55c5eae5c37578`;
its receipt SHA-256 is
`0f7136ab261431ec50903990a7cd378c5e5be9b7bac2d534b01942cb27346b95`.
The first v2 resource pilot then failed at the builder's 1 GiB DuckDB limit
during the FULL_DATA summary write. The v2-only builder cap is now 4 GiB;
v1 remains at 1 GiB. A new 32-partition resource pilot passed both variants,
82,928 FULL_DATA and 25,969 AFTER_EXCLUSION bucket keys, with independent
partition validation, all 12 output hashes, matching source/parent/code
identities, 4,773,183,488-byte peak process RSS, and more than 100 GiB free.
Its readback-verified receipt SHA-256 is
`e4fcbdd15956c920767bb76b11ad19f52f70e2ce53f4ed6e5788421cc6e6e4ad`.
That earlier code change invalidated the r4 code-bound parent gate. A subsequent
r6 full parent validation passed on the former r3 code identity, as recorded
above. The partial-start repair requires a new code-bound parent validation.

The historical accepted parent receipt was recovered from the documented
external handoff. An external C0 receipt, SHA-256
`5aefcd5c0fefdb7e59a3f564ea787f2a32a382204fb365554a31af189ccebef9`,
verifies the parent manifest, historical receipt, three historical gate hashes,
retained reference comparison, newer integrated validation evidence, canonical
source sidecar, source file size, both variant names, and the engineering-only
scope. This closes the missing-historical-receipt question, but current full
parent validation and the C4 immutable-byte checks remain pending.

The isolated review branch is `codex/readmissions-20260924`. The recorded public
suite and packaging checks passed on code identity
`63ecb329b10d902acfa925e2bfdb28aa65eb6f2df1f2b4f09316a41924b66b17`:
71 affected tests, 522 full-suite tests, Ruff check and format, offline lock
check, non-editable wheel installation, and isolated old/new consumer smokes.
The private source and parent bundle identities and C1 aggregate
coverage profile have external receipts; private clinical rows and receipts
remain outside Git. New targeted synthetic probes reproduced defects in
precision NULL handling, gas three-state results, link/evidence validation,
resume scratch handling and uncertainty summaries. The passing test count
therefore does not close C2 or C3.

The historical v1 32-partition resource pilot completed both variants and passed its
summary-key, artifact-hash, input-identity, and 100 GiB free-space gates.
The first full outcomes-only build stopped during required validation of the
accepted parent encounter bundle, before creating any return partition. Its
1 GiB DuckDB validator cap was insufficient for an exact distinct-membership
check; the external failed receipt, log, and work files are preserved. This is
a resource failure, not a passed parent gate or a completed return build.
The existing encounter validator still defaults to 1 GiB for old callers.
The opt-in return build and validator now request 4 GiB for the same checks.
A separate 4 GiB preflight still ran out of memory at the same exact distinct
count. The opt-in path now partitions that count by stable key hash and sums
exact per-partition counts; it also verifies that each scratch projection
preserves every evidence row. The old validator path remains the default.
A locked full-scale preflight passed the memory-intensive exact-count stage,
then stopped because the accepted schema 2.0 parent bundle lacks the required
`event_datetime_precision` column in diagnosis, procedure, and medication
component evidence for both variants. The producer retains raw `date` (or
medication `start_date`) and `event_datetime` but does not write that field for those
tables. The historical v1 validator requires it, and the accepted bundle cannot be
rebuilt or modified under this request. The external schema audit records all
six affected artifacts and the exact parent/code identities. No return bundle,
independent return validation, post-build byte comparison, or acceptance seal
exists.

A separate read-only aggregate audit of those artifacts found that their
producer-defined raw date fields (`date` or `start_date`) are present,
parseable as date-only values, and agree with the parsed event calendar dates;
the parsed events have no time of day. Its private receipts remain external.
This evidence did not add the missing field; the owner later authorized the
versioned v2 compatibility proof described above.

The audit reproduced this mismatch with the unchanged synthetic evidence
producer. Day-only dates are already permitted by v1. The owner accepted a
versioned parent-validation compatibility rule proving equivalent precision
from retained raw fields while preserving the accepted parent schema and bytes.
An unchanged producer rebuild would reproduce the missing field. Complete the
current parent validation and remaining private C3/C4 gates before building
outcomes. Do not bypass the validator.

The equivalent public command shape is:

```sh
python -m trinetx_preprocessing build-returns \
  --database "$CANONICAL_DB" --parent-bundle "$ACCEPTED_ENCOUNTER_BUNDLE" \
  --output-dir "$EXTERNAL_RETURN_BUNDLE" --work-dir "$EXTERNAL_WORK" \
  --partitions 32 --contract-version 2.0
python -m trinetx_preprocessing validate-returns \
  --bundle "$EXTERNAL_RETURN_BUNDLE" \
  --parent-bundle "$ACCEPTED_ENCOUNTER_BUNDLE" \
  --database "$CANONICAL_DB" --work-dir "$EXTERNAL_VALIDATION_WORK" \
  --report "$EXTERNAL_VALIDATION_REPORT"
```

The private runner adds the shared lock, immutable-input checks, execution
receipts, source byte comparison, and the external acceptance seal. These
outputs and their exact paths remain outside Git.

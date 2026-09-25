# Return outcomes acceptance

Status: **C0 provenance recovered; C1 v2 contract frozen; C2 implemented;
C3 public and synthetic checks passed, private gate pending; C4 gated**.
This page tracks private acceptance for the opt-in v2
return bundle. The executable rules are in [RETURN_CONTRACT.md](RETURN_CONTRACT.md).
The [2026-09-25 audit](RETURN_AUDIT.md) supersedes earlier completion claims.
The owner explicitly resumed the goal under the calendar-day v2 contract.
Historical v1 text remains in [RETURN_CONTRACT_V1.md](RETURN_CONTRACT_V1.md).

The calendar-day v2 build and independent validator are implemented on code
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
The code change invalidates the r4 code-bound parent gate. A fresh locked r5
full parent validation is running on the current code; no current-code
full-parent pass or C4 acceptance is claimed.

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

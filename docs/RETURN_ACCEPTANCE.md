# Return outcomes acceptance

Status: **C0 provenance recovered; C1 v2 contract frozen; C2/C3 repairs in
progress; C4 gated**. This page tracks private acceptance for the opt-in v2
return bundle. The executable rules are in [RETURN_CONTRACT.md](RETURN_CONTRACT.md).
The [2026-09-25 audit](RETURN_AUDIT.md) supersedes earlier completion claims.
The owner explicitly resumed the goal under the calendar-day v2 contract.
Historical v1 text remains in [RETURN_CONTRACT_V1.md](RETURN_CONTRACT_V1.md).

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

The 32-partition resource pilot completed both variants and passed its
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
tables. The current validator requires it, and the accepted bundle cannot be
rebuilt or modified under this request. The external schema audit records all
six affected artifacts and the exact parent/code identities. No return bundle,
independent return validation, post-build byte comparison, or acceptance seal
exists.

A separate read-only aggregate audit of those artifacts found that their
producer-defined raw date fields (`date` or `start_date`) are present,
parseable as date-only values, and agree with the parsed event calendar dates;
the parsed events have no time of day. Its private receipts remain external.
This evidence does not add the missing field or authorize a new schema rule.

The audit reproduced this mismatch with the unchanged synthetic evidence
producer. Day-only dates are already permitted by v1. The recommended repair is
a versioned parent-validation compatibility rule proving equivalent precision
from retained raw fields while preserving the accepted parent schema and bytes.
An unchanged producer rebuild would reproduce the missing field. Resolve the
versioned compatibility rule, all audit findings, trusted parent acceptance provenance,
complete parent validation and refreshed C3 gates before retrying the outcomes
build. Do not bypass the validator.

The equivalent public command shape is:

```sh
python -m trinetx_preprocessing build-returns \
  --database "$CANONICAL_DB" --parent-bundle "$ACCEPTED_ENCOUNTER_BUNDLE" \
  --output-dir "$EXTERNAL_RETURN_BUNDLE" --work-dir "$EXTERNAL_WORK" \
  --partitions 32
python -m trinetx_preprocessing validate-returns \
  --bundle "$EXTERNAL_RETURN_BUNDLE" \
  --parent-bundle "$ACCEPTED_ENCOUNTER_BUNDLE" \
  --database "$CANONICAL_DB" --work-dir "$EXTERNAL_VALIDATION_WORK" \
  --report "$EXTERNAL_VALIDATION_REPORT"
```

The private runner adds the shared lock, immutable-input checks, execution
receipts, source byte comparison, and the external acceptance seal. These
outputs and their exact paths remain outside Git.

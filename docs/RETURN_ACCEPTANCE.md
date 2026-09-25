# Return outcomes acceptance

Status: **BLOCKED at C4: accepted parent schema decision required**. This page tracks private acceptance for
the opt-in v1 return bundle. The rules are in [RETURN_CONTRACT.md](RETURN_CONTRACT.md).

The isolated review branch is `codex/readmissions-20260924`. C0–C3 public
verification passed on code identity
`63ecb329b10d902acfa925e2bfdb28aa65eb6f2df1f2b4f09316a41924b66b17`:
71 affected tests, 522 full-suite tests, Ruff check and format, offline lock
check, non-editable wheel installation, and isolated old/new consumer smokes.
The private source and parent bundle identities and C1 aggregate
coverage profile have external receipts; private clinical rows and receipts
remain outside Git.

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
component evidence for both variants. The producer retains raw `date` and
`event_datetime` but does not write that explicit precision field for those
tables. The current validator requires it, and the accepted bundle cannot be
rebuilt or modified under this request. The external schema audit records all
six affected artifacts and the exact parent/code identities. No return bundle,
independent return validation, post-build byte comparison, or acceptance seal
exists.

An owner-approved schema-version decision is required: either supply a newly
accepted parent bundle with the required field, or authorize a versioned
validation rule for the existing bundle that proves equivalent precision from
its retained source fields. Until that decision and its tests/private gate
pass, do not bypass the parent validator or retry the outcomes build.

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

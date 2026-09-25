# Return outcomes acceptance

Status: **C4 parent-validation resource diagnosis; acceptance pending**. This page tracks private acceptance for
the opt-in v1 return bundle. The rules are in [RETURN_CONTRACT.md](RETURN_CONTRACT.md).

The isolated review branch is `codex/readmissions-20260924`. C0–C3 public
verification passed on the preceding code identity
`c1be9fba59bbfd70c94cd2001165b461faf4ce6510d0dbdcd949748a34e6bac3`:
16 focused return tests, 520 full-suite tests, Ruff check and format, offline
lock check, non-editable wheel installation, and isolated old/new consumer
smokes. The subsequent memory-cap change passed 70 affected tests, Ruff check
and format, and offline lock check; a new full-suite and installed-wheel run
are pending. The private source and parent bundle identities and C1 aggregate
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
A new locked parent-validation preflight must pass before an explicit full
build retry. Independent return validation, post-build
byte comparison, and the external acceptance seal remain pending.

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

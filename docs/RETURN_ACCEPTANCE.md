# Return outcomes acceptance

Status: **C4 build running; validation pending**. This page tracks private acceptance for
the opt-in v1 return bundle. The rules are in [RETURN_CONTRACT.md](RETURN_CONTRACT.md).

The isolated review branch is `codex/readmissions-20260924`. C0–C3 public
verification passed on frozen code identity
`c1be9fba59bbfd70c94cd2001165b461faf4ce6510d0dbdcd949748a34e6bac3`:
16 focused return tests, 520 full-suite tests, Ruff check and format, offline
lock check, non-editable wheel installation, and isolated old/new consumer
smokes. The private source and parent bundle identities and C1 aggregate
coverage profile have external receipts; private clinical rows and receipts
remain outside Git.

The 32-partition resource pilot completed both variants and passed its
summary-key, artifact-hash, input-identity, and 100 GiB free-space gates.
The one full outcomes-only build is running under the shared lock using the
installed wheel and a non-symlinked external work and output location. Its
execution receipt records the exact private paths and frozen identities.
Independent validation, post-build byte comparison, and the external
acceptance seal remain pending. Preserve any failed attempt and diagnose it
before an explicit resume.

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

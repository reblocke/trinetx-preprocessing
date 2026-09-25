# Return outcomes acceptance

Status: **C4 pending**. This page records the private acceptance result for
the opt-in v1 return bundle. The rules are in [RETURN_CONTRACT.md](RETURN_CONTRACT.md).

The isolated review branch is `codex/readmissions-20260924`. C0–C3 public
verification passed on frozen code identity
`c1be9fba59bbfd70c94cd2001165b461faf4ce6510d0dbdcd949748a34e6bac3`:
16 focused return tests, 520 full-suite tests, Ruff check and format, offline
lock check, non-editable wheel installation, and isolated old/new consumer
smokes. The private source and parent bundle identities and C1 aggregate
coverage profile have external receipts; private clinical rows and receipts
remain outside Git.

The resource pilot is still running under the shared build lock. A full
outcomes-only build, independent validation, post-build byte comparison, and
external acceptance seal have not been completed or claimed here. When C4 is
terminal, record the exact commands, input identities, variant counts,
validation result, output manifest, external seal path, and limitations on
this page. Preserve any failed attempt and diagnose it before an explicit
resume.

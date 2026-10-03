# Bounded preprocessing audit corrections (2026-10-03)

## Failure modes and independent expectations before implementation

The existing retained workflows exercise successful payloads and scientific
corruption rejection, but do not rerun their own CLI into retained output or
force two writers past a preflight existence check. The calendar transport
fixture omits an unavailable table and uses a key relation named `keys`, so it
cannot expose empty canonical placeholders or SQL alias shadowing.

- Every retained runner must claim its output directory atomically before its
  failure handler can write. Existing passed and failed artifacts, files and
  symlinks retain their complete byte inventory after rejection (exit 2).
- Two concurrent CLI writers to one fresh destination have one successful
  owner and one rejected writer. The owner retains its passed receipt and
  payload. A new payload failure retains its own failed receipt (exit 1).
- The CLI lifecycle fixture substitutes only the payload stage to force that
  race and a post-claim exception. It executes the six actual CLI entrypoints
  in subprocesses and retains their source, commands, outputs and hashes. It
  supplements, rather than substitutes for, the real synthetic SQL/Parquet E2Es.
- A present empty table without inventoried input is `unavailable_domain` for
  every requested key. An inventoried empty domain or unmatched selector is
  `zero_matches`, never a clinical negative. Inventory query failure raises
  `SourceTransportError`, including when the event table is absent.
- Availability uses the canonical inventory names: labs, vitals, diagnosis,
  procedure and meds. Temporary views cannot shadow the canonical inventory.
- Key relations named selected, keyed, enriched or their case variants retain
  every requested original key. Fixed independent expected rows verify raw
  values, NULLs, multiplicity, selector unions and ordering.
- The installed transport qualification runs a noneditable wheel outside the
  checkout, with PYTHONPATH removed, and binds its actual module bytes to the
  retained source snapshot. No database schema, public record type or scientific
  definition changes.

## Qualification and delivery boundary

Retain and verify synthetic E2E receipts, fixtures, source/runtime identities,
exit statuses and generated output hashes. Require locked Ruff, affected E2Es,
documentation references, diff checks and final-head hosted artifact readback.
The GLP-1 child's immutable dependency and lock move together; its clinical
readiness flags stay false and its migration PR remains a draft.

Historical private source and return acceptance stays bound to its original
implementation, runtime and scope. The corrected transport is a newly qualified
interface, not a reissued private receipt. Accepted databases, products, raw
exports, catalogues, reference bytes and completed heavy proofs are preserved.

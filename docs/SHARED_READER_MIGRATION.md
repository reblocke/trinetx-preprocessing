# Shared reader migration

Trusted encounter and return readers and the aggregate return quality report
belong to preprocessing. Study selection, BMI ranking, clinical eligibility,
weights and reporting remain in their study repositories.

## Failure modes and independent expectations recorded before implementation

The existing producer E2Es verify products but do not import a standalone
installed upstream reader. Source-only child migration checks do not exercise
installed imports or packaged configuration. The following boundary E2Es close
those gaps without introducing another validation framework:

- Real synthetic Parquet retains repeated string patient/encounter keys,
  requested column order, nullable fields and both independent variants.
- Trusted receipt, schema, artifact, complete-parent and original composite-key
  checks reject corruption, missing/extra/duplicate/null keys and wrong trust.
  Lazy scans recheck bytes on exit and remove temporary views after failure.
- Production reads never fall back to the explicit development reader.
- Return quality retains every alternative. Positive, negative, unknown,
  unavailable and not applicable partition the original denominator; unknown
  never becomes negative. Reports remain aggregate-only and require a fresh
  destination.
- The installed GLP-1 child works outside all checkouts without the monolith.
  Its key audit uses the upstream scanner; frozen Stata rounding keeps its
  independent half-step and missing-value expectations. Its verification
  policy loads the packaged JSON rather than depending on a checkout.
- Import-only child adaptations reconstruct the original selected source bytes
  through the existing reversible migration manifest. The dependency and lock
  move together to an immutable upstream revision.

The implementation is relocated from the retained monolith baseline. Scientific
functions, signatures, schemas, receipt requirements and report definitions are
preserved. Synthetic installed checks qualify this interface migration, not
clinical study acceptance. Historical private acceptance remains bound to its
original runtime and scope; it is never overwritten or rerun for a source move.

## Delivery order

Publish the upstream API and qualification first, then pin and qualify the GLP-1
child. Keep monolith compatibility imports as a reviewable handoff patch while
its other owner task is active. Reconcile issues #22 and #6 against actual source
evidence and current study ownership; do not claim study readiness from them.

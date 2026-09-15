# GLP-1 source acceptance

Accepted 2026-09-15 at behavior head `9fe392b`. Database-backed GLP-1
processing is the production route for the validated source contract.
Raw-reference mode remains available for reproduction.

## Evidence and repair boundary

The canonical source product retains producer `3391371`. The completed raw
GLP-1 build retains producer `1947e36`; the original database-backed build
retains producer `48294b5`. Source identity, configuration, catalog, producing
code and output provenance were checked before reusing these completed builds.

The full exact comparison at `5ebf82f` checked all 24 contracted tables and six
Parquet-to-table comparisons, plus the eight-file inventory, manifests, cohort
flow, dictionary and QA report. Twenty-two tables matched, including eligibility
and supporting evidence. Two encounter tables differed only in the precision
label for missing encounter end dates: the reference labels these `timestamp`,
whereas canonical capture retains NULL.

At `9fe392b`, the adapter applies the unchanged reference date classifier to the
retained source end-date field. It preserves canonical source values and the
reference output convention. Exact full-row comparisons of both repaired
projections passed, including duplicate multiplicity. A separate copy of the
completed package received only those two precision-column repairs; readback
verified the repair, and its regenerated encounter Parquet matched the reference
exactly. Original packages and failed receipts were preserved until sealing.
Historical producer manifests were not rewritten: the separate repair receipt
records this operation explicitly. This was targeted recovery, not a fresh
full build at the repair revision.

Clinical derivation code is unchanged from the completed producer. Its encounter
end-bound helper chooses the fallback whenever the end date is missing, before
consulting precision. The remaining use copies the precision label into the
encounter output. Thus the repair changes no inclusion decision, observation
window, eligibility flag or evidence row. Full-data results support this boundary;
synthetic tests alone were not used to authorize adoption.

The composed private acceptance receipt binds the original complete comparison,
the two repaired full-row comparisons, the corrected package, source/configuration
identities, CI, and three analytical content fingerprints. No clinical fields were
excluded to obtain parity. Hashes route comparison partitions only; full typed
values and signed duplicate counts determine equality. Operational run fields
and explicitly checked producer revisions retain their documented exceptions.

Hosted CI passed at `9fe392b`; seven missing/date-precision regressions augment the
583-test suite. Publication adds documentation and progress reporting, with
separate final CI. Private receipts, inputs and row-level outputs remain outside
Git. Owned temporary comparison packages are removed only after evidence sealing.

## Scope

Traditional and GLP-1 source elements stay in the same shared clinical domains.
Study outputs are derivations of that source, not a second preprocessing product.
The approved definitions and existing 36-file compatibility bridge are preserved.

This accepts GLP-1 source interchangeability for the validated contract. It does
not certify every traditional source row, retire the Stata bridge, establish exact
clinical eligibility, close all issue #6 clinical requirements, or import the
broader downstream cohort workflow. Those tasks retain their separate scope.

Use `UPDATE_VERIFICATION.md` for subsequent changes. The sealed private
`acceptance_complete.json` includes the accepted head and analytical fingerprints
for `--baseline-receipt`; use that behavior head as `--base`. Preserve the full
receipt chain, including the explicit repair receipt, when reusing this baseline.

# Return outcomes acceptance

Updated 2026-10-03. **The integrated implementation at `0bb9c905655d` passed
fresh full private acceptance.** Publication and authentication of the merged
installed package remain in progress. Public integration checks and private
product acceptance are separate evidence records.

## Current integrated acceptance

The current implementation passed a fresh complete source stage, production and
independent validation over both original variants, mandatory global keys, exact
retained-reference comparisons, unchanged-input authentication and a new product
seal. Native observations verified fresh partition workers and joined exits.
A separate noneditable installed consumer passed strict reading, exact accepted
parent joins and aggregate quality denominator checks. Independent terminal
composition completed within the original authorized clock.

Private artifacts, measurements and receipts remain external. Prior failed
attempts remain unaccepted and retained. The implementation preserves calendar-day
definitions, types, NULLs, duplicate multiplicity and routing. Downstream
pinning, publication and study endpoint selection remain downstream-owned.
The historical records below describe earlier revisions and do not substitute
for this current acceptance.

## Accepted original revision

The accepted readmissions branch ends at review commit `82d3bd5`. Its sealed
producer commit is `5d9ddd5`, with package identity
`de9d4268bb64ffa47411f019d42c7e3f1abd76a8935bd96d285d7081ba752d88`.
The final review commit adds documentation and explicit transfer E2E cases;
it leaves the sealed producer code and contract unchanged.

The original C0 provenance, exact parent validation, resource pilot, one locked
outcomes-only build of both variants, independent full return validation,
pre/post input byte comparison and terminal seal audit passed. The independent
audit rehashed every source/parent/output artifact covered by its receipt.
Full pytest (464 cases), Ruff, lock, legacy E2Es, return E2Es, noneditable wheel
and installed old-consumer checks passed. Detailed private identities, row
counts, logs, paths, resource measurements and receipts remain external.
The original branch and validation runtime are retained for reproduction.

## Integration with current main

The integration starts from `c81650b` and keeps the existing encounter builder,
CLI, coverage, cache format, default validator and shared production acceptance
contract. The return-specific parent proof is preserved in
`encounters/return_parent_validation.py`; only opt-in return callers use it.
Its historical receipt format is not substituted for the production encounter
acceptance API. The approved scientific rules in
[RETURN_CONTRACT.md](RETURN_CONTRACT.md) remain unchanged.

This adds Python source and therefore changes the package identity. Existing
return validation requires the producing code identity; the old seal cannot
validate a newly integrated runtime. Do not rewrite the old manifest or receipt,
relax identity checks, or resume old partitions under the new identity.

Public checks passed at integration commit `99b2a3a`: 492 pytest cases, both
retained E2E runners with artifact readback, Ruff, formatting, lockfile and diff
checks, and a noneditable wheel with existing consumer API/CLI checks without
PYTHONPATH. The integrated package identity is
`ae5f2428d3155868711c9d42cae72fa5c4178074a7b3c0a24654bafd4cb4b33b`.
See the [integration handoff](RETURN_INTEGRATION.md) for scope and commands.
Hosted CI is reported separately on the draft PR. No private source scans,
parent revalidation, resource pilots, builds or analysis ran in this session.

After reorganization, private acceptance of the integrated revision requires
fresh exact-parent/resource gates, one locked outcomes-only build, independent
validation, unchanged-input proof and a new external seal. Downstream return
reading and study endpoint selection remain separate work.

## Historical repairs

The dated [audit](RETURN_AUDIT.md), [decision package](RETURN_DECISION_PACKAGE.md)
and [testing review](testing_review.md) document earlier states. Their pending
or blocked language applies to those revisions. The full historical acceptance
ledger remains in Git at `82d3bd5`; private failed-run artifacts remain external.

- The initial parent gate found missing precision metadata in the accepted
  producer representation. The approved v2 proof derives day precision from
  retained raw date fields without changing accepted input bytes.
- Exact parent checks and return summary writes required bounded partitions and
  explicit resource limits. Those repairs preserved the comparisons and rows.
- Two earlier attempts failed because of external storage. Their outputs were
  preserved without acceptance.
- The r3 run was rejected when an independent fixture exposed false negative
  flags for a partially missing return start. The fixture failed before repair;
  the corrected rules preserve possible-window uncertainty. The fresh r4 run
  subsequently passed all original acceptance gates.
- The supplemental transfer E2E verifies coherent same-ID ED/inpatient
  progression and separate events when distinct IDs lack transfer linkage.

## Commands and limits

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

The private runner adds the shared lock, gate receipts, immutable-input checks
and external seal. Use the matching frozen package for the existing accepted
bundle. Calendar-day outcomes do not establish complete return capture,
intraday ordering, planned status, causality or clinical eligibility.

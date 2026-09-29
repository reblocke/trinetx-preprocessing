# Testing review and evidence

Review baseline: `8a1185b`, 2026-09-25. The owner requested removal of tests
without a concrete failure absent from broader workflow coverage, E2E-first
verification, and reproducible evidence. Production behavior and private
acceptance requirements are outside this cleanup.

Every original test function is accounted for in the parallel reviews:

- [Clinical transforms and stages](testing_review_clinical.md)
- [Encounter and return interfaces](testing_review_encounters.md)
- [Pipeline, CLI, storage and source contracts](testing_review_pipeline.md)

The retained exceptions protect specified failures that the current small E2E
fixtures do not exercise. A stage integration or mocked lifecycle test is not
described as whole-program E2E. In particular, complete real-boundary
source-to-parent-to-returns coverage was a private acceptance gate, later
completed at the original sealed revision. Integration has its own gate record
in [RETURN_ACCEPTANCE.md](RETURN_ACCEPTANCE.md).

## E2E evidence runner: failure modes recorded before implementation

The runner will invoke the existing five complete pipeline/source workflows;
it will not duplicate their assertions in new unit tests. Verification will
exercise the executable runner and its saved outputs directly.

| Failure | Required behavior and executable verification |
| --- | --- |
| Temporary test products vanish after a green summary. | Force pytest to retain all temporary products, independently require output CSVs from each workflow, and preserve JUnit results and captured output in a new external evidence directory. Inspect the resulting files after the process exits. |
| A typo, skip or changed selection gives a vacuous pass. | Require exactly the five selected, successful test cases as well as pytest exit zero. Missing, skipped, failing or duplicate cases cannot produce a passing receipt. |
| Existing evidence is overwritten by pytest's basetemp cleanup. | Require a fresh output directory and reject symlinked ancestors and in-repository output. Repeat with the existing path and confirm its manifest hash is unchanged. |
| Saved artifacts are edited, added or removed. | Hash and inventory every retained file and safe internal symlink. Read back the complete inventory. Alter a copied artifact and require verification to fail. |
| Code changes during the run or the environment is ambiguous. | Retain a source/configuration/fixture snapshot and hashes before and after, the Git revision, pinned lockfile, Python/package versions and exact command. A changed source inventory cannot pass. |
| A failed subprocess is reported as successful or its evidence is discarded. | Preserve stdout/stderr, JUnit when present and native exit status; write a failed receipt. Exercise this through the actual runner with a failing workflow in a disposable synthetic checkout. |

Review before execution also identified malformed JUnit, unavailable package
metadata, wrong test modules, nested manifests and post-run inventory errors as
ways to lose or falsely pass evidence. Preserve failed receipts and match full
test identities. Include nested manifests in the file inventory.

The manifest provides local integrity and reproducibility evidence, not a
signed acceptance seal. Its printed SHA-256 can be retained independently.
Timestamps, timings and absolute temporary paths can vary between repeat runs;
the retained E2E assertions establish the documented output contracts.
Saved products include deliberate negative-case corruption from the existing
combined contract workflow; they are synthetic test evidence, not an accepted
source product.

## Review result

An independent AST comparison against `8a1185b` and the three inventories
accounts for all **434 original test functions**: **58 removed, 376 retained**.
No test function was added. Two redundant modules were deleted. Existing
assertions were moved into broader checks, including the frozen output-schema
oracle and logical Parquet hash keys in full pipeline E2E.

| Scope | Original functions | Removed | Retained |
| --- | ---: | ---: | ---: |
| Clinical transforms and stages | 116 | 21 | 95 |
| Encounter and handoff | 79 | 4 | 75 |
| Pipeline, CLI and infrastructure | 239 | 33 | 206 |
| Total | 434 | 58 | 376 |

Production source, dependency pins, scientific expectations and private
acceptance tolerances are unchanged. The original checkout receives only the
AGENTS.md testing policy; test edits belong to the existing readmissions review
worktree. The owner-requested Python/R starter updates cover all four ZIPs and
both expanded templates. Original archives were backed up and hashed; ZIP
readback verified identical member inventories and unchanged bytes outside the
23 intended guidance members against the retained current-base archives. The
starter checkout was first fast-forwarded to the already merged `67456a6`
readiness implementation, preserving the new workflow. Both maintained exports
passed their authoritative rebuild check and all four existing packager checks;
25 runtime/configuration files remain identical to that base. The final starter
diff contains 12 guidance files and four ZIPs.

## Verification checkpoint

The existing pinned environment ran the five selected E2Es through
`uv run --offline --no-sync python scripts/verify_e2e.py --output-dir <external>`:
**5 passed in 59.23 seconds**. The saved bundle contains 647 inventoried files
and internal symlinks, including a source snapshot, fixtures/configurations,
JUnit, log and generated workflow products. Its independently retained
manifest SHA-256 is
`c1696233b165870b3ceb3afb80b94e2c896001237d3c980154a204856a86d59f`.

Executable CLI checks verified the positive receipt, refused an existing output
path without changing its manifest, rejected altered CSV bytes, rejected an
unlisted nested manifest and rejected a wrong manifest hash. The copied evidence
passed before mutation and after restoration. An intentionally broken frozen
schema in a disposable checkout made the real pipeline E2E fail; the runner
preserved pytest exit 1, the failed case and a failed receipt. The original
evidence and repository fixture were unchanged.

The final full suite passed **464 cases**, with 238 existing pandas fragmentation
warnings, in **669.06 seconds**. It ran as
`uv run --offline --no-sync pytest -q --junitxml=<external>/full-suite.xml`,
with stdout/stderr retained alongside the XML. The original suite had 522 cases.

Scoped agent runs passed 101 clinical, 115 encounter and 80 pipeline cases.
These overlap the final suite and are not additive coverage claims. Root Ruff,
format checks on all 30 touched Python files, lockfile and diff checks passed.
No original readmissions goal checkpoint is completed by this test cleanup.

## Integration with current main — 2026-09-29

The original cleanup inventory remains a dated record. Integration retains all
current-main acceptance, validation, coverage and checkpoint tests. The existing
return-parent regressions move to `test_return_parent_validation.py`, matching
the isolated opt-in implementation. The old duplicate default-CLI failure check
is covered by main's structured-failure CLI test. The distinct empty-population,
CLI policy misuse and typed/reordered-cache scenarios are preserved against
main's public interfaces. Equivalent zero-linkage, same-count tampering and
legacy-cache rejection scenarios are already covered by the retained main tests.
This relocation adds no new post-implementation unit-test design.

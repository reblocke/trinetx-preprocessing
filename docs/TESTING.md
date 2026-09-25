# Testing

## Goals
- Make correctness cheap to verify.
- Guard against silent behavior change during refactor.
- Keep tests free of confidential data.

## E2E first

Follow the owner-required [testing policy](../AGENTS.md#testing-policy).
Highly prefer E2E as the sole testing mechanism. Never write unit tests after
implementation. If isolation is necessary, first write down the ways the system
could fail and the failures missing from E2E coverage, then write the code.

The primary synthetic workflows exercise the complete CSV and chunked Parquet
pipeline, `run`/`baseline`/`compare`/`profile`, a repeatable canonical-source
build, and the 36-file compatibility contract. Expected schemas come from the
frozen fixture, independently of the implementation constant.

The [2026-09-25 review](testing_review.md) accounts for every original test
function, records deleted duplication, and justifies retained checks. These
exceptions include:

1. Clinical boundaries, missingness, duplicates, ties and malformed values absent
   from the three-encounter E2E fixture, exercised through stage integrations or
   necessary isolated regressions.
2. Cohort-source contract tests: manifest/schema/catalog validation, required
   element and catalog-pin failures, read-only external spill cleanup, and
   traditional-rule coverage
3. GLP-1 migration tests: direct-raw versus adapter-backed source and downstream
   parity across all five clinical domains, including traditional-only source
   candidates and concept-independent raw observability
4. Return-outcome tests: opt-in synthetic episode, ICD/gas, partition/resume,
   artifact-identity and summary reconciliation checks. The private source
   capability preflight must pass before any outcomes-only resource pilot or
   build; public fixtures never replace that gate.

A component test with a mocked parent/source validator is not complete
source-to-parent-to-returns E2E coverage. The resumed return goal requires
the real parent/source gate and a locked full build before acceptance.

For the calendar-day v2 return partition, use a new external directory:

```bash
uv run python scripts/verify_return_v2_partition_e2e.py /external/new-return-e2e
uv run python scripts/verify_return_v2_partition_e2e.py \
  /external/new-return-e2e --verify
```

This E2E retains synthetic source data, all six outputs at one and three
partitions, hand-authored results, independent reconciliation, adversarial
corruption results, code/fixture/script identities and SHA-256 inventory. Its
receipt identifies its partition scope; it does not replace full manifest-bound
parent/source validation or private C4 acceptance.

## Retained E2E artifact

Use a **new external directory**. The runner rejects existing directories and
symlinked ancestors; on macOS use `/private/tmp` rather than the `/tmp` symlink.

```bash
uv run python scripts/verify_e2e.py --output-dir /external/new-e2e-run
uv run python scripts/verify_e2e.py --verify /external/new-e2e-run \
  --manifest-sha256 <printed-manifest-sha256>
```

The directory retains the exact command, JUnit, stdout/stderr, exit status,
source/configuration/fixture snapshot, lockfile, environment versions and all
five workflows' generated products. A JSON manifest inventories their bytes
and SHA-256 hashes. Verification checks the inventory and recorded outcome;
an empty/skipped/failed selection or missing saved outputs cannot pass. Failed
runs retain a failed receipt. Treat the printed manifest hash as an independent
integrity anchor, not a signed acceptance seal.

Repeat from the recorded revision with matching source hashes, or restore the
retained `source/` files into a separate checkout of that revision, run
`uv sync --locked`, and use a new output directory. The snapshot excludes private
data. Preserve the original evidence at its recorded location because pytest
creates absolute internal symlinks. Timings, temporary paths and logs may differ
between runs. The existing E2E assertions verify deterministic output contracts.
Some retained outputs deliberately contain negative-case corruption; the bundle
is synthetic test evidence, not an accepted canonical product. Review before
publishing generated artifacts.

## Commands
```bash
uv run ruff format --check .
uv run ruff check .
uv lock --check
uv run pytest -q
uv run python -m trinetx_preprocessing --help
uv run python -m trinetx_preprocessing validate-cohort-source --help
uv run python -m trinetx_preprocessing build-returns --help
uv run python -m trinetx_preprocessing validate-returns --help
```

The full suite includes the justified isolated and adversarial checks. Its pass
does not replace the retained E2E artifact or private scientific acceptance.

## Fixtures
- Put only synthetic or de-identified fixtures under `tests/fixtures/`.
- Prefer tiny tables that still exercise edge cases (missing values, duplicates, etc.).

## Regression strategy (recommended)
- Snapshot key outputs (or hashes) from the legacy pipeline on a fixture dataset.
- In CI/local runs, regenerate outputs from the refactored pipeline and compare.
- For real-data golden-master validation, hash approved local legacy outputs with
  `hash-outputs --scope final --hash-chunk-rows 100000`, hash refactor outputs
  the same way, and compare with `compare-manifests --report`. Summarize the
  gate with `validation-status` and save JSON/Markdown reports under the
  private external validation root. Do not commit row-level outputs or
  unreviewed manifests.
- `validation-status` remains the strict historical-parity gate. Milestone 2's
  corrected release evidence is the explicit exception documented in
  `docs/VALIDATION.md`; it does not claim a ready strict status while source
  encounter-setting conflicts remain unadjudicated.
- Current code/API and synthetic CI acceptance does not claim a private
  full-data run for the expanded traditional catalog or current GLP-1 adapter.
  See `CURRENT_STATE.md` and `VALIDATION.md` before making cutover claims.

## Selecting checks for an update

Use [UPDATE_VERIFICATION.md](UPDATE_VERIFICATION.md) for change-based routing,
exact source-mode comparison, safe staged-product reuse, and compact private
receipts. Public checks do not authorize source cutover.

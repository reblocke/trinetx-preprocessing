# Encounter preprocessing release summary

Updated 2026-09-24. This is the single public status and command reference for
the merged encounter preprocessing interface. It contains no private bundle,
source, receipt, or row identities.

## Public code and reported private evidence

- Upstream PR [#14](https://github.com/reblocke/trinetx-preprocessing/pull/14)
  merged at `4bbe8cfee3dad3b7c07fb8c42d7217804150b650`; its CI check passed:
  [upstream CI run](https://github.com/reblocke/trinetx-preprocessing/actions/runs/35945323601).
- Downstream PR [#15](https://github.com/reblocke/trinetx-hypercapnia-code/pull/15)
  merged at `d5d269168eafc7905c9238a5486fc03a62b55ec3`; its CI check passed:
  [downstream CI run](https://github.com/reblocke/trinetx-hypercapnia-code/actions/runs/35945482347).
- The repository continuity record reports exact legacy parity, complete
  patient/composite-encounter linkage, a completed two-variant private bundle,
  and a successful retained-reference comparison. It reports 2,662,675
  FULL_DATA encounters and 833,476 AFTER_EXCLUSION encounters. These are
  historical reported results; this ticket has not independently reopened the
  private bundle or compared its receipt to those results.
- The continuity record says a private acceptance receipt exists. A bounded
  search of the currently accessible external volumes did not locate the private
  handoff index or that receipt. Its exact bundle binding and remaining private
  gates are therefore **unverified in this checkout**. No new private build or
  clinical-row scan was run.
- The current checkout began at the upstream merge commit above. Ticket changes
  are local and uncommitted. No encounter membership, retained value, timing
  rule, or evidence content has been changed.

## Gate status

| Gate | Status |
| --- | --- |
| Upstream/downstream merged source and hosted CI | Verified from GitHub PR metadata; both required CI checks passed |
| New code and synthetic mutation tests in this ticket | Complete: 109 encounter tests passed after the four validation fixes; the focused validation and coverage checks passed 62 tests. Ruff, `git diff --check`, and affected local Markdown link checks passed. The earlier 24-test RESEARCH FAST scratch run remains historical evidence for the preceding hardening pass. |
| Stronger validation of the existing private bundle | Pending; private bundle and trusted receipt identity are not accessible here |
| Retained-reference comparison bound to that exact bundle | Historically reported pass; exact private identity binding not verified here |
| Installed package pair and downstream receipt readback | Not established by the merged CI checks; remains a downstream/private gate |
| Scientific-analysis acceptance | Not established by preprocessing, CI, or this ticket |

Local verification used the pinned environment with an external temporary uv
cache because the default cache was inaccessible in this checkout:

```bash
UV_CACHE_DIR=/private/tmp/codex-trinetx-review-uv-cache uv run --offline --no-sync pytest -q tests/test_encounter_validation.py tests/test_encounter_coverage.py --tb=short
UV_CACHE_DIR=/private/tmp/codex-trinetx-review-uv-cache uv run --offline --no-sync pytest -q tests/test_encounter_*.py --tb=short
UV_CACHE_DIR=/private/tmp/codex-trinetx-review-uv-cache uv run --offline --no-sync ruff check src/trinetx_preprocessing/encounters/{builder,checkpoints,cli,coverage,validation}.py tests/test_encounter_{checkpoints,coverage,validation}.py
UV_CACHE_DIR=/private/tmp/codex-trinetx-review-uv-cache uv run --offline --no-sync ruff format --check src/trinetx_preprocessing/encounters/{builder,checkpoints,cli,coverage,validation}.py tests/test_encounter_{checkpoints,coverage,validation}.py
git diff --check
```

A `complete` manifest proves build completion only. The upstream validation
report proves artifact checks only. Production acceptance requires the trusted
private release process to bind the required gates to the exact manifest and
report. A neighboring JSON file is not trusted by its presence or self-hash.
The versioned receipt records product/schema identity, both source identities,
covered variants and output hashes, the historical producer code identity, the
validator revision and contract version, linkage policy/origin/results, reference
comparison identity/contract/results, tested producer/consumer revisions,
required gate statuses, exceptions, and limitations. Receipt verification takes
the expected manifest, policy, variants, required gates, and report bytes from
the trusted caller.

Stage-cache fingerprints use `duckdb-json-multiset-v1`: DuckDB serializes each
complete typed row as an ordered JSON object; the serialized row strings are
sorted lexically, then length-prefixed UTF-8 bytes are fed to SHA-256 in bounded fetch
batches. Identical rows are included once per occurrence. DuckDB's logical JSON
rendering defines date, null, string, and numeric representation for this
version. The fingerprint is created with the stage receipt and recomputed only
when the stage is reused; legacy receipts without it require verified adoption
or rebuilding the affected materialization.

## Use and revalidate the existing bundle

This route does not rebuild. Resolve the private paths and lock from the existing
private `LOCAL_PATHS.md`; keep all real paths and reports outside Git. Run under
the existing shared execution lock:

```bash
python3 scripts/with_execution_lock.py "$HANDOFF_DIR/locks/build.lock" -- \
  trinetx-preprocessing validate-encounters \
    --bundle "$ACCEPTED_BUNDLE" \
    --linkage-policy complete_linkage \
    --work-dir "$NEW_PRIVATE_VALIDATION_WORK" \
    --report "$NEW_PRIVATE_VALIDATION_REPORT"
```

For a legacy bundle without policy metadata, validation defaults to strict
`complete_linkage`; the explicit flag above records the release choice. The
validator recomputes linkage from its immutable coverage Parquet and records the
effective policy and its origin in the new external report. A legacy incomplete
linkage exception requires both `--linkage-policy permit_incomplete_linkage` and
`--linkage-exception` with the approved rationale. A newer bundle supplies its
own policy; conflicting flags and partial policy metadata fail. Across both
formats, contradictory keys, zero linked sources, and strict-policy missing
links fail. Catalogue summary checks independently apply the inclusive window
lengths bound in the manifest.

Then run the downstream retained-reference comparator and installed-consumer
readback against the same immutable bundle, using the same lock. Pass the report
and exact expected manifest identity to the trusted private release process. Do
not rewrite the old receipt or the bundle manifest; preserve historical receipts
and use a new, externally stored report/receipt for new validator behavior.

## Build a new bundle

Use this only when the existing immutable bundle cannot satisfy the stronger
checks or a concrete data-affecting discrepancy requires a rebuild. The
authenticated compatibility companion supplies legacy population and
transformation inputs; the canonical database supplies enrichment. Keep inputs
read-only and all databases, spill, manifests, logs, and products in validated
external locations. Run every phase under the same existing lock:

```bash
python3 scripts/with_execution_lock.py "$HANDOFF_DIR/locks/build.lock" -- \
  trinetx-preprocessing build-encounters \
    --compatibility-database "$COMPATIBILITY_DATABASE" \
    --legacy-only --output-dir "$NEW_LEGACY_BASE"

python3 scripts/with_execution_lock.py "$HANDOFF_DIR/locks/build.lock" -- \
  trinetx-preprocessing build-encounters \
    --database "$CANONICAL_DATABASE" \
    --compatibility-database "$COMPATIBILITY_DATABASE" \
    --legacy-bundle "$NEW_LEGACY_BASE" \
    --legacy-acceptance "$LEGACY_ACCEPTANCE" \
    --coverage-only --linkage-policy complete_linkage \
    --output-dir "$NEW_COVERAGE"

python3 scripts/with_execution_lock.py "$HANDOFF_DIR/locks/build.lock" -- \
  trinetx-preprocessing build-encounters \
    --database "$CANONICAL_DATABASE" \
    --compatibility-database "$COMPATIBILITY_DATABASE" \
    --legacy-bundle "$NEW_LEGACY_BASE" \
    --legacy-acceptance "$LEGACY_ACCEPTANCE" \
    --coverage-bundle "$NEW_COVERAGE" \
    --output-dir "$NEW_ENCOUNTER_BUNDLE"

python3 scripts/with_execution_lock.py "$HANDOFF_DIR/locks/build.lock" -- \
  trinetx-preprocessing validate-encounters \
    --bundle "$NEW_ENCOUNTER_BUNDLE" \
    --work-dir "$NEW_PRIVATE_VALIDATION_WORK" \
    --report "$NEW_PRIVATE_VALIDATION_REPORT"
```

The explicit `permit_incomplete_linkage` policy requires `--linkage-exception`
with a documented rationale when creating new coverage. It is available only
when the release process approves the exception and incomplete capture is
propagated. It does not suppress demographic or anchor contradictions. The
downstream retained-reference comparison and installed-pair verification remain
separate gates after artifact validation.

## Scope and limits

The encounter interface does not contain propensity or weight estimates, new
GLP-1 estimates, prevalence results, or figures. Anchors remain at calendar-day
precision. Source availability is distinct from absence; observed spans do not
establish continuous or lifetime capture. Catalog membership is source
candidacy, not clinical eligibility. Fresh-source equivalence to the retained
compatibility population remains unestablished. Canonical-only recovery and
failed-run procedures in earlier notes are historical unless the private release
owner explicitly authorizes them.

## Preserved 2026-09-20 failure history

The first integrated enrichment attempt was interrupted by a host restart while
materializing FULL_DATA vital sources. A later recovery attempt exceeded the
DuckDB cap during the encounter-type context join; narrow patient-partitioned
inputs were then introduced. Its partition export encountered macOS AppleDouble
sidecars as invalid Parquet inputs. Those failed artifacts and their private
checkpoint records were retained. Subsequent continuity notes report a corrected
private build and reference comparison passing for both variants. This chronology
is retained as history and does not replace the current private receipt check.

> Historical verifier documentation. The study verifier now lives in trinetx_analysis.glp1_verification downstream; this page records its pre-relocation interface.

# Verifying preprocessing updates

Use one change plan to select the necessary evidence. Keep the canonical
DuckDB, raw inputs, and the frozen Stata reference; the verifier removes only
its own temporary GLP-1 comparison products after successful acceptance.

```bash
uv run python -m trinetx_preprocessing verify-update plan --base <accepted-commit>
uv run python -m trinetx_preprocessing verify-update run \
  --base <accepted-commit> --receipt-dir /private/verification/new-run
uv run python -m trinetx_preprocessing verify-update status \
  --receipt-dir /private/verification/new-run
```

Commit first: execution requires the exact clean head selected by the plan.
`config/verification_policy.json` records ordered path rules and product
ownership. The plan lists every changed path, unknown paths, revisions, and
policy/code hashes. Unknown paths require the broader materialization gate.
Review the classification: filenames cannot determine scientific intent.
Changes to this registry or observer-only exclusions require particular review.

| Change | Required evidence |
| --- | --- |
| Documentation, tests, verification tools | Public suite and lint; no private scan |
| GLP-1 source adapter or orchestration | Source contract and full raw/database GLP-1 parity |
| Shared source transformations or dependencies | Canonical build, all 36 compatibility projections, GLP-1 parity |
| Scientific definitions or configuration | Applicable product checks, approved decision, baseline comparison, explicit drift review |

The public suite includes synthetic source-mode equivalence, duplicates,
missingness, row identities, schema drift, serialization, publication, and
negative contract tests. Small relations use bidirectional `EXCEPT ALL`. Large
relations are written once into 64 hash partitions, then compared by grouping
complete typed rows and summing signed multiplicities within each partition.
Hashes only route rows: collisions do not establish equality. The positive and
negative multiplicity differences equal the two `EXCEPT ALL` counts. Typed
Parquet round trips and complete row coverage are checked explicitly. This
bounds each aggregation and preserves duplicate counts, nulls and row values.
The eight required output files are checked; AppleDouble filesystem metadata
is excluded from that inventory. Ordinarily only
`run_id` is excluded from table values; deterministic index-event IDs remain
exact. Proven raw-reference reuse additionally permits the two recorded producer
revisions to differ, after checking every stored producer value against its
expected revision. Clinical values and row identities retain exact comparison.
All contracted source/evidence/observability, clinical, flow and QA tables are
compared. Exported Parquet must also equal its database table. Manifest and
stable report comparisons preserve their existing operational exceptions.

## Initial source migration and private updates

```bash
uv run python -m trinetx_preprocessing verify-update run \
  --base <accepted-commit> --full-glp1 \
  --database /private/preprocessed/trinetx_preprocessed.duckdb \
  --raw-input /private/approved-export \
  --config config/glp1_eligibility.yml \
  --receipt-dir /private/verification/new-run
```

`--full-glp1` establishes initial private source-mode parity even when the
current diff only changes verification code. A normal workflow update selects
this automatically. Both modes use the same clinical derivations. Database
mode uses the shared clinical domains and saved audit evidence without opening
raw files. This proves source interchangeability; it does not independently
validate clinical definitions or certify every upstream retained source row.

Materialization changes additionally require `--preprocessing-config` and
`--compatibility-baseline`. The baseline is an approved
`capture_compatibility_evidence` JSON receipt with 36 distinct table entries.
The verifier builds the configured canonical product and compares all 36
schemas, row counts and normalized content hashes in one CSV scan. Broader
source certification and historical Stata parity retain their existing gates.
A GLP-1-only acceptance receipt cannot retire that compatibility bridge.

To check future behavior against an accepted run, supply `--baseline-receipt`
pointing to its `acceptance_complete.json`; its head must equal `--base`.
Receipts retain counts, missingness/status summaries, cohort flow, and SHA256
fingerprints of complete analytical/evidence output contents, including
identities. Those fingerprints detect changes that preserve totals. Fingerprint
construction streams sorted row hashes with bounded Python memory and external
DuckDB spill. Run IDs and producer revisions are recorded separately and excluded
from scientific content fingerprints. Treat these as private aggregate evidence,
not publishable data.
Different inputs, catalogs or runtime versions must be investigated when drift
is observed; raw/database parity alone cannot establish across-version stability.

Scientific changes require `--decision` containing `base`, `head`,
`status: "approved"`, `approved_by`, `decision_reference`, and `expected_drift`.
This records an existing scientific decision; the verifier does not grant one.
A scientifically changed run ends `review_required`, preserving outputs.
After reviewing `drift_report.json`, record its SHA256 in that decision as
`drift_report_sha256` and run:

```bash
uv run python -m trinetx_preprocessing verify-update accept-drift \
  --receipt-dir /private/verification/new-run --decision /private/decision.json
```

Failed parity can never be accepted by this command. Resolve source-mode
mismatches before scientific drift review. An unapproved change detected against
a baseline fails and preserves its private evidence.

## Reusing a completed staged canonical database

```bash
uv run python -m trinetx_preprocessing verify-update check-candidate \
  --database /private/build/.trinetx-combined-build-ID/trinetx_preprocessed.duckdb \
  --preprocessing-config /private/build/config.yaml --producer <producer-commit>
uv run python -m trinetx_preprocessing verify-update promote-candidate \
  --database /private/build/.trinetx-combined-build-ID/trinetx_preprocessed.duckdb \
  --preprocessing-config /private/build/config.yaml --producer <producer-commit> \
  --receipt /private/verification/promotion.json
```

Reuse requires terminal source/export stages, unchanged database/export file
state, matching historical producer code, unchanged materialization code,
configuration/catalog/runtime/input inventory, matching embedded and sidecar
manifests, and an empty destination. Verification-only modules are excluded
from the materialization fingerprint. Historical producer hashes remain intact.
Promotion uses the existing locks and publication journal; it never substitutes
new metadata for missing records. Input inventory reuse checks stat/header
identity under the immutable-input contract; it does not rehash every raw file.
The subsequent raw/database comparison checks the saved full-file audit hashes.
Promotion certifies reuse, not scientific acceptance.

## Recovering an adapter build without repeating the raw reference

If a run completed its raw-reference build and then failed in the database-backed
build, a new run can borrow that completed reference:

```bash
uv run python -m trinetx_preprocessing verify-update run \
  --base <failed-run-head> --full-glp1 \
  --database /private/preprocessed/trinetx_preprocessed.duckdb \
  --raw-input /private/approved-export \
  --config config/glp1_eligibility.yml \
  --reuse-raw-receipt /private/verification/failed-run/status.json \
  --receipt-dir /private/verification/recovery
```

Reuse fails if raw-producing code, dependencies, configuration, catalog or source
identity changed. The raw-code fingerprint conservatively includes all source
modules except the database adapter and the declared verification-only modules.
The verifier checks the reference manifest, database provenance, complete output
inventory and aggregate counts against the previous receipt. It does not rewrite
the original producer revision or rescan raw exports. The new receipt binds both
producer revisions and the reuse proof, then performs the full exact comparison.
Reference reuse is never a substitute for that comparison.

The new run owns only its new output directory. Borrowed reference outputs and
the failed run remain intact, including after successful recovery; remove their
owned temporary products only after reviewing the acceptance evidence.

Large GLP-1 comparisons use 64 partitions and 8,192-row Parquet groups.
This reduces concurrent column-buffer spill and external-filesystem overhead.
A bounded synthetic test on the execution drive measured the same exact result
about four times faster than 256 partitions with 2,048-row groups; this timing
does not replace private full-data acceptance.

## Retrying comparison without rebuilding either dataset

If both builds completed and comparison failed, commit the observer-only repair
and borrow both completed packages in a new verification run:

```bash
uv run python -m trinetx_preprocessing verify-update run \
  --base <failed-comparison-head> --full-glp1 \
  --database /private/preprocessed/trinetx_preprocessed.duckdb \
  --raw-input /private/approved-export \
  --config config/glp1_eligibility.yml \
  --reuse-build-receipt /private/verification/failed-comparison/status.json \
  --receipt-dir /private/verification/comparison-recovery
```

This cannot be combined with `--reuse-raw-receipt`. Each build's original
producer, producing-code/dependency fingerprint, source identity, configuration,
catalog, complete output inventory, database provenance and recorded counts
must still match. A producing-code change requires rebuilding the affected
product. The new receipt retains both original producer revisions and a hash
of the failed receipt; historical manifests and failed receipts are unchanged.
Both packages remain borrowed through comparison and evidence sealing.

`comparison_progress.json` reports the current table and partition counts. The comparison
phase is reported immediately after writing finishes and after every completed
partition, so a long first group does not retain a stale writing label.
Partition hashes are never used as scientific content checksums. Synthetic
regressions compare forced partitions against the original exact operator,
including forced bucket collisions, duplicates, nulls, signed zero, NaNs,
precision-sensitive numeric/timestamp values and every output-table contract.
The private all-table comparison still has to pass before adoption.

## Runtime and evidence discipline

Run on the Mini with approved external storage; the Air is needed only for a
fresh licensed Stata discrepancy investigation. Preflight space and retain the
established process-family memory limit. Do not overlap large source scans.
Use status records and stage events rather than repeatedly loading full logs.
A quiet process does not establish progress or an ETA. Estimate from measured
comparable stages; source ingestion may dominate even after comparison improves.

Each run owns a fresh receipt directory and records phase durations, revisions,
policy/config/source identities, exact comparison results, and scientific
summaries. Failures preserve private diagnostics and comparison products.
Success writes aggregate evidence before removing only `.verification-outputs`;
canonical databases, raw inputs, and unrelated directories are untouched.
A rerun uses a new receipt directory; failed-run resumption is deliberately not
automatic. The explicit guarded reuse options above recover adapter or comparison failures.
Preserve an accepted baseline receipt to avoid rebuilding historical
reference products for later updates. The verifier does not claim a static-only
pass is private acceptance, or relabel incomplete work as passed.

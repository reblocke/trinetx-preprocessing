# Validation

Validation artifacts may contain sensitive metadata or row-level data and stay
under `/Volumes/LOCKE BOOK/trinetx-preprocessing-validation`. Do not commit raw
exports, subsets, work tables, manifests, logs, profiles, or output CSVs.

## Frozen replication evidence

`refactor-milestone-1` is the immutable historical-replication fallback. Its
full legacy/refactor comparison had identical schemas, row counts, and key sets.
An aggregate audit found `4,412,875 / 4,412,932` exactly matching rows
(`99.998708%`) and 57 Weight-related residual rows. Those private diagnostics
remain external and are not the acceptance target for corrected releases.

## Corrected release evidence

Post-Milestone 1 validation uses `docs/SPEC.md` as the behavior authority:

1. Unit and characterization tests prove every corrected rule and reducer.
2. Synthetic and staged tiers prove the stable 36-file/534-column contract and
   corrected invariants. Expected intentional deltas from notebooks are not
   treated as failures.
3. A fresh full profile proves real-data execution, resource use, one-pass
   index construction, and output completeness. Strict execution separately
   proves that source encounter-setting conflicts fail closed.
4. A PHI-safe aggregate report compares corrected output to Milestone 1 by
   cohort additions/removals, rule exclusions, setting conflict resolution,
   and screening effects. It contains no identifiers or row examples.

Any behavior-code, dependency, version, or ruleset change invalidates the full
profile evidence and requires a fresh run.

## Unified preprocessing Stage 1

The combined-product acceptance gate supplements the historical and corrected
release evidence above. Keep all evidence external.

```bash
ROOT="/Volumes/LOCKE BOOK/trinetx-preprocessing-validation/unified_v1"

./.venv/bin/python scripts/capture_combined_baseline.py \
  --output-dir "$ROOT/baseline/output" \
  --out "$ROOT/manifests/compatibility_baseline.json"

./.venv/bin/python scripts/benchmark_combined_preprocessing.py \
  --config "$ROOT/config.yaml" \
  --strict --replace \
  --out "$ROOT/manifests/combined_benchmark.json"

# When supervising a background benchmark, pass its Python PID and the same
# result path. Watch mode succeeds only for that observed process family and an
# explicit terminal "complete" result.
./.venv/bin/python scripts/monitor_combined_preprocessing.py \
  --pid "$BENCHMARK_PID" \
  --config "$ROOT/config.yaml" \
  --result "$ROOT/manifests/combined_benchmark.json" \
  --out "$ROOT/manifests/combined_monitor.json"

./.venv/bin/python scripts/verify_combined_parity.py \
  --database "$ROOT/output/trinetx_preprocessed.duckdb" \
  --output-dir "$ROOT/output" \
  --baseline "$ROOT/manifests/compatibility_baseline.json" \
  --out "$ROOT/manifests/combined_parity.json"

./.venv/bin/python scripts/verify_element_completeness.py \
  --database "$ROOT/output/trinetx_preprocessed.duckdb" \
  --out "$ROOT/manifests/element_completeness.json"
```

Acceptance requires all 36 ordered schemas, row counts, and normalized hashes
to match; database validation to pass; every source element to have a rule;
aggregate observed-match gaps to be reviewed; peak RSS to remain at or below
6,238 MiB using the sampled concurrent process-family sum; and free space to
remain above 100 GiB. Every source element must have at least one included
rule. The element report may list unobserved rules because absence in one
export is evidence, not necessarily an implementation failure.

The committed 20-case synthetic test additionally requires adapter-backed and
direct-raw GLP-1 source, analysis, cohort-flow, and evidence tables to match.
This proves the shared source boundary; it does not move study-specific GLP-1
eligibility decisions into preprocessing.

## Local gates

```bash
git diff --check
./.venv/bin/ruff check .
TMPDIR="/Volumes/LOCKE BOOK/trinetx-preprocessing-validation/tmp" \
UV_CACHE_DIR="/Volumes/LOCKE BOOK/trinetx-preprocessing-validation/uv-cache" \
./.venv/bin/python -m pytest -q
```

Tests use only synthetic/de-identified fixtures.

## External preflight

```bash
ROOT="/Volumes/LOCKE BOOK/trinetx-preprocessing-validation"

./.venv/bin/python -m trinetx_preprocessing inspect-inputs \
  --config "$ROOT/config.yaml" \
  --min-free-gb 100 \
  --json-out "$ROOT/manifests/corrected_v0.2.0_input_status.json"

./.venv/bin/python -m trinetx_preprocessing validate-inputs \
  --config "$ROOT/config.yaml"

./.venv/bin/python -m trinetx_preprocessing clean-scratch \
  --root "$ROOT" \
  --json-out "$ROOT/manifests/corrected_v0.2.0_scratch_inventory.json"
```

Preflight must confirm exact input discovery, valid headers, at least 100 GiB
free, no active competing run, and no unexplained scratch.

## Full corrected profile

Use fresh corrected-version work/output/profile directories. Do not overwrite
Milestone 1 evidence.

```bash
ROOT="/Volumes/LOCKE BOOK/trinetx-preprocessing-validation"

TMPDIR="$ROOT/tmp" \
UV_CACHE_DIR="$ROOT/uv-cache" \
PYTHONUNBUFFERED=1 \
./.venv/bin/python -m trinetx_preprocessing profile \
  --config "$ROOT/config.yaml" \
  --out "$ROOT/profile-corrected-v0.2.0"
```

Run the same command with `--strict` when source conflict adjudication is part
of the acceptance gate. The current full input has 286 encounter IDs assigned
to multiple settings, so strict execution intentionally fails; non-strict
execution records an aggregate conflict report and applies the specified
deterministic resolution.

Required evidence:

- 36 final CSVs with the ordered 534-column schema;
- positive stage timings and disk footprints;
- peak RSS no greater than 6,238 MB;
- final assembly no greater than 80,882 seconds;
- total wall time at least 25% below the 281,840.675-second baseline;
- final-assembly metrics showing each compact feature source scanned once;
- aggregate gas rejection and encounter-conflict counts;
- external free space remaining above 100 GiB.

If a performance target is missed, correctness evidence remains useful, but the
release waits while the measured top bottleneck is addressed.

## Earlier corrected profile evidence

The earlier review-clean full non-strict profile from commit `1112963`
completed with:

- 36 final CSVs and the ordered 534-column schema;
- 73,589.093 seconds total wall time;
- 49,180.54 seconds final-assembly time;
- 6,122.562 MB peak RSS;
- 15,894,947,783 bytes of work tables and 7,898,323,229 bytes of outputs;
- five compact feature sources scanned once, totaling 2,375,800,669 indexed
  rows;
- zero recognized scratch artifacts after completion.

The review-clean output differs from the pre-review profile only in six
obesity/ventilatory-support `AFTER` hashes; schemas and row counts are unchanged.
The PHI-safe Milestone 1 delta contains only aggregate counts: 4,412,932
Milestone 1 rows, 6,949,511 corrected rows, 3,471,448 shared keys, 941,484
Milestone-only keys, and 3,478,063 corrected-only keys. Local and GitHub review
are clean. Milestone 2 accepts the documented deterministic non-strict
resolution for the 286 source conflicts; strict execution continues to fail
closed and is the required mode when upstream conflict adjudication is part of
the analysis acceptance policy.

`validation-status` remains intentionally unchanged as the strict
historical-parity/merge-readiness verifier. Consequently, the Milestone 2
evidence bundle is expected to report that its strict-provenance gate is not
ready, and the release does not claim `validation_status.json` has
`ready: true`. For this release only, acceptance is the corrected evidence
checklist above plus the explicit aggregate conflict policy. A future run on
adjudicated source data should return to the strict `validation-status` gate.

## Current unified Milestone 2 evidence

The accepted fresh product was built from behavior head `c96dc40`; read-only
element-evidence head `f3c1b03` changes only bounded inspection and its
regression, not transforms, database materialization, compatibility export, or
the published product. The raw work manifest therefore remains correctly bound
to `c96dc40`, while the evidence correction is independently tested and
reviewed at `f3c1b03`.

The completed Step 2 gates are:

- atomic publication completed with exactly 38 product files: the canonical
  DuckDB, its manifest, and all 36 compatibility CSVs;
- total wall time was `89,270.965 s`; authoritative concurrent process-family
  peak RSS was `4,722,294,784` bytes (`4,503.531 MiB`), leaving
  `1,818,722,304` bytes below the `6,238 MiB` ceiling;
- corrected-baseline parity matched all 36 tables and all `6,949,511` rows,
  with zero schema, row-count, or normalized-hash mismatches;
- bounded database and element inspection passed with zero validation warnings
  or errors, all 534 historical elements, 92 source elements, and all 118
  included rules represented. Two transparently reported source rules had no
  observed match in this export and are not contract failures;
- both synthetic GLP-1 adapter cases passed without modifying any of the 38
  product files;
- the prescribed `run-final-assembly --strict` proof exited before writes with
  the exact 286-conflict failure, while the work manifest, conflict report, and
  published-product metadata remained unchanged;
- exact-head diff, repository-wide Ruff, and all 430 tests passed; free space
  remained above 100 GiB; product sidecars, WAL, product scratch, and recognized
  validation scratch all rechecked at zero after approved cleanup; and
- CI and Codex review passed at the `f3c1b03` evidence head with zero unresolved
  review threads. The final documentation-only head is reconciled separately
  in the live PR before completion is reported.

The aggregate evidence files remain external and untracked. They include
`combined_benchmark_c96dc40.json`, `combined_parity_c96dc40.json`,
`element_completeness_f3c1b03.json`, `adapter_contract_f3c1b03.json`,
`strict_resume_proof_c96dc40_worktree.json`, and
`local_release_gates_f3c1b03.json`. They contain no committed row-level data.

## Hygiene and review

Before release:

- `clean-scratch` reports zero known scratch artifacts after approved cleanup;
- `git status` contains no private or generated validation artifacts;
- local holistic review and GitHub Codex review have no unresolved actionable
  correctness, security, privacy, or performance findings;
- the aggregate Milestone 1 delta report is PHI-safe and external-only.

## GLP-1 downstream full-data evidence

The exact behavior-head additive GLP-1 build from commit `459cbda` completed in
20,941.55 seconds with 5,635,293,184 bytes maximum RSS. It used the supported
4,096 MiB/one-thread DuckDB configuration and atomically published exactly the
eight public files. The terminal validation gate found zero warnings, errors,
WAL files, recognized scratch artifacts, AppleDouble sidecars, hidden
workspaces, blank data-dictionary descriptions, or missing required concept
matches. External free space remained about 7.40 TiB.

The final run contains 59,954 analysis rows, 1,320,409 candidate encounters,
9,527 strict primary rows, 12,028,276 evidence rows, and all 15 cohort-flow
stages. Parquet, DuckDB, command-summary, and flow counts agree. Every paired
PaCO2 and arterial-pH evidence row retains its raw value, raw unit, normalized
value, and source-record hash.

The PHI-safe comparison against the preserved reviewed `71ef56f` build records:

- 59,954 shared index-event keys, with zero baseline-only or corrected-only
  keys;
- unchanged 1,320,409 candidate encounters, 9,527 strict primary rows,
  payer-route counts, and cohort-flow counts;
- 191 analysis rows changed by the all-history cirrhosis correction, affecting
  `dx_cirrhosis`, `cirrhosis_status`, and a suppressed small number of
  `mash_f2_f3_status` rows;
- 12,028,276 evidence rows, a net reduction of 2,603,596 comprising 9,193
  additional diagnosis rows and 2,612,789 removed post-index non-GLP-1
  medication rows;
- no full-data key/count effect from patient-scoped encounter reductions or
  precision-aware date-only procedure context.

The earlier `71ef56f` run remains a valid independent resource and
publication-contract baseline. The `e7bf01a` run verifies the cirrhosis,
encounter, medication, and procedure-context corrections. The exact-head
`459cbda` run additionally validates ruleset `2026-07-19.1` CKD source-precision
handling. Direct aggregate comparison between `459cbda` and `e7bf01a` found
zero schema, key-set, table-count, non-provenance analysis-value, or semantic
fingerprint differences across 59,954 analysis rows, 1,320,409 candidate
encounters, and 12,028,276 evidence rows.

The exact-head run root is
`/Volumes/LOCKE BOOK/trinetx-preprocessing-validation/glp1/full_final_459cbda_20260719`.
Its terminal validation, aggregate JSON/Markdown comparison, and final scratch
inventory are under `manifests/` and remain external and untracked.

The aggregate JSON and Markdown reports remain external and untracked. No
identifiers or row examples are emitted. Full-data computational validation does
not remove the separate investigator terminology and private record-review
requirements described in `docs/GLP1_ELIGIBILITY.md`.

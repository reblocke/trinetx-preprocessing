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

## Current corrected evidence

The review-clean full non-strict profile from commit `1112963` completed with:

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

## Hygiene and review

Before release:

- `clean-scratch` reports zero known scratch artifacts after approved cleanup;
- `git status` contains no private or generated validation artifacts;
- local holistic review and GitHub Codex review have no unresolved actionable
  correctness, security, privacy, or performance findings;
- the aggregate Milestone 1 delta report is PHI-safe and external-only.

## GLP-1 additive full-data evidence

The corrected additive GLP-1 build from commit `00e24a9` completed in
20,247.71 seconds with 5,342,773,248 bytes maximum RSS. It used the supported
4,096 MiB/one-thread DuckDB configuration and published all eight public files
atomically. The terminal validation gate found zero warnings, errors, WAL
files, recognized scratch artifacts, AppleDouble sidecars, blank data-dictionary
descriptions, or missing required concept matches.

The PHI-safe comparison against the preserved provisional build records:

- 59,954 shared index-event keys, with zero baseline-only or corrected-only
  keys;
- unchanged 1,320,409 candidate encounters and 9,527 strict primary rows;
- 14,631,872 corrected evidence rows, a reduction of 4,095,499 driven mainly by
  phenotype-specific measurement windows, partially offset by source-traceable
  paired-pH and corrected diagnosis, procedure, medication, and derived
  evidence;
- 12,378 code-only obesity rows represented by the added `dx_obesity` field;
- 29,841 rows with at least one non-provenance semantic change after excluding
  the global compact-date gas-pairing label correction.

The aggregate JSON and Markdown reports remain external and untracked. No
identifiers or row examples are emitted. Full-data computational validation does
not remove the separate investigator terminology and private record-review
requirements described in `docs/GLP1_ELIGIBILITY.md`.

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

The pre-review full non-strict profile from commit `3b87b83` completed with:

- 36 final CSVs and the ordered 534-column schema;
- 73,993.53 seconds total wall time;
- 49,153.049 seconds final-assembly time;
- 5,896.062 MB peak RSS;
- 15,894,947,783 bytes of work tables and 7,898,119,999 bytes of outputs;
- five compact feature sources scanned once, totaling 2,375,800,669 indexed
  rows;
- zero recognized scratch artifacts after completion.

The full output manifest exactly reproduces the independently run bounded final
assembly across all 36 tables. The PHI-safe Milestone 1 delta contains only
aggregate counts: 4,412,932 Milestone 1 rows, 6,949,511 corrected rows,
3,466,002 shared keys, 946,930 Milestone-only keys, and 3,483,509
corrected-only keys. GitHub review subsequently found a behavior-changing
`AFTER` mask-alignment defect and a strict-resume gap. Both are fixed and pass
local/staged tests, but this profile and delta are no longer current release
evidence. They must be regenerated before the explicit decision on whether the
286 source conflicts require upstream adjudication.

## Hygiene and review

Before release:

- `clean-scratch` reports zero known scratch artifacts after approved cleanup;
- `git status` contains no private or generated validation artifacts;
- local holistic review and GitHub Codex review have no unresolved actionable
  correctness, security, privacy, or performance findings;
- the aggregate Milestone 1 delta report is PHI-safe and external-only.

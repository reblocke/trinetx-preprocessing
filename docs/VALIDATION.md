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
3. A fresh full `profile --strict` proves real-data execution, resource use,
   one-pass index construction, and output completeness.
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
  --out "$ROOT/profile-corrected-v0.2.0" \
  --strict
```

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

## Hygiene and review

Before release:

- `clean-scratch` reports zero known scratch artifacts after approved cleanup;
- `git status` contains no private or generated validation artifacts;
- local holistic review and GitHub Codex review have no unresolved actionable
  correctness, security, privacy, or performance findings;
- the aggregate Milestone 1 delta report is PHI-safe and external-only.

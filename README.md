# TriNetX Preprocessing Pipeline

This repository provides a deterministic, CLI-driven preprocessing pipeline for
TriNetX exports. Its canonical product is one versioned
`trinetx_preprocessed.duckdb` containing the historical encounter-level payload
and additive source elements needed by the GLP-1 work and future studies. The
historical 36 CSV files are generated compatibility projections of that product.

Refactor Milestone 1 completed the replication phase under near-exact
legacy-vs-refactor row parity: `4,412,875 / 4,412,932` final analytic rows
matched exactly (`99.998708%`), with no schema, row-count, or key-set
differences. The remaining `57` shared-key row differences are documented as
Weight/previous-Weight legacy quirks for this milestone fallback point. Internal
work tables can use Parquet for lower-overhead execution; final analytic outputs
remain legacy CSV files.

Post-Milestone 1 development follows the corrected analytic contract in
`docs/SPEC.md`. The corrected pipeline uses explicit clinical rules, derives
encounter screening from diagnosis or lab availability, and builds compact
partitioned indexes while streaming each domain instead of repeatedly scanning
legacy group tables. Complete normalized domain copies are opt-in compatibility
artifacts rather than default work products.

This is a code-only repository; no manuscript version is expected here. The
repository may describe restricted export schemas, but it must not include raw
TriNetX exports, row-level extracts, PHI, credentials, or generated local
validation artifacts unless explicitly reviewed.

## Quickstart (synthetic fixtures)
```bash
mkdir -p .uv_cache
export UV_CACHE_DIR="$PWD/.uv_cache"
uv sync
./.venv/bin/python scripts/run_synthetic_example.py
```

The helper writes the canonical database and 36 compatibility CSVs under
`/tmp/trinetx-preprocessing-synthetic-example/`. Pass `--output-root` to use a
different location outside a Git worktree.

## Unified preprocessing product

Build the combined database and all 36 historical compatibility CSVs into an
external private output directory:

```bash
./.venv/bin/python -m trinetx_preprocessing build-preprocessed \
  --config /private/path/config.yaml

./.venv/bin/python -m trinetx_preprocessing validate-preprocessed \
  --database /private/output/trinetx_preprocessed.duckdb \
  --output-dir /private/output --json
```

Set `combined.enabled: true` to make `run` and `run-all` use this same builder.
The accepted full source contains 286 encounter-setting conflicts, so the
release build uses deterministic non-strict resolution. Use the prescribed
`run-final-assembly --strict` resume check as the separate fail-closed
data-adjudication proof; on the current source it exits before final-output
writes. Do not run a full strict replacement build against the accepted product.

Regenerate the compatibility CSVs into a separate external destination. The
source database must have one terminal `complete` manifest row. The command
keeps export scratch in its owned staging tree, validates all 36 files against
the database manifest, and publishes the set atomically; replacing an existing
compatibility-only tree is explicit:

```bash
./.venv/bin/python -m trinetx_preprocessing export-legacy \
  --database /private/output/trinetx_preprocessed.duckdb \
  --output-dir /private/compatibility-export --replace
```

See `docs/UNIFIED_PREPROCESSING.md` for the table grains, provenance contract,
compatibility boundary, and acceptance gates.

## Cohort-source handoff

The canonical DuckDB is also the handoff surface for future cohort builders.
It retains complete patient and encounter records plus source-faithful clinical
events matching the union of current GLP-1 and traditional hypercapnia/RFS
extraction rules. These rows are source candidates, not a study cohort: all
index selection, time windows, reductions, phenotype decisions, and analysis
logic remain downstream.

Validate a published source contract before a downstream process opens it:

```bash
./.venv/bin/python -m trinetx_preprocessing validate-cohort-source \
  --database /private/output/trinetx_preprocessed.duckdb \
  --require-element source.traditional.diagnosis.has_j9612 --json
```

The existing `export-legacy` command remains the exact 36-file CSV bridge for
the Stata reference workflow. The next migration phase will import cohort code
into a separate `trinetx_preprocessing.cohorts.hypercapnia` package; it will
consume this contract rather than raw exports.

## Downstream GLP-1 eligibility

The standalone raw-ingestion GLP-1 CLI remains the validated production
reference during migration. The unified product is currently an
adapter-validated source boundary, not a production CLI cutover or a second
canonical preprocessing product. The adapter is temporary: GLP-1 elements and
later cohort derivations belong in the same shared workflow as the legacy
elements, not in a permanent standalone module. A separate PR must add the
manifest-bound source and prove full-data adapter-versus-reference parity
before the raw scan can be deprecated:

```bash
./.venv/bin/python -m trinetx_preprocessing.glp1_eligibility validate-export \
  --input /path/to/trinetx_export

./.venv/bin/python -m trinetx_preprocessing.glp1_eligibility build \
  --input /path/to/trinetx_export \
  --output /path/to/output/glp1_eligibility \
  --config config/glp1_eligibility.yml

./.venv/bin/python -m trinetx_preprocessing.glp1_eligibility status \
  --output /path/to/output/glp1_eligibility \
  --watch --interval-seconds 30
```

See `docs/GLP1_ELIGIBILITY.md`, `docs/GLP1_DATA_CONTRACT.md`, and GitHub issue
#6 for the downstream analytic contract and clinical-review requirements.

## Real data placement (do not commit)
Put raw TriNetX exports under `data/` (git-ignored) and update `config.yaml`:
```
data/
  Encounter/
  Diagnosis/
  Lab Results/
  Medications/
  Procedure/
  Vital Signs/
  Patient/
```
Adjust domain patterns in `config.yaml` if your filenames differ.

Keep real-data validation under a private external root:
```bash
export VALIDATION_ROOT="/private/path/trinetx-preprocessing-validation"
export UV_CACHE_DIR="$VALIDATION_ROOT/uv-cache"

./.venv/bin/python -m trinetx_preprocessing scaffold-validation \
  --data-dir "/private/path/TriNetX" \
  --validation-root "$VALIDATION_ROOT"
```
Use the mounted private raw-data tree as `data_dir`, and place `work_dir`,
`output_dir`, profile output, logs, and manifests under that external root.

## CLI basics
```bash
./.venv/bin/python -m trinetx_preprocessing --help
./.venv/bin/python -m trinetx_preprocessing inspect-inputs --config config.yaml
./.venv/bin/python -m trinetx_preprocessing inspect-inputs --config config.yaml --json-out artifacts/input_status.json --max-matches 1 --skip-space-check --domain-timeout-seconds 20
./.venv/bin/python -m trinetx_preprocessing validate-inputs --config config.yaml
./.venv/bin/python -m trinetx_preprocessing run --config config.yaml
```
The JSON `inspect-inputs` output includes the resolved config path, config
SHA-256, generation time, domain matches, search-directory existence, and free-space checks so it
can be saved with validation manifests. It stores counts plus a bounded path
sample, not row-level data. Use `--json` for stdout or `--json-out` to write the
status file by atomic replacement. Use `--max-matches 1` for quick restore
monitoring; omit it when you need exact per-domain file counts. Use
`--domain NAME` to isolate one configured domain, and `--skip-space-check` if
the mounted volume is stalling on free-space queries. Add
`--domain-timeout-seconds N` with
`--max-matches` when a single restored directory can stall the whole metadata
scan; unreleased probes are recorded instead of blocking the parent command,
and timed-out domains must still pass exact `validate-inputs` before a real run.

## Performance
Profile the pipeline with cProfile and stage timers:
```bash
./.venv/bin/python -m trinetx_preprocessing profile --config config.yaml \
  --out artifacts/profile
```
For the non-combined corrected pipeline, `--strict` enables guardrail checks
for joins and required identifiers. For the current combined full source, use
strict mode only for the separate conflict-adjudication proof described above.
`profile` writes metadata-only provenance with the
config hash, package/Python version, git commit/dirty state, behavior-code
state hash for `src/`, `pyproject.toml`, and `uv.lock`, output inventory, stage
timings, peak RSS, and work/output disk footprint.

Recommended finalization configs use Parquet intermediates:
```yaml
chunking:
  enabled: true
  lines_per_chunk: 250000

storage:
  intermediate_format: parquet
  emit_legacy_csv_intermediates: false
  parquet_row_group_size: 250000
  analysis_bucket_count: 256
  emit_legacy_group_tables: false

rfs:
  ruleset: corrected_v1
  abg_min_pco2_mmhg: 45
  vbg_min_pco2_mmhg: 45

cohort:
  event_selection: earliest_per_setting

data_screen:
  mode: diagnosis_or_lab
  source: derived
```
With chunking enabled, `lines_per_chunk` bounds raw CSV reads,
work-table reads, and Parquet record-batch reads. Domain stages classify codes
once per chunk and write compact RFS/feature candidates. Final assembly builds
separate patient-partitioned vital, lab, diagnosis, procedure, and medication
indexes, loading one clinical domain at a time while reusing each bucket across
all 18 cohorts. Hidden scratch remains bucket-bounded and is removed strictly. A
versioned `pipeline_work_manifest.json` prevents stale or partially completed
work from being resumed. If an interrupted run leaves
hidden `.trinetx-*` scratch files under the external validation root,
inspect them before deleting:
```bash
./.venv/bin/python -m trinetx_preprocessing clean-scratch \
  --root "/Volumes/LOCKE BOOK/trinetx-preprocessing-validation" \
  --json-out "/Volumes/LOCKE BOOK/trinetx-preprocessing-validation/manifests/scratch_cleanup.json"

./.venv/bin/python -m trinetx_preprocessing clean-scratch \
  --root "/Volumes/LOCKE BOOK/trinetx-preprocessing-validation" \
  --delete
```
The command is dry-run by default and only matches known hidden scratch prefixes
created by this pipeline.

## Golden-master validation
Milestone 1 uses the aggregate row-parity audit as the accepted replication
evidence. Exact content-hash comparison remains useful for debugging, but a
hash mismatch no longer blocks the `refactor-milestone-1` fallback point when
schema, row counts, key sets, and the documented row-parity threshold are met.
Corrected post-milestone releases are validated against `docs/SPEC.md` and an
aggregate delta report rather than required to reproduce known legacy defects.

The release-grade unified build produced the canonical DuckDB, its manifest,
and all 36 compatibility exports in 89,270.965 seconds. Concurrent
process-family peak RSS was 4,503.531 MiB, below the 6,238 MiB ceiling. All 36
exports and 6,949,511 rows match the corrected baseline exactly; database,
element-completeness, adapter, local-test, free-space, and scratch-hygiene gates
also pass. Milestone 2 accepts deterministic non-strict resolution for 286
source encounter IDs assigned to multiple settings. Strict execution still
fails closed on those conflicts and remains available for upstream data-quality
adjudication.

The historical `c96dc40` product remains the corrected-baseline comparison
point. Fresh exact-behavior release evidence was subsequently recovered for
behavior head `7ef967d`; its parity, source, strict no-write, and recovery
contracts are recorded privately. The later `2305f16`/`cefc861` changes are
output-neutral lifecycle and test-fixture hardening, verified by focused
quality evidence rather than a replacement full-data build.

Hash local legacy outputs without committing row-level data:
```bash
./.venv/bin/python -m trinetx_preprocessing hash-outputs \
  --output-dir "/Volumes/LOCKE BOOK/trinetx-preprocessing-validation/legacy/output" \
  --scope final \
  --hash-chunk-rows 100000 \
  --out "/Volumes/LOCKE BOOK/trinetx-preprocessing-validation/manifests/legacy_final"
```
Then hash the refactor outputs and compare manifests without rerunning:
```bash
./.venv/bin/python -m trinetx_preprocessing inspect-inputs \
  --config "/Volumes/LOCKE BOOK/trinetx-preprocessing-validation/config.yaml" \
  --min-free-gb 100 \
  --json-out "/Volumes/LOCKE BOOK/trinetx-preprocessing-validation/manifests/input_status.json"

./.venv/bin/python -m trinetx_preprocessing hash-outputs \
  --output-dir "/Volumes/LOCKE BOOK/trinetx-preprocessing-validation/refactor/output" \
  --scope final \
  --hash-chunk-rows 100000 \
  --out "/Volumes/LOCKE BOOK/trinetx-preprocessing-validation/manifests/refactor_final"

./.venv/bin/python -m trinetx_preprocessing compare-manifests \
  --baseline "/Volumes/LOCKE BOOK/trinetx-preprocessing-validation/manifests/legacy_final" \
  --current "/Volumes/LOCKE BOOK/trinetx-preprocessing-validation/manifests/refactor_final" \
  --report "/Volumes/LOCKE BOOK/trinetx-preprocessing-validation/manifests/final_comparison.json"

./.venv/bin/python -m trinetx_preprocessing validation-status \
  --input-status "/Volumes/LOCKE BOOK/trinetx-preprocessing-validation/manifests/input_status.json" \
  --legacy-manifest "/Volumes/LOCKE BOOK/trinetx-preprocessing-validation/manifests/legacy_final" \
  --refactor-manifest "/Volumes/LOCKE BOOK/trinetx-preprocessing-validation/manifests/refactor_final" \
  --comparison-report "/Volumes/LOCKE BOOK/trinetx-preprocessing-validation/manifests/final_comparison.json" \
  --profile-provenance "/Volumes/LOCKE BOOK/trinetx-preprocessing-validation/profile/provenance.json" \
  --required-root "/Volumes/LOCKE BOOK" \
  --required-root-min-free-gb 100 \
  --json-out "/Volumes/LOCKE BOOK/trinetx-preprocessing-validation/manifests/validation_status.json" \
  --markdown-out "/Volumes/LOCKE BOOK/trinetx-preprocessing-validation/manifests/validation_status.md"
```
`validation-status` rejects old-schema input snapshots, capped input snapshots,
snapshots without `--min-free-gb 100` filesystem evidence, non-strict,
old-schema, or incomplete profile provenance, profile/input config path or
SHA-256 mismatches, recorded config SHA-256 values that no longer match the
current config file, profile provenance whose behavior-code state hash no
longer matches the current `src/`, `pyproject.toml`, and `uv.lock` contents,
legacy/refactor manifests without current schema v2 / `sha256` header metadata,
`generated_at`, `scope: final`, manifest `output_dir`, and per-table row-count
and column metadata from current `hash-outputs --scope final`,
validation artifacts or configured `data_dir`/`work_dir`/`output_dir` paths that
fall outside `--required-root`, insufficient free space on `--required-root`,
manifests that include
non-final `work_dir/` keys, manifest `source_path` files that no longer exist or
are not `.csv` files or do not live under the manifest `output_dir`, final
manifest keys that do not end with `.csv`, final
manifest keys whose filenames do not match the recorded `source_path` filenames,
final manifest source files whose current byte size or mtime no longer match the
manifest metadata, final manifests containing non-CSV tables, refactor manifests
whose source paths do not exactly match the profile final-output inventory or
point outside the configured `output_dir`, refactor manifest keys that do not
match source paths relative to configured `output_dir`, profile final-output
inventories whose paths are not regular `.csv` files, point outside the
configured `output_dir`, no longer exist, or no longer match the recorded byte
sizes or mtimes, old-schema comparison reports, and stale
comparison reports whose recorded baseline/current manifest paths or manifest
SHA-256 digests do not match the manifest directories supplied above. It also
reloads the current
manifest JSON files and recomputes the comparison, so a hand-edited or internally
inconsistent
comparison report cannot pass the final gate.

That command remains the strict historical-parity/merge-readiness gate. The
Milestone 2 corrected release does not claim `validation-status` reports
`ready: true`: its documented source conflicts make strict provenance
unavailable. Milestone 2 instead uses the corrected evidence checklist in
`docs/VALIDATION.md`; this release-specific policy does not weaken
`validation-status` for future conflict-adjudicated runs.

`--hash-chunk-rows` bounds both CSV sorting and Parquet record-batch hashing;
scratch files stay beside the table being hashed, so external-drive validation
does not spill row-level data onto the internal disk.

## Tests + quality checks
```bash
./.venv/bin/ruff format .
./.venv/bin/ruff check .
./.venv/bin/python -m pytest -q
```

## More docs
- `docs/ONBOARDING.md`: step-by-step setup + legacy notebook notes
- `docs/CONFIG.md`: config file details
- `docs/DATA_CONTRACT.md`: inputs, outputs, and required columns
- `docs/ARCHITECTURE.md`: pipeline structure

## Citation and license
Cite the GitHub repository URL and the commit or release used. No publication DOI
is assigned to this repository. Code is MIT licensed; see `LICENSE`.

# TriNetX Preprocessing Pipeline

This repository refactors the TriNetX hypercapnia preprocessing notebooks into a
deterministic, CLI-driven pipeline. The CLI reads exported CSVs, normalizes each
domain, derives RFS cohorts, and assembles final encounter-level datasets for the
2022 analysis window.

Refactor Milestone 1 completed the replication phase under near-exact
legacy-vs-refactor row parity: `4,412,875 / 4,412,932` final analytic rows
matched exactly (`99.998708%`), with no schema, row-count, or key-set
differences. The remaining `57` shared-key row differences are documented as
Weight/previous-Weight legacy quirks for this milestone fallback point. Internal
work tables can use Parquet for lower-overhead execution; final analytic outputs
remain legacy CSV files.

This is a code-only repository; no manuscript version is expected here. The
repository may describe restricted export schemas, but it must not include raw
TriNetX exports, row-level extracts, PHI, credentials, or generated local
validation artifacts unless explicitly reviewed.

## Quickstart (synthetic fixtures)
```bash
mkdir -p .uv_cache
export UV_CACHE_DIR="$PWD/.uv_cache"
uv sync

cp config.example.yaml config.yaml
mkdir -p artifacts/synthetic_example/work artifacts/synthetic_example/output
./.venv/bin/python -m trinetx_preprocessing validate-config --config config.yaml
./.venv/bin/python -m trinetx_preprocessing run --config config.yaml
```

Or run the helper script that builds a config for you:
```bash
./.venv/bin/python scripts/run_synthetic_example.py --output-root artifacts/synthetic_example
```

Outputs land under `artifacts/synthetic_example/output/`.

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

For the current low-space machine, keep real-data validation on the external
drive instead:
```bash
export UV_CACHE_DIR="/Volumes/LOCKE STUDY/trinetx-preprocessing-validation/uv-cache"

./.venv/bin/python -m trinetx_preprocessing scaffold-validation \
  --data-dir "/Volumes/LOCKE STUDY/TriNetX" \
  --validation-root "/Volumes/LOCKE STUDY/trinetx-preprocessing-validation"
```
Use `/Volumes/LOCKE STUDY/TriNetX` as `data_dir`, and place `work_dir`,
`output_dir`, profile output, logs, and manifests under
`/Volumes/LOCKE STUDY/trinetx-preprocessing-validation`.

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
Use `--strict` with `run` or `profile` to enable guardrail checks for joins and
required identifiers. `profile` writes metadata-only provenance with the
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
```
With chunking enabled, `lines_per_chunk` bounds raw CSV reads,
final-assembly patient-demographics/data-check/work-table reads, and Parquet
record-batch reads from work tables.
Encounter-stage setting reducers use hidden hash-bucket scratch directories
under `work_dir`, so retained setting-level encounter rows stay on the external
validation volume without random SQLite writes.
RFS flag membership and first-seen encounter rows also use hidden hash-bucket
scratch directories under `work_dir`, so high-cardinality encounter-id checks
stay sequential and bucket-bounded.
Final assembly reuses setting-level encounter/data-check inputs and reads each
per-category `RFS_*` event work table once to avoid repeated external-drive
reads while preserving final CSV names and contents. Final patient demographics
and data-check encounter-id membership are stored in transient SQLite scratch
under `work_dir`; setting encounters and per-category final event candidates use
hidden hash-bucket scratch directories. This keeps large patient, encounter,
screening, and RFS event files off the Python heap. If an interrupted run leaves
hidden `.trinetx-*` scratch files under the external validation root,
inspect them before deleting:
```bash
./.venv/bin/python -m trinetx_preprocessing clean-scratch \
  --root "/Volumes/LOCKE STUDY/trinetx-preprocessing-validation" \
  --json-out "/Volumes/LOCKE STUDY/trinetx-preprocessing-validation/manifests/scratch_cleanup.json"

./.venv/bin/python -m trinetx_preprocessing clean-scratch \
  --root "/Volumes/LOCKE STUDY/trinetx-preprocessing-validation" \
  --delete
```
The command is dry-run by default and only matches known hidden scratch prefixes
created by this pipeline.

## Golden-master validation
Milestone 1 uses the aggregate row-parity audit as the accepted replication
evidence. Exact content-hash comparison remains useful for debugging, but a
hash mismatch no longer blocks the `refactor-milestone-1` fallback point when
schema, row counts, key sets, and the documented row-parity threshold are met.

Hash local legacy outputs without committing row-level data:
```bash
./.venv/bin/python -m trinetx_preprocessing hash-outputs \
  --output-dir "/Volumes/LOCKE STUDY/trinetx-preprocessing-validation/legacy/output" \
  --scope final \
  --hash-chunk-rows 100000 \
  --out "/Volumes/LOCKE STUDY/trinetx-preprocessing-validation/manifests/legacy_final"
```
Then hash the refactor outputs and compare manifests without rerunning:
```bash
./.venv/bin/python -m trinetx_preprocessing inspect-inputs \
  --config "/Volumes/LOCKE STUDY/trinetx-preprocessing-validation/config.yaml" \
  --min-free-gb 100 \
  --json-out "/Volumes/LOCKE STUDY/trinetx-preprocessing-validation/manifests/input_status.json"

./.venv/bin/python -m trinetx_preprocessing hash-outputs \
  --output-dir "/Volumes/LOCKE STUDY/trinetx-preprocessing-validation/refactor/output" \
  --scope final \
  --hash-chunk-rows 100000 \
  --out "/Volumes/LOCKE STUDY/trinetx-preprocessing-validation/manifests/refactor_final"

./.venv/bin/python -m trinetx_preprocessing compare-manifests \
  --baseline "/Volumes/LOCKE STUDY/trinetx-preprocessing-validation/manifests/legacy_final" \
  --current "/Volumes/LOCKE STUDY/trinetx-preprocessing-validation/manifests/refactor_final" \
  --report "/Volumes/LOCKE STUDY/trinetx-preprocessing-validation/manifests/final_comparison.json"

./.venv/bin/python -m trinetx_preprocessing validation-status \
  --input-status "/Volumes/LOCKE STUDY/trinetx-preprocessing-validation/manifests/input_status.json" \
  --legacy-manifest "/Volumes/LOCKE STUDY/trinetx-preprocessing-validation/manifests/legacy_final" \
  --refactor-manifest "/Volumes/LOCKE STUDY/trinetx-preprocessing-validation/manifests/refactor_final" \
  --comparison-report "/Volumes/LOCKE STUDY/trinetx-preprocessing-validation/manifests/final_comparison.json" \
  --profile-provenance "/Volumes/LOCKE STUDY/trinetx-preprocessing-validation/profile/provenance.json" \
  --required-root "/Volumes/LOCKE STUDY" \
  --required-root-min-free-gb 100 \
  --json-out "/Volumes/LOCKE STUDY/trinetx-preprocessing-validation/manifests/validation_status.json" \
  --markdown-out "/Volumes/LOCKE STUDY/trinetx-preprocessing-validation/manifests/validation_status.md"
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

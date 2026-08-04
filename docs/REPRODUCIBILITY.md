# Reproducibility

See `CURRENT_STATE.md` for the distinction between accepted historical
full-data evidence, accepted current code/synthetic evidence, and the pending
current-head private parity gate.

## Environment
- Use `uv` to manage dependencies.
- Commit `pyproject.toml` and `uv.lock`.
- For real-data validation on the current machine, put `UV_CACHE_DIR` on the
  external drive:
  ```bash
  export UV_CACHE_DIR="/Volumes/LOCKE STUDY/trinetx-preprocessing-validation/uv-cache"
  ```
- Create the external/private validation layout and real-data config with:
  ```bash
  ./.venv/bin/python -m trinetx_preprocessing scaffold-validation \
    --data-dir "/Volumes/LOCKE STUDY/TriNetX" \
    --validation-root "/Volumes/LOCKE STUDY/trinetx-preprocessing-validation"
  ```

## Determinism
- Avoid implicit working-directory dependence.
- Make all I/O paths explicit via config.
- If randomness exists (bootstraps, sampling), use `np.random.default_rng(seed)` and pass `rng`.

## Provenance
For each pipeline run, record:
- git commit hash
- config file used
- package versions (from lockfile)
- start/end timestamps
- row counts per stage
- stage wall times
- peak RSS where available
- work/output disk footprint

Store profiling provenance in `provenance.json` under the requested profiling
artifact directory. It records the resolved config path, config SHA-256,
strict-mode flag, package/Python version, git commit and dirty-state metadata,
behavior-code dirty-state plus a SHA-256 hash of `src/`, `pyproject.toml`, and
`uv.lock`, stage timings, output-file inventory, peak RSS, and work/output disk
footprint. It does not record row-level output contents.

For cohort-source consumers, pin the published
`cohort_source_catalog_sha256` with `expected_catalog_sha256` and record the
`cohort_source_schema_version`, schema digest, GLP-1 subset digest, run ID,
package version, code-state digest, and source-work-manifest digest returned by
`open_cohort_source()`. Require every element ID the cohort implementation uses.
Keep the database and any DuckDB `spill_root` on an approved external private
volume; the reader is read-only and cleans its owned spill directory on exit.

These identity checks make a consumer reproducible but do not substitute for
data parity. The expanded catalog/current adapter still requires a frozen-head
private full-data comparison before raw-ingestion references can be retired.

## Intermediate storage
- Default code behavior remains CSV for backwards compatibility.
- The recommended finalization setting is Parquet intermediates:
  ```yaml
  storage:
    intermediate_format: parquet
    emit_legacy_csv_intermediates: false
    parquet_row_group_size: 250000
  ```
- Final analytic outputs remain legacy CSV files regardless of intermediate
  format.
- When `chunking.enabled: true`, `chunking.lines_per_chunk` bounds both raw CSV
  reads and Parquet record-batch reads from work tables.

## Profiling
Use the profiling harness to capture performance data without changing outputs:
```bash
./.venv/bin/python -m trinetx_preprocessing profile \
  --config "/Volumes/LOCKE STUDY/trinetx-preprocessing-validation/config.yaml" \
  --out "/Volumes/LOCKE STUDY/trinetx-preprocessing-validation/profile" \
  --strict
```
The command writes:
- `profile.pstats` and `profile.txt` for cProfile output
- `provenance.json` with run timestamps, stage timings, output file count, disk
  footprint, peak RSS, code/config metadata, strict-mode flag, and output-file
  inventory

## Golden-master comparison
Hash approved local legacy outputs without committing row-level data:
```bash
./.venv/bin/python -m trinetx_preprocessing hash-outputs \
  --output-dir "/Volumes/LOCKE STUDY/trinetx-preprocessing-validation/legacy/output" \
  --scope final \
  --hash-chunk-rows 100000 \
  --out "/Volumes/LOCKE STUDY/trinetx-preprocessing-validation/manifests/legacy_final"
```
Then hash the refactor outputs and compare manifests without rerunning:
```bash
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
`--hash-chunk-rows` applies to CSV sort chunks and Parquet record batches, and
hash scratch files are created beside the table being hashed so external-drive
runs do not spill row-level data onto the internal disk. Manifest discovery
ignores hidden sidecars, leftover `.trinetx-hash-*` scratch folders, and
`__MACOSX` archive folders.
If an interrupted run leaves hidden `.trinetx-*` scratch artifacts behind,
record a dry-run inventory before deleting them:
```bash
./.venv/bin/python -m trinetx_preprocessing clean-scratch \
  --root "/Volumes/LOCKE STUDY/trinetx-preprocessing-validation" \
  --json-out "/Volumes/LOCKE STUDY/trinetx-preprocessing-validation/manifests/scratch_cleanup.json"

./.venv/bin/python -m trinetx_preprocessing clean-scratch \
  --root "/Volumes/LOCKE STUDY/trinetx-preprocessing-validation" \
  --delete
```
The cleanup command only targets known hidden scratch prefixes created by the
pipeline and hashing helpers, and it requires `--delete` before removing files.
The final `validation-status` summary also requires the resolved config path and
config SHA-256 in `input_status.json` to match `profile/provenance.json`, so
readiness evidence cannot mix input and profiling artifacts from different
configs or different versions of the same config file. It also hashes the
current config file at that path and requires it to match the recorded SHA-256,
so changing `config.yaml` invalidates older input/profile evidence until those
artifacts are regenerated.
When `--required-root "/Volumes/LOCKE STUDY"` is supplied, the same summary also
requires validation artifact paths, config paths, configured `data_dir`,
`work_dir`, `output_dir`, manifest roots/source paths, and profiled final-output
paths to resolve under that external volume. With
`--required-root-min-free-gb 100`, it also records current free-space evidence
for that root and fails the root gate below the threshold.
It also requires `input_status.json` to use current `inspect-inputs`
`schema_version: 1`, exact input inspection with `--min-free-gb 100` or higher,
and data/work/output filesystem evidence at or above that threshold.

`validation-status` is the strict historical-parity/merge-readiness verifier.
Milestone 2 does not claim this status is ready because its reviewed full source
contains 286 unresolved cross-setting encounter IDs and therefore cannot
produce strict profile provenance. The release-specific corrected acceptance
record is documented in `docs/VALIDATION.md` and `docs/DECISIONS.md`; the CLI
gate remains unchanged for future conflict-adjudicated runs.
Legacy and refactor manifests must be generated with current
`hash-outputs --scope final` and include `schema_version: 2`,
`hash_algorithm: sha256`, `generated_at`, `scope: final`, manifest
`output_dir`, only `output_dir/` keys, per-table row counts, column metadata,
`.csv` key suffixes, `physical_format: csv`, and current `.csv` `source_path`
files that live under the manifest `output_dir` and whose filenames, byte sizes,
and mtimes match the manifest metadata; older hash-only, missing-root,
non-final-scope, non-CSV, wrong-algorithm, or stale-source manifests can still
be loaded for troubleshooting but cannot satisfy the final validation summary.
The refactor final-output manifest and profile output inventory must describe
the same final CSV file set under the configured `output_dir`; this prevents
combining a profile run from one output tree with a manifest from another output
tree, a manifest that only hashes a subset of profiled outputs, or a manifest
whose key hides the file's actual relative path under `output_dir`. Profile
`output_files` is final-output-only and limited to regular `.csv` files under
`output_dir`; intermediate work-table footprint is recorded through
`disk_footprint_bytes.work_dir`, and total generated path count is recorded as
`generated_file_count`. `validation-status` also requires
`profile/provenance.json` to use `schema_version: 2` and verifies that each
profiled final output path is still a regular `.csv` file and matches the byte
size and mtime recorded there. It also verifies that the recorded behavior-code
state hash still matches the current `src/`, `pyproject.toml`, and `uv.lock`
contents.
The final comparison report must use `schema_version: 1` and carry SHA-256
digests for the exact legacy/refactor `hashes.json` files it compared; after
regenerating either manifest, rerun `compare-manifests --report ...` before
rerunning `validation-status`. The status command recomputes the manifest
comparison from the current JSON manifests and requires the report `ok` flag and
counts to match that recomputation.

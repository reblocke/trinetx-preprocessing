# Validation

This document records how the refactor proves it preserves historical behavior.
Do not commit raw TriNetX exports, row-level legacy outputs, or real-data hash
manifests unless they have been explicitly reviewed.

## Historical parity gate
- Acceptance bar: final analytic CSV contents and inclusion logic must match the
  historical notebook pipeline.
- Comparison units:
  - output schemas and column order for final CSVs
  - row counts by stage, RFS category, and encounter setting
  - normalized SHA-256 hashes for final outputs and shared intermediates
  - targeted mismatch reports for any non-matching table
- Approved deltas must be documented in `docs/DECISIONS.md` with the historical
  source, refactor source, reason, and reviewer signoff.

## Refactor Milestone 1 acceptance
- The replication phase is accepted for `refactor-milestone-1` under aggregate
  row-level parity rather than exact final-file hashes.
- Full legacy/refactor manifests contain the same 36 final CSV tables with no
  missing, extra, schema, row-count, or key-set differences.
- A PHI-safe aggregate audit of the 25 hash-mismatched outputs found
  `4,412,875 / 4,412,932` exact final-row matches (`99.998708%`) and only `57`
  mismatched shared-key rows.
- Residual differences are limited to `date_Weight`, `value_Weight`, and
  occasional previous-weight fields. The audit artifacts remain external and
  untracked under
  `/Volumes/LOCKE BOOK/trinetx-preprocessing-validation/manifests/diagnostics/`.
- This milestone does not include row-level validation artifacts or PHI in the
  repository. Future behavior changes should use this tag as the fallback point.

## Golden-master workflow
1. For real-data validation on the current machine, keep artifacts on the
   external drive because the internal drive has limited free space:
   - raw restore root: `/Volumes/LOCKE STUDY/TriNetX`
   - validation root: `/Volumes/LOCKE STUDY/trinetx-preprocessing-validation`
   - refactor work/output/profile/log/manifest directories all live under the
     validation root.
   Staged legacy-vs-refactor parity runs also live under the external
   validation root at `parity_runs/`. The current external runners are:
   ```bash
   COPYFILE_DISABLE=1 PYTHONDONTWRITEBYTECODE=1 python3 \
     "/Volumes/LOCKE STUDY/trinetx-preprocessing-validation/parity_runs/tools/run_tier00_fixture.py" \
     --root "/Volumes/LOCKE STUDY/trinetx-preprocessing-validation/parity_runs"

   COPYFILE_DISABLE=1 PYTHONDONTWRITEBYTECODE=1 python3 \
     "/Volumes/LOCKE STUDY/trinetx-preprocessing-validation/parity_runs/tools/run_tier01_prefix.py" \
     --root "/Volumes/LOCKE STUDY/trinetx-preprocessing-validation/parity_runs"
   ```
   `tier_00_fixture` is synthetic/de-identified. `tier_01_prefix` copies
   header plus the first 10,000 rows per raw domain from restored real inputs
   and is PHI-bearing; its data, logs, manifests, and outputs must remain
   external and untracked.
2. Create the external validation layout and real-data config:
   ```bash
   export UV_CACHE_DIR="/Volumes/LOCKE STUDY/trinetx-preprocessing-validation/uv-cache"

   ./.venv/bin/python -m trinetx_preprocessing scaffold-validation \
     --data-dir "/Volumes/LOCKE STUDY/TriNetX" \
     --validation-root "/Volumes/LOCKE STUDY/trinetx-preprocessing-validation"
   ```
   Pass `--overwrite` only when intentionally replacing an existing local config.
3. Run the legacy notebooks on approved local inputs and place outputs under an
   untracked private folder, for example:
   - `/Volumes/LOCKE STUDY/trinetx-preprocessing-validation/legacy/work`
   - `/Volumes/LOCKE STUDY/trinetx-preprocessing-validation/legacy/output`
4. Hash final legacy outputs:
   ```bash
   ./.venv/bin/python -m trinetx_preprocessing hash-outputs \
     --output-dir "/Volumes/LOCKE STUDY/trinetx-preprocessing-validation/legacy/output" \
     --scope final \
     --hash-chunk-rows 100000 \
     --out "/Volumes/LOCKE STUDY/trinetx-preprocessing-validation/manifests/legacy_final"
   ```
5. Preflight refactor inputs:
   ```bash
   ./.venv/bin/python -m trinetx_preprocessing inspect-inputs \
     --config "/Volumes/LOCKE STUDY/trinetx-preprocessing-validation/config.yaml" \
     --max-matches 1 \
     --skip-space-check

   ./.venv/bin/python -m trinetx_preprocessing inspect-inputs \
     --config "/Volumes/LOCKE STUDY/trinetx-preprocessing-validation/config.yaml" \
     --allow-missing --json-out "/Volumes/LOCKE STUDY/trinetx-preprocessing-validation/manifests/input_status.json" \
     --max-matches 1 \
     --skip-space-check \
     --domain-timeout-seconds 20

   ./.venv/bin/python -m trinetx_preprocessing validate-inputs \
     --config "/Volumes/LOCKE STUDY/trinetx-preprocessing-validation/config.yaml"
   ```
   The saved JSON status includes a schema version, generation timestamp,
   resolved config path and SHA-256, domain match counts, search-directory existence,
   bounded path samples, whether counts were capped, and free-space results
   when checked. Metadata evidence files are written by atomic replacement so
   an interrupted write should leave the previous completed artifact intact
   rather than truncating it. Use `--max-matches 1` while monitoring a slow
   restore, `--domain NAME` to isolate one configured domain, and
   `--skip-space-check` if the mounted volume stalls on free-space queries.
   Use `--domain-timeout-seconds N` with `--max-matches` if one domain
   directory can stall the entire snapshot; timed-out domains are recorded in
   JSON/Markdown status, later domains skipped after an unreleased timeout are
   recorded as probe errors, the parent command does not block trying to drain
   output from a stuck child process, and all affected domains must be
   rechecked exactly before profiling.
   The final `validation-status` Markdown includes a compact domain-status
   table with match counts, timeout flags, search-directory existence, first
   matched path, and probe errors; it is metadata-only and does not include row
   data.
   Monitoring snapshots that use `--max-matches`, `--skip-space-check`, or
   `--domain-timeout-seconds` are not sufficient for the final gate. When the
   mount is responsive, regenerate the status exactly before profiling:
   ```bash
   ./.venv/bin/python -m trinetx_preprocessing inspect-inputs \
     --config "/Volumes/LOCKE STUDY/trinetx-preprocessing-validation/config.yaml" \
     --min-free-gb 100 \
     --json-out "/Volumes/LOCKE STUDY/trinetx-preprocessing-validation/manifests/input_status.json"
   ```
   `validate-inputs` remains the strict header gate after all domains are
   present.
6. Run the refactor with profiling and strict checks:
   ```bash
   ./.venv/bin/python -m trinetx_preprocessing profile \
     --config "/Volumes/LOCKE STUDY/trinetx-preprocessing-validation/config.yaml" \
     --out "/Volumes/LOCKE STUDY/trinetx-preprocessing-validation/profile" \
     --strict
   ```
   The final `validation-status` gate requires `input_status.json` to use
   current `inspect-inputs` schema version 1, to come from an exact run with
   `--min-free-gb 100` or higher, and to include `data_dir`, `work_dir`, and
   `output_dir` filesystem evidence at or above that threshold.
   It also requires `profile/provenance.json` to record `strict: true` and to
   contain positive `generated_file_count`, positive `output_file_count`,
   nonnegative `total_seconds`, positive `peak_rss_mb`,
   `disk_footprint_bytes.work_dir`,
   `disk_footprint_bytes.output_dir`, `stage_timings_seconds`, `started_at`,
   `ended_at`, package/Python version metadata, git commit/dirty-state
   metadata, behavior-code dirty-state and SHA-256 metadata for `src/`,
   `pyproject.toml`, and `uv.lock`, config path/hash metadata, and an
   output-file inventory whose length matches `output_file_count`.
   `output_files` is intentionally limited to regular final CSV files under
   `output_dir`; total generated work/final path count is recorded separately
   as `generated_file_count`, and intermediate disk use is covered by
   `disk_footprint_bytes.work_dir`.
   If a run is stopped after upstream work tables are complete, the RFS and
   final-output steps can be resumed without replaying raw-domain stages:
   ```bash
   ./.venv/bin/python -m trinetx_preprocessing run-rfs \
     --config "/Volumes/LOCKE STUDY/trinetx-preprocessing-validation/config.yaml"

   ./.venv/bin/python -m trinetx_preprocessing run-final-assembly \
     --config "/Volumes/LOCKE STUDY/trinetx-preprocessing-validation/config.yaml" \
     --strict
   ```
   Resume runs are useful for debugging, but final merge readiness still
   requires a current `profile --strict` provenance bundle from the exact code
   state under review.
7. Hash final refactor outputs and compare without rerunning:
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
   ```
   `--hash-chunk-rows` bounds in-memory row sorting for CSV files and Parquet
   record batches; temporary sorted chunks are written beside the file being
   hashed so spill files stay on the external validation volume. Hidden path
   components such as `.trinetx-hash-*`, AppleDouble `._*.csv` sidecars, and
   `__MACOSX` archive folders are ignored during manifest discovery. The final
   legacy and refactor manifests must be generated by current
   `hash-outputs --scope final` so the manifest declares `schema_version: 2` and
   `hash_algorithm: sha256`, `generated_at`, `scope: final`, and manifest
   `output_dir`, every table includes row-count and column metadata, every key
   is under `output_dir/` and ends with `.csv`, every table records
   `physical_format: csv`, and every recorded `source_path` lives under the
   manifest `output_dir` and still exists as a `.csv` file whose filename, byte
   size, and mtime match the manifest metadata; hash-only, missing-root,
   non-final-scope, non-CSV, wrong-algorithm, or stale-source manifests remain
   readable for comparison troubleshooting but cannot satisfy merge readiness.
   Non-final keys are also emitted as explicit
   `final_scope_blockers` so the Markdown `Gate Blockers` table identifies the
   affected manifest key without requiring a JSON-only inspection.
   The final refactor manifest must be generated from the
   profiled refactor output tree; `validation-status` verifies that refactor
   manifest `source_path` entries and `profile/provenance.json` output
   inventory describe the same final output file set under the configured
   `output_dir`, that manifest keys match each source path relative to that
   `output_dir`, and that profiled output files still exist with the byte sizes
   recorded in provenance.
   If an interrupted hash or pipeline run leaves hidden row-level scratch files
   under the external validation root, inventory them before deleting:
   ```bash
   ./.venv/bin/python -m trinetx_preprocessing clean-scratch \
     --root "/Volumes/LOCKE STUDY/trinetx-preprocessing-validation" \
     --json-out "/Volumes/LOCKE STUDY/trinetx-preprocessing-validation/manifests/scratch_cleanup.json"

   ./.venv/bin/python -m trinetx_preprocessing clean-scratch \
     --root "/Volumes/LOCKE STUDY/trinetx-preprocessing-validation" \
     --delete
   ```
   `clean-scratch` is dry-run by default and only targets known hidden
   `.trinetx-*` scratch prefixes created by hashing and disk-backed stage
   helpers. It does not match public final CSV outputs or non-hidden work
   tables.
8. If comparison fails, inspect `final_comparison.json` for missing, extra,
   hash-mismatched, row-count-mismatched, and schema-mismatched keys before
   changing implementation behavior. The report also records the resolved
   `--baseline` and `--current` manifest paths plus the SHA-256 digest of each
   `hashes.json`; final validation requires comparison report
   `schema_version: 1` and rejects the report if those paths or digests do not
   match the legacy/refactor manifest directories supplied to
   `validation-status`. The final status command also reloads the current
   manifest JSON files and recomputes their comparison, so the report `ok` flag
   and counts must agree with the current manifests.
9. Summarize the evidence artifacts without rerunning the pipeline:
   ```bash
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
   This command reports not ready until input presence, free-space threshold status,
   legacy/refactor manifests, comparison report, and profiling provenance are
   all present and passing. `input_status.json` must be `schema_version: 1`,
   `final_comparison.json` must be `schema_version: 1`, and profile provenance
   must be `schema_version: 2`. It also checks that
   `input_status.json` and
   `profile/provenance.json` were generated from the same resolved config path
   and config SHA-256, and that the recorded config SHA-256 still matches the
   current config file. It also checks that profile provenance's recorded
   behavior-code SHA-256 still matches the current `src/`, `pyproject.toml`,
   and `uv.lock` contents. With `--required-root`, it also checks that supplied
   artifact paths, config paths, configured `data_dir`/`work_dir`/`output_dir`,
   manifest roots/source paths, and profiled final-output paths all resolve under
   the external volume, and `--required-root-min-free-gb 100` records current
   free-space evidence for that external root. It also checks that both final
   manifests include only final-output keys plus row-count and schema metadata,
   and that the refactor manifest describes exactly the regular CSV files under
   configured
   `output_dir` produced by the profiled refactor run with matching relative
   keys, current file sizes, and mtimes. It also verifies that
   `final_comparison.json` was generated from the current legacy/refactor
   manifest file contents, not just the same manifest directory names, and that
   its `ok` flag and mismatch counts match a fresh metadata-only manifest
   comparison.
   The JSON file is machine-readable; the Markdown file is a non-row-level human
   summary suitable for review handoff and includes a `Gate Blockers` table when
   checks expose specific stale, incomplete, or mismatched evidence fields,
   including missing/capped/timed-out input evidence, input probe errors, missing
   artifact paths, missing artifact files, artifact-consistency failures for
   config path, config SHA-256, and current config-file hash checks.

## Automated coverage
- Unit tests cover pure transforms for encounter, labs, diagnosis, medications,
  procedure, vital signs, RFS derivation, regression hashing, config parsing,
  storage helpers, and guardrails.
- Stage tests use synthetic/de-identified fixtures under `tests/fixtures/`.
- End-to-end synthetic tests cover the full CLI pipeline in default CSV mode,
  chunked Parquet intermediate mode, and the `baseline`, `compare`, and
  `profile` command paths.

## Performance gate
- Run `profile` before and after performance-oriented changes.
- Preserve parity first; a faster run that changes inclusion logic is a failed
  run.
- Record wall time, stage timings, peak RSS, output file count, and work/output
  disk footprint from `provenance.json`.
- Encounter-stage setting reducers are stored in transient hash-bucket scratch
  directories under `work_dir` so retained encounter rows stay on the external
  work volume while preserving earliest-start-date selection without random
  SQLite writes.
- RFS flag membership and first-seen encounter rows are written to transient
  hash-bucketed scratch directories under `work_dir` during the RFS stage, so
  high-cardinality membership checks stay sequential and bucket-bounded on the
  external work volume instead of becoming full-domain Python sets or random
  SQLite lookups.
- Final assembly loads patient demographics into a transient SQLite lookup
  under `work_dir` and queries only patient IDs needed by each RFS/setting event
  frame, so the full patient table does not have to remain in Python memory.
- Final assembly loads each setting encounter table into deterministic
  hash-bucketed scratch directories under `work_dir`, validates duplicate
  encounter IDs per bucket, and reads only matching buckets for each RFS/setting
  event frame, so setting-level encounter tables stay on the external work
  volume without random SQLite writes.
- Final assembly streams each per-category `RFS_*` event work table into
  setting-independent event-candidate hash buckets, reduces duplicate
  encounters and patients one bucket at a time, and reuses the reduced candidate
  frame for all three care settings. This keeps the largest RFS categories from
  being loaded wholesale into Python memory.
- Final assembly parses each unique setting-level data-check CSV once into a
  transient SQLite lookup under `work_dir` and reuses that lookup across RFS
  categories, so large screening files stay on the external work volume instead
  of Python heap memory.
- Final assembly reuses cached setting encounter inputs and returns output paths
  in the legacy setting/category order.

## Current status
- Synthetic coverage exists for extracted transforms, stage runners, storage,
  hashing, profiling, cleanup, and CLI validation workflows.
- A fresh strict real-data refactor profile and full legacy notebook evidence
  completed under `/Volumes/LOCKE BOOK/trinetx-preprocessing-validation`.
- The legacy and refactor final manifests both contain 36 final CSV tables, and
  the profile provenance matches the refactor output inventory.
- The exact-hash comparison still reports 25 hash mismatches, but the
  aggregate row-level audit documented `99.998708%` exact final-row agreement
  with no schema, row-count, or key-set differences. That documented delta is
  accepted for the `refactor-milestone-1` fallback point.
- Do not commit private real-data manifests, comparison reports, profile logs,
  or row-level outputs. Reproduce or inspect them only under the external
  validation root.

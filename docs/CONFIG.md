# Configuration

The CLI reads YAML configuration. Relative paths resolve from the configuration
file, not the process working directory. See `config.example.yaml` for a
complete synthetic configuration.

See `CURRENT_STATE.md` before configuring downstream consumers; cohort
construction is not yet part of this repository.

## Required paths and domains

- `data_dir`: private raw-export root.
- `work_dir`: private intermediate and scratch root.
- `output_dir`: private root for the canonical database and 36 compatibility
  CSV projections.
- `domains`: input glob patterns for encounter, diagnosis, labs, medications,
  procedure, vital signs, and patient demographics.

`work_dir` contains `pipeline_work_manifest.json`. The manifest fingerprints
the configuration, source metadata, ruleset, intermediate schema, and completed
stages. Resume commands reject missing, stale, or incomplete work.

## Execution controls

```yaml
chunking:
  enabled: true
  lines_per_chunk: 250000

storage:
  intermediate_format: parquet
  emit_legacy_csv_intermediates: false
  emit_normalized_domain_tables: false
  parquet_row_group_size: 250000
  analysis_bucket_count: 256
  emit_legacy_group_tables: false

guardrails:
  max_join_multiplier: 1.0

combined:
  enabled: true
  database_name: trinetx_preprocessed.duckdb
  schema_version: "1.0"
  concept_sets_dir: config/concept_sets
  duckdb_memory_limit_mib: 3072
  duckdb_core_memory_limit_mib: 2816
```

- `chunking.lines_per_chunk` bounds raw CSV and work-table reads.
- `storage.intermediate_format` is `csv` or `parquet`; Parquet is recommended.
- `storage.emit_legacy_csv_intermediates` mirrors Parquet work tables to CSV for
  controlled notebook/debug compatibility.
- `storage.emit_normalized_domain_tables` writes complete normalized `*_NEW_*`
  domain tables. It defaults to `false`; enable it only for stage-level
  inspection or historical notebook compatibility.
- `storage.parquet_row_group_size` controls Parquet row groups.
- `storage.analysis_bucket_count` must be a positive power of two. It defaults
  to `256` for patient/encounter partition stores.
- `storage.emit_legacy_group_tables` writes historical `HAS_*`, `IPmed_*`,
  `OPmed_*`, and `value_*` files. It defaults to `false`; compact indexes are
  the normal implementation surface.
- `combined.enabled: true` routes `run` and `run-all` to the canonical combined
  builder. `build-preprocessed` always invokes that builder explicitly.
- `combined.database_name` controls the database filename beneath
  `output_dir`.
- `combined.schema_version` must match the supported combined contract.
- `combined.concept_sets_dir` supplies the versioned GLP-1 concept rules. The
  builder unions them with the typed traditional rules shipped in code and
  fingerprints both the merged cohort-source catalog and the GLP-1 subset for
  stale-work and consumer validation.
- `combined.duckdb_core_memory_limit_mib` bounds DuckDB's internal buffer pool
  while the core and source tables are created. It defaults to the lower of
  `2816` and `combined.duckdb_memory_limit_mib`, preserving an explicitly lower
  legacy cap.
- `combined.duckdb_memory_limit_mib` bounds the later observability, membership,
  finalization, compatibility export, provenance refresh, inspection, and
  validation sessions. It defaults to `3072`; observability requires this
  larger pool at full scale. Temporary spill is written beside the database on
  the configured output volume, and every combined-product connection uses one
  DuckDB thread.

## Corrected analytic controls

```yaml
rfs:
  enabled: true
  ruleset: corrected_v1
  abg_min_pco2_mmhg: 45
  vbg_min_pco2_mmhg: 45

cohort:
  event_selection: earliest_per_setting

data_screen:
  mode: diagnosis_or_lab
  source: derived
```

- `rfs.ruleset` is currently fixed at `corrected_v1`.
- ABG/VBG minimums are exclusive lower bounds in mmHg after recognized unit
  conversion. The upper bound is the version-controlled corrected rule.
- `cohort.event_selection` is fixed at `earliest_per_setting`.
- `data_screen.mode` is fixed at `diagnosis_or_lab`.
- `data_screen.source` defaults to `derived`. `legacy_files` remains available
  only for controlled comparison work. That mode requires
  `work_dir/data_checks/amb_enc_screen.csv` and
  `work_dir/data_checks/inp_enc_screen.csv` before manifest initialization;
  both files are fingerprinted and later changes fail stale-work validation.

## External real-data template

Keep private work, output, caches, logs, and profiles on the external volume:

```bash
./.venv/bin/python -m trinetx_preprocessing scaffold-validation \
  --data-dir "/Volumes/LOCKE BOOK/TriNetX" \
  --validation-root "/Volumes/LOCKE BOOK/trinetx-preprocessing-validation"
```

The generated private config and every row-level artifact remain untracked.
Use `clean-scratch` to inventory hidden interrupted-run scratch before deletion.

## Validation

```bash
./.venv/bin/python -m trinetx_preprocessing validate-config --config config.yaml
./.venv/bin/python -m trinetx_preprocessing validate-inputs --config config.yaml
```

Validation checks directory availability, glob resolution, source headers,
supported enum values, numeric bounds, and power-of-two partition counts.

Published cohort-source readers do not use YAML for their contract pins.
`validate-cohort-source` accepts the database and repeatable required element
IDs. Python consumers pass `expected_catalog_sha256`, `memory_limit_mib`, and an
optional external `spill_root` directly to `open_cohort_source()` or
`validate_cohort_source()`. Both the database parent and explicit spill root are
rejected when they resolve inside a Git worktree.

# Configuration

The CLI reads YAML configuration. Relative paths resolve from the configuration
file, not the process working directory. See `config.example.yaml` for a
complete synthetic configuration.

## Required paths and domains

- `data_dir`: private raw-export root.
- `work_dir`: private intermediate and scratch root.
- `output_dir`: final 36-file CSV root.
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
  only for controlled comparison work.

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

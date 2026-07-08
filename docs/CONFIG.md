# Configuration

The CLI uses YAML configuration files to locate inputs and outputs. Paths are
resolved relative to the config file location unless they are absolute.

## Required fields
- `data_dir`: root directory containing the TriNetX export folders.
- `work_dir`: scratch outputs (must exist). Some memory-bounded stages create
  hidden `.trinetx-*` scratch files or directories here and remove them on
  normal completion; use `clean-scratch` for a dry-run inventory before
  deleting leftovers from interrupted runs.
- `output_dir`: final outputs (must exist).
- `domains`: mapping of domain names to glob patterns under `data_dir`.

## Optional fields
- `chunking.enabled` + `chunking.lines_per_chunk`: stream large raw CSVs,
  final-assembly patient-demographics/data-check reads, and downstream
  CSV/Parquet work-table reads in bounded chunks.
- `rfs.enabled`: currently informational; the pipeline always runs the RFS stage.
- `guardrails.max_join_multiplier`: maximum allowed join multiplier when
  `--strict` is enabled.
- `storage.intermediate_format`: `csv` or `parquet` for work-table outputs.
- `storage.emit_legacy_csv_intermediates`: when Parquet is enabled, also emit
  CSV work tables for notebook/debug compatibility.
- `storage.parquet_row_group_size`: row group size passed to Parquet writes.

## Example config.yaml
See `config.example.yaml` for a runnable, synthetic example.
```yaml
data_dir: tests/fixtures/example_data
work_dir: artifacts/synthetic_example/work
output_dir: artifacts/synthetic_example/output

chunking:
  enabled: false
  lines_per_chunk: 10000000

storage:
  intermediate_format: parquet
  emit_legacy_csv_intermediates: false
  parquet_row_group_size: 250000

guardrails:
  max_join_multiplier: 1.0

domains:
  encounter: { pattern: "Encounter/encounter*.csv" }
  diagnosis: { pattern: "Diagnosis/diagnosis*.csv" }
  labs: { pattern: "Lab Results/lab_result*.csv" }
  meds:
    patterns:
      - "Medications/medication[0-9]*.csv"
      - "Medications/medication_ingredient*.csv"
  procedure: { pattern: "Procedure/procedure*.csv" }
  vitals: { pattern: "Vital Signs/vital*_signs*.csv" }
  patient: { pattern: "Patient/patient*.csv" }

rfs:
  enabled: true
```

## External-drive real-data template
For the current low-space machine, keep real-data paths off the internal drive:
```bash
./.venv/bin/python -m trinetx_preprocessing scaffold-validation \
  --data-dir "/Volumes/LOCKE STUDY/TriNetX" \
  --validation-root "/Volumes/LOCKE STUDY/trinetx-preprocessing-validation"
```
The generated config is equivalent to the template below and should stay
untracked/private.
```yaml
data_dir: "/Volumes/LOCKE STUDY/TriNetX"
work_dir: "/Volumes/LOCKE STUDY/trinetx-preprocessing-validation/refactor/work"
output_dir: "/Volumes/LOCKE STUDY/trinetx-preprocessing-validation/refactor/output"

chunking:
  enabled: true
  lines_per_chunk: 250000

storage:
  intermediate_format: parquet
  emit_legacy_csv_intermediates: false
  parquet_row_group_size: 250000
```
With Parquet intermediates, `lines_per_chunk` is also used as the Parquet
record-batch size for work-table readers such as the RFS and final-assembly
stages, and as the CSV chunk size for final-assembly patient demographics,
data-check files, and legacy CSV work-table fallbacks. Encounter reducers, RFS
membership, RFS first-seen encounter rows, final setting encounters, and final
event candidates use hidden hash-bucket scratch directories under `work_dir`.
Final assembly still stores patient demographics and data-check membership in
hidden transient SQLite files under `work_dir`. These structures keep large
lookup tables on the external validation volume without full-domain Python heap
tables.
Keep profile output, logs, uv cache, and manifests under the same validation
root. Do not commit this real-data config if it captures local private paths or
restore details that need review.
The vitals default intentionally matches both historical `vital_signs...` files
and restored `vitals_signs...` files. If another domain uses a different export
name, update the corresponding `domains` pattern in the private config.
Medication uses explicit raw-file patterns so generated `medication_NEW_*`
intermediates in the same folder are not treated as raw inputs.

## Validation
The config loader:
- checks directories exist
- expands glob patterns under `data_dir`
- fails fast with actionable error messages

CLI helpers:
```bash
./.venv/bin/python -m trinetx_preprocessing validate-config --config config.yaml
./.venv/bin/python -m trinetx_preprocessing validate-inputs --config config.yaml
```

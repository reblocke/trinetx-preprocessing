# Configuration

The CLI uses YAML configuration files to locate inputs and outputs. Paths are
resolved relative to the config file location unless they are absolute.

## Required fields
- `data_dir`: root directory containing the TriNetX export folders.
- `work_dir`: scratch outputs (must exist).
- `output_dir`: final outputs (must exist).
- `domains`: mapping of domain names to glob patterns under `data_dir`.

## Optional fields
- `chunking.enabled` + `chunking.lines_per_chunk`: used by the medications,
  procedure, and vital-signs stages to stream large CSVs in chunks.
- `rfs.enabled`: currently informational; the pipeline always runs the RFS stage.
- `guardrails.max_join_multiplier`: maximum allowed join multiplier when
  `--strict` is enabled.

## Example config.yaml
See `config.example.yaml` for a runnable, synthetic example.
```yaml
data_dir: tests/fixtures/example_data
work_dir: artifacts/synthetic_example/work
output_dir: artifacts/synthetic_example/output

chunking:
  enabled: false
  lines_per_chunk: 10000000

guardrails:
  max_join_multiplier: 1.0

domains:
  encounter: { pattern: "Encounter/encounter*.csv" }
  diagnosis: { pattern: "Diagnosis/diagnosis*.csv" }
  labs: { pattern: "Lab Results/lab_results*.csv" }
  meds: { pattern: "Medications/medication*.csv" }
  procedure: { pattern: "Procedure/procedure*.csv" }
  vitals: { pattern: "Vital Signs/vital_signs*.csv" }
  patient: { pattern: "Patient/patient*.csv" }

rfs:
  enabled: true
```

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

# Configuration

The refactor should replace hard-coded paths and magic numbers with a configuration file.

## Config file format
- Preferred: YAML (`config.yaml`)
- Alternative: TOML (`config.toml`)

## Example config.yaml
```yaml
data_dir: data/raw
work_dir: data/work
output_dir: Output

chunking:
  enabled: true
  lines_per_chunk: 10000000

domains:
  encounter: { pattern: "Encounter/encounter*.csv" }
  diagnosis: { pattern: "Diagnosis/diagnosis*.csv" }
  labs: { pattern: "Lab Results/lab_results*.csv" }
  meds: { pattern: "Medications/medications*.csv" }
  procedure: { pattern: "Procedure/procedure*.csv" }
  vitals: { pattern: "Vital Signs/vital_signs*.csv" }

rfs:
  enabled: true
  # TODO: define criteria sets here (codes, thresholds, etc.)
```

## Validation
The config loader should:
- check directories exist
- expand glob patterns
- fail fast with actionable error messages

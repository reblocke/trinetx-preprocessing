# Data Contract

This file defines the **expected inputs and outputs** of the pipeline.

## Inputs

### Directory layout (example)
```
data/
  raw/
    Encounter/
    Diagnosis/
    Lab Results/
    Medications/
    Procedure/
    Vital Signs/
    Patient/
    RFS/
```

**Note:** do not commit anything under `data/`.

### Expected files per domain
Document the canonical filenames here. Example:

- Encounter: `encounter.csv` or chunked `encounter_*.csv`
- Diagnosis: `diagnosis.csv`
- Lab Results: `lab_results.csv`
- Medications: `medications.csv`
- Procedure: `procedure.csv`
- Vital Signs: `vital_signs.csv`

For each file, document:
- required columns
- key identifiers (encounter_id, patient_id, dates)
- value coding systems (ICD, LOINC, RxNorm) if applicable

## Outputs

### Output directories
Document canonical output structure. Example:
```
Output/
  AMBULATORY/
  EMERGENCY/
  INPATIENT/
```

### Output tables
For each output dataset, define:
- file naming convention
- row grain (encounter-level vs patient-level)
- required columns (and units)
- sorting expectations (if any)

## Integrity checks
Define invariants the code must enforce:
- no missing required identifiers
- row grain is preserved
- joins do not explode row counts unexpectedly

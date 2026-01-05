# Data Contract

This file defines the **expected inputs and outputs** of the legacy pipeline.

## Inputs

### Raw export layout (legacy)
```
data/
  Encounter/
  Diagnosis/
  Lab Results/
  Medications/
  Procedure/
  Vital Signs/
  Patient/
  RFS/
  Final Datasets/
  Master Dataset/
```

**Note:** do not commit anything under `data/`.

### Canonical filenames (default patterns)
The default `config.example.yaml` patterns expect:
- `Encounter/encounter*.csv`
- `Diagnosis/diagnosis*.csv`
- `Lab Results/lab_results*.csv`
- `Medications/medication*.csv`
- `Procedure/procedure*.csv`
- `Vital Signs/vital_signs*.csv`
- `Patient/patient*.csv`

If your export uses singular filenames (for example `lab_result.csv` or
`medication_ingredient.csv`), update the `domains` patterns in `config.yaml`.

### Input validation behavior
- `trinetx_preprocessing validate-inputs` reads CSV headers (no full-file scan) and
  confirms required columns exist for each configured domain.
- All domain CSVs must include `patient_id`. Encounter-linked tables (encounter,
  diagnosis, labs, meds, procedure, vitals) must also include `encounter_id`.

### Required columns per domain
#### Encounter
- `encounter_id`, `patient_id`, `start_date`, `end_date`, `type`
- `start_date_derived_by_TriNetX`, `end_date_derived_by_TriNetX`, `derived_by_TriNetX`, `source_id`

### Encounter stage derivations
- Retain only encounter types `AMB`, `EMER`, `IMP`.
- Exclude encounters with `start_date` before `2022-01-01`.
- Fill missing `end_date` with `2022-12-31`.
- Deduplicate by `encounter_id` after sorting by `start_date` (asc) and `encounter_id` (desc).
- Compute `LOS` as `(end_date - start_date).days + 1`, dropping rows with `LOS <= 0`.

### Lab results stage derivations
- Retain `patient_id`, `encounter_id`, `code`, `date`, `lab_result_num_val`.
- Drop `code_system`, `lab_result_text_val`, `units_of_measure`, `derived_by_TriNetX`, `source_id`.
- Parse `date` as datetime during normalization.

### Diagnosis stage derivations
- Retain `patient_id`, `encounter_id`, `code`, `principal_diagnosis_indicator`, `admitting_diagnosis`, `reason_for_visit`, `date`.
- Drop `code_system`, `derived_by_TriNetX`, `source_id`.
- Replace `Unknown` values in indicator columns with `U`.
- Parse `date` as datetime during normalization.
- Generate code-group extracts to `HAS_*.csv` as defined in `src/trinetx_preprocessing/transform/diagnosis.py`.

### Medications stage derivations
- Retain `patient_id`, `encounter_id`, `code`, `start_date`.
- Drop `unique_id`, `code_system`, `route`, `brand`, `strength`, `derived_by_TriNetX`, `source_id`.
- Parse `start_date` as datetime during normalization.
- Generate `IPmed_list1`–`IPmed_list7` and `OPmed_list1`–`OPmed_list6` extracts per `src/trinetx_preprocessing/transform/medications.py`.

### Procedure stage derivations
- Retain `patient_id`, `encounter_id`, `code`, `date`.
- Drop `code_system`, `principal_procedure_indicator`, `derived_by_TriNetX`, `source_id`.
- Parse `date` as datetime during normalization.
- Generate `HAS_*.csv` extracts per `src/trinetx_preprocessing/transform/procedure.py`.

### Vital signs stage derivations
- Retain `patient_id`, `encounter_id`, `code`, `date`, `value`.
- Drop `code_system`, `text_value`, `units_of_measure`, `derived_by_TriNetX`, `source_id`.
- Parse `date` as datetime during normalization.
- Generate `value_*.csv` extracts with temperature conversions and range filters per `src/trinetx_preprocessing/transform/vitals.py`.

### RFS stage derivations
- Use normalized encounter, lab, diagnosis, procedure, and vital-sign outputs from `work_dir`.
- Derive encounter-level flags for RFS categories: ABG, VBG, RESPFAIL, OBESITY, VENTSUPPORT, PREDISPOSITION.
- Code lists and thresholds are defined in `src/trinetx_preprocessing/transform/rfs.py`.
- Emit per-category event extracts `RFS_<RFS>.csv` with `patient_id`, `encounter_id`, and `date`.

#### Diagnosis (current + prior)
- `patient_id`, `encounter_id`, `code_system`, `code`, `principal_diagnosis_indicator`
- `admitting_diagnosis`, `reason_for_visit`, `date`, `derived_by_TriNetX`, `source_id`

#### Lab Results
- `patient_id`, `encounter_id`, `code_system`, `code`, `date`
- `lab_result_num_val`, `lab_result_text_val`, `units_of_measure`, `derived_by_TriNetX`, `source_id`

#### Medications
- `patient_id`, `encounter_id`, `unique_id`, `code_system`, `code`, `start_date`
- `route`, `brand`, `strength`, `derived_by_TriNetX`, `source_id`

#### Procedure
- `patient_id`, `encounter_id`, `code_system`, `code`, `principal_procedure_indicator`
- `date`, `derived_by_TriNetX`, `source_id`

#### Vital Signs
- `patient_id`, `encounter_id`, `code_system`, `code`, `date`, `value`
- `text_value`, `units_of_measure`, `derived_by_TriNetX`, `source_id`

#### Patient (demographics)
- `patient_id`, `sex`, `race`, `ethnicity`, `year_of_birth`
- `patient_regional_location`, `month_year_death`

### Intermediate outputs (`work_dir`)
- `encounter_NEW_####.csv`: `patient_id`, `encounter_id`, `start_date`, `end_date`, `type`
- `diagnosis_NEW_####.csv`: `patient_id`, `encounter_id`, `code`, `principal_diagnosis_indicator`, `admitting_diagnosis`, `reason_for_visit`, `date`
- `lab_results_NEW_####.csv`: `patient_id`, `encounter_id`, `code`, `date`, `lab_result_num_val`
- `medication_NEW_####.csv`: `patient_id`, `encounter_id`, `code`, `start_date`
- `procedure_NEW_####.csv`: `patient_id`, `encounter_id`, `code`, `date`
- `vital_signs_NEW_####.csv`: `patient_id`, `encounter_id`, `code`, `date`, `value`
- `AMB_encounters.csv`, `EMER_encounters.csv`, `INPAT_encounters.csv`: `patient_id`, `encounter_id`, `start_date`, `end_date`, `type`, `LOS`
- `HAS_*.csv` (diagnosis): `patient_id`, `encounter_id`, `code`, `principal_diagnosis_indicator`, `admitting_diagnosis`, `reason_for_visit`, `date`
- `HAS_*.csv` (procedure): `patient_id`, `encounter_id`, `code`, `date`
- `IPmed_list*.csv`, `OPmed_list*.csv`: medication code-group extracts with `patient_id`, `encounter_id`, `code`, `start_date`
- `value_*.csv`: vital-sign extracts with `patient_id`, `encounter_id`, `code`, `date`, `value`
- `rfs_encounter_flags.csv`: `patient_id`, `encounter_id`, `rfs_abg`, `rfs_vbg`, `rfs_respfail`, `rfs_obesity`, `rfs_ventsupport`, `rfs_predisposition`
- `RFS_<RFS>.csv`: event-level RFS extracts with `patient_id`, `encounter_id`, `date`

### Data checks outputs (`work_dir/data_checks`)
- `amb_enc_screen.csv` and `inp_enc_screen.csv` are optional filters applied during
  final assembly. If they are missing, `*_AFTER.csv` matches `*_BEFORE.csv`.

## Outputs

### Output directories
```
output/
  AMBULATORY/
  EMERGENCY/
  INPATIENT/
```

### Output tables
- Files: `RFS_<RFS>_ENC_<SETTING>_BEFORE.csv`, `RFS_<RFS>_ENC_<SETTING>_AFTER.csv`
- Row grain: de-duplicated to one encounter per patient per RFS/setting.
- Required columns: `patient_id`, `encounter_id`, `qualify_date`, `RFS`,
  `encounter_type`, `age_at_encounter`, `sex`, `race`, `ethnicity`,
  `patient_regional_location`, `death_year_month`, `LOS`.
- Filters: qualifying date within 2022, patient age 18–109 years, encounter
  `qualify_date` between `start_date` and `end_date`, exclude
  `patient_regional_location` of `Ex-US` or `Unknown`.
- Additional derived vitals/labs/medication/procedure features remain in the
  legacy notebook workflow.

## Integrity checks
- No missing `patient_id` or `encounter_id` in intermediate or output files.
- RFS files must include `patient_id`, `encounter_id`, `date`.
- Final outputs must include encounters present in `*_encounters.csv` and respect `data_checks` filters.

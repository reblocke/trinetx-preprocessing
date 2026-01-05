# Architecture

## Design goals
- Preserve semantics of the legacy pipeline.
- Provide a single, documented entrypoint (CLI).
- Keep the computational core pure and testable.
- Isolate I/O, configuration, and orchestration.

## Legacy components (today)
- `split_db.sh` — splits raw exports into chunked CSVs.
- Preprocessing notebooks: encounter, diagnosis (prior/current), lab results, medication, procedure, vital signs.
- `Hypercapnia NEW DATA - RFS Processing.ipynb` — derives RFS cohorts.
- `Hypercapnia Final Dataset Generation - Master.ipynb` — builds final datasets per RFS/setting.
- `Hypercapnia Data Checks.ipynb` — data quality encounter lists.
- `Hypercapnia Master.ipynb` — orchestration via `nbconvert`.

## Current `src/` mapping (legacy → module)
- `split_db.sh` → `src/trinetx_preprocessing/tools/split_csv.py` + CLI `split` command.
- `Hypercapnia NEW DATA - Encounter (CSV Processing).ipynb` → `transform/encounter.py` + `pipeline/encounter_stage.py`.
- `Hypercapnia NEW DATA - Prior Diagnosis (CSV Processing).ipynb` + `Hypercapnia NEW DATA - Current Diagnosis (CSV Processing).ipynb` → `transform/diagnosis.py` + `pipeline/diagnosis_stage.py`.
- `Hypercapnia NEW DATA - Lab Results (CSV Processing).ipynb` → `transform/labs.py` + `pipeline/labs_stage.py`.
- `Hypercapnia NEW DATA - Medication (CSV Processing).ipynb` → `transform/medications.py` + `pipeline/medications_stage.py`.
- `Hypercapnia NEW DATA - Procedure (CSV Processing).ipynb` → `transform/procedure.py` + `pipeline/procedure_stage.py`.
- `Hypercapnia NEW DATA - Vital Signs (CSV Processing).ipynb` → `transform/vitals.py` + `pipeline/vitals_stage.py`.
- `Hypercapnia NEW DATA - RFS Processing.ipynb` → `transform/rfs.py` + `pipeline/rfs_stage.py`.
- `Hypercapnia Final Dataset Generation - Master.ipynb` → `pipeline/final_assembly.py`.
- `Hypercapnia Data Checks.ipynb` → still a notebook; `pipeline/final_assembly.py` optionally
  consumes `work_dir/data_checks/amb_enc_screen.csv` or `work_dir/data_checks/inp_enc_screen.csv`.
- `Hypercapnia Master.ipynb` → `pipeline/run.py` + `cli.py` (config-driven orchestration).

## Target data flow
1. Discover inputs from config and validate paths.
2. Normalize encounter data and emit encounter subsets (AMB/EMER/INPAT).
3. Normalize labs, diagnosis, medications, procedures, and vital-sign domains.
4. Derive RFS flags/events from normalized work files.
5. Assemble final datasets per RFS/setting and apply optional data checks.

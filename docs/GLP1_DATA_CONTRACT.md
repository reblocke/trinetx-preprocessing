# GLP-1 Eligibility Data Contract

The additive GLP-1 build publishes one DuckDB database plus Parquet, CSV, HTML,
and JSON companions. It does not replace or modify the 36 Milestone 2 analytic
CSV files.

## Published files

| File | Grain | Purpose |
|---|---|---|
| `glp1_hypercapnia.duckdb` | database | Authoritative tables, views, terminology, and provenance |
| `analysis_glp1_eligibility.parquet` | one row per `index_event_id` | Wide eligibility analysis table |
| `eligibility_evidence_long.parquet` | one row per source or derived rule record | Auditable evidence ledger |
| `cohort_hypercapnia_encounter.parquet` | one row per candidate encounter | Primary and sensitivity cohort decisions |
| `cohort_flow.csv` | one row per flow stage | Aggregate cohort reconciliation |
| `data_dictionary.csv` | one row per published column | Physical schema catalog |
| `data_quality_report.html` | aggregate report | Source, cohort, normalization, and missingness QA |
| `run_manifest.json` | one row | Build identity and provenance |

The DuckDB database also contains one-row-per-patient
`cohort_hypercapnia_patient_index`, source inventory and concept-set tables, and
the six `analysis_*` views described in `GLP1_PHENOTYPES.md`.

`cohort_flow.csv` always contains the 15 ordered endpoint stages: source
patients, adult candidate encounters, arterial PaCO2, valid units, paired pH,
strict hypercapnia, post-context exclusions, unique patients, valid BMI, BMI at
least 30, disease-specific FDA evidence, guideline/society evidence,
RCT-supported evidence, prior GLP-1 orders, and payer-route classification.
The final five rows are parallel characterizations of the BMI-at-least-30
denominator rather than nested clinical exclusions.

Parquet companions and the HTML QA report are enabled by default. Controlled
builds may disable them with `output.write_parquet` and
`output.write_html_qa`; DuckDB, cohort flow, data dictionary, and run manifest
remain mandatory.

## Keys and timing

- `index_event_id` is the deterministic analytic key. The wide table has
  exactly one row per key and the patient-index table has one row per patient.
- Baseline phenotype inputs are constrained to each row's `index_date`.
- Index-context fields use only the selected encounter window and are separated
  from pre-index history.
- Dates, raw/normalized values, units, source file, source record hash, and
  source encounter are preserved where the export supplies them.
- Nullable indication booleans use `NULL` for indeterminate or unevaluable,
  not `FALSE`.

## Evidence contract

`eligibility_evidence_long` contains source rows from diagnosis, procedure,
lab, vital, and medication domains plus one derived row for each canonical
status and each non-null indication. `rule_id`, `component`, `status`,
`certainty`, temporal fields, and source provenance allow a reviewer to trace
wide results without exposing identifiers in aggregate logs or summaries.

## Reproducibility and privacy

The run identifier is derived from configuration, the complete parsed concept
catalog, input inventory (including supplied export metadata), and code content
anchored to the installed package or its source checkout. Identical completed
runs are reused; a differing run requires `--replace` and is published
atomically only after staging succeeds. Repository-local output is accepted
only when Git ignores the entire output directory. Real databases, Parquet
files, manifests, logs, and reports are private generated artifacts and must
remain untracked.

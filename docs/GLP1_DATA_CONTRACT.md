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
the six `analysis_*` views described in `GLP1_PHENOTYPES.md`. The aggregate
`source_duplicate_summary` table reports rows beyond the first identical source
record hash by domain without retaining row examples in QA output.

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
- Source encounter identifiers are scoped by patient. Encounter de-duplication,
  first-gas selection, encounter maxima, and downstream joins use the composite
  `(patient_id, encounter_id)` key.
- Baseline phenotype inputs are constrained to each row's `index_date`.
- Index-context fields use only the selected encounter window and are separated
  from pre-index history.
- Timestamped context rows use exact encounter bounds. Date-only diagnosis and
  procedure rows on the selected encounter use encounter calendar-date overlap;
  date-only encounter ends include their complete calendar day.
- Configured lookback starts use exact elapsed-time bounds for timestamped rows
  and inclusive calendar-day bounds for date-only rows. Date-only medication
  end dates remain active through the end of their reported calendar day.
  Post-index medication windows use the exact index instant and endpoints for
  timestamped rows, and inclusive index-day and endpoint calendar dates for
  date-only rows. Only GLP-1 orders are retained after index; non-GLP-1
  medication components and source evidence are baseline-only.
- Dates, raw/normalized values, units, source file, source record hash, and
  source encounter are preserved where the export supplies them.
- Gas normalization accepts common textual mmHg/pH labels and canonical UCUM
  `mm[Hg]`/`[pH]` labels; normalized pressure values use `mm Hg`.
- Nullable indication booleans use `NULL` for indeterminate or unevaluable,
  not `FALSE`.

## Evidence contract

`eligibility_evidence_long` contains source rows from diagnosis, procedure,
lab, vital, and medication domains plus one derived row for each canonical
status and each non-null indication. `rule_id`, `component`, `status`,
`certainty`, temporal fields, and source provenance allow a reviewer to trace
wide results without exposing identifiers in aggregate logs or summaries. The
strict hypercapnia evidence includes distinct source-traceable PaCO2 and paired
arterial pH rows.

## Reproducibility and privacy

The run identifier is derived from configuration, the complete parsed concept
catalog, input inventory (including supplied export metadata), and code content
anchored to the installed package or its source checkout. Identical completed
runs are reused; a differing run requires `--replace` and is published
atomically only after staging succeeds. Repository-local output is always
rejected; real databases, Parquet files, manifests, logs, and reports must live
outside Git worktrees and remain untracked.

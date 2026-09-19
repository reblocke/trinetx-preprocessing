# Encounter preprocessing interface

The maintained data-creation implementation lives in trinetx-preprocessing.
The direct Stata implementation and its accepted Python port remain unchanged
in trinetx-hypercapnia-code as reproduction references.

## Run

From this repository, with the locked environment:

```bash
uv sync --locked
uv run trinetx-preprocessing build-encounters \
  --database /private/source/trinetx_preprocessed.duckdb \
  --output-dir /private/encounter-bundle
```

Use a new private output directory outside Git. The command validates the
canonical manifest/catalog, opens the source read-only, processes the two
variants sequentially, and publishes an owned staging directory only after
both pass. An existing destination is rejected. Interrupted staging remains
private for diagnosis; it is not a completed product. DuckDB uses one thread,
2816 MiB for enrichment, and external spill within staging. On the Mini, run
under caffeinate and retain logs on the private output volume.

## Products and grain

- encounter_features_full_data.parquet: BEFORE compatibility projections,
  original ordered cleaning/merges and pre-screen population.
- encounter_features_after_exclusion.parquet: independently transformed AFTER
  projections, original quality/timing rules and measurement imputation.
- Companion Parquet evidence tables for catalog elements, diagnosis, procedure,
  laboratories, blood pressure and medications.
- Per-variant element inventories, data_dictionary.json,
  quality_summary.json and versioned manifest.json.

Each feature table is unique by original string patient_id plus encounter_id.
Repeated encounters remain. first_encounter is a flag, not a row restriction.
legacy_patient_id preserves the variant-specific encoded identifier;
legacy_encounter_id and pat_enc_hash preserve reference identifiers.
Use original source keys for linkage, never encoded patient numbers across
variants. Hash collisions are rejected.

AFTER_EXCLUSION is not a filtered FULL_DATA: inputs, timing and values can
differ. The frozen saturation-imputation fits belong only to AFTER_EXCLUSION;
FULL_DATA retains its original pre-screen values. No propensity estimation,
weights, study-index selection, indication decisions, prevalence or figures
are invoked. Legacy clinical derived variables remain part of the extraction.

## Time, evidence and missingness

encounter_anchor_date is the established legacy daily encounter_date, expressed
as a calendar date. New evidence lookbacks therefore use inclusive calendar
days, retaining original timestamps and precision in evidence. No time of day
is invented. General diagnosis/procedure/medication lookback is 730 days;
measurements use 365 days. Existing component-specific all-history rules and
five-year sleep-study lookback remain explicit in feature_sources.py.

Catalog evidence retains same-encounter observations even outside the baseline
window. in_baseline_window identifies records eligible for its latest baseline
value/date/unit summaries; future same-encounter measurements cannot populate
those summaries. Record counts describe retained source records, not absence
of disease. Medication follow-up retains the inherited 365-day horizon and
date-only rule: anchor-day starts may appear in both history and follow-up.
Downstream studies must choose an appropriate exposure time definition.

Legacy NIV/IMV procedure definitions are retained as niv_proc and imv_proc,
with their dates; cpap remains separate. The older GLP-1 invasive-ventilation
component is a narrower CPT-only definition and must not replace these fields.
Evidence preserves source references, units, dates, specimen/panel identifiers,
statuses and missingness. Raw catalog latest values are explicitly raw-unit
values; normalized component measurements are separate.

Null means unavailable under that field's rule. A zero source-record count
does not prove clinical absence. Unsupported severity measurements remain
unavailable. Catalog membership is source candidacy, not study eligibility.
Catalog inventories cover traditional and GLP-1 source concepts; the 534 raw
compatibility input columns remain documented in legacy/raw_schema.json and
in the canonical source dictionary. The encounter dictionary describes the
transformed output columns and retains legacy labels/value coding.

## Scope of verification

Focused fixtures exercise repeated encounters, merge precedence and overlap,
source-key collisions, temporal boundaries, negative-versus-missing states,
imputation and retention of rows failing GLP-1 study eligibility. Private
comparison uses exact keys, categorical values and missingness, with bounded
numerical comparison rather than byte-identical serialization.

The private build/comparison result is recorded separately; synthetic tests
alone do not establish current-data acceptance. Historical scientific issues
in the study package are not repaired or newly validated by relocation.
See the downstream ENCOUNTER_PREPROCESSING.md for that boundary.

The final observability day-bound adjustment is output-neutral for the accepted
private source: an aggregate scan found zero non-midnight timestamps in all
five source-observability domains. The private build retains its original
producer identity; the follow-up validation records this bounded equivalence
proof instead of rerunning unchanged transformations.

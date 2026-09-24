# Encounter preprocessing interface

The maintained data-creation implementation lives in trinetx-preprocessing.
The direct Stata implementation and its accepted Python port remain unchanged
in trinetx-hypercapnia-code as reproduction references.

## Run

The owner approved a one-time authenticated import of the original 36 CSVs
on 2026-09-20. Schema 2.0 separates that population authority from the canonical
clinical evidence source. The original canonical compatibility projections did
not reproduce accepted membership. The companion bypasses that mismatch; it
does not explain or repair the canonical projections. The corrected private build,
retained-reference comparison and historical artifact validator passed for both
variants. The old private receipt predates the strengthened validator and cannot
authorize the new strict consumer. See [current state](CURRENT_STATE.md) for the
postmerge release gates.

Install the locked environment and import the authenticated immutable snapshot
once. The identity receipt supplies the exact accepted hashes for all 36 files:

```bash
uv sync --locked
uv run trinetx-preprocessing import-compatibility \
  --input-root /private/accepted-compatibility \
  --identity-receipt /private/accepted-input-identity.json \
  --database /private/compatibility.duckdb
```

The import preserves exact headers, text, missing sentinels, duplicate rows and
logical row order. It uses the accepted CSV parser settings, compares every
stored text cell before clinical coercion, and checks identities before and
after import. Routine builds read the companion read-only and apply the
unchanged accepted cleaners, merges and imputation.
The reader bounds ordinal-range queries and shares equal text values per
column, avoiding wide sorts and duplicate whole-frame allocations. Reader and
key-ingestion SQL use 512 MiB; final wide key publication uses the existing
2816 MiB enrichment cap after the pandas frames have been released.

Build both independent bases before any clinical enrichment:

```bash
uv run trinetx-preprocessing build-encounters \
  --compatibility-database /private/compatibility.duckdb \
  --legacy-only --output-dir /private/legacy-base
```

Run the downstream `compare_encounter_reference.py` with its mandatory accepted
reference `--identity-receipt`, writing `/private/legacy-acceptance.json`. The
versioned contract requires all 33 FULL_DATA and 534 AFTER_EXCLUSION fields,
including explicit patient/encounter and demographic aliases; only 14 documented
propensity/weight fields are excluded. Discrete values and missingness are exact;
only the named continuous fields use `rtol=atol=1e-6`. References are authenticated
before decoding and checked unchanged after comparison. Fresh key caches are
bound to those identities; failed-build caches are never accepted.

Then validate patient demographics, composite encounter linkage, anchor-day
agreement and source-history availability, before constructing evidence:

```bash
uv run trinetx-preprocessing build-encounters \
  --database /private/source/trinetx_preprocessed.duckdb \
  --compatibility-database /private/compatibility.duckdb \
  --legacy-bundle /private/legacy-base \
  --legacy-acceptance /private/legacy-acceptance.json \
  --coverage-only --output-dir /private/source-coverage
```

Coverage defaults to the version-1.0 `complete_linkage` policy: every accepted
patient and composite encounter must link, with no demographic or anchor-day
contradictions. The report separately records linked/unlinked counts,
proportions, contradiction status and history-availability states. A bounded
`approved_incomplete_linkage` use requires an explicit
`--approved-incomplete-linkage-exception` and retains unlinked encounters as
incomplete capture. Zero linked records fail both policies. A source span never
proves continuous history or clinical absence.

The corrected enrichment command requires both gates and creates the bundle:

```bash
uv run trinetx-preprocessing build-encounters \
  --database /private/source/trinetx_preprocessed.duckdb \
  --compatibility-database /private/compatibility.duckdb \
  --legacy-bundle /private/legacy-base \
  --legacy-acceptance /private/legacy-acceptance.json \
  --coverage-bundle /private/source-coverage \
  --source-cache-dir /private/encounter-source-cache \
  --output-dir /private/encounter-bundle
```

Validate every artifact after completion, then run the same mandatory retained
reference comparison against the enriched bundle:

```bash
uv run trinetx-preprocessing validate-encounters \
  --bundle /private/encounter-bundle \
  --work-dir /private/new-validation-work \
  --report /private/encounter-validation.json
```

Use a new private output directory outside Git. The command validates the
canonical manifest/catalog, opens the source read-only, processes the two
variants sequentially, and publishes an owned staging directory only after
both pass. An existing destination is rejected. Interrupted staging remains
private for diagnosis; it is not a completed product. DuckDB uses one thread,
2816 MiB for enrichment, and external spill within staging. On the Mini, run
under caffeinate and retain logs on the private output volume.

The optional `--source-cache-dir` retains expensive source materializations in
separate per-variant databases. Each completed stage and its receipt commit in
one transaction. A retry checks source and base identities, catalog, configuration,
producer code, table schemas, counts and a version-1.0 content fingerprint before
reusing a stage. The fingerprint sorts SHA-256 digests of DuckDB's typed-row JSON
representation and hashes the resulting multiset, retaining duplicate
multiplicity without depending on physical row order. An older cache without
content fingerprints is rejected rather than blessed from its current bytes.
The build then regenerates derived evidence and publishes a new output bundle.
Cache paths must be external,
non-symlinked and disjoint from inputs and outputs. An older database without
these bindings is rejected; its tables cannot be reused just because they exist.
Recovery of such a database requires a separately validated import into a new
owned cache, preserving the original artifacts and producer provenance. Cache
completion does not establish final bundle acceptance. The encounter-type
context step partitions narrow encounter and vital keys by patient hash before
applying the original first-row rule. All rows for a composite encounter remain
together, including its null type and date values. The completed context table
is also checkpointed; the memory cap and clinical selection rules are unchanged.

Source-element evidence joins run on bounded source-ID partitions; summaries
run on encounter-ID partitions. Duplicate membership/source rows and the
inclusive-day or same-encounter predicate are preserved. The completed clinical
feature group and element evidence/summary group have atomic cache receipts.
Partition files exclude AppleDouble metadata. These are execution changes;
private bundle acceptance still requires the complete artifact gates.

The optional `--vital-selection-acceptance /private/vital-equivalence.json`
selects the exact normalized vital codes only after a complete, per-source-row
comparison proves equivalence to catalog membership on the same canonical
database. The receipt must bind the source identity, catalog and exact query,
with zero selection differences; matching totals or a sample are insufficient.
Without this receipt, the original membership selection remains in use. The
manifest records the receipt hash and the source cache binds the chosen predicate.
This query optimization changes neither patient scope nor projected raw values,
units, dates or duplicate multiplicity.

## Products and grain

- encounter_features_full_data.parquet: authenticated BEFORE snapshot partitions,
  original ordered cleaning/merges and pre-screen population.
- encounter_features_after_exclusion.parquet: independently transformed authenticated AFTER
  snapshot partitions, original quality/timing rules and measurement imputation.
- Companion Parquet evidence tables for catalog elements, diagnosis, procedure,
  laboratories, blood pressure and medications.
- Per-variant element inventories, data_dictionary.json,
  quality_summary.json and versioned manifest.json.

Each feature table is unique by original string patient_id plus encounter_id.
Parquet row order is unspecified. Consumers must explicitly sort by original
`patient_id, encounter_id` (and evidence by `index_event_id`, source date and
source identity) whenever order matters. Repeated encounters remain. first_encounter is a flag, not a row restriction.
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
captured-history exceptions remain explicit in feature_sources.py. The
procedure evidence implementation uses its 730-day rule; the declared sleep-study
constant does not establish a separate five-year eligibility calculation here.

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

The feature contract is version 1.0. Each required source element has a wide
column/evidence destination and availability inventory. Per-encounter domain
coverage distinguishes unavailable domains, incomplete capture and observed
history spans. Each element inventory separates observed matches from zero
matching records under each history state. An observed span does not establish
continuous capture or complete lifetime history. All-history summaries cover
only records captured by the canonical export. Missing source history is not
recovered by querying a different projection.

Null means unavailable under that field's rule. A zero source-record count
does not prove clinical absence. Unsupported severity measurements remain
unavailable. Catalog membership is source candidacy, not study eligibility.
Catalog inventories cover traditional and GLP-1 source concepts; the 534 raw
compatibility input columns remain documented in legacy/raw_schema.json and
in the canonical source dictionary. The encounter dictionary describes the
transformed output columns and retains legacy labels/value coding.

## Scope of verification

The shared acceptance contract is version 1.0 in
`trinetx_preprocessing.encounters.acceptance`. The validator report now binds
the exact manifest digest, product kind, schema and feature-contract versions,
output inventory, source and compatibility identities, producer code digest,
both variant results, and validation-contract version. A production receipt is
external to the immutable bundle and must bind that report's digest, the same
manifest and output inventory, the declared coverage policy/results, passing
artifact, retained-reference, source-coverage and installed-pair gates, and the
actual producer, validator and consumer revisions. The downstream consumer
requires both the receipt file and its expected SHA-256 from a trusted private
release configuration; an adjacent JSON file is never trusted automatically.

`complete_linkage` requires positive patient and composite-encounter linkage
results. An `approved_incomplete_linkage` release must identify its approved
exception explicitly. A historical receipt lacking this schema is not silently
upgraded. The existing private bundle requires revalidation under the stronger
validator and a new integrated receipt before the strict reader may consume it.
Build completion, artifact validation, reference parity, installed-pair
verification and scientific acceptance remain distinct.

The version-1.0 evidence schema contract is packaged as
`encounters/artifact_contract.json`: it lists the exact version-1.0 feature
schema for each independent variant (1,108 FULL_DATA fields and 1,172
AFTER_EXCLUSION fields) from the accepted writer/dictionary, plus exact names
and Arrow types for each clinical evidence and source-coverage table. The
validator checks those schemas from Parquet metadata, including typed empty
domains, and requires the manifest-bound feature dictionary to agree with the
fixed contract. It independently scans
the feature table to compare every QA null count with the emitted values.
It independently compares catalogue source-record memberships with the wide
count columns, and inventory availability with distinct encounter/element
matches joined to the declared source-history states. Repeated source rows
remain counted in the membership total; availability is per encounter/element.
It checks the raw latest value/date/unit triplet for `source.hba1c` and
`source.bmi` against eligible baseline evidence under the documented date and
source-record tie order. Context-only rows remain in evidence and cannot supply
those baseline triplets. It also reconstructs normalized latest HBA1c
value/date and systolic blood-pressure value, and independently checks the
published blood-pressure unit conversion, including kPa. These four enumerated
summaries are not exhaustive clinical phenotype validation. Assertions about
the original canonical raw-record counts need separate bounded source reads.
The CLI writes a versioned failure report with artifact, invariant and
aggregate discrepancy and exits nonzero when a required check fails. Row-level
diagnostic samples remain private and are not included in that report.

Focused fixtures exercise repeated encounters, merge precedence and overlap,
source-key collisions, temporal boundaries, negative-versus-missing states,
imputation and retention of rows failing GLP-1 study eligibility. Private
comparison uses exact keys, categorical values and missingness, with bounded
numerical comparison rather than byte-identical serialization.

The corrected private build completed both independent variants. Its retained
reference comparison passed exact membership and all 33 FULL_DATA and 534
AFTER_EXCLUSION fields; the separate validator passed the complete artifact
contract. Those results are bound to the private bundle manifest and do not by
themselves establish final acceptance. Historical scientific issues in the study
package are not repaired or newly validated by relocation.
See the downstream ENCOUNTER_PREPROCESSING.md for that boundary.

The final observability day-bound adjustment is output-neutral for the accepted
private source: an aggregate scan found zero non-midnight timestamps in all
five source-observability domains. The failed private build retains its original
producer identity. The corrected integrated build and comparison now provide the
separate completion evidence; the bounded date proof remains limited to that
observability question.

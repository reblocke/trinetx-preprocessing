# Unified Preprocessing Product

## Endpoint

`trinetx_preprocessed.duckdb` is the sole canonical preprocessed product. One
bounded raw-data pass produces:

- the complete historical 534-column encounter observations;
- source-faithful lab, vital, diagnosis, procedure, medication, encounter, and
  patient tables needed by the GLP-1 work and future studies;
- a versioned element catalog and rule table;
- source-element membership, observability, RFS membership, encounter
  availability, provenance, data-dictionary, and aggregate quality tables; and
- 36 compatibility views that regenerate the historical CSV contract.

The product does not contain GLP-1 eligibility decisions, study cohorts,
imputation, propensity models, or outcome analyses. Those remain downstream
logic. The adapter in `combined_preprocessing/glp1_adapter.py` proves that the
existing GLP-1 derivation can consume the unified source tables without a
second raw clinical-data scan.

## Stable grains

- `preprocessed_encounter`: one row per compatibility output observation. Its
  identity includes output key, category, setting, variant, and stable source
  order; the remaining columns are the ordered historical 534-column payload.
- `source_*`: one row per retained raw source record. Clinical records require
  at least one `include: true` element membership; duplicate records remain
  distinct through `source_record_id`, source file, and source row number.
- `element_catalog`: one row per versioned historical derived element or
  additive source concept.
- `element_rule`: one row per exact, prefix, or regular-expression matching
  rule.
- `element_membership`: one row per source-record/element match. Overlapping
  memberships are preserved.
- `patient_observability`: aggregate raw-domain availability by patient.
- `encounter_availability`: diagnosis/lab availability by encounter.

Raw values and normalized values are retained separately where relevant.
Patient source values remain strings exactly as exported before demographic
conversion. Dates preserve parsed timestamp precision. Source tables use the
same explicit DuckDB types whether work tables are CSV or Parquet.

## Build and inspect

Use an external private `output_dir`; repository-local row-level output is
rejected.

```bash
python -m trinetx_preprocessing build-preprocessed \
  --config /private/path/config.yaml --strict

python -m trinetx_preprocessing preprocessed-status \
  --database /private/output/trinetx_preprocessed.duckdb --json

python -m trinetx_preprocessing validate-preprocessed \
  --database /private/output/trinetx_preprocessed.duckdb \
  --output-dir /private/output --json
```

With `combined.enabled: true`, the existing `run` and `run-all` commands route
to the same builder. `export-legacy` can regenerate all 36 CSV projections from
the database without reading raw exports again.

## Reproducibility and resume

The work manifest fingerprints source metadata, effective configuration,
pipeline code, runtime versions, intermediate schema, ruleset, and the loaded
element catalog. A changed identity fails closed. The database embeds its run
identity, source inventory, catalog fingerprint, compatibility-output hashes,
and table-level data dictionary.

Publication is transactional at the product-directory boundary: all 36 CSVs,
the database, and its sidecar are built and validated in a sibling staging
directory. `--replace` moves the prior product to a rollback backup and installs
the completed directory only after every check passes. Failed builds leave the
published product unchanged; output roots with unmanaged files are rejected.

## Acceptance evidence

Stage 1 is accepted only after:

1. the 36 compatibility exports match the approved historical baseline by
   ordered schema, row count, and normalized SHA-256;
2. every required source element has a catalog rule and aggregate coverage is
   reported without identifiers;
3. the combined product passes structural, referential-integrity, manifest,
   and export validation;
4. the full build satisfies the existing external-space and peak-memory gates;
   and
5. no private database, row-level output, log, manifest, or validation artifact
   is tracked by Git.

The scripts `capture_combined_baseline.py`, `verify_combined_parity.py`,
`verify_element_completeness.py`, and `benchmark_combined_preprocessing.py`
produce aggregate-only external evidence for these gates.

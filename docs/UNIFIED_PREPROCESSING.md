# Unified Preprocessing Product

See `CURRENT_STATE.md` for the current accepted evidence, pending private gate,
and downstream refactor blocker.

## Endpoint

`trinetx_preprocessed.duckdb` is the sole canonical preprocessed product. One
bounded raw-data pass produces:

- the complete historical 534-column encounter observations;
- source-faithful lab, vital, diagnosis, procedure, medication, encounter, and
  patient tables needed by the current GLP-1 reference and future cohort
  builders;
- a versioned element catalog and rule table;
- source-element membership, observability, RFS membership, encounter
  availability, provenance, data-dictionary, and aggregate quality tables; and
- 36 compatibility views that regenerate the historical CSV contract.

The product does not contain GLP-1 eligibility decisions, study cohorts,
imputation, propensity models, or outcome analyses. Those remain downstream
logic. The adapter in `combined_preprocessing/glp1_adapter.py` proves on
synthetic fixtures that the existing GLP-1 derivation can consume the unified
source tables without a second raw clinical-data scan. It remains a temporary
parity bridge; the current exact head has not completed a new private full-data
adapter-versus-reference run.

## Stable grains

- `preprocessed_encounter`: one row per compatibility output observation. Its
  identity includes output key, category, setting, variant, and stable source
  order; the remaining columns are the ordered historical 534-column payload.
- `source_*`: one row per retained raw source record. Clinical records require
  at least one `include: true` element membership; duplicate records remain
  distinct through `source_record_id`, source file, and source row number.
- `source_encounter_flow`: a compact complete encounter inventory containing
  patient, encounter, start timestamp, and type for reproducible raw-universe
  cohort-flow denominators without a second encounter-export scan.
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

## Cohort-source consumer contract

The stable cohort-source surface is the complete `source_patient` and
`source_encounter` tables; the five typed clinical `source_*` tables;
`element_catalog`, `element_rule`, and `element_membership`; availability and
observability tables; and the preprocessing manifest and sidecar. Its catalog
contains current GLP-1 concepts plus the existing typed traditional
hypercapnia, feature-candidate, and RFS extraction rules. Matching records are
source candidates only: value ranges, time windows, reductions, index-event
choices, and cohort inclusion remain downstream.

`source.traditional.medication.stata_op_mat` preserves a documented Stata
reference annotation so its raw records survive this source build. Codes
`3304`, `236913`, and `28863` are the three annotated additions beyond the
existing Python `OPmed_list3` source rule. They are not a validated
medication-assisted-treatment definition: adjudicate the original TriNetX
query/export before a cohort uses them for clinical inclusion.

`preprocessed_encounter`, `rfs_membership`, and the 36 compatibility views are
compatibility surfaces, not the future cohort API. `export-legacy` remains the
temporary CSV bridge for Stata consumers.

Use the public reader only against a published product:

```python
from pathlib import Path

from trinetx_preprocessing.combined_preprocessing.cohort_source import (
    open_cohort_source,
)

with open_cohort_source(
    Path("/private/output/trinetx_preprocessed.duckdb"),
    required_elements=("source.traditional.diagnosis.has_j9612",),
    expected_catalog_sha256="<approved-cohort-source-catalog-sha256>",
    memory_limit_mib=3072,
    spill_root=Path("/private/scratch/duckdb"),
) as source:
    result = source.connection.execute(
        "SELECT count(*) FROM source_encounter"
    ).fetchone()
```

The context manager signature is
`open_cohort_source(database_path, *, required_elements=(),
expected_catalog_sha256=None, memory_limit_mib=3072, spill_root=None)` (the
memory default follows the package configuration constant). The reader requires
a terminal manifest, the adjacent sidecar, an exact cohort-source schema
fingerprint, an optional pinned merged-catalog digest, and any requested element
IDs. It opens DuckDB read-only with owned spill cleanup. The database parent and
an explicit spill root must both be external to Git worktrees.

`validate_cohort_source()` accepts the same arguments and returns a structured
validation result. The `validate-cohort-source` CLI exposes `--database`,
repeatable `--require-element`, and `--json`; catalog pinning, memory selection,
and explicit spill placement are Python-only controls in the current interface.

## Build and inspect

Use an external private `output_dir`; repository-local row-level output is
rejected.

```bash
python -m trinetx_preprocessing build-preprocessed \
  --config /private/path/config.yaml

python -m trinetx_preprocessing preprocessed-status \
  --database /private/output/trinetx_preprocessed.duckdb --json

python -m trinetx_preprocessing validate-preprocessed \
  --database /private/output/trinetx_preprocessed.duckdb \
  --output-dir /private/output --json

python -m trinetx_preprocessing validate-cohort-source \
  --database /private/output/trinetx_preprocessed.duckdb \
  --require-element source.traditional.diagnosis.has_j9612 --json
```

With `combined.enabled: true`, the existing `run` and `run-all` commands route
to the same builder. The accepted full source uses deterministic non-strict
resolution for 286 documented encounter-setting conflicts. The prescribed
`run-final-assembly --strict` resume check remains the separate fail-closed
adjudication proof and exits before final-output writes for that source; do not
run a full strict replacement build against the accepted product.

`export-legacy` regenerates all 36 CSV projections without reading raw exports.
It requires a terminal `complete` database and a separate external
compatibility-only destination, keeps spill/scratch in owned staging, validates
the complete set against the embedded database manifest, and atomically
publishes it. Pass `--replace` to replace an existing compatibility-only export
tree; the canonical database product directory is never mutated in place.

## Reproducibility and resume

The work manifest fingerprints source metadata, effective configuration,
pipeline code, runtime versions, intermediate schema, ruleset, and the loaded
element catalog. A changed identity fails closed. The database embeds its run
identity, source inventory, catalog fingerprint, compatibility-output hashes,
and table-level data dictionary.

Publication is transactional at the product-directory boundary: all 36 CSVs,
the database, and its sidecar are built and validated in a sibling staging
directory. `--replace` moves the prior product to a rollback backup and installs
the completed directory only after every check passes. A durable publication
journal repairs an interrupted directory swap on the next invocation. Staging
and phase state use deterministic source/code/config identities, so a failure
after the raw pipeline completes resumes database, export, or validation work
without rescanning the exports. Exclusive locks cover both the canonical work
and output roots. Failed builds leave the published product unchanged; output
roots with unmanaged descendants or symlinks are rejected.

Validation requires the adjacent sidecar and reconciles its run, catalog,
runtime, database size/path, and table counts with the embedded manifest.
Literal source values such as `NA`, `N/A`, and `NULL` remain source strings;
only empty CSV fields are treated as missing.

## Acceptance evidence

The following list records the historical combined-product acceptance gate.
The expanded shared catalog and cohort-source API additionally pass current
code review and synthetic CI. No new private full-data source-completeness or
adapter-versus-reference run has been completed at this exact head, so the
standalone raw-ingestion reference remains in service.

Stage 1 is accepted only after:

1. the 36 compatibility exports match the approved historical baseline by
   ordered schema, row count, and normalized SHA-256;
2. every required source element has at least one included catalog rule and
   aggregate coverage is reported without identifiers;
3. the combined product passes structural, referential-integrity, manifest,
   and export validation;
4. the full build satisfies the existing external-space and peak-memory gates;
   and
5. no private database, row-level output, log, manifest, or validation artifact
   is tracked by Git.

The scripts `capture_combined_baseline.py`, `verify_combined_parity.py`,
`verify_element_completeness.py`, and `benchmark_combined_preprocessing.py`
produce aggregate-only external evidence for these gates.

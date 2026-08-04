# Current Repository State

Status date: 2026-08-04. This page is the durable human-readable status source
for the repository. Historical evidence and decision detail remain in
`VALIDATION.md` and `DECISIONS.md`; future work is ordered in `PLAN.md`.

## Delivered and accepted

- `trinetx_preprocessed.duckdb` is the canonical preprocessing product. Its 36
  historical 534-column CSV projections remain the Stata compatibility bridge.
- One versioned element catalog contains both current GLP-1 source concepts and
  typed traditional Hypercapnia/RFS source candidates. This is a permanent
  expansion of the original workflow, not a second GLP-1 preprocessing product.
- The manifest-bound cohort-source schema, command-line validator, and Python
  read-only consumer API are implemented. They validate schema and catalog
  identity, required element IDs, the terminal manifest, and the adjacent
  sidecar before exposing rows.
- The code/API contract and synthetic CI are accepted. Synthetic adapter tests
  show that the existing GLP-1 derivation reads the same five clinical-domain
  inputs and produces the same downstream fixture outputs from raw ingestion
  and from the canonical database.
- Historical combined-build and 36-file compatibility evidence remains valid
  for the behavior heads named in `VALIDATION.md`.
- The preserved Stata cohort reference is frozen at
  [`trinetx-hypercapnia-code` merge `0584b0e`](https://github.com/reblocke/trinetx-hypercapnia-code/commit/0584b0e13fe547f4a67b7d05e00aa40c0e95fa94)
  (PR #4). Its exact-head and post-merge `master` CI passed; this commit is the
  reference boundary for the later cohort migration and the full
  `source_version` recorded on its Stata-annotated catalog rows.

## Boundary and pending evidence

- Source capture is not cohort construction. An `element_membership` row says
  that a source record matched a versioned extraction rule; it does not apply a
  value threshold, time window, index selection, phenotype, exclusion, or
  study-cohort decision.
- Cohort construction has not been imported into this repository. The next
  migration will place traditional and GLP-1 derivations in the same primary
  cohort workflow and consume only the cohort-source contract.
- `combined_preprocessing/glp1_adapter.py` and the standalone GLP-1 raw-ingestion
  command are temporary migration references. Raw ingestion cannot be retired
  until a frozen exact head passes private full-data adapter-versus-reference
  parity.
- The expanded cohort-source catalog and current adapter have code/API and
  synthetic evidence, but no new private full-data source-completeness or
  adapter-parity run has been completed at this exact head. Earlier full-data
  GLP-1 evidence is reference evidence only.
- Cohort import is paused because the downstream cohort-creation repository is
  being refactored. Work resumes when that repository exposes a stable behavior
  head; the exact restart commit is not yet known.
- `source.traditional.medication.stata_op_mat` retains five Stata-annotated
  source codes. Codes `3304`, `236913`, and `28863` are the three additions not
  present in the existing Python `OPmed_list3` rule. They remain unadjudicated
  source candidates pending review of the original TriNetX query/export and
  must not be treated as a medication-assisted-treatment phenotype.

## Supported consumer interfaces

Validate a published database from the command line:

```bash
python -m trinetx_preprocessing validate-cohort-source \
  --database /private/output/trinetx_preprocessed.duckdb \
  --require-element source.traditional.diagnosis.has_j9612 \
  --require-element source.arterial_pco2 \
  --json
```

`--require-element` is repeatable. The CLI intentionally exposes only the
database path, required element IDs, and JSON output selection.

Downstream Python consumers can additionally pin the catalog and select an
external DuckDB spill root:

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
    rows = source.connection.execute(
        "SELECT * FROM source_diagnosis LIMIT 100"
    ).fetchall()
```

`open_cohort_source()` is a context manager with keyword-only
`required_elements`, `expected_catalog_sha256`, `memory_limit_mib`, and
`spill_root` arguments. It opens DuckDB read-only and removes its owned spill
directory on exit. Both the database parent and an explicit spill root must be
external to every Git worktree. `validate_cohort_source()` accepts the same
arguments and returns a result instead of raising for contract failures.

## Safe next handoff

Once the downstream refactor publishes a stable behavior head, freeze its
inputs and expected outputs, import one cohort slice at a time behind the
cohort-source contract, and compare each imported result with the preserved
Stata/standalone reference. The private full-data parity gate—not synthetic CI
alone—authorizes retirement of either legacy raw-data path.

# TriNetX preprocessing: source and encounter data creation

This public repository normalizes captured TriNetX exports into a canonical,
manifest-bound source DuckDB and creates reusable encounter-level feature
bundles. Study cohort decisions, GLP-1 indications, weights, prevalence,
figures and reporting belong to
[trinetx-hypercapnia-code](https://github.com/reblocke/trinetx-hypercapnia-code).
The direct Stata implementation, accepted Python port and 36-file CSV/DTA
workflows remain reproduction references. No real TriNetX records or private
validation artifacts belong in this repository.

[Current state](docs/CURRENT_STATE.md) records dated implementation and gate
status; [encounter preprocessing](docs/ENCOUNTER_PREPROCESSING.md) is the
maintained production and verification runbook. A merged interface or complete
manifest does not alone establish installed-pair, private-data or scientific
acceptance. The earlier GLP-1 source acceptance is
[historical evidence](docs/GLP1_SOURCE_ACCEPTANCE.md), not a new encounter receipt.

## Products and handoff

| Product | Role and source authority | Unit/key and consumer | Validation boundary |
| --- | --- | --- | --- |
| `trinetx_preprocessed.duckdb` | Canonical captured-source product from normalized exports; supplies clinical evidence and catalog provenance | Source patient, encounter and event records; upstream builders and downstream source readers | Manifest/schema/catalog validation; source acceptance is separate from encounter acceptance |
| Authenticated compatibility companion DuckDB | One-time authorized import of the original accepted 36-file snapshot; preserves legacy population and transformation inputs | Original compatibility rows/partitions; encounter builder | Input identity and cell comparison; bypasses an unexplained canonical-projection membership mismatch without repairing it |
| FULL_DATA and AFTER_EXCLUSION encounter bundles | Independently transformed legacy bases enriched from canonical clinical evidence | One row per original string `patient_id` + `encounter_id` within each variant; downstream encounter reader | Retained-reference comparison, coverage and full artifact validator, followed by separately recorded acceptance |
| Per-variant evidence, dictionary, quality summary and manifest | Catalog-element records, availability and output interpretation | Encounter/evidence keys; consumers and reviewers | Inventory/hash/schema gates do not establish clinical eligibility or complete capture |
| Historical CSV/DTA bridge | 36 CSV compatibility exports and frozen Stata/Python references | Legacy table/analysis contracts; reference reproduction | Historical parity and corrected-source gates are scoped to their named heads |

See [schema, independent-variant and timing details](docs/ENCOUNTER_PREPROCESSING.md#products-and-grain),
[source contract](docs/DATA_CONTRACT.md) and
[validation boundaries](docs/VALIDATION.md).

## Choose a route

| Task | Access, input and working directory | Output and success check |
| --- | --- | --- |
| Small public example | From this repository root, use bundled fixtures and a new external output root with the command below | Synthetic source DuckDB plus 36 CSVs; inspect output and successful exit. This does **not** exercise `build-encounters`. |
| Restricted source/encounter production | Approved raw exports and authenticated companion under private external roots; follow the [encounter runbook](docs/ENCOUNTER_PREPROCESSING.md#run) from this checkout | Independent bundles and evidence; stage completion is not validation or acceptance. Do not repeat the one-time import without its identity authority. |
| Bundle validation | Approved existing private bundle; run the [artifact validator](docs/ENCOUNTER_PREPROCESSING.md#run) in a new private work directory | Validation report plus separate retained-reference comparison and acceptance review. A downstream reader hash check is narrower. |
| Downstream consumption | Validated bundle and approved study context; use the downstream [encounter reader](https://github.com/reblocke/trinetx-hypercapnia-code/blob/master/docs/ENCOUNTER_PREPROCESSING.md) | Read-only encounter rows; study selection remains downstream. |
| Historical reproduction | Preserved reference inputs and approved environment; use the [operator and legacy notes](docs/OPERATOR_AND_LEGACY_GUIDE.md) | Historical CSV/DTA or comparison artifacts, evaluated against their own dated receipts. |

## Small public source example

Review `scripts/run_synthetic_example.py` and the fixture before running. With
Python/`uv` available, from this repository root:

```bash
uv sync --locked
uv run python scripts/run_synthetic_example.py \
  --output-root /tmp/trinetx-preprocessing-readme-example-new
```

Choose a new output path outside Git; the helper writes `config.yaml`, `work/`
and `output/` there and calls `build-preprocessed` on the bundled fixtures.
Check its exit status and `output/trinetx_preprocessed.duckdb` plus the 36
compatibility CSVs. This is a source-builder smoke, not an encounter-interface
fixture, private full-data build or scientific validation. If that output root
already exists, choose another new one rather than overwriting evidence.

## Scientific and access limits

Both encounter variants preserve repeated encounters; `first_encounter` is a
flag, not a row filter. AFTER_EXCLUSION is independently derived, with its own
timing and imputation, and cannot be recreated by filtering FULL_DATA. Join by
original string patient and encounter keys, never variant-specific encoded IDs.
The daily anchor supports inclusive calendar-day windows; source timestamps and
raw versus normalized units remain distinct. Observed history is not proof of
continuous capture, a missing record is not a negative, and catalog source
candidacy is not cohort eligibility. The canonical compatibility projection
mismatch remains unexplained. See the [encounter contract](docs/ENCOUNTER_PREPROCESSING.md#time-evidence-and-missingness)
and downstream [known scientific limits](https://github.com/reblocke/trinetx-hypercapnia-code/blob/master/docs/ENCOUNTER_PREPROCESSING.md#known-scientific-limitations-retained).

Real exports, manifests, spill, row-level outputs and validation reports stay
outside this public Git checkout under approved private storage. No restricted
import, full build or data acceptance is implied by these instructions.

## Source-builder and historical operator detail

The former root README's source commands, profiling, milestone evidence and
legacy comparison instructions are preserved in the
[operator and legacy guide](docs/OPERATOR_AND_LEGACY_GUIDE.md). For current
encounter build order use the [runbook](docs/ENCOUNTER_PREPROCESSING.md#run).

<!-- Preserve historical README section anchors for inbound links. -->
## Unified preprocessing product

See the [preserved operator detail](docs/OPERATOR_AND_LEGACY_GUIDE.md#unified-preprocessing-product).

## Cohort-source handoff

See the [preserved operator detail](docs/OPERATOR_AND_LEGACY_GUIDE.md#cohort-source-handoff).

## Downstream GLP-1 analysis

See the [preserved operator detail](docs/OPERATOR_AND_LEGACY_GUIDE.md#downstream-glp-1-analysis).

## Real data placement (do not commit)

See the [preserved operator detail](docs/OPERATOR_AND_LEGACY_GUIDE.md#real-data-placement-do-not-commit).

## CLI basics

See the [preserved operator detail](docs/OPERATOR_AND_LEGACY_GUIDE.md#cli-basics).

## Performance

See the [preserved operator detail](docs/OPERATOR_AND_LEGACY_GUIDE.md#performance).

## Golden-master validation

See the [preserved operator detail](docs/OPERATOR_AND_LEGACY_GUIDE.md#golden-master-validation).

## Tests + quality checks

See the [preserved operator detail](docs/OPERATOR_AND_LEGACY_GUIDE.md#tests--quality-checks).

## More docs
- `docs/CURRENT_STATE.md`: delivered capabilities, pending gates, and restart boundary
- `docs/ONBOARDING.md`: step-by-step setup + legacy notebook notes
- `docs/CONFIG.md`: config file details
- `docs/DATA_CONTRACT.md`: inputs, outputs, and required columns
- `docs/ARCHITECTURE.md`: pipeline structure

## Maintenance and contact

Contact the repository maintainer by opening a
[GitHub issue](https://github.com/reblocke/trinetx-preprocessing/issues) for
setup questions, reproducibility problems, or proposed changes.

## Citation and license
Cite the GitHub repository URL and the commit or release used. No publication DOI
is assigned to this repository. Code is MIT licensed; see `LICENSE`.

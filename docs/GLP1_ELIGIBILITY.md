# GLP-1 Eligibility Augmentation

GitHub issue #6 is the authoritative endpoint specification for the additive
GLP-1 eligibility database. This work begins after immutable tags
`refactor-milestone-2` and `v0.2.0`.

## Compatibility boundary

- The existing `trinetx-preprocessing run` command, its work tables, and its 36
  final CSV files are unchanged.
- GLP-1 code lives under `trinetx_preprocessing.glp1_eligibility` and writes only
  beneath the output directory passed to that command.
- GLP-1 ingestion must preserve source provenance independently. It must not use
  lossy legacy feature tables as its source of truth.
- Real databases, Parquet files, manifests, logs, and validation artifacts stay
  external and untracked.

## Current commands

Validate the versioned rule contract:

```bash
python -m trinetx_preprocessing.glp1_eligibility validate-config \
  --config config/glp1_eligibility.yml
```

Discover split or unsplit exports and validate headers without reading rows:

```bash
python -m trinetx_preprocessing.glp1_eligibility validate-export \
  --input /path/to/trinetx_export
```

When a restored root contains both a canonical unsplit export and legacy split
artifacts, discovery selects the nearest canonical file. Headered split files
remain the fallback when no unsplit source exists. If multiple nearest export
roots or same-root source families tie, validation fails and requires the root
of exactly one export. Either a medication export or a medication-ingredient
export satisfies the medication source contract;
independently valid headered medication and ingredient families are both
retained even when optional columns or column order differ. Legacy medication
chunks lacking required header fields are ignored when a canonical ingredient
file is available. Ingredient exports must provide
`patient_id`, `code_system`, `code`, and `start_date` because those fields
define medication phenotype membership and timing.

Build the additive database and study files:

```bash
python -m trinetx_preprocessing.glp1_eligibility build \
  --input /path/to/trinetx_export \
  --output /path/to/output/glp1_eligibility \
  --config config/glp1_eligibility.yml
```

An identical rerun reuses the completed output. A different input, config,
parsed concept catalog, supplied export metadata file, or package code state
requires `--replace`; replacement preserves the previous output until the
staged build is complete.

Confidential output should normally live outside the repository. A
repository-local output is accepted only when Git ignores the complete output
directory, including its staging and replacement siblings. Before atomic
publication, the builder checkpoints and closes DuckDB and refuses to publish
if a write-ahead log remains.

Long builds publish atomic aggregate progress to a hidden state file adjacent
to their output directory while artifacts are staged, so the final output tree
can still be published by one rename. The status reader checks that file and
does not signal or attach to the worker:

```bash
python -m trinetx_preprocessing.glp1_eligibility status \
  --output /path/to/output/glp1_eligibility \
  --watch --interval-seconds 30
```

Watch mode emits aggregate state only and exits when the build completes,
fails, or its recorded local worker is no longer active. It does not attach to,
signal, or restart the worker.

Print aggregate counts without identifiers:

```bash
python -m trinetx_preprocessing.glp1_eligibility summarize \
  --database /path/to/output/glp1_eligibility/glp1_hypercapnia.duckdb
```

The current build implements source and export-metadata inventory,
first-observed arterial PaCO2 selection before validity checks, unit-aware pH
pairing, hypercapnia sensitivity cohorts, the measured/calculated BMI hierarchy,
concept-independent raw observability, temporal component phenotypes,
indication tiers, payer-route modeling, medication and ingredient order
history, all 15 flow stages, long-form source and derived evidence, study views,
and atomic file publication. The committed synthetic export exercises the 20
mandatory issue cases without proprietary data, and the same suite runs in
GitHub Actions.

See `GLP1_DATA_CONTRACT.md`, `GLP1_PHENOTYPES.md`, and
`GLP1_MIGRATION.md` for the database contract, interpretation boundaries, and
relationship to the historical notebooks. Concept files and high-risk
phenotypes still require investigator terminology and record-level validation
before clinical use.

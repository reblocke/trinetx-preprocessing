# GLP-1 Eligibility Augmentation

GitHub issue #6 is the authoritative endpoint specification for the additive
GLP-1 eligibility database. Standalone software and behavior-head-scoped
aggregate evidence are already delivered; the issue remains open for its
optional-domain, catalog/configuration, smoke-summary, final-catalog evidence,
and clinical/private-review requirements.

## Compatibility boundary

- `trinetx_preprocessed.duckdb` is the canonical shared preprocessing product;
  its compatibility views preserve the existing 36 final CSV files.
- GLP-1 code lives under `trinetx_preprocessing.glp1_eligibility` and remains
  downstream of preprocessing.
- GLP-1 source provenance comes from typed unified source tables. It must not
  use lossy legacy feature tables as its source of truth.
- The canonical manifest preserves the GLP-1 catalog fingerprint separately
  from the broader cohort-source catalog, so additive traditional source rules
  cannot silently change the validated GLP-1 reference boundary.
- The unified-source adapter also selects clinical rows through active GLP-1
  element memberships. Traditional-only source candidates remain available to
  future cohort consumers but cannot enter GLP-1 clinical source tables.
  Raw observability intentionally remains concept-independent in both paths,
  so it continues to represent all raw clinical activity.
- Real databases, Parquet files, manifests, logs, and validation artifacts stay
  external and untracked.

The standalone raw-ingestion command below remains the validated reference
implementation during migration. The adapter-backed synthetic gate verifies
equivalent source and downstream outputs from the unified product. It is a
temporary compatibility bridge: the permanent design integrates GLP-1 elements
and later cohort derivations into the shared legacy workflow rather than a
separate GLP-1 product.

## Status against issue #6

Delivered but not issue closure: the standalone CLI, eight-file contract,
versioned configuration/concept sets, 20-case synthetic acceptance/CI, and
behavior-head-scoped aggregate full-data reference evidence. Still open are
optional-domain ingestion when present; final catalog/rule/configuration and
clinical terminology review; remaining data-driven policy; the required
smoke-query interface and specified aggregate summaries; fresh evidence at the
final catalog/rule head; and investigator/private record-level review. The
standalone raw-ingestion implementation remains the production reference.

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
of exactly one export. Selected clinical domains must also share one flat root
or recognized sibling domain-folder root, preventing partial domain folders
from being combined with a sibling or nested export. Either a medication export
or a medication-ingredient export
satisfies the medication source contract; independently valid headered
medication and ingredient families are both retained even when optional columns
or column order differ. Legacy medication chunks, including one-file chunk
families, lacking required header fields are ignored when a canonical ingredient
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

The `runtime` configuration bounds DuckDB execution. The supported defaults are
`duckdb_memory_limit_mib: 4096` and `duckdb_threads: 1`; both effective values
are recorded in the database and JSON run manifests. Lower settings may be used
for constrained systems, but changing them creates a distinct configured run.
Source ingestion materializes unique gas-candidate patient and encounter keys
once and reuses them for bounded hash membership across later domain scans.
Exact concept rules also use hash membership; validated prefix and regex rules
compile to constant predicates. This preserves duplicate source records and
overlapping-rule semantics without building correlated joins over full exports.
Vital, diagnosis, procedure, and medication ingestion each scan the raw source
once into 32 concept-filtered patient-hash Parquet partitions under DuckDB's
external temp directory, then append one partition after joining only its
matching candidate-patient bucket. Source timestamps accept both standard ISO
representations and TriNetX's compact `YYYYMMDD` dates. Scratch is removed
strictly on success or failure and is recognized by `clean-scratch`.

Confidential output must live outside every Git worktree. Repository-local
output is rejected even when ignore rules appear to cover it, because negation
rules can re-expose selected children. Existing non-directory output paths are
also rejected before Git probing. Ignore patterns remain defense in depth.
Before atomic publication, the builder checkpoints and closes DuckDB and refuses
to publish if a write-ahead log remains.

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
including a one-day same-encounter fallback when encounter end is missing,
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

## Full-data validation

The exact behavior-head build from commit `459cbda` completed against the
restored full export with the supported 4,096 MiB/one-thread DuckDB settings.
It completed in 20,941.55 seconds, used 5,635,293,184 bytes maximum RSS, and
atomically published exactly eight contracted files with zero warnings,
errors, WAL files, recognized scratch artifacts, AppleDouble sidecars, or
hidden build workspace.

Aggregate-only validation reported 1,320,409 candidate hypercapnia encounters,
59,954 patient index events, 9,527 strict primary obesity-hypercapnia rows, and
12,028,276 evidence rows. PaCO2 and paired-pH evidence each contain 59,954
source-traceable rows with raw and normalized values and units. Parquet,
DuckDB, command-summary, and cohort-flow counts agree across all 15 stages.

Compared with the preserved reviewed `71ef56f` build, all index-event keys and
candidate, strict-primary, payer-route, and cohort-flow counts are unchanged.
The all-history cirrhosis correction changes 191 analysis rows. The corrected
evidence boundary adds 9,193 diagnosis rows and removes 2,612,789 post-index
non-GLP-1 medication rows. Patient-scoped encounter reductions and
precision-aware date-only procedure context produce no additional full-data
key/count changes. Ruleset `2026-07-19.1` also preserves source precision for
the CKD 90-day boundary. Compared directly with the reviewed `e7bf01a` parent
build, the exact-head output has zero schema, key-set, table-count,
non-provenance analysis-value, or semantic-fingerprint differences.

These results establish computational completion and aggregate consistency.
They do not replace the investigator terminology review and private record-level
validation required before clinical use.

This full-data evidence is scoped to behavior head `459cbda`. PR #8 later
rewrote the anesthesia procedure regex with an equivalent non-capturing group,
which changed deterministic catalog identity without intending to change
matches. The preserved run is therefore reference evidence, not current-head
release proof; issue #6 requires a fresh full-data run at its final exact
catalog/rule head.

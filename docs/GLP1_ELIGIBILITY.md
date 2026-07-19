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

The review-clean corrected build from commit `00e24a9` completed against the
restored full export with the supported 4,096 MiB/one-thread DuckDB settings.
It completed in 20,247.71 seconds, used 5,342,773,248 bytes maximum RSS, and
published all eight contracted files with zero warnings, errors, WAL files, or
recognized scratch artifacts.

Aggregate-only validation reported 1,320,409 candidate hypercapnia encounters,
59,954 patient index events, 9,527 strict primary obesity-hypercapnia rows, and
14,631,872 evidence rows. All 59,954 index-event keys match the earlier
provisional build; candidate and strict-primary counts are unchanged. The
corrected build adds `dx_obesity`, represents 12,378 rows as code-only obesity,
and records all compact-date gas pairings as date-only rather than exact-time
pairings. PaCO2 and paired-pH evidence each contain 59,954 source-traceable rows
with raw and normalized values and units.

These results establish computational completion and aggregate consistency.
They do not replace the investigator terminology review and private record-level
validation required before clinical use.

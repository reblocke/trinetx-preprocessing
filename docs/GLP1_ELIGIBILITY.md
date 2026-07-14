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

Long builds publish atomic aggregate progress to `.glp1_build_state.json` in
their output directory. The status reader does not signal or attach to the
worker:

```bash
python -m trinetx_preprocessing.glp1_eligibility status \
  --output /path/to/output/glp1_eligibility
```

The production `build` and `summarize` commands are added with the DuckDB
storage implementation. Concept files currently seed the mandatory blood-gas
safety distinctions and initial component rules; they require investigator
terminology review before clinical use.

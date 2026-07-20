# GLP-1 Augmentation Completion Plan

Refactor Milestones 1 and 2 remain immutable fallbacks. The current branch adds
the independent GLP-1 eligibility database specified by GitHub issue #6 without
changing the released 36-file preprocessing pipeline.

## Implementation milestones

1. Validate split and unsplit export discovery, metadata inventory, and source
   headers without loading confidential rows.
2. Fingerprint package code, configuration, concepts, phenotype rules, export
   metadata, and clinical inputs in a deterministic run identity.
3. Stream full source domains through bounded DuckDB and patient-hash Parquet
   paths while preserving source provenance and duplicate-row QA.
4. Build hypercapnia cohorts, paired gas evidence, BMI, temporal phenotypes,
   indication tiers, payer routes, observability, and all 15 flow stages.
5. Publish the eight-file database/Parquet/report contract atomically with
   aggregate status monitoring and strict scratch/WAL cleanup.
6. Pass synthetic acceptance, local and Linux CI gates, exact-head Codex review,
   a full-data build, and a PHI-safe aggregate comparison.

## Current status

Implementation and synthetic verification are complete with 336 passing tests.
The exact behavior-head full-data build from commit `459cbda` completed all
phases in 20,941.55 seconds with 5,635,293,184 bytes maximum RSS, below the
6,238 MiB gate. Exactly eight outputs were published with zero warnings,
errors, WAL files, recognized scratch artifacts, hidden workspaces, or
AppleDouble sidecars. Aggregate validation passes every automated check and
contains 59,954 index-event rows, 1,320,409 candidate encounters, 9,527 strict
primary rows, and 12,028,276 evidence rows.

Relative to the preserved reviewed `71ef56f` baseline, the parent build
retains every index-event key and all candidate, primary, payer-route, and
cohort-flow counts. The all-history cirrhosis correction changes 191 analysis
rows. Corrected evidence retention adds 9,193 diagnosis rows and removes
2,612,789 post-index non-GLP-1 medication rows. Composite encounter and
date-only procedure-context corrections do not change the full-data key or
count contracts.

Ruleset `2026-07-19.1` requires 90 elapsed days for timestamped low-eGFR
measurements and uses inclusive calendar-day boundaries only when an endpoint
is date-only. The exact-head run matched the reviewed `e7bf01a` parent build
with zero schema, key, count, analysis-value, or semantic-fingerprint changes.
The remaining engineering gate is a final review of this evidence-only commit.
Investigator terminology expansion and private record-level clinical
validation remain separate requirements before clinical use.

## Definition of done

- All synthetic acceptance and temporal boundary tests pass locally and in CI.
- The full export is processed once per source stage with bounded memory and
  maximum RSS no greater than 6,238 MiB.
- All eight contracted public outputs publish atomically with complete run,
  source, concept, duplicate, cohort-flow, and data-dictionary provenance.
- Full-data validation reports no warnings, errors, WAL files, scratch,
  AppleDouble sidecars, missing required concepts, or output-count
  inconsistencies.
- A PHI-safe aggregate report explains changes from the preserved provisional
  build without identifiers or row examples.
- The final branch head has clean local, CI, and GitHub Codex reviews.

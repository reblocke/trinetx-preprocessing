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

Implementation and synthetic verification are complete with 334 passing tests.
The latest completed corrected full-data build from reviewed commit `71ef56f`
completed all phases in 20,284.53 seconds with 5,012,209,664 bytes maximum RSS, below the
6,238 MiB gate. Exactly eight outputs were published with zero warnings,
errors, WAL files, recognized scratch artifacts, or AppleDouble sidecars.
Aggregate validation passes every automated check and preserves all 59,954
index-event keys, 1,320,409 candidate encounters, and 9,527 strict primary rows
from the provisional build. Complete semantic fingerprints also match the
preserved corrected diagnostic output across all 14,631,872 evidence rows.

Final review found fixed-label threshold, remote cirrhosis, reused encounter
identifier, and future non-GLP-1 baseline-evidence defects. Their focused
corrections pass the complete synthetic suite. The remaining engineering gates
are CI/Codex review and a fresh full-data build from the corrected head.
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

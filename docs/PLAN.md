# Corrected Pipeline Release Plan

Refactor Milestone 1 completed historical replication and remains frozen at the
`refactor-milestone-1` tag. Post-milestone work intentionally corrects known
notebook defects under `docs/SPEC.md` while preserving the public 36-file,
534-column output contract.

## Implementation milestones

1. Specify corrected clinical and reduction semantics.
2. Replace regex-centric definitions with typed exact/prefix/numeric rules.
3. Retain code-system and unit metadata and report aggregate rule rejections.
4. Validate encounter-setting conflicts and derive diagnosis-or-lab screening.
5. Build compact RFS and feature candidates during each domain's single scan.
6. Use bounded Parquet partitions and a fail-closed work manifest.
7. Reuse patient-partitioned feature/history indexes across all 18 cohorts.
8. Remove the unsupported shell splitter and maintain the Python CLI path.
9. Pass local, corrected staged, full profile, aggregate delta, and holistic
   review gates; document the strict source-conflict acceptance decision.
10. Release `0.2.0` as `v0.2.0` and `refactor-milestone-2` without changing
    Milestone 1 tags.

## Current status

Implementation, local tests, staged tiers, holistic review, the review-clean
full profile, output hashes, scratch cleanup, and the aggregate-only Milestone 1
delta are complete. All measured correctness, time, memory, disk, and public
output-contract gates pass. Release acceptance uses deterministic non-strict
resolution for the 286 source encounter-setting conflicts; strict mode remains
fail-closed for workflows that require upstream conflict adjudication. The
remaining work is GitHub release bookkeeping.

## Definition of done

- Every corrected invariant in `docs/SPEC.md` has focused synthetic coverage.
- Strict and non-strict encounter conflict behavior is deterministic.
- All 36 final CSVs retain exact ordered schema and stable filenames.
- Profiling proves one sequential domain scan, bounded memory, at least 25%
  total wall-time improvement, and at least 50% final-assembly improvement.
- Peak RSS is at most 6,238 MB and external free space remains above 100 GiB.
- A PHI-safe aggregate report explains changes from Milestone 1 without row
  examples or identifiers.
- Local and GitHub reviews are clean, package version is `0.2.0`, and both
  `v0.2.0` and `refactor-milestone-2` identify the reviewed release commit.

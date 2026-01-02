# Refactor Plan

This is a living plan for the `refactor-pipeline` branch.

## Principles
- Preserve results first.
- Make behavior changes explicit and documented.
- Keep milestones small and testable.

## Milestones (suggested)
0. Scaffold: docs + tests + packaging
1. Baseline: fixture dataset + snapshot outputs from legacy pipeline
2. Extract: move shared logic from notebooks into `src/` functions
3. CLI: single entrypoint with config
4. Validation: regression suite + provenance
5. Performance: profile + optimize bottlenecks
6. Clean-up: simplify notebooks, improve docs

## Current status
- Done:
- In progress:
- Next:

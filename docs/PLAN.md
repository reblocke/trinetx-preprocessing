# Refactor Plan

This is a living plan for the `refactor-pipeline` branch.

## Principles
- Preserve results first.
- Make behavior changes explicit and documented.
- Keep milestones small and testable.

## Milestones (suggested)
0. Inventory + runbook docs (Milestone 001)
1. Baseline: synthetic fixture + snapshot outputs
2. Extract: domain preprocessing into `src/`
3. Implement RFS derivation + data checks
4. Assemble final dataset pipeline + config
5. CLI: single entrypoint + reproducibility hooks
6. Validation + performance + notebook cleanup

## Current status
- Done:
- In progress: Milestone 0 (docs inventory/runbook)
- Next: Milestone 1 (synthetic fixture + baseline outputs)

# Finish the encounter preprocessing refactor

Handoff: 2026-09-20. Implementation exists, but **private encounter validation
has failed and neither PR is ready to merge**. Continue on the Mac mini.
Exact paths, authenticated receipts and launch instructions are in the private
`encounter-refactor-handoff/LOCAL_PATHS.md` beside the Mini checkouts. Keep that
file and all real-data receipts out of this public repository.

## Completed

- [x] Extract accepted cleaning, ordered merges, derived variables and measurement
  imputation; all 92 extracted function/class ASTs matched the accepted source.
- [x] Implement `build-encounters`, independent FULL_DATA/AFTER_EXCLUSION tables,
  repeated encounters, source identifiers, evidence, dictionary, inventory, QA
  and versioned manifest. Include traditional and GLP-1 elements without study
  eligibility filtering; retain legacy NIV/IMV and separate CPAP.
- [x] Relocate GLP-1 study code/configuration/tests downstream. Preserve the
  original Stata implementation and accepted direct Python port.
- [x] Complete bounded review, initial fixtures and repository CI. Diagnose the
  private-build OOM; commit `8b19b7f` narrows context deduplication to required
  columns and keys. Ten focused encounter tests, Ruff and its CI passed.
- [x] Authenticate all 36 original compatibility inputs against the retained
  producer manifest. Full-data confirmation of the repair remains outstanding.

## Remaining work, in order

1. [ ] **Establish the Mini as the only executor.** Read this file, private
   `LOCAL_PATHS.md`, both repositories' instructions and continuity notes.
   Inspect existing processes once; never duplicate an active build. Use the
   release upstream worktree and downstream encounter worktree. Preserve the old
   upstream branch, dirty `AGENTS.md` and failed-run artifacts. Restore Mini
   GitHub authentication, fetch and inspect branches; never reset or force-push
   to achieve synchronization.

2. [ ] **Reconcile legacy inputs before enrichment.** Required reference keys
   are absent from both canonical compatibility variants. Capture settings
   `corrected_v1` and `earliest_per_setting` document different source behavior,
   but are not a complete causal diagnosis. Do not change expected membership.
   Recommended route: one-time checksum-authenticated import of the original
   36 CSVs into a private DuckDB companion; routine builds then read DuckDB only.
   This adjusts the original no-CSV-read plan and is not implemented yet. The
   private launcher's normal start includes this choice in its startup instruction;
   running that start authorizes the route. Without that instruction, obtain the input
   decision before implementing it. Repairing canonical projection generation
   remains the alternative if the owner chooses it.

3. [ ] **Implement the smallest explicit source adapter.** Preserve the accepted
   CSV loader's coercions, input ordering, ordered merge precedence and independent
   variants. Use authenticated compatibility data for legacy population creation
   and canonical clinical data for GLP-1 evidence. Maintain one catalog/entrypoint
   and record both source identities, schema/configuration and hashes. Validate
   source-key linkage; never join on variant-specific encoded IDs. Open sources
   read-only and publish to a new private directory with existing safeguards.
   Update interface/decision documentation with the final command and boundary.

4. [ ] **Pass an inexpensive population gate for both variants first.** Build
   only the legacy base required to check keys, membership, categories, missingness
   and unchanged numerical fields. Preserve timing, imputation and repeated
   encounters. Authenticate any retained reference-key cache before reuse. The
   failed run's legacy base is not an accepted population. If keys differ, trace
   coercion, ordering and merges before expensive enrichment. Do not waive
   population differences as numerical tolerance.

5. [ ] **Prove coverage before reusing large projections.** Restored reference
   encounters may add patients absent from the failed run's projection scope.
   Check required patient/encounter keys and evidence-domain coverage. Reuse only
   identity-verified projections with sufficient scope; otherwise materialize
   missing scope from the existing canonical source. Recapture only for a
   specifically demonstrated missing element. Leave failed staging intact.

6. [ ] **Run affected checks, then one corrected integrated private build.**
   Use the accepted numerical environment, sequential variants, existing memory
   cap/external spill and `caffeinate -i`. Add focused import/source-boundary
   regressions and reuse encounter fixtures, including negative-versus-missing
   states and rows failing GLP-1 eligibility. Record the final producer tree.
   Keep logs private; expose aggregate status only. Repeat expensive work only
   for a concrete failure. Do not blindly restart the failed run script.

7. [ ] **Validate the bundle and retained references.** Use downstream
   `scripts/compare_encounter_reference.py` with the new bundle, accepted reference
   directory, fresh work directory and aggregate report. Require exact keys,
   membership, categories and missingness; current numeric `rtol=atol=1e-6`.
   Byte serialization need not match. Verify reference SHA256 against the retained
   identity receipt, source immutability, unique patient–encounter keys, both
   variants, completed manifest/hashes, inventory and evidence coverage. Explain
   intended excluded/renamed analysis fields; do not silently lose clinical data.
   The earlier day-grain proof does not validate the failed build or later fixes.

8. [ ] **Deliver coordinated changes.** Update the downstream immutable upstream
   dependency and lockfile to the final upstream code. Run affected downstream
   fixtures/reader checks and normal CI/relevant audits at final heads. Keep known
   study defects documented; no full downstream analysis or renewed Stata
   qualification is required. Update PR descriptions with verified conclusions
   and limitations; private receipts stay outside Git. Merge
   [upstream PR14](https://github.com/reblocke/trinetx-preprocessing/pull/14)
   first with a merge commit, preserving pinned dependency ancestry, then
   [downstream PR15](https://github.com/reblocke/trinetx-hypercapnia-code/pull/15)
   after its final checks pass. Authorization to land the changes already exists.

9. [ ] **Synchronize and close.** Fast-forward safe development checkouts;
   preserve the Mini's older branch and uncommitted work. Record merged heads,
   validated bundle location and final working command. If the laptop is offline,
   leave a concrete fetch/fast-forward action for it; do not claim its files were
   synchronized. Close the checkpoint and disable remaining completion monitors
   only when the refactor is complete. Never lock or eject drives as part of this.

## Done means

One documented upstream Python command creates validated encounter-level products
with all available traditional and GLP-1 elements. The direct reference port
remains preserved, study analysis remains downstream, scientific limitations are
documented, and coordinated changes have passed validation and landed.

# Encounter release follow-up

The original encounter split is merged: upstream `main` contains `4bbe8cf` and
downstream `master` contains `d5d2691`. The corrected private bundle and its
historical retained-reference comparison passed at those revisions. The older
private receipt predates the stronger shared acceptance contract; it does not
authorize the new strict reader. The current postmerge work must complete the
stronger artifact check, compose a manifest-bound integrated receipt through the
trusted private release process, pin the new immutable upstream revision in the
downstream package, and pass installed-pair CI. The downstream GLP-1 scientific
report has its own unresolved gates. See [current state](docs/CURRENT_STATE.md)
and [encounter interface](docs/ENCOUNTER_PREPROCESSING.md) for the maintained
status and commands.

Revalidate the existing immutable bundle before considering a rebuild. The
validator needs a fresh private work directory and report outside Git, under the
same private `build.lock` used by comparisons. A new build requires the
authenticated compatibility companion, legacy-reference gate, explicit linkage
policy, enrichment, artifact validation and retained-reference comparison shown
in the encounter interface. Neither route proves fresh-source equivalence,
continuous clinical history, new GLP-1 estimates or Stata qualification.

## Historical 2026-09-20 handoff

The following checklist records the earlier recovery session. Its initial
failed-build and unmerged-PR status has been superseded by the merged state
above. Preserve these steps as provenance; do not relaunch the old wrapper to
repeat completed work.
Exact paths, authenticated receipts and launch instructions are in the private
`encounter-refactor-handoff/LOCAL_PATHS.md` beside the Mini checkouts. Keep that
file and all real-data receipts out of this public repository.

## Start the audited handoff

After fetching/fast-forwarding the upstream handoff branch on the Mini, run
`bash scripts/start_encounter_handoff.sh` from its release checkout. This wraps
the existing private launcher with a session lock and copies this updated
checklist into the private handoff folder. The old private notes remain useful
for paths/receipts; this checklist supersedes their former acceptance rules.
Use this wrapper instead of invoking the old private launcher directly. The
laptop need not stay online once the Mini-local session starts.

Every data build and comparison must use the same private build lock, including
detached or monitor-driven runs. For example, substitute the actual command:

```bash
python3 scripts/with_execution_lock.py "$HANDOFF_DIR/locks/build.lock" -- COMMAND ARGUMENTS
```

Set `HANDOFF_DIR` to the existing private handoff folder. The lock is advisory:
all entrypoints must use it; it cannot block a command deliberately launched
outside the wrapper. Preserve the lock file even after a process exits. The
kernel releases ownership automatically; a leftover empty file is not a stale
held lock. Keep the Mini online and its Terminal session open.

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

## Source authority and scope

| Source | Authority |
| --- | --- |
| Authenticated legacy compatibility snapshot | Legacy population, 36 partitions, ordering, independent variants and preserved transformation inputs |
| Provenance-validated canonical clinical database | Additional clinical records/evidence for encounter enrichment |
| Accepted reference products | Expected retained legacy outputs |

The owner approved proceeding with the one-time authenticated CSV-to-DuckDB
import and the audit additions on 2026-09-20. Routine builds then read DuckDB.
This bypasses the incompatible canonical population projections; it does not
repair or fully explain their mismatch. Record that limitation in provenance.
Repository ownership means code/responsibility; real data remain private and
external. Relocated study code still constructs its existing patient-index cohort
from the canonical source. Adopting these encounter tables as its denominator or
changing its estimand is a subsequent analysis task.

## Remaining work, in order

1. [x] **Establish one Mini executor.** Read this checklist, private
   `LOCAL_PATHS.md`, repository instructions and current continuity notes.
   Use an OS-backed execution lock for the full Mini session and a shared build
   lock for every build/comparison, including monitor-driven runs. Repeated
   launch must fail without starting another process; locks release when their
   owning processes exit. Check for pre-existing unwrapped work once. Never
   delete a live lock file to bypass it. Keep the laptop monitor paused. Restore
   Mini GitHub authentication; fetch/inspect branches without reset/force-push.
   Preserve the older branch, dirty AGENTS.md and failed-run artifacts.

2. [x] **Implement and prove the compatibility adapter boundary.** Import all
   36 authenticated partitions with exact headers, explicit logical row order,
   duplicate multiplicity and accepted identifier/missing/date/numeric coercions.
   Use explicit types or preserved text followed by accepted coercions, not
   sampled CSV type inference. Compare each frame delivered to `clean_per_file()`
   against the accepted CSV loader, including leading zeros, numeric-looking
   strings, empty strings/sentinels, all-missing columns, dates, duplicates and
   floating boundary values. Hash identity alone does not establish interpretation
   parity. Preserve both independently supplied variants and raw source files.

3. [x] **Repair both the reader and enrichment key mapping.** In
   `encounters/builder.py`, `CompatibilityFrames` and `_enrich()` independently
   use canonical `preprocessed_encounter`. Changing only the reader is insufficient.
   Carry authoritative original patient/encounter keys from the authenticated
   snapshot through cleaning/merges into `source_keys`; never reconstruct them
   from the incompatible canonical projection or variant-specific encoded IDs.
   Prove composite-key integrity and compatible identifier namespaces/export
   history across the source pair; matching strings alone is insufficient.
   Keep one catalog/entrypoint, sources read-only and new private output staging.
   Record both source identities, schemas/configuration and producer hashes.

4. [x] **Close comparator false-pass paths before making it a release gate.**
   Downstream `scripts/compare_encounter_reference.py` currently intersects columns
   and can pass while a clinical reference field is missing. Replace that with a
   versioned, explicit retained/renamed/excluded field contract. Every retained
   field is required; every rename is mapped, including patient and encounter
   legacy identifiers. Every intentional analysis-field exclusion needs a reason.
   Reconcile the former 11 omitted demographic dummy aliases through explicit
   mappings where retained; do not blindly grandfather all 25 old omissions.
   Make accepted-reference identity-receipt verification mandatory, as well as
   reference immutability during comparison. Use semantic comparison modes:
   identifiers, counts, codes, flags and dates exact even if stored as floats;
   approved continuous fields/classes use `rtol=atol=1e-6`. Missingness remains
   exact. Regressions must fail for a missing required clinical column, wrong
   reference identity and a discrete-field mismatch; test explicit renames and
   documented exclusions. New enrichment fields have their own contract.

5. [x] **Pass the cheap legacy population/value gate for both variants first.**
   Build only the legacy base needed for exact keys, membership, categories,
   missingness and required field comparison under the repaired comparator.
   Preserve repeated encounters, independent timing and imputation behavior.
   Authenticate retained reference-key caches. The failed base is not an accepted
   population. Trace coercion/order/merges for any discrepancy before enrichment;
   population changes cannot be waived as numerical tolerance.

6. [x] **Pass a separate enrichment linkage and source-coverage gate.** Define
   the approved, versioned encounter-feature contract. Produce a per-variant
   report mapping every required element to its wide/evidence destination and
   availability state, including patient/encounter linkage and required history
   windows. Distinguish observed values, available domains with zero matching
   records, unavailable domains and incomplete capture. Zero records never prove
   no disease, no medication or no indication. Restored patients may fall outside
   cached projection scope: prove key/history coverage before reuse. If records
   exist in the canonical source, rematerialize missing scope; if that source
   lacks them, use explicit unavailable/incomplete states or narrowly justified
   recapture. Another query cannot recover absent source history. Undocumented
   gaps fail the contract; justified unavailability is an explicit contract state.

7. [x] **Make temporal, unit and row-order semantics explicit.** Preserve the
   legacy calendar-day anchor and existing inclusive-day/same-encounter rules.
   Dictionary entries must specify anchor precision, lookback, baseline versus
   context/follow-up, source dates, raw versus normalized values/units and
   unavailable states. Calendar-day values are not established admission-time or
   pre-blood-gas predictors. Decide and document either deterministic final output
   ordering or an explicit consumer-sort requirement; joined Parquet row order
   must not be silently treated as guaranteed. No byte-identical serialization
   requirement or unapproved temporal-rule changes.

8. [ ] **Run focused regressions, then one corrected integrated private build.**
   Confirm steps 2–7 before launching. Use the accepted numerical environment,
   sequential variants, existing memory cap, external spill and caffeinate.
   Measure peak whole-process memory, stage completion and scratch-space growth;
   the DuckDB cap is not a process-wide ceiling. Diagnose a demonstrated evidence
   expansion/OOM before changing limits. Reuse existing encounter/relocated-study
   fixtures, including negative-versus-missing and ineligible-study encounters.
   Record final producer code and source identities. Keep private logs/rows out
   of agent output. Repeat expensive work only for a concrete failure; do not
   blindly restart the failed run script or start broad renewed qualification.

9. [ ] **Validate all bundle artifacts and publish a small acceptance receipt.**
   Run the repaired reference comparator and separate enrichment/schema checks.
   Verify both variants' uniqueness, required features, evidence, inventories,
   dictionary, QA, manifest/hash completeness and source immutability. A manifest
   marked `complete` records build completion, not validation acceptance. Create
   one private acceptance receipt bound to the exact manifest hash, output hashes,
   source pair, reference identity, producer revisions, contract versions and gate
   results/limitations. Do not alter the validated bundle to add a circular hash.
   The historical date-grain proof does not validate the failed build/later fixes.

10. [ ] **Verify the installed pair and deliver coordinated changes.** Pin the
    final upstream revision in downstream pyproject/lockfile. Test the installed,
    pinned packages and consumer readback without `PYTHONPATH` or another local
    import override; record imported module locations and versions. Run affected
    relocated-study fixtures, final CI and relevant repository audits. Document
    the actual final command including its compatibility-companion argument
    (interface still to be implemented), not the old canonical-only command.
    Update PR descriptions with results/limits, keeping private receipts out of
    Git. Merge [upstream PR14](https://github.com/reblocke/trinetx-preprocessing/pull/14)
    first with a merge commit preserving pinned ancestry, then
    [downstream PR15](https://github.com/reblocke/trinetx-hypercapnia-code/pull/15)
    after its final checks. Commit/push/merge authorization already exists.

11. [ ] **Synchronize and close with an accurate scope statement.** Fast-forward
    safe checkouts, preserving older branches/uncommitted work. Record merged
    heads, accepted bundle and final command. If the laptop is offline, leave its
    concrete sync command instead of claiming synchronization. Close checkpoints
    and disable remaining monitors on completion. No drive locking/ejection.
    Report encounter data creation/enrichment, interfaces and bounded validation
    separately from unresolved study defects, clinical terminology validation,
    new indication/prevalence results and encounter-denominator adoption. Those
    analysis tasks are not completed by this ticket.

## Done means

One documented upstream command, using an authenticated legacy compatibility
snapshot and a provenance-validated canonical clinical source, creates both
independent encounter-level products and their required evidence, inventory,
dictionary and QA artifacts. The complete retained legacy field contract passes
reference comparison, with no unapproved missing fields or population differences.
All elements in the approved, versioned encounter-feature contract are represented
with observed values or explicit availability states. Enrichment linkage, source
coverage, temporal semantics and unavailable states pass separate checks.
Acceptance is bound to the exact source pair, producer code and output bundle.
The pinned downstream reader and relocated study fixtures pass at the final
coordinated revisions. Historical reference implementations remain unchanged,
private data remain outside Git, and known study-analysis defects remain explicitly
unresolved. Coordinated changes are merged and safe development copies synchronized
or their offline synchronization is explicitly pending.

## Mini implementation checkpoint (2026-09-20)

The authenticated one-time import and both independent legacy builds completed.
The repaired reader preserves exact text/order/duplicates with bounded allocation;
wide publication uses the existing enrichment SQL cap after releasing pandas.
FULL_DATA has 2,662,675 encounters; AFTER_EXCLUSION has 833,476. The complete retained-field
comparison passed both variants with zero membership/missingness differences
and no retained-value discrepancies under the declared rules. Canonical linkage
and corrected history coverage also passed, with all patients/encounters linked
and no demographic/anchor disagreements. Clinical enrichment was interrupted
by a host restart during FULL_DATA vital-source materialization. No enriched
variant completed. The accepted companion/base/coverage hashes survived the
restart; recovery is limited to a validated copy of committed source stages.
Atomic source checkpoints passed focused tests. Full-source vital-selection
equivalence passed with zero per-row differences; the optional query optimization
requires that exact source/catalog/query receipt. Recovery adoption passed and all FULL_DATA source tables completed. The
subsequent encounter-type context join exceeded the DuckDB cap. The repair
partitions its narrow inputs by patient while preserving the original first-row
rule. Private partition export completed, then AppleDouble sidecars caused a
Parquet input failure. Explicit data-file filtering is tested; the corrected
retry remains pending.
AppleDouble filesystem companions are kept outside the
analytical artifact inventory. Neither PR is ready to merge. Exact execution
handles, source identities and failed attempts remain in the private CHECKPOINT.md.
The laptop is not needed and no offline synchronization is claimed.

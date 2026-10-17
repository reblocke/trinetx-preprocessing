# Cross-machine source and consumer handoff

Checked 2026-10-17. Source synchronization, installed-interface qualification and
accepted clinical products have separate identities. Updating a checkout never
upgrades an existing product, receipt or qualified study runtime.

## Source checkpoint

The Air and Mini primary preprocessing checkouts match published `main` at
`787fba64319c0285244e2e17a9e303c739f31a14`. The additive mapper implementation at
`fba6d54b782dffe774a29b6ad94bb482cf46362f` is qualified on open
[PR28](https://github.com/reblocke/trinetx-preprocessing/pull/28).
Its review branch and isolated wheel are available on both machines; it is not
yet the default-branch delivery. Later documentation commits do not change those
qualified implementation bytes. See [current delivery status](CURRENT_STATE.md).

| Repository | Published default-branch checkpoint | Air / Mini source disposition |
| --- | --- | --- |
| [GLP-1 eligibility](https://github.com/reblocke/glp1-eligibility-hypercapnia) | `56fcae7b13a7a6df3a792cf908fec95fa2b64737` | Clean source mirrors synchronized; the Air remains the designated study writer |
| [Diagnostic equity](https://github.com/reblocke/hypercapnia-diagnostic-equity) | `0d38bedc262920880234640e2d17a844648ba72a` | Clean Air and Mini source mirrors synchronized; corrected clinical output qualification remains a separate gate |
| [Diagnostic model](https://github.com/reblocke/hypercapnia-diagnostic-model) | `4bc4ef232fe5e17e4ada605a39bed6ed5d9dd186` | Clean Air and Mini source mirrors match GitHub |
| [Bicarbonate screening](https://github.com/reblocke/bicarbonate-hypercapnia-screening) | `ddd4cb0675d847108ba63dd2ba564291107cc5d4` | Air published baseline retained with existing local edits; Mini preparation branch retained as a reference; published source separately checked |
| [BMI study](https://github.com/reblocke/obes-pop-attrib-fract-hypercap) | `2fdc05abba5728e6aa557b7e0f10896bb0f298f4` | Air source matches GitHub; dirty Mini preparation and qualified clinical references preserved |
| [Historical monolith](https://github.com/reblocke/trinetx-hypercapnia-code) | `d73c0559f480da16db0a5b46258a507ce4b75338` | Frozen Air oracle/encounter branches and modified Mini owner work preserved; these are intentionally distinct from the published default head |

Each child retains its own execution-host and activation authority. This source
check does not transfer writer ownership. Older commits, dirty files, ignored
outputs and qualified runtimes remain available with their original identities.

## Consumer pins and compatible routes

| Handoff | Existing authority | Effect of PR28 |
| --- | --- | --- |
| GLP-1 Python interfaces | Paired dependency declaration/lock at upstream `b74476459f7a061f76fff9f483bb5401a88bda38` | Installed child/interface E2E passes against the new wheel on both machines; active dependency and readiness flags remain unchanged |
| BMI source preparation | Preparation profile at `787fba6`; mapped profile at `72c91a21d4ff65aadca970cf60a168971a8c4a6e`, with exact reader hashes | The four shared-reader modules are byte-identical. The corrected mapper has a new hash, so the historical mapped profile correctly refuses it |
| Historical monolith readers | Paired dependency/lock at `9159e59ff7d9775b75644f14c8a30bd5ff4f91a6` | Historical return acceptance and runtime remain bound to that pin; no compatibility adoption is inferred |
| Bicarbonate, equity and diagnostic model | Explicit accepted input, migration/source inventory and fresh-output launcher contracts | No new upstream mapper dependency. Source-only launcher checks qualify path handling, not Stata, R, Quarto or clinical outputs |

For existing BMI products, use their original manifest/configuration and exact
qualified runtime. A new mapper adoption must update the child's reviewed source
revision and module hashes together, qualify the actual installed pair and retain
the historical reproduction route. Do not relax the hash gate or substitute the
new wheel into the old runtime. Changing a public example pin alone would break
old configuration/runtime checks. The upstream mapper does not choose study
indexes, gas definitions, population membership or clinical thresholds.

## Retained qualification

- The same upstream wheel passed all 28 mapper E2E cases on the Mini and Air,
  with noneditable installation and `PYTHONPATH` removed. Saved receipt, fixture,
  runner, result and product hashes were read back independently.
- The child at `56fcae7` passed its existing installed GLP-1 interface E2E on
  both hosts using that wheel and the retained synthetic encounter fixture.
  Original-key coverage, trust rejection, BMI rounding, policy and CLI checks
  passed with Python 3.11.10, DuckDB 1.5.5 and Arrow 25.0.1.
- Bicarbonate, equity and diagnostic-model migration E2Es check published source
  inventories, explicit paths, fresh output destinations and rejected unsafe
  handoffs. All 21 cases passed on each host (5, 11 and 5 respectively). They
  execute no clinical engine and use opaque path sentinels.
- Hosted CI and artifact readback for the mapper implementation passed at
  `fba6d54`; subsequent documentation delivery must also pass its final-head CI.

Commands, fixture/runtime identities, source snapshots, preservation inventories
and trusted artifact hashes are retained in the owner-only handoff. No private
data or clinical job was used. Historical private acceptance is not reissued.

## Synchronization and remaining delivery

1. Check current GitHub refs, local branch/status, ignored-path collisions and
   active work before advancing a checkout. Preserve a recovery ref and any local
   edits; fast-forward clean mirrors only. Do not reset or clean a study root.
2. Keep deployment isolated from existing qualified runtimes. For the mapper,
   use [installed-wheel qualification](TESTING.md#calendar-covariate-mapping)
   and its read-only receipt verification. For GLP-1 use the child's existing
   `scripts/verify_installed_interfaces_e2e.py` with the retained encounter fixture.
3. The Air's direct GitHub authentication failed during this check. Source refs
   were synchronized from Mini-fetched Git bundles after SHA-256 verification.
   This works without transferring credentials. Reauthenticate on the Air with
   `gh auth login -h github.com`, then verify `gh auth status` and a fetch before
   treating direct Air publication as operational.
4. PR28 remains open pending merge approval. After merge, verify actual merged
   implementation bytes against the qualified candidate before synchronizing
   `main`. A child adoption requires its own paired pin/lock or reviewed module
   profile update and installed-interface checks. Preserve existing data receipts
   and keep study readiness unchanged until its separately owned gates pass.

The [audit inventory](DOWNSTREAM_PREPROCESSING_AUDIT.md) explains which
transformations belong upstream. The [mapping contract](CALENDAR_COVARIATES.md)
and each child's current instructions govern use; this checkpoint is not an
instruction to rerun or requalify clinical analyses.

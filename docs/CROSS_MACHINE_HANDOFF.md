# Cross-machine source and consumer handoff

Checked 2026-10-17. Source synchronization, installed-interface qualification and
accepted clinical products have separate identities. Updating a checkout never
upgrades an existing product, receipt or qualified study runtime.

## Source checkpoint

The Air and Mini primary preprocessing sources contain the mapper implementation
published through [PR28](https://github.com/reblocke/trinetx-preprocessing/pull/28)
at `751d794e0a277f72ced2e2b5b48246858f4dcf9b`. Its merged tree matches qualified
PR head `327c6ac` exactly. The actual merged wheel was rebuilt and authenticated;
the installed runtime is separately available on both machines. Later
documentation commits may advance `main` without changing that immutable
implementation/pin authority. See [current delivery status](CURRENT_STATE.md).

| Repository | Published default-branch checkpoint | Air / Mini source disposition |
| --- | --- | --- |
| [GLP-1 eligibility](https://github.com/reblocke/glp1-eligibility-hypercapnia) | `56fcae7b13a7a6df3a792cf908fec95fa2b64737` | Clean source mirrors synchronized; the Air remains the designated study writer |
| [Diagnostic equity](https://github.com/reblocke/hypercapnia-diagnostic-equity) | `0d38bedc262920880234640e2d17a844648ba72a` | Clean Air and Mini source mirrors synchronized; corrected clinical output qualification remains a separate gate |
| [Diagnostic model](https://github.com/reblocke/hypercapnia-diagnostic-model) | `4bc4ef232fe5e17e4ada605a39bed6ed5d9dd186` | Clean Air and Mini source mirrors match GitHub |
| [Bicarbonate screening](https://github.com/reblocke/bicarbonate-hypercapnia-screening) | `ddd4cb0675d847108ba63dd2ba564291107cc5d4` | Air published baseline retained with existing local edits; Mini preparation branch retained as a reference; published source separately checked |
| [BMI study](https://github.com/reblocke/obes-pop-attrib-fract-hypercap) | `dd6b9277f69d75b343014c91c29f26ef6234cfd9` | Merged mapper pin from PR11; Air source and isolated Mini handoff source match. Dirty Mini preparation and qualified clinical references preserved |
| [Historical monolith](https://github.com/reblocke/trinetx-hypercapnia-code) | `d73c0559f480da16db0a5b46258a507ce4b75338` | Frozen Air oracle/encounter branches and modified Mini owner work preserved; these are intentionally distinct from the published default head |

Each child retains its own execution-host and activation authority. This source
check does not transfer writer ownership. Older commits, dirty files, ignored
outputs and qualified runtimes remain available with their original identities.

## Consumer pins and compatible routes

| Handoff | Existing authority | Effect of PR28 |
| --- | --- | --- |
| GLP-1 Python interfaces | Paired dependency declaration/lock at upstream `b74476459f7a061f76fff9f483bb5401a88bda38` | Installed child/interface E2E passes against the new wheel on both machines; active dependency and readiness flags remain unchanged |
| BMI source preparation | Preparation profile at `787fba6`; active mapped profile at merged `751d794e0a277f72ced2e2b5b48246858f4dcf9b`, with exact reader hashes | Child PR11 updates revision and mapper hash together. The four shared-reader modules are byte-identical. Historical `72c91a2` configurations retain their original child source/runtime |
| Historical monolith readers | Paired dependency/lock at `9159e59ff7d9775b75644f14c8a30bd5ff4f91a6` | Historical return acceptance and runtime remain bound to that pin; no compatibility adoption is inferred |
| Bicarbonate, equity and diagnostic model | Explicit accepted input, migration/source inventory and fresh-output launcher contracts | No new upstream mapper dependency. Source-only launcher checks qualify path handling, not Stata, R, Quarto or clinical outputs |

The owner approved the BMI pin adoption. Its active mapper SHA-256 is
`0e1036b94cce9f7e753c57f5c860997df41adc313ba440c7b13c4897bab5844e`.
The strict child gate accepts that reviewed revision/hash pair and rejects mixed
old/new pairs. For existing BMI products, use their original configuration,
qualified runtime and preserved child source at `2fdc05a` or its recorded clinical
release checkout. Do not replace that runtime in place. Future mapping uses the
new isolated runtime and a separately reviewed source configuration; no private
configuration or product was migrated by this delivery. The upstream mapper does
not choose study indexes, gas definitions, population membership or thresholds.

## Retained qualification

- The actual merged upstream wheel passed all 28 mapper E2E cases on Mini and Air,
  with noneditable installation and `PYTHONPATH` removed. Saved receipt, fixture,
  runner, result and product hashes were read back independently.
- The child at `56fcae7` passed its existing installed GLP-1 interface E2E on
  both hosts using the qualified implementation and retained encounter fixture.
  Original-key coverage, trust rejection, BMI rounding, policy and CLI checks
  passed with Python 3.11.10, DuckDB 1.5.5 and Arrow 25.0.1. The delivered merged
  wheel's package payload is byte-identical to that tested implementation.
- The BMI child's actual pin gate passed on both hosts; unreviewed revisions,
  forged hashes and crossed historical/current pins were rejected. All 16
  existing preparation checks passed with the qualified Mini R library active.
- Bicarbonate, equity and diagnostic-model migration E2Es check published source
  inventories, explicit paths, fresh output destinations and rejected unsafe
  handoffs. All 21 cases passed on each host (5, 11 and 5 respectively). They
  execute no clinical engine and use opaque path sentinels.
- Final-head PR28 CI at `327c6ac` passed (594 tests passed, 7 skipped), with both
  uploaded artifact sets independently verified. Subsequent documentation
  delivery must also pass its final-head CI. The BMI child has no hosted checks
  configured; its retained installed-pair checks are recorded separately.

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
3. The Air's direct GitHub authentication failed at the initial checkpoint. Source refs
   were synchronized from Mini-fetched Git bundles after SHA-256 verification.
   This works without transferring credentials. Reauthenticate on the Air with
   `gh auth login -h github.com`, then verify `gh auth status`, Git credential
   configuration and a fetch before treating direct publication as operational.
   Device confirmation requires the owner's signed-in browser. Current
   authentication status is retained in the private operational handoff.
4. PR28 and BMI child PR11 are merged under direct owner approval. Their actual
   merged trees match the tested candidates; the new isolated installed pair is
   qualified. Later pin changes require another exact paired update and affected
   installed checks. Preserve existing data receipts and keep scientific/release
   review states at their separately recorded scopes.

The [audit inventory](DOWNSTREAM_PREPROCESSING_AUDIT.md) explains which
transformations belong upstream. The [mapping contract](CALENDAR_COVARIATES.md)
and each child's current instructions govern use; this checkpoint is not an
instruction to rerun or requalify clinical analyses.

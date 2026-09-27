# Continuity

## Goal (incl. success criteria)
Complete C0–C4 of Goal Readmissions.md under the owner-approved calendar-day
v2 contract while preserving the established encounter and cohort-source behavior.

## Constraints/Assumptions
Preserve FULL_DATA and AFTER_EXCLUSION membership, timing, repeated encounters,
and measurement imputation. Keep v1 as the default and all private outputs
external. Do not rebuild the accepted parent or canonical source. Require exact
parent validation, a resource pilot, one locked outcomes-only build, independent
validation and unchanged input bytes before C4 acceptance.

## Key decisions
Reuse accepted transformations; reconcile incompatible source projections before
another private build. Owner approved the one-time authenticated companion import
and targeted audit gates on 2026-09-20. See NEXT_STEPS.md. Publish two
encounter-grain Parquet products with evidence, dictionary, manifest and QA.
Move study analysis without claiming its known scientific defects are repaired.
For returns, the owner accepted D1–D6 calendar-day decisions on 2026-09-25;
the versioned rules are in docs/RETURN_CONTRACT.md. A source-catalog row does
not establish clinical eligibility, and observed follow-up is not complete
capture. Preserve unsupported timing and phenotypes as unknown.

## State
The approved encounter implementation is merged upstream at `4bbe8cfee3dad3b7c07fb8c42d7217804150b650` and downstream at `d5d269168eafc7905c9238a5486fc03a62b55ec3`. Both required hosted CI checks passed. The active readmissions work is isolated on `codex/readmissions-20260924`; the v2 builder memory repair is committed at `cc6d4cc`. The original checkout's unrelated changes remain untouched.

## Done
Implementation, 10 focused encounter checks, relocated GLP-1 fixtures, bounded
review, lint/format and layout checks complete. All 92 extracted legacy
function/class ASTs match their accepted originals. Reference port untouched.

## Now
2026-09-27 readmissions checkpoint (supersedes the historical notes below):
The locked C4 r3 run on LOCKE STATION completed both variants and all 64
partitions, but a new E2E revealed a scientific uncertainty defect while its
independent validator ran. A same-ID ED/inpatient return with one missing
component start and another known start on day 366 was incorrectly marked as
negative for 30/90/365-day all-cause horizons; the approved contract requires
unknown because the missing start could be in any of those windows. The
validator mirrored the builder formula, so its eventual pass could not close
this gap. The r3 worker was terminated before a validation report or seal; both
processes exited, the shared lock has no open holder, and all external output
and scratch files remain preserved. The scientific-gate failure receipt SHA-256
is `010966fc8aef1ed1a3487737ed47da6c599701b9153959b24f699d3250fa501a`;
the terminal rejection receipt SHA-256 is
`9b19ac4d294137592459db92d494d661adc01249ea99f9bf03f7fa48d3f177d5`.
The expanded hand-authored E2E failed on the frozen r3 code before the repair.
The repair carries source missing-start provenance into return links and uses
the earliest observed component start as an upper bound. Six independent
partial-start cases, forged provenance rejection, and one-versus-three
partition equivalence pass in the readback-verified E2E receipt SHA-256
`d28bfe6d0c8afdd93b85946a60e8326207dcc305a842275f19531bf4bd03366c`.
The contract is clarified without changing its approved meaning. Repaired code
identity is `de9d4268bb64ffa47411f019d42c7e3f1abd76a8935bd96d285d7081ba752d88`.
Full pytest passed 464 cases (238 existing warnings); Ruff check/format,
offline lock, five legacy E2Es with readback, noneditable wheel and installed
old-consumer API/CLI smoke passed. The synthetic wrapper E2E also passed with
readback-verified receipt SHA-256
`dc9c7af94c2647bc1591f3b415f9a82ac1f68439955d7ac3a6e5d2cdd7271126`.
Prior exact-parent, resource-pilot and C4 receipts bind the former code
identity and must be refreshed. Do not reuse or seal r3.
Next: freeze a reviewable commit, repeat exact parent and Station pilot,
then run a fresh locked full C4 build,
independent validation, byte comparison and seal.

Historical 2026-09-26 readmissions checkpoint:
The words "current" and "next" in the retained older notes below refer to
their dated snapshots; the 2026-09-27 checkpoint above controls active work.
C0–C2 and the public C3 proof are complete on code identity
`c16ef758b1d5506343d4de0d1a20b19b4ed704f93556de4fd1e710710dade2cf`.
The current-code r6 exact validation of the accepted parent passed both
variants; its external receipt SHA-256 is
`c075bcfe2fc7b595723e5ba0c4d12219e50643c8ff5be10aeac7c7bf6a2098b0`.
The 32-partition pilot passed. The first C4 build on LOCKE BOOK stopped on
ExFAT AppleDouble scratch files and was preserved without acceptance. The
diagnosed retry on RESEARCH FAST APFS passed its launch gates and wrote at
least 25 FULL_DATA partitions. During a later partition write, the SSD returned
an I/O error and the volume disappeared. The runner exited; no C4 seal or
post-build input-byte/independent-return validation exists. The last verified
checkpoint was 25 partitions at 2026-09-26 12:27:21 UTC; the count at failure
is UNCONFIRMED until the same volume is accessible. The external volume-loss
observation receipt SHA-256 is
`61e7e1f2f817a98f126bbd5b27ec7626eb3f38065aa21c7769e0f7ab9feefbf5`.
At this handoff, macOS sees the OWC Express 1M2 enclosure and T-FORCE SSD in
the hardware tree, but the NVMe controller reports a write-command timeout
and exposes no disk or mount. A separate APFS volume, LOCKE STATION, passed
read-only filesystem verification and a 4 GiB write/fsync/readback probe. A
fresh location-specific, locked 32-partition pilot passed both variants:
82,928 FULL_DATA and 25,969 AFTER_EXCLUSION bucket keys, all 12 artifact hashes,
5,400,756,224-byte peak RSS, and more than 100 GiB free. Its receipt SHA-256
is `4897d6574f93aa704c3d7133d8205357e4ca752de156ee9795bf2a751f4f73df`.
The inaccessible RESEARCH FAST attempt remains preserved
and unaccepted. The Station probe receipt SHA-256 is
`225b05d2dee1dbbd7e211060246c0bcc2f68763a6ace4cf7d7ad7171e4f50a99`;
the provisional location decision SHA-256 is
`72237685750936cf907f0fb79725d0930de1dfdb867e8b2ed8864564b0329e72`.
No full C4 replacement build has started.

2026-09-25 resumed readmissions checkpoint: C0 historical parent receipt and
source/parent identities were reverified; C1 calendar-day v2 D1–D6 contract is
frozen. Opt-in v2 build/validator code is implemented with v1 as the default.
The current code identity is
`c16ef758b1d5506343d4de0d1a20b19b4ed704f93556de4fd1e710710dade2cf`.
All 464 tests pass; Ruff, offline lock, noneditable wheel, installed old
consumer, five legacy E2Es, v2 partition E2E and synthetic wrapper checks
pass on this code. The wrapper explicitly stubs upstream parent/source
validation. The corrected calendar-day precision and NULL/zero/positive
element-count proof passed the full accepted parent at r4 on the preceding
code hash `e74ef7d`; a new r5 code-bound validation is now running. The first
v2 resource pilot failed at its 1 GiB builder cap during the FULL_DATA summary
write; its partial files and receipt are preserved. V2 now uses 4 GiB for key
and partition building; v1 remains 1 GiB. A fresh 32-partition pilot passed
both variants on the current code: 82,928 FULL_DATA and 25,969
AFTER_EXCLUSION bucket keys, twelve verified files, independent partition
validation, matching input identities, 4,773,183,488-byte peak process RSS,
and more than 100 GiB free. Its receipt SHA-256 is
`e4fcbdd15956c920767bb76b11ad19f52f70e2ce53f4ed6e5788421cc6e6e4ad`.
An attempted pilot on LOCKE STATION could not start because the volume stopped
responding before the shared lock; its diagnostic is external. The passing
pilot and planned C4 output use safe external roots on LOCKE BOOK. Full C4
build, independent full return validation, immutable-byte comparison and seal
remain pending. Preserve failed scratch/receipts and do not mark the goal DONE
from public or partition checks.

The owner provisionally accepted all D1–D6 recommendations and repair strategies
on 2026-09-25, then requested parallel removal of low-signal tests, E2E-first
guidance and updated starter ZIPs before goal relaunch. The three test reviews
account for every original test function; redundant checks are removed and
useful assertions moved into broader workflows. See docs/testing_review.md.
AGENTS.md contains the requested rules. A new E2E runner retains synthetic
products, source/fixture identity, results and hashes outside the repository.
All 464 remaining cases passed (238 existing warnings, 669.06 seconds); the
five selected E2Es also passed with retained outputs and a verified manifest.
Artifact checks rejected changed files, extra files, a wrong manifest hash and
an existing destination; an injected workflow failure retained a failed receipt.
The full 434-function inventory reconciles exactly (58 removed, 376 retained).
Ruff, formatting, lockfile and diff checks passed. The original checkout's unrelated changes
are preserved; only its AGENTS.md receives the same testing policy. Four starter
archives and their two expanded templates in locke_cv receive consistent guidance,
with original archives preserved externally. Starter verification passed after
fast-forwarding to the already merged `67456a6` readiness implementation:
maintained exports rebuild exactly, four packager checks pass, and all runtime
and configuration files match that base. No production source or private
product is changed. The owner explicitly resumed the readmissions goal on 2026-09-25. C4 remains gated by repaired code, private proof and resource checks.

2026-09-25 audit update (supersedes return completion claims below): the user
requested an explanation, code audit and proposed day-resolution course. The
immediate precision failure is an inherited producer/validator schema mismatch;
v1 already allows day-only returns. Eight targeted synthetic probes reproduced
that mismatch, NULL precision fall-through, false flags for rejected gases,
undetected omitted links and inconsistent gas conversion, real parent scratch
reuse failure, omitted uncertainty summaries and an applicability inconsistency.
See docs/RETURN_AUDIT.md and the draft docs/RETURN_DAY_RESOLUTION_PROPOSAL.md.
C2/C3 repairs and proof remain active; C4 still has unpassed gates. The original 522-test pass remains
historical evidence, not proof that all acceptance requirements were met.
This audit changes documentation only; its synthetic script/results and private
receipt references remain external. The original checkout and accepted inputs
were not changed. The historical parent acceptance receipt was located in the documented external handoff. Its exact SHA-256 and named gate hashes match the later integrated acceptance record; current product validation remains a separate gate.

The opt-in return-outcome contract and separate build/validation commands are
implemented locally in isolated worktree `codex/readmissions-20260924`.
C0 copied the uncommitted encounter hardening baseline without changing the
original checkout; its 109 encounter tests passed. The accepted parent manifest
and canonical source sidecar hashes agree. A locked aggregate profile found
date-only encounter starts/ends, missing/conflicting index episode ends, and
shared ED/inpatient source IDs. A source-catalog preflight found that the
accepted catalog lacked ICD-10-CM-specific exact rules for four J96 codes.
A follow-up aggregate query found rows for all five exact codes in the canonical
diagnosis table; the four J96 codes have exact wildcard code-system rules that
capture ICD-10-CM rows. The source-capability check was corrected and now
passes. No private row-level return product has been published.
The locked C1 forward-coverage profile has now completed for both variants.
It reconciles to 2,662,675 FULL_DATA and 833,476 AFTER_EXCLUSION original
keys, records unavailable index anchors separately, and shows that last
observed events often precede the 365-day horizon. The aggregate receipt is
external; it does not establish continuous follow-up or complete capture.
The canonical database's full byte SHA-256 baseline was recorded externally
before any outcomes pilot or build, with unchanged source/parent manifest
identities. On the preceding return code at `e21c6ed`, sixteen focused tests
and the full suite passed 520 tests with 238 existing performance warnings.
Ruff check and format, `uv lock --check --offline`, `git diff --check`, and
non-editable wheel installation all passed. The installed wheel's code identity
matches the checkout; the new return commands and old cohort-source consumer
smokes passed without `PYTHONPATH`. Earlier full runs on changing code and an
intermittent compatibility-export worker failure remain historical evidence;
the frozen pass supersedes them. These checks do not satisfy the unfinished
resource pilot or C4 acceptance seal. The return validator now independently
recomputes episode/source mapping, link times and categories, link flags from
diagnosis/gas evidence, and summaries; synthetic tampering checks include an
uncertain link omitted from summaries.
An initial pilot launcher was stopped before pilot output because an external
helper named `profile.py` shadowed Python's standard module and started an
unintended read-only aggregate query. Its evidence was preserved externally.
The corrected 32-partition resource pilot completed one entire patient bucket
in each variant. Its external receipt passed source/parent identity,
summary-key, artifact-hash, and free-space checks. The first full outcomes-only
build stopped during required parent-bundle validation, before any return
partition, with DuckDB out of memory at the validator's fixed 1 GiB limit.
Its external receipt, log, and work are preserved. The encounter validator
now accepts an optional memory cap while keeping its old 1 GiB default;
opt-in return validation requests 4 GiB. No retry or acceptance is claimed. Independent
return validation, post-build source byte comparison, and the external
acceptance seal remain pending.
The final bounded-validator code passed 71 affected tests and 522 full-suite
tests with 238 existing performance warnings. Ruff check and format, offline
lock check, non-editable wheel installation, and isolated old/new consumer
smokes also passed; an external C3 receipt binds those checks to code identity
`63ecb329b10d902acfa925e2bfdb28aa65eb6f2df1f2b4f09316a41924b66b17`.
A separate 4 GiB parent preflight also failed at the same exact distinct
aggregation. The opt-in validator now writes two complete, hash-partitioned
scratch projections and sums exact per-partition distinct counts; default
encounter validation remains unchanged. Seventy-one affected tests pass.
The locked full-scale bounded preflight passed that memory stage, then found
the accepted schema 2.0 parent bundle lacks `event_datetime_precision` in
diagnosis, procedure, and medication evidence for both variants. All other
required columns were present in the schema audit. The producer retains raw
`date` and `event_datetime` in those tables but does not emit the required
precision field. No full return product or seal exists. At that historical
checkpoint, the missing validation rule blocked progress. The owner has since
accepted the versioned compatibility approach and explicitly resumed the goal;
the new proof must pass without waiving validation or rebuilding the accepted
parent under this ticket.
A separate external aggregate audit found all six producer-defined raw date
fields parse as date-only values, with no raw-versus-event calendar-date
mismatch or parsed time of day. This supports review of a versioned
compatibility proof but does not satisfy the missing schema field.

This ticket adds versioned per-table Parquet evidence contracts, independent
feature-missingness and source-coverage reconciliations, explicit strict versus
permitted-incomplete linkage policy, manifest-bound validation reports and
receipt verification helpers, and deterministic duplicate-preserving content
fingerprints for reusable stage tables. The follow-up fixes let the validator
read older policy-free bundles without modifying them, recompute linkage and
baseline eligibility from Parquet, and reject incomplete report/receipt
identities. The full encounter suite passed 109 tests; the focused validation
and coverage suite passed 62 tests. Ruff, `git diff --check`, and affected
local Markdown link checks passed. Verification used the pinned uv environment
with an external temporary cache and `uv run --offline --no-sync`. No
encounter membership, retained value, timing rule, or evidence content changed.
The earlier 24-test run with pytest scratch on RESEARCH FAST and 33-test focused
rerun remain historical evidence for the preceding hardening pass; its task-owned
scratch was removed. RESEARCH FAST is not currently mounted.

The historical handoff reports that all pre-enrichment gates passed. Both legacy variants match authenticated
references across the complete 33/534-field contracts, with zero membership and
missingness differences. Canonical patient/composite-encounter linkage covers
every encounter, with zero demographic or anchor-day disagreements. Corrected
coverage recognizes both medication export families and distinguishes observed
spans from incomplete capture; observed spans do not prove continuous history.
The corrected private build completed both independent variants: FULL_DATA
2,662,675 and AFTER_EXCLUSION 833,476 encounter rows. It used a provenance-bound
recovery cache after earlier memory and file-proliferation failures; all failed
attempts and their artifacts remain preserved. Source/element joins, availability
and the wide output use bounded partitions without changing output semantics.
The full retained-reference comparison passed exact membership and all 33/534
field checks; the separate validator passed all bundle artifacts, schema, source
coverage, inventories and manifest hashes. Peak whole-process RSS was measured
at 7,404,158,976 bytes. The prior continuity note reports a private acceptance
receipt and exact installed-pair evidence, but the receipt was not found in a
bounded search of currently accessible external volumes; its identity and
current gate state remain UNCONFIRMED here. No new private data scan or build
was run. Upstream PR14 and downstream PR15 are now verified merged with passing
required CI, correcting the old active instructions below.
Parquet row order is unspecified; consumers explicitly sort by original keys.
Preserve all failed/superseded artifacts, older branches and dirty instructions.

## Next
For return outcomes, use the verified LOCKE STATION pilot as a resource gate.
If the volume remains healthy, a fresh, separate C4 attempt may use that APFS
volume after exact
source/parent/code/contract gate checks; preserve the RESEARCH FAST partial run
without treating it as reusable or accepted. If RESEARCH FAST later returns,
verify its identity and filesystem health and audit its checkpoint read-only
before any resume. C4 still requires a complete locked outcomes build,
independent full return validation, pre/post source and parent byte comparison,
and an external acceptance seal. Cross-ID continuations remain unconfirmed
because the flow table has no transfer or discharge authority.

In the Mini private handoff, use the existing shared lock to
revalidate the immutable accepted bundle, run downstream comparator and installed
consumer readback, and verify the trusted receipt against exact manifest/report
identities. Do not rebuild unless a concrete data-affecting discrepancy requires
it. See [docs/ENCOUNTER_RELEASE.md](docs/ENCOUNTER_RELEASE.md).

## Open questions
Canonical source validated: 837 catalog elements including 303 source concepts.
Canonical compatibility capture uses corrected_v1 and earliest_per_setting;
its encounter population differs from the retained accepted reference.
The source/input boundary needs reconciliation; no scientific acceptance claimed.

## Working set
Encounter builder and relocated GLP-1 modules; focused pytest, Ruff,
source/output comparison and normal repository checks.

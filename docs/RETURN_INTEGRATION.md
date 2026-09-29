# Readmissions integration handoff — 2026-09-29

## Scope and status

Local public integration gates passed. The target is a draft PR; hosted CI,
review, private acceptance of this package identity, downstream work and merging
are separate gates. The session has a hard one-hour limit and starts no recurring
monitor or unattended continuation.

| Identity | Revision |
| --- | --- |
| Fresh upstream main used for integration | `c81650b47f120f7eb35a9d0b63ece2617ba9b886` |
| Accepted readmissions review | `82d3bd5c796cdeb1afb999700b1a84fe1e08f8a7` |
| Frozen source tested locally | `99b2a3a83f4d8c9c5006a182cdb5082a8ceb2c47` |
| Integrated package identity | `ae5f2428d3155868711c9d42cae72fa5c4178074a7b3c0a24654bafd4cb4b33b` |

The integration commit has both recorded branches as parents. The final review
head adds documentation only; no executable source, tests, fixtures, dependency
pins or schemas changed after verification. The external composed receipt binds
both the tested commit and final review head.

## Conflict-resolution record

The 13 conflicts were resolved with current main as the encounter-interface
authority. Its builder, checkpoint cache, CLI, coverage implementation, default
validator and shared receipt verifier remain byte-identical to the upstream
base. The 19 tests added upstream since the common base remain AST-identical and
were exercised by the full suite.

The accepted return-parent validator is isolated in
`encounters/return_parent_validation.py`. Its implementation is AST-identical
to the accepted branch after excluding module documentation. Only return callers
use this interface. Its older parent-proof receipt is not substituted for the
shared production encounter acceptance API.

Return definitions and schemas are unchanged. Calendar-day v2 remains explicit
through `--contract-version 2.0`, with the existing v1 default preserved. The
reviewed test cleanup is retained; distinct typed/reordered-cache,
empty-population, policy-misuse and return-parent cases remain covered. See
[testing_review.md](testing_review.md).

## Passed local verification

Checks ran on the frozen source with locked dependencies, Python 3.12.11 and
DuckDB 1.5.4. Source inventories before and after each check matched.

| Gate | Result |
| --- | --- |
| Complete pytest suite | 492 passed; 238 existing pandas fragmentation warnings; 709.83 seconds |
| Ruff lint and formatting | Passed across the repository |
| Lockfile and diff checks | Passed; dependency pins unchanged |
| Retained legacy E2E runner | Five workflows passed; saved artifact inventory read back successfully |
| Retained return v2 E2E runner | Passed hand-authored day/window uncertainty, transfer linkage, independent reconciliation, tampering rejection and one/three-partition equivalence; artifact readback passed |
| Noneditable wheel | Built and installed into a separate environment with locked dependencies |
| Existing consumer smoke | Without PYTHONPATH: cohort API/CLI validation, read-only rejection, and the existing downstream encounter reader passed on synthetic artifacts |
| Existing downstream reader | Both variants retained original repeated composite keys and rejected an incorrect trusted receipt digest |
| Original runtime preservation | Its installed package still has the original sealed code identity |

The existing downstream reader was taken from `master` at
`4a57843990f13c7755eacb325011f4b19a46c2b4`. This is an installed synthetic consumer
smoke, not private installed-pair acceptance or a downstream return reader.

Commands retained with external logs, exit statuses, environment/source
identities, JUnit and hashed artifacts include:

```sh
uv run --offline pytest -q --junitxml="$EVIDENCE/full-suite.xml"
uv run --offline ruff check .
uv run --offline ruff format --check .
uv lock --check --offline
git diff --check
uv run --offline python scripts/verify_e2e.py --output-dir "$EVIDENCE/legacy-e2e"
uv run --offline python scripts/verify_e2e.py --verify "$EVIDENCE/legacy-e2e" \
  --manifest-sha256 "$LEGACY_MANIFEST_SHA256"
uv run --offline python scripts/verify_return_v2_partition_e2e.py "$EVIDENCE/return-e2e"
uv run --offline python scripts/verify_return_v2_partition_e2e.py \
  "$EVIDENCE/return-e2e" --verify
uv build --wheel --offline --out-dir "$EVIDENCE/wheel"
env -u PYTHONPATH "$EVIDENCE/installed/bin/python" -I "$EVIDENCE/installed_smoke.py"
```

Use fresh external directories when repeating the runners. Their manifests
retain the exact original commands and output hashes. Public artifacts remain
outside Git; no private data, operational paths or private receipts are included
in this handoff.

A preliminary affected-test invocation reached its four-minute time limit; the
complete passing suite supersedes that incomplete check. The first installed
smoke wrapper incorrectly assumed the header-only example encounter fixture was
nonempty. The corrected wrapper asserts its exact expected empty content and
passed the remaining consumer checks. Both attempts and the original wrapper
are retained; production code and fixture expectations were unchanged.

## Work after reorganization

1. Finish draft review and required hosted CI. Establish fresh private
   acceptance for the integrated identity: exact parent validation, resource
   pilot, one locked outcomes-only build, independent validation, unchanged-input
   checks and an external seal. Preserve the existing accepted bundle and frozen
   runtime throughout.
2. From current downstream master, add a read-only return-summary interface
   requiring an explicit bundle, variant, trusted acceptance digest and validation
   report. Validate provenance, schema, artifact hashes and original composite
   keys; reject failures without fallback.
3. Run an installed upstream/downstream return E2E with retained artifacts for
   joins, missingness, incorrect receipts, altered files and unsupported
   contracts. Produce an aggregate outcome-quality report across existing windows
   and phenotypes. Preserve alternatives without selecting a study endpoint or
   changing its population.
4. After the upstream gates pass, merge through review and then update the
   downstream immutable dependency pin and complete its checks. Record the actual
   accepted revisions in release and continuity documents.

The original [C0–C4 acceptance](RETURN_ACCEPTANCE.md) remains valid only for its
recorded producer and artifacts. Public integration checks do not transfer that
acceptance to this package identity.

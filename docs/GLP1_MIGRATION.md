# GLP-1 Migration and Compatibility

The migration boundary is one shared preprocessing and cohort workflow. GLP-1
source elements are a permanent expansion of the same catalog used for typed
traditional elements; they do not define a separate product or package. See
`CURRENT_STATE.md` for the exact delivered/pending status.

Do not feed lossy legacy group tables into GLP-1 logic. The tested adapter reads
typed source tables from `trinetx_preprocessed.duckdb` and reproduces the
current downstream GLP-1 source contract on synthetic fixtures without
rescanning raw clinical CSVs. Element membership is source candidacy, not a
GLP-1 phenotype or cohort decision.

The standalone `python -m trinetx_preprocessing.glp1_eligibility` command is
retained as a computational reference during migration. Its `--database` mode
validates the canonical source contract and consumes the shared domain tables
and source-audit evidence without opening raw CSVs. Its explicit `--input` mode
is retained only for private parity and historical reproduction.
`combined_preprocessing/glp1_adapter.py` is likewise a temporary parity bridge.
Neither defines a second canonical preprocessing output, and neither should
remain as a permanent parallel workflow after full-data parity.

Full-data raw-versus-database equivalence passed at behavior head `9fe392b`, as recorded in
`GLP1_SOURCE_ACCEPTANCE.md`. Database-backed processing is the documented
production route; explicit raw-reference mode remains for reproduction.
Cohort import is additionally paused until the downstream cohort repository's
refactor publishes a stable behavior head.

For subsequent updates, use `verify-update` as described in
`UPDATE_VERIFICATION.md`. The database-backed build
validates the unified database, its manifest-bound catalog, the required
included GLP-1 concepts, and canonical source-audit evidence; then compare the
adapter-backed GLP-1 derivation with the frozen standalone result using
`compare-reference-outputs`. It checks schemas and exact rows across source,
observability, cohort, evidence, and source-QA tables; verifies byte-identical
data dictionaries and aggregate QA reports; and checks public-output inventory
and manifests, excluding only declared operational run fields; deterministic index-event
identifiers are compared exactly. This is
the evidence needed to retire the GLP-1 raw-data path after exact-head private
full-data parity. Real row-level outputs and validation extracts must remain
external and untracked.

The exhaustive 36-file compatibility certification and all-source
retained-record membership audit remain valuable upstream preprocessing release
evidence. They do not answer whether GLP-1 scientific inputs, cohort flow, or
outputs changed, so they are deliberately separate from this migration gate.

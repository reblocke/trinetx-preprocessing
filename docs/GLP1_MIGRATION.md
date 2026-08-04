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
retained as the computational reference during migration.
`combined_preprocessing/glp1_adapter.py` is likewise a temporary parity bridge.
Neither defines a second canonical preprocessing output, and neither should
remain as a permanent parallel workflow after full-data parity.

The expanded source/API contract and synthetic adapter gate are accepted. A new
private full-data source-completeness and adapter-versus-standalone run has not
been completed at this exact head, so raw ingestion remains the reference.
Cohort import is additionally paused until the downstream cohort repository's
refactor publishes a stable behavior head.

At restart, validate the unified database, required catalog elements, exact
36-file compatibility evidence, and additive element completeness; then compare
the adapter-backed GLP-1 derivation with the frozen standalone result. Retire a
raw-data path only after exact-head private full-data parity. Real row-level
outputs and validation extracts must remain external and untracked.

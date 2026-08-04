# GLP-1 Migration and Compatibility

The migration boundary is now one shared preprocessing product. Historical
notebooks remain references, Milestone 2 remains the corrected 36-file
fallback, and `trinetx_preprocessed.duckdb` contains both the historical
payload and source-faithful elements required by the GLP-1 derivation.

Do not feed lossy legacy group tables into GLP-1 logic. The tested adapter reads
typed source tables from the canonical database and reproduces the current
downstream GLP-1 source contract without rescanning raw clinical CSVs.

The standalone `python -m trinetx_preprocessing.glp1_eligibility` command is
retained as the validated derivation/reference during migration. It does not
define a second canonical preprocessing output. Stata replication and later
semantic improvements remain separate future branch/PR work.

For migration, first validate the unified database, exact 36-file compatibility
evidence, and additive element completeness. Then compare the adapter-backed
GLP-1 derivation with the preserved standalone result. Real row-level outputs
and validation extracts must remain external and untracked.

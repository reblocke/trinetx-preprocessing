# GLP-1 Migration and Compatibility

The GLP-1 eligibility endpoint is additive. Historical notebooks remain
references for the original hypercapnia preprocessing, and Milestone 2 remains
the fallback for its corrected 36-file output contract.

Use the GLP-1 module when the analytic target is the issue #6 eligibility
database. It reads the original TriNetX export independently, preserves source
provenance, and writes to a separate output root. Do not feed legacy normalized
group tables into this build: they omit source fields and timing detail needed
for auditable component phenotypes.

Existing automation can continue invoking `python -m trinetx_preprocessing`.
The additive endpoint uses
`python -m trinetx_preprocessing.glp1_eligibility`; no existing CLI arguments,
configuration files, work manifests, or final CSV names are changed.

For migration, validate the export and concept contract, run the build into a
new private directory, inspect aggregate QA and summary outputs, and compare
only approved aggregate counts. Real row-level outputs and validation extracts
must remain external and untracked.

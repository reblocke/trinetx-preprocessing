# Glossary

- **TriNetX**: A platform providing de-identified or limited datasets from electronic health records.
- **Encounter**: A visit or care episode (definition depends on the export).
- **RFS**: Reasons for suspicion (domain-specific criteria used to define cohorts).
- **ABG**: Arterial blood gas.
- **VBG**: Venous blood gas.
- **PHI**: Protected health information.
- **Canonical preprocessing product**: The versioned
  `trinetx_preprocessed.duckdb`; the 36 CSVs are compatibility projections.
- **Cohort-source contract**: The manifest-bound, read-only DuckDB tables and
  fingerprints exposed to downstream cohort builders.
- **Element rule**: A versioned source-code matching rule.
- **Element membership**: A source record's match to an element rule. It means
  source candidacy, not phenotype or cohort inclusion.
- **Catalog pin**: The expected merged cohort-source SHA-256 supplied by a
  Python consumer to reject an incompatible source product.
- **GLP-1 adapter**: The temporary migration bridge that presents canonical
  source tables to the preserved standalone GLP-1 derivation for parity tests.
- **Compatibility bridge**: The 36 historical CSV exports consumed by the
  preserved Stata workflow while cohort logic migrates.
- **Full-data parity gate**: A private, exact-head comparison against the
  preserved raw-ingestion or Stata reference; synthetic parity does not replace
  this gate.

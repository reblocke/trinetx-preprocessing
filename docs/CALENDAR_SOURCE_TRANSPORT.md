# Exact-key calendar source transport

`combined_preprocessing.cohort_source_calendar_transport.iter_calendar_source_records()`
is an additive raw interface for an accepted, read-only canonical source session.
It takes a caller-supplied relation of unique original VARCHAR patient/encounter
keys, a domain, and an explicit finite union of catalogue IDs and/or exact
normalized code-system/code pairs. Repeated patients are supported. Fully consume
or close the iterator before reusing the connection. Query failure raises
`SourceTransportError` with state `query_failed_or_incomplete`; partial iterator
consumption establishes neither completion nor absence.

Each raw matched row retains all captured columns, including source record/file,
raw dates, event precision, raw numeric/text values, raw units, specimen/panel
fields where captured, and code-system/code. Catalogue unions report distinct
matched IDs without multiplying raw rows. Explicit code selectors expose captured
records without modifying the manifest/catalogue. PaCO2 LOINC 2019-8, pH 2744-1
and adjusted PaCO2 32771-8 remain distinct. BMI 39156-5, weight 29463-7, height
8302-2, HbA1c 4548-4/17856-6 and creatinine 2160-0 can use exact LOINC selectors.
The interface performs no unit conversion or phenotype/index selection.

States distinguish `zero_matches`, `matched`, `matched_unusable`,
`unavailable_domain` and `unavailable_field`. `matched` describes transport
completeness for observed date/provenance and numeric fields; it is not clinical
validity, linkage acceptance, or a negative phenotype. Unusable matched records
remain available as raw evidence. Missing captured evidence columns are also
reported in `missing_fields`. The existing strict gas projection remains
available and continues to reject absent/conflicting starts or undated gases.

The owner-approved closeout covers date-level access/scope. Historical elapsed
first-24-hour requirements cannot be reconstructed from date-only source.
Clinical decisions and study reporting remain downstream. Public synthetic
E2Es are engineering evidence; private scope and identity acceptance is separate.

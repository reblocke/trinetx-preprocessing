# Original GLP-1 abstract: timestamp source gate

The original patient-level abstract requires the first available arterial
PaCO2 from encounter start through 24 hours after start, ordered by clinical
timestamp and source-record key, then paired with pH. This is the rule in
[issue #6, section 6.2](https://github.com/reblocke/trinetx-preprocessing/issues/6).
The accepted encounter bundle remains valid for its engineering contract, but
its calendar-day anchor does not prove this temporal rule.

## Observed limitation in the accepted source snapshot

A bounded, aggregate-only private audit on 2026-09-24 checked the accepted
bundle's manifest-bound canonical DuckDB. It found date-only precision for
every preserved encounter start, every selected arterial PaCO2/pH source record,
and the broader preserved lab domain. A separate aggregate inventory found
date-only precision throughout the preserved vital, diagnosis, procedure, and
medication domains too. Some bundle-linked encounters have
multiple distinct source start dates. The canonical source preserves raw date
strings and explicit precision labels; its parsed midnight values do not add
an observed time of day. The audit did not select a study index or validate a
scientific estimate. Its source identity and aggregate receipt remain private.

The accepted build's work-manifest digest matches the bundle's recorded source
identity. Direct header checks on its recorded, unchanged raw export files found
only `start_date`/`end_date` in the encounter export and `date` in the lab,
vital, diagnosis, and procedure exports; the medication export has `start_date`.
No separate time-of-day column appears in these raw headers. This rules out a
currently omitted raw time field in the accepted input layout; it does not
establish whether TriNetX can provide times in a new approved export.
The accepted medication export also lacks `end_date`, `order_status`, and
`status` fields. An aggregate check of the manifest-bound canonical medication
table found no populated values in those columns. A missing end date in this
snapshot represents an absent source field, not evidence of an open order.
This independently blocks the original documented no-active-order denominator.
The source identity and path-free audit receipt remain private.

A [TriNetX-authored July 2021 deidentified dataset dictionary](https://www.stonybrookmedicine.edu/sites/default/files/TriNetX%20Research%20Data%20Dictionary%20-%20July%202021.pdf)
describes encounter `start_date` and laboratory `date` as eight-character
`YYYYMMDD` fields. This is consistent with the accepted snapshot and makes a
repeat of that standard layout unlikely to add hour precision. The dictionary
is dated and does not determine whether a current alternative product or an
approved site-specific extract can supply clinical event timestamps.

The current snapshot cannot establish an exact first-24-hour interval or the
first gas within it. The same precision limit affects other claims about
pre-presentation and same-day order or measurement timing. Adding these
date-only fields to the existing bundle would not resolve this. Do not infer
midnight, choose an arbitrary conflicting start, or replace 24 hours with an
inclusive calendar-day window in the original abstract without an approved
scientific decision.

The draft `audit_candidate_source_capabilities()` helper can screen a
validated canonical source without returning patient rows, file paths or raw
headers. It separately counts date-only rows, timestamp-labeled rows with and
without a parsed datetime, and other/missing precision for encounter starts,
lab events and medication starts. It also counts populated medication end and
status fields and how many raw encounter, lab and medication files contain
those column names. A parsed midnight date remains date-only under this audit.
These are aggregate source-capability diagnostics, not a gas-specific
first-24-hour validation or an acceptance receipt. A new source still needs
the index-specific arterial gas and pH, time-zone, shift and provenance checks
below.

For an approved canonical product, run the read-only screen locally:

```bash
uv run --locked trinetx-preprocessing audit-cohort-source-capabilities \
  --database /approved/output/trinetx_preprocessed.duckdb \
  --spill-root /approved/local/scratch
```

The command validates the canonical product first and emits aggregate JSON to
standard output without source paths, row identifiers or raw headers. Its
`source_accepted=false` and `abstract_report_ready=false` fields are deliberate;
this screen does not issue an acceptance receipt. Retain full private source
identity in the approved local audit record, not in a public issue or PR.
The spill root must already exist outside the repository; use an approved fast
scratch volume when available.

## Request to the source provider

Ask whether a current alternative TriNetX product or approved site-specific
extract can supply actual clinical event times, rather than another download
of the date-only `YYYYMMDD` layout. Request a current field dictionary and a
safe, aggregate precision inventory before any transfer. At minimum, ask for:

- Encounter `patient_id`, `encounter_id`, start datetime, time precision,
  source/HCO identifier, and source-record identity. Preserve all duplicate or
  conflicting source rows for review. End datetime is useful for context.
- Arterial PaCO2 and pH event datetimes, precision, stable source-record keys,
  specimen/panel identifiers, original numeric values, units, and arterial
  provenance. The two measurements need a defensible time basis for first-gas
  ordering and the section 6.2 pairing hierarchy.
- Medication order start and end datetimes with precision, status and
  status-effective time if available, stable order IDs, ingredient/product,
  and source capture period. Confirm whether these represent orders,
  prescriptions, administrations, or another event; absent end/status fields
  cannot establish an active versus documented-no-active order at index.
- The extract's source snapshot and manifest, time-zone/offset semantics if
  supplied, date-shift behavior if applicable, coverage interval, and field
  dictionary. Confirm whether the time values describe the clinical event,
  ingestion, or another timestamp type.

The request must use the approved research/data-use route. Store any new raw
export and full provenance outside Git. Do not transfer row-level data through
an issue, PR, or external service.

## Acceptance before use

The upstream build must preserve source precision and provenance, then report
aggregate coverage of timed versus date-only encounter starts and arterial
gases. Reconcile original patient/encounter keys, duplicate starts, absent
events, and source snapshot identities against the accepted population. Confirm
that each proposed patient index has a defensible encounter start and that gas
events can be ordered and bounded by 24 hours. Date-only or conflicting cases
remain explicitly unavailable under the original rule unless a separate
scientific decision defines their handling.

Publish any new source interface as a separately versioned, validated product
with a fresh private acceptance receipt. Keep the existing accepted bundle
immutable. Downstream must consume the trusted interface through its installed
reader, reconcile patient/index membership, and pass hand-specified first-gas,
boundary, tie, and pH-pairing fixtures before a primary estimate is released.
The original abstract report remains blocked until these gates and its other
scientific decisions are resolved; the approved Stage 34 proxy is separate.

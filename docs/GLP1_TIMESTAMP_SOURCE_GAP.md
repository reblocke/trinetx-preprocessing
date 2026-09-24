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

The current snapshot cannot establish an exact first-24-hour interval or the
first gas within it. The same precision limit affects other claims about
pre-presentation and same-day order or measurement timing. Adding these
date-only fields to the existing bundle would not resolve this. Do not infer
midnight, choose an arbitrary conflicting start, or replace 24 hours with an
inclusive calendar-day window in the original abstract without an approved
scientific decision.

## Request to the source provider

Ask whether a new approved TriNetX export can supply actual clinical event
times, at least for:

- Encounter `patient_id`, `encounter_id`, start datetime, time precision,
  source/HCO identifier, and source-record identity. Preserve all duplicate or
  conflicting source rows for review. End datetime is useful for context.
- Arterial PaCO2 and pH event datetimes, precision, stable source-record keys,
  specimen/panel identifiers, original numeric values, units, and arterial
  provenance. The two measurements need a defensible time basis for first-gas
  ordering and the section 6.2 pairing hierarchy.
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

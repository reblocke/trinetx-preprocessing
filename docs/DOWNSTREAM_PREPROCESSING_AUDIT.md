# Downstream preprocessing audit — 2026-10-17

## Scope and baseline

Reviewed code/history since the preceding 2026-10-03 upstream closeout in six
known downstream repositories, current local uncommitted adapters and the
unpublished upstream `codex/broader-bmi-mapping` branch at `45d3fc0`.
The upstream base is `787fba6`. Remote default heads were checked as well as
local checkouts; several local checkouts were behind GitHub.
Downstream dirty files are read-only audit inputs, not approved releases.
Keep original source/products and historical receipts immutable. No private job,
new cohort, downstream edit or clinical result is part of this repair.

## Failure scenarios recorded before corrections

Existing historical pipeline E2Es do not call the new mapper. Its original
11-key source-to-Parquet fixture covers hierarchy, simple conflicts, rounding
and a damaged product, but omits the following complete invocation scenarios.
Extend that E2E before changing the implementation, with literal expectations.

- Suspected candidate/CTE name collisions for `chosen`, `typed` and case
  variants. Expected: identical exact-key rows and values without source
  changes. All four passed before correction; no alias refactor was needed.
- An output name equal to an input only by case can shadow the source.
  Expected: reject before creating any output; preserve all source rows.
- A caller product carries an unsupported schema version or lacks a required
  column, even with internally matching file hashes. Expected: reader refuses
  a product outside its supported contract.
- Empty or whitespace source-record identifiers pass the NULL-only check.
  Expected: reject unusable provenance and leave the connection reusable.
- Invalid candidate date ordering or noncalendar date types can silently
  produce an apparently valid prior BMI or change the product schema.
  Expected: reject malformed input rather than choose a clinical meaning.
- Existing output relations/directories and symlinks, damaged manifests,
  missing/duplicate product keys and partial failures must preserve earlier
  evidence, release only owned temporary resources and fail explicitly.

Independent controls also retain every original key (including no-BMI/no-gas
keys), current/prior/calculated hierarchy, exact float16/CSV/float32 rounding,
unit conversions, recorded masking bounds, missing versus unresolved evidence,
NULL demographics, repeated encounters, future measurements and calendar ties.
Unknown precision cannot establish prior timing; only the existing date-only
source contract is supported. No scientific threshold is changed.

## Human-readable change inventory

| Source inspected | What changed and why | Disposition |
| --- | --- | --- |
| Upstream BMI draft `45d3fc0` (producer code from `72c91a2`) | Added reusable current/prior/calculated BMI and demographic mapping for caller-supplied encounters; corrected float16/CSV and float32-before-rounding to reproduce inherited values | Publish the separate mapper here with the focused corrections below; keep accepted bundles and raw source unchanged |
| Obesity study `2fdc05a`, plus local adapter edits based on `8735505` | Decode the accepted Stata day/category layout; bind mapping to original FULL_DATA keys; distinguish missing BMI from unresolved mapping; select study indexes and prepare gas/ICD summaries | Mapping producer belongs upstream; original-list selection, gas rules, thresholds, R input preparation and BMI-response presentation remain study-owned |
| GLP-1 `56fcae7` (local checkout `9eb61f0`) | Shared-reader pins and launch preparation; new patient selection and CKD/MASLD evidence classifiers retain raw values, units, missingness and separate operational evidence states | Already uses upstream transport/readers. Disease definitions, creatinine-derived evidence, thresholds and patient-index selection remain in the child; no classifier is imported here |
| Bicarbonate `ddd4cb0` and preparation branch `e990ce7` | Explicit CONSORT input handoff; separate fresh Quarto render root from the reserved data-output root | Sensible launch/presentation boundary; no preprocessing derivation to move upstream |
| Diagnostic equity `0d38bed` | Migration checks and a plot correction using arterial CO2 consistently across groups instead of a venous series in one group | Study figure correction; no canonical source or preprocessing change |
| Diagnostic model `4bc4ef2` | Explicit input/output adapters, render destination and activation documentation | Study runtime/presentation plumbing; no new reusable source transformation |
| Legacy analysis `d73c055` | Installed-reader adoption, evidence retention and project routing after the split | Shared readers are already upstream; retain the compatibility and project routing downstream |

The later obesity-study decision on 2026-10-16 restricts its candidate
population to the authenticated original selected encounter list. It supersedes
that study's earlier broader-population qualification. The generic mapper does
not choose either population: it returns one row per supplied key. Its results
must not be described as an expanded FULL_DATA product or a new clinical cohort.
The remote obesity mapper and original-population/qualification adapters match
the inspected local copies; its preparation script has additional remote changes,
which were inspected separately. Downstream files were not edited.

## Confirmed defects and corrections

The pre-correction E2E retained **10 failing and 15 passing synthetic cases**:

- Three case-only output aliases could shadow input relations in DuckDB.
  Compare identifiers without case and reject every existing destination
  relation before staging. Valid `chosen`/`typed` names remain supported.
- Two blank source-record ID cases bypassed the NULL-only provenance check.
  Require nonblank identities and retain cleanup after a failed invocation.
- Reversed encounter dates and timestamp-typed candidate dates were accepted.
  Require the documented DATE-typed inputs and reject end-before-start; missing
  dates still produce unresolved evidence, not an inferred date.
- The reader accepted an unsupported manifest version, a missing BMI column
  and a NULL original key when hashes were internally consistent. Authenticate
  the existing v1 column names/types, version and nonblank/unique keys as well
  as manifest/product bytes. The writer checks the same product contract before
  claiming its destination. No valid v1 field or numeric calculation changes.

Style changes move imports to the module boundary, add type annotations and use
Ruff formatting. Temporary tables keep the existing unique names and cleanup;
we did not replace the working SQL selection or introduce a general eligibility
framework. The new retained runner exercises the existing E2E fixture, including
all 11 original value expectations and 27 adversarial/control scenarios.

## Interpretation and remaining boundaries

The inherited numeric sequence, recorded-BMI masking cutoff, metric/UCUM unit
handling, deterministic calendar-day hierarchy and demographic precedence are
consistent with their stated purpose. They are preserved, including the
historical float32 representation; direct double rounding would change boundary
values. Current measurements require the exact encounter and known end bound;
prior measurements are strictly earlier than each supplied encounter's start.
Only the mapper's existing date-only source contract is supported; timestamp or
unknown precision is not converted to an inferred prior day. Caller-supplied
starts must already be qualified source consensus dates.

Completed search with no usable BMI remains distinct from unavailable capture,
unknown chronology or conflicts. The source's original raw records are not
rewritten. The selected product retains method/component dates, but it is not a
replacement raw-evidence ledger. Unit defaults require authenticated source
metadata, not inference from value magnitude.

This is an engineering audit of identified changes, not an exhaustive clinical
review of every downstream classifier or model. No new downstream defect was
established by the bounded code inspection. Downstream source capture, scientific
policies and actual-data qualification remain their owners' responsibility.
Historical private qualification is not transferred to this implementation.
The study's existing pin/lock and acceptance receipts must not be relabeled as
qualification of the corrected mapper; downstream adoption needs its own review.

See [the mapping contract](CALENDAR_COVARIATES.md) and
[verification commands](TESTING.md#calendar-covariate-mapping).

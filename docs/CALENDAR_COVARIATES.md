# Calendar encounter covariates

Derived from the owner-authorized 2026-10-15 mapping; audited on 2026-10-17.
Map caller-supplied original encounter keys without choosing a population.
The obesity study's 2026-10-16 correction restricts its use to the authenticated
original selected FULL_DATA keys; its earlier broader-population qualification
is superseded for that use. Historical FULL_DATA/AFTER_EXCLUSION and
the canonical source are immutable. The caller supplies population/date/type
consensus; this interface does not select an index, impose BMI eligibility or
require gases. It applies the inherited year-minus-birth-year age calculation
and demographic codes, preserving missing/unknown/conflicting source evidence.

BMI: valid encounter-reported value, then latest valid prior reported value,
then observed current/prior height and weight. Current values use the earliest
valid dated measurement in that exact encounter; prior values precede each
candidate's own start. Equal-day conflicting values remain unresolved. Do not
use a later encounter, statistical imputation, or one historical patient anchor.
Record component dates, method and unavailable-evidence reasons. Recognized
units and caller-authenticated defaults are applied during mapping; original raw
units/records remain in the immutable source rather than a new row-level ledger.

The recorded-BMI exclusion at 50.1 remains the documented legacy masking rule.
No assumption that larger raw numbers are exact is authorized. Calculated BMI
uses inherited pound/inch conversion, integer component rounding and 0.1 BMI
rounding; no arbitrary recorded-BMI cap is imposed on calculated values.
The effective inherited height/weight upper screens are 84 inches and 450
pounds from the earlier normalized-vital layer. Source metadata must
authenticate missing unit defaults; otherwise unsupported
units remain unusable. Missing after a complete search differs from unresolved
source timing or conflicts. No new covariate or BMI value is imputed.

## Failure-first verification

Existing pipeline E2Es cover the historical selected population, not repeated
caller encounters with no syndrome membership. The additional source-to-product
E2E has hand-authored expected values and retained Parquet/JSON evidence for:

- dropped no-BMI/no-gas keys, duplicate/mutated keys, and unchanged historical inputs;
- current/prior/calculated hierarchy, prior dates relative to repeated encounters,
  future measurements, invalid/masked values, units and rounding;
- same-day ties, missing dates, unavailable capture versus searched absence;
- year-based age and inherited category precedence, missing/conflicting demographics;
- mapping/policy/source identity, damaged output, and reader hash mismatch.

The [downstream audit](DOWNSTREAM_PREPROCESSING_AUDIT.md) records pre-correction
failures and dispositions. Run the retained mapping E2E and existing historical
pipeline runner; see [verification commands](TESTING.md#calendar-covariate-mapping).
Read back each receipt and its artifact hashes. Private population reconciliation
and human scientific review remain separate from synthetic success.

The mapper also preserves the earlier normalized-vital numeric transport:
float16 followed by its CSV-visible decimal representation, then Stata float32
BMI storage. Raw height screening is 54 <= inches <84 and weight screening is
10 <= pounds <450, followed by the frozen Stata cleaning and rounding. These
steps matter for fractional values. The source-to-product regression includes
30.04 reported BMI, 200.49-pound weight and the 84-inch boundary.

## Interface and product contract

Call `build_calendar_covariates()` on a validated read-only canonical source
connection with a unique temporary output name. Patient/encounter keys and
encounter type are VARCHAR; start and optional end are DATE; birth year is a
signed integer through BIGINT. Unknown starts may be NULL; non-NULL ends must
not precede starts. The caller qualifies calendar-date consensus first. Only
date-only vital evidence supplies timing; timestamp/unknown precision remains
unresolved where relevant, without inferring a date.

The function preserves every supplied key, including encounters with no usable
BMI or gas, and returns the temporary relation name. It never selects an index,
requires gas positivity, or applies BMI eligibility. Output names are compared
without case, and all existing relation names are refused. Temporary staging and
the numeric-conversion function are removed after both success and failure.

`write_calendar_covariates()` exclusively claims a fresh external nonsymlinked
directory and publishes `covariates.parquet` plus `manifest.json`. Existing
destinations remain unchanged. Interrupted/incomplete directories are retained
as incomplete evidence; choose a new destination rather than resume them.
`read_calendar_covariates()` requires a caller-trusted manifest digest, schema
version 1, the exact policy and 18-column/type contract, product hashes, declared
row count and unique nonblank original keys. It does not itself accept the
source population or authenticate caller-supplied source metadata.

The audited revision keeps the mapper signatures, policy and valid v1 values/
column types unchanged while refusing malformed inputs and incomplete products.
It changes code identity: previous private receipts and downstream pins remain
bound to their original producer. No old product or acceptance is replaced.

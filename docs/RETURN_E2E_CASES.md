# Return v2 E2E cases and failure modes

These expected results were written before changing production code. The E2E
fixture must run source validation, the actual encounter producer and validator,
the return builder and independent validator, then retain a hash inventory and
machine-readable result externally. Expected values here are hand authored;
the builder must not supply its own oracle. Both parent variants must be checked.

Use an inpatient index ending 2024-01-02 unless a case specifies otherwise.
All dates below are recorded calendar dates; a midnight parsing artifact does
not establish within-day order.

| Case | Source return | Expected 30-day all-cause / phenotype result |
|---|---|---|
| Day zero | Distinct ED ID starts 2024-01-02 | zero confirmed; one same-day uncertain; day-1 flag false if no other candidate |
| Day one | Inpatient ID starts 2024-01-03 | one readmission and one acute union return; first date Jan 3; days since end 1 |
| Day 30 | ED ID starts 2024-02-01 | one ED-only, any-ED and acute union return in 30 days |
| Day 31 | ED ID starts 2024-02-02 | zero at 30 days; one at 90 and 365 days |
| Day 365/366 | Separate IDs start 2025-01-01/02 | day 365 included; day 366 outside horizon |
| Same ID ED to IP | ED Jan 3–5, IP Jan 4–7, with duplicate ED source row | one coherent episode, one acute union return; ED and IP categories, not ED-only |
| Conflicting same ID | ED Jan 3–4, IP Jan 5–7 | no confirmed return; explicit conflict/unsupported reason |
| Missing index end | Observed inpatient index without end | index row present; primary counts, flags and first date NULL |
| Known nonacute index | Outpatient index with valid dates | index row present; primary values NULL with not-applicable reason |
| Unknown index setting | Unrecognized type | index row present; unavailable applicability reason |
| Missing return start | Acute episode with unknown start | zero confirmed count; unknown horizon flag if membership could change |
| Derived return start | Date marked derived | zero confirmed; uncertainty recorded; cannot establish first event |
| Invalid return order | Return end before start | zero confirmed; invalid order count; never phenotype positive |
| Unusable return end | Valid return start Jan 3, end missing | all-cause count 1; phenotype unavailable despite linked evidence |
| Index history code | Exact J96.02 only on index | return ICD phenotype not positive |
| Return exact ICD | Exact J96.02 or E66.2 inside coherent return | ICD and corresponding ICD-or-gas composite true |
| Broad or wrong system | J96.9 or qualifying code in a non-ICD-10-CM system | no exact ICD qualification |
| Boundary gases | ABG 45 and VBG 50 mmHg on return | strict ABG>45/VBG>50 false; inclusive paired union true |
| Converted gas | VBG 6.666118 kPa on return | normalized mmHg near 50; threshold determined by unrounded converted value |
| Rejected gas | Wrong specimen, unsupported unit, absent date, or outside interval | evidence and reason retained; criterion NULL absent usable test |
| Normal and untested | Two confirmed returns, one ABG 40, one without usable ABG | ABG>=45 count 0, flag NULL, tested 1, untested 1 |
| Positive and untested | Two confirmed returns, ABG 50 then no usable ABG | ABG>=45 count 1, flag true, tested 1, untested 1 |
| Only normal | One confirmed return with ABG 40 | ABG>=45 count 0, flag false |
| No return | No confirmed or possible return | all-cause observed count 0/flag false; gas flag NULL |

Adversarial corruption after build must fail even when the manifest is rehashed:
remove or add a link; remove or duplicate a source episode; change raw gas or
normalized value independently; flip gas rejection or ICD eligibility; alter
index anchors; shift a return across a window; change any uncertainty count;
alter a parent evidence raw date, parsed date, or explicit precision; collide
patient partitions; and change any input or code identity before resume.
Fresh, interrupted/resumed and differently partitioned builds must agree as
complete multisets for every published data artifact. The E2E artifact must
record source, parent, output, contract and code hashes, commands, case results,
and SHA-256 of every output file.

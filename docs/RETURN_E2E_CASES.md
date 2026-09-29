# Return v2 E2E cases and failure modes

Historical planning/verification record. The original v2 revision subsequently
passed C0–C4; current integration status is in
[RETURN_ACCEPTANCE.md](RETURN_ACCEPTANCE.md).

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

## Parent availability reconciliation under bounded memory

The real accepted parent exposed a separate 4 GiB and 8 GiB failure in the
exact element-by-history availability join after the earlier distinct-count
stage. Before changing this validator query, preserve these failure modes:
partitioning can lose or duplicate source evidence rows; a missing or duplicate
coverage key can change join multiplicity; the same encounter can appear in
multiple partitions and make summed distinct counts wrong; a domain or history
state can disappear; an empty evidence artifact can be misread as incomplete;
and a larger scratch projection can violate the external free-space gate. The
bounded path must prove complete row multiplicity, keep each encounter in one
stable partition, sum exact per-group distinct counts, and compare every group
against the original manifest report. The default validator path is unchanged.

The accepted producer writes an element summary row only when an encounter has
at least one retained element-evidence row, then left-joins that summary to all
index rows. Its count for a particular element is therefore NULL when the
encounter has no element evidence of any kind, zero when it has other elements
but not that element, and positive for matching rows. A validator must preserve
that three-way distinction; coalescing the no-evidence NULL to zero can create
a false parent-bundle failure. The synthetic proof needs all three cases and
must still reject a genuinely changed count.

## V2 builder memory boundary

The first final-code private bucket reached the v2 FULL_DATA summary write and
failed at the builder's 1 GiB DuckDB cap. Five partition files were left in the
failed external pilot directory; no summary, independent validation result, or
passing pilot receipt exists. Before changing the builder connection, preserve
these failure modes: a v1 caller could silently receive a larger cap; the v2
key-collision check and partition builder could use different caps; a resumed
build could reuse a part from different code or memory configuration; a failed
summary could be mistaken for a complete part; the larger cap could exceed
physical memory or external free-space limits; and a memory increase could hide
an incorrect output. The next pilot must run both variants in a new external
directory, measure process memory and free space, independently reconcile all
six tables and exact keys, and verify source, parent, code and artifact hashes.
The original v1 default and public old-consumer behavior must stay unchanged.

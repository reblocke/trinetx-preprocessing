# GLP-1 source precision audit and revised calendar-date decision

This file retains the evidence behind the **historical** first-arterial-gas-
within-24-hours limitation. The owner confirmed on 2026-09-24 that the TriNetX
source has day resolution and the missing times cannot be obtained. The owner
accepted a revised patient-level calendar-date phenotype and prohibited email
contact. No source inquiry or timestamp acquisition remains open for this
ticket. The downstream versioned GLP-1 abstract contract specifies the revised
rule; the approved Stage 34 encounter proxy remains separate.

## Accepted-source evidence

A bounded aggregate-only private audit of the accepted manifest-bound canonical
DuckDB found date-only precision for every preserved encounter start and
catalog-matched arterial PaCO2/pH candidate. Preserved laboratory, vital,
diagnosis, procedure and medication domains were also date-only. Some linked
encounters have multiple distinct source start dates. Raw date strings and
precision labels are retained; a parsed midnight does not supply a clinical
time. Source identity and the path-free receipt remain private.

Header checks on the unchanged accepted raw export found encounter
`start_date`/`end_date`, laboratory, vital, diagnosis and procedure `date`, and
medication `start_date`, without a separate clinical time field. A header-only
screen of two archived 2022 layouts found the same field pattern. The archived
screen did not read clinical values or prove those records' precision.
The accepted medication export lacks `end_date`, `order_status` and `status`;
those canonical medication columns have no populated values. Missing end data
cannot be treated as an open or active order.

The TriNetX-authored [July 2021 deidentified dataset dictionary](https://www.stonybrookmedicine.edu/sites/default/files/TriNetX%20Research%20Data%20Dictionary%20-%20July%202021.pdf)
describes encounter `start_date` and laboratory `date` as `YYYYMMDD` fields.
This is consistent with the audited snapshot. It is historical background,
not the approved study contract.

## Scientific consequence

The historical issue #6 first-observed arterial PaCO2 within an elapsed 24
hours, with timed pH pairing, cannot be calculated from this accepted source.
The owner-approved revision uses the encounter start **date** D, selects the
first arterial testing date in D..D+1 before inspecting PaCO2 values, and
classifies any valid arterial PaCO2 >45 mmHg on that date as the primary gas
phenotype. pH is reported separately as genuinely linked sample evidence or
explicitly unpaired same-day evidence. Pre-index history ends D-1; D records
are separate. The full cleaned BMI>=30 patient cohort is the primary
indication denominator; active medication and the historical no-active-order
denominator are unavailable, while recorded prior orders may be described.

The source-specific adapter must still reconcile original patient/encounter
keys, conflicting encounter starts, arterial provenance, specimen/panel
linkage, source coverage and incomplete historical index membership. Its
calendar-date classification must retain missing and invalid evidence as
unknown and compare D-only and first-day concordance sensitivity definitions.
The accepted encounter bundle remains valid for its existing engineering
contract. The historical timed selector remains a reproduction aid and cannot
be run against date-only records to claim the revised phenotype.

## Audit-tool scope

The draft `audit_candidate_source_capabilities()` helper counts precision
labels and populated medication fields in aggregate after canonical-source
validation. The header-only `screen-glp1-export-headers` command reports
field-presence hints without clinical rows. Their outputs do not establish a
clinical phenotype or issue an acceptance receipt. An owner-only capability
run on the accepted snapshot agreed with the earlier audits, with stable
source identity and private receipt. No additional timestamp-source search is
part of the revised work.

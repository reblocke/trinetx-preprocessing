# GLP-1 source closeout and ownership reconciliation

This maps upstream issues [#22](https://github.com/reblocke/trinetx-preprocessing/issues/22)
and [#6](https://github.com/reblocke/trinetx-preprocessing/issues/6) to the current
source contract and child study ownership. The owner-approved pragmatic
calendar-date contract supersedes the earlier timestamp-based clinical proposal.
Closing a source ticket does not establish clinical eligibility or study readiness.

## Issue #22: bounded source handoff

| Requirement | Implementation and evidence scope |
| --- | --- |
| U1 exact candidate keys and original source rows | `combined_preprocessing.cohort_source_calendar_population` and `cohort_source_calendar_transport` preserve original string keys, repeated encounters and raw source records. No patient index is selected upstream. |
| U1 gas, vital, lab and context access | The read-only transport accepts explicit code-system selectors and catalog-element unions. PaCO2, adjusted PaCO2 and pH remain distinct; BMI/weight/height, HbA1c and creatinine retain raw units and dates. Diagnosis/procedure and ingredient-family records retain observed provenance, not clinical eligibility or treatment inference. |
| U2 absence, unusable/undated, conflict and failure states | Existing calendar population/batch/history/vital fixtures plus `verify_calendar_transport_e2e.py` cover the distinctions, exact-key rejection, overlapping membership deduplication and raw-row retention. The captured catalog and source remain immutable. |
| U3 private source scope | The independently accepted source-access closeout at `0bb9c905655d` binds source/sidecar identity, declared candidate access, historical-key evidence, domain readbacks and a noneditable installed consumer. The retained artifact chain was authenticated during this reconciliation. It is source scope only, not equality of selected clinical populations. No completed private query was rerun. |
| U4 installed interface and documentation | The canonical-source implementation remains byte-identical to that accepted source-access revision. Standalone installed reader E2Es and the GLP-1 child interface check qualify the relocation and immutable dependency pin. The child receives the existing private handoff through its owner; public CI contains synthetic evidence only. |

Accepted return-product evidence remains separately scoped in
[RETURN_ACCEPTANCE.md](RETURN_ACCEPTANCE.md). The earlier GLP-1 source-equivalence
acceptance remains separately scoped in
[GLP1_SOURCE_ACCEPTANCE.md](GLP1_SOURCE_ACCEPTANCE.md). Neither is substituted for
clinical study acceptance.

## Issue #6: disposition of the original broad epic

The original issue body is preserved for history. The numbered sections below
cover all its requirements; study-specific subrequirements stay with the child
[GLP-1 completion ticket](https://github.com/reblocke/glp1-eligibility-hypercapnia/issues/2).
No new upstream scientific work is inferred from the old checklist.

| Original section | Current disposition |
| --- | --- |
| 1 definition of done | Split: reusable source delivery upstream; clinical outputs and investigator acceptance in the GLP-1 child. The old combined endpoint is superseded. |
| 2 pipeline corrections | Source fidelity remains upstream; gas selection, pH interpretation, index and BMI decisions use the later approved child contract. |
| 3 data request and optional domains | Existing immutable captured fields and unavailable-domain states are upstream. New exports/access and clinical sufficiency remain owner/study decisions; they are not required by bounded #22. |
| 4 command/configuration | Canonical source CLI/configuration are delivered upstream. Study commands/configuration belong to the child. |
| 5 terminology/rules | The shared source catalog and raw code-system transport are upstream. Clinical concept adjudication and phenotype rules belong to the child. |
| 6 cohort construction | Child-owned. The later approved calendar-date method, independent variants and original keys supersede the old timestamp/first-ABG proposal. |
| 7 temporal rules | Raw timing/precision preservation upstream; approved lookbacks/index policy in the child. No timestamp recovery is implied. |
| 8 evidence states | Raw observation/availability/query-failure states upstream; clinical evidence status and evaluability in the child. |
| 9 component phenotypes | Entirely child-owned, including diabetes, CKD, OSA, liver, cardiovascular and other guideline/trial phenotypes. Missing source evidence is not negative. |
| 10 eligibility tiers | Child-owned; later approved pragmatic definitions govern, not an automatic revival of the original comprehensive phenotype proposal. |
| 11 Medicare routes | Child/owner clinical-policy scope. No insurance coverage determination upstream. |
| 12 treatment exposure | Raw ingredient-family provenance upstream; order role, timing, exposure and treatment-gap conclusions child-owned. An export-family name is not an active prescription. |
| 13 database contract | Canonical source inventory/provenance/schema upstream. Cohort, index, eligibility evidence, wide analysis table and views are child derivations. |
| 14 flow and summaries | Generic source fidelity and return quality upstream; study cohort flow, prevalence and reporting in the child. |
| 15 units | Raw values/labels preserved upstream. Existing frozen conversion helper remains available; index-specific normalization/BMI and clinical interpretation follow the child contract. |
| 16 performance/reproducibility | Canonical out-of-core ingestion, immutable inputs, restart/provenance and bounded return execution are upstream. Study reproducibility/performance belongs to its delivered workflow. |
| 17 repository deliverables | Upstream package/CLI/catalog/source documentation delivered. Study package, configuration, phenotype documentation and compatibility requirements belong to the child. |
| 18 synthetic acceptance cases | Source cases remain upstream; scientific cohort/phenotype cases belong to the child and are evaluated against the later approved definitions. |
| 19 integrity criteria | Source schema, inventory, stable raw keys and fidelity upstream; analytic keys, baseline leakage, phenotype evidence and study tables child-owned. |
| 20 analysis smoke | Child-owned. It must not be run upstream to justify source acceptance. |
| 21 study-ready outputs | Child-owned and still subject to its clinical/report acceptance gates. |
| 22 non-goals | Preserved: no effectiveness, insurance, dispensing, prescribing or scientific-validation claim is added by source delivery. |
| 23 milestones | Source ingestion/packaging delivered upstream; clinical normalization/cohort/phenotype/eligibility/reporting milestones now tracked by the child. |
| 24 completion statement | This reconciliation reports the source endpoint only. A study completion statement requires the child workflow's actual evidence and owner decisions. |

No uncovered reusable capability was identified by the bounded review. Additional
study requirements remain in the existing child ticket; creating duplicate
upstream tickets would obscure ownership. The broad epic can be closed as
superseded without marking its historical clinical checklist complete.

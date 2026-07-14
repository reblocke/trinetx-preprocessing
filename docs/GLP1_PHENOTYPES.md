# GLP-1 Phenotype Definitions

GitHub issue #6 is the authoritative analytic specification. Versioned concept
sets under `config/concept_sets/` define source code membership; the build
records their version and source rows in DuckDB.

## Core cohort

- The index measurement is the first usable arterial PaCO2 in the first 24
  hours of an adult emergency or inpatient encounter.
- Strict hypercapnia requires PaCO2 greater than 45 mm Hg and paired pH at or
  below 7.45. Pressure units are normalized explicitly; total CO2 LOINC
  `2026-3` cannot create a PaCO2 candidate.
- Later arterial elevation, VBG-only elevation, acute acidemia, compensated
  hypercapnia, and 14-84 day persistent arterial elevation are retained as
  separate sensitivity/context fields.
- Arterial bicarbonate, PaO2, and oxygen saturation are supplemental values:
  they are unit-normalized and paired to the selected arterial PaCO2 by the same
  specimen/panel, timestamp, tolerance, and date-only hierarchy used for pH.
  They do not define cohort membership. The current LOINC seeds and broad
  plausibility bounds require investigator review before interpretation.
- BMI follows measured BMI, then measured weight/height calculation, within the
  configured pre-index hierarchy. Missing BMI remains indeterminate.

## Component and indication semantics

- Diagnosis, procedure, laboratory, vital, and medication evidence is limited
  to each row's configured lookback and index date unless a field explicitly
  represents index context or post-index GLP-1 orders.
- Strict OSA requires AHI/REI evidence; an OSA code without severity remains
  indeterminate for the strict indication.
- Laboratory-only CKD requires persistent low eGFR on measurements separated by
  at least 90 days.
- Strict noncirrhotic MASH requires MASH, structured F2/F3 fibrosis staging,
  and no cirrhosis. FIB-4 is retained as a derived analytic value but does not
  create strict staging.
- Strict HFpEF and uncontrolled-hypertension branches require their structured
  measurements and treatment components; code-only evidence is represented at
  lower certainty.
- FDA, guideline/society, and randomized-trial tiers remain separate. Payer
  routes are hypothetical clinical-route categories, not coverage decisions.
- An EHR medication order is not evidence that medication was dispensed or
  taken.

## Study views

- `analysis_primary_obesity_hypercapnia`: strict primary denominator with BMI
  at least 30.
- `analysis_documented_indication_prevalence`: conservative documented
  prevalence using the full denominator.
- `analysis_evaluable_indication_prevalence`: prevalence among non-null rows and
  the indeterminate fraction.
- `analysis_indication_overlap`: per-patient count and compact UpSet membership
  key.
- `analysis_treatment_gap`: indication and pre-index GLP-1 order comparison.
- `analysis_missingness`: aggregate data-availability counts by required field.

## Required review

The concept sets are implementation seeds, not clinically validated phenotype
definitions. Investigator review is required before real-data interpretation,
especially for MASH staging, symptomatic PAD, neurologic/chest-wall causes,
procedure families, supplemental arterial-gas measurements, medication
mappings, and site-specific units or code systems. Record-level validation must
occur in an approved private environment.

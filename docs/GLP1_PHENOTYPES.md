# GLP-1 Phenotype Definitions

GitHub issue #6 is the authoritative analytic specification. Versioned concept
sets under `config/concept_sets/` define source code membership; the build
records their version and source rows in DuckDB.

## Core cohort

- The index measurement candidate is the first observed arterial PaCO2 in the
  first 24 hours of an adult emergency or inpatient encounter. Selection occurs
  before unit and plausibility checks; an unusable first result is retained with
  an explicit exclusion reason and a later result is not promoted into its
  place. Every encounter-scoped reduction uses `(patient_id, encounter_id)`
  because source encounter identifiers are not assumed globally unique.
- Strict hypercapnia requires PaCO2 greater than 45 mm Hg and paired pH at or
  below 7.45. Pressure units are normalized explicitly; total CO2 LOINC
  `2026-3` cannot create a PaCO2 candidate.
- Later arterial elevation, VBG-only elevation, acute acidemia, compensated
  hypercapnia, and 14-84 day persistent arterial elevation are retained as
  separate sensitivity/context fields. Maximum PaCO2 uses all valid arterial
  values from encounter start through discharge, not only the 24-hour index
  window.
- Arterial bicarbonate, PaO2, and oxygen saturation are supplemental values:
  they are unit-normalized and paired to the selected arterial PaCO2 by the same
  specimen/panel, timestamp, tolerance, and date-only hierarchy used for pH.
  They do not define cohort membership. The current LOINC seeds and broad
  plausibility bounds require investigator review before interpretation.
- BMI follows measured BMI, then measured weight/height calculation, within the
  configured pre-index hierarchy. A qualifying obesity diagnosis with no BMI is
  represented separately as `code_only`; it does not satisfy a measured BMI
  threshold or enter the strict BMI >=30 primary view.
- Candidate and primary tables retain documented arrest, trauma,
  anesthesia/sedation, postoperative, implausible-value, and probable-venous
  context flags. `analysis_primary_cleaned_obesity_hypercapnia` applies only the
  flags named in `exclusions.cleaned_view_excludes`; the unfiltered primary view
  remains available. The narrow trauma and procedure seeds require investigator
  review and should not be interpreted as proof that an unflagged event lacked
  those contexts.

## Component and indication semantics

- Chronic diagnosis and routine measurement evidence uses its configured
  lookback. MI, stroke, PAD, revascularization, bariatric, and liver-staging
  history uses all available pre-index data; AHI/REI uses five years; kidney and
  cardiac measurements use the general history window; structured fibrosis
  staging uses all prior data. GLP-1 `ever ordered` uses all pre-index orders,
  while active-at-index medication components retain the medication window.
  Timestamped rows use exact lookback bounds; date-only rows use inclusive
  calendar-day bounds, date-only medication ends include the reported day, and
  post-index order flags use the exact index instant for timestamped rows and
  the inclusive index calendar day for date-only rows, with the same
  precision-aware endpoint convention.
- Non-GLP-1 medication components and source evidence are limited to the
  baseline/active-at-index window. Post-index retention is reserved for GLP-1
  follow-up order endpoints.
- Strict OSA requires AHI/REI evidence; an OSA code without severity remains
  indeterminate for the strict indication.
- Laboratory-only CKD requires persistent low eGFR on measurements separated by
  at least 90 days.
- Strict noncirrhotic MASH requires MASH, structured F2/F3 fibrosis staging,
  and no cirrhosis across all available pre-index diagnosis history. FIB-4 is
  retained as a derived analytic value but does not create strict staging.
- Strict HFpEF and uncontrolled-hypertension branches require their structured
  measurements and treatment components; code-only evidence is represented at
  lower certainty.
- Blood pressure accepts recognized mmHg aliases or converts kPa before
  plausibility filtering and uses the configured measurement lookback. Raw
  values and units remain distinct from normalized mmHg evidence.
- FDA, guideline/society, and randomized-trial tiers remain separate. Payer
  routes are hypothetical clinical-route categories, not coverage decisions.
- An EHR medication order is not evidence that medication was dispensed or
  taken.
- Medication and medication-ingredient exports feed the same versioned
  medication concepts. Data-sufficiency counts come from all candidate-patient
  source rows before concept matching, so terminology gaps do not masquerade as
  absent longitudinal history.

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
trauma and anesthesia/procedure families, supplemental arterial-gas
measurements, medication
mappings, and site-specific units or code systems. Record-level validation must
occur in an approved private environment.

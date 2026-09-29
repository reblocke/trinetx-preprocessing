# Clinical and legacy-pipeline test review

Historical cleanup inventory. Status statements below describe 2026-09-25;
current return acceptance is recorded in [RETURN_ACCEPTANCE.md](RETURN_ACCEPTANCE.md).

Date: 2026-09-25. Scope: 116 original test functions in the transform modules,
domain stage modules, final assembly/source modules, legacy-NA compatibility,
and traditional catalog. This review changes tests only; it does not authorize
readmissions execution or alter any scientific acceptance gate.

## Failure modes recorded before test edits

The existing whole-pipeline E2E fixture has three encounters, positive examples
for six RFS categories, and few clinical values. It cannot replace boundary,
tie-order, malformed-input, privacy, durability, or cross-chunk failure tests
without corresponding inputs and independent output assertions. The retained
isolated regressions below each identify such a gap.

The following existing assertions will move to existing broader checks before
their original unit functions are deleted. These are migrations of existing
expectations, not newly invented scientific requirements.

| Potential failure | Existing coverage gap | Destination |
| --- | --- | --- |
| The final output schema and its implementation constant drift together. | Whole-pipeline E2E currently compares against the implementation constant. | `tests/test_pipeline_run.py::test_run_pipeline_end_to_end` will compare actual outputs to the frozen JSON fixture (coordinated with the pipeline reviewer). |
| Normalization loses a row, retains an unsupported encounter type, changes normalized codes/units, or changes missing-value behavior. | Stage integration writes the same richer fixtures but currently checks only a subset of their values. | Existing `test_run_*_stage_outputs` functions gain the remaining observed-output assertions from the removed transform structure tests. |
| Clinical group splitting loses a code family or overlapping membership. | Domain stage integration reads the same fixture but checks fewer groups. | Diagnosis, medication, procedure and vital stage-output tests gain the remaining group output assertions. Duplicate-specific transform regressions remain. |
| Legacy encounter finalization changes its selected date, length of stay, or negative-LOS exclusion. | Encounter stage already checks selected IDs and some dates but not all unit expectations. | `tests/test_encounter_stage.py::test_run_encounter_stage_outputs` gains the remaining output date/LOS assertions. |
| RFS flag derivation introduces false positives on an entirely negative encounter, loses patient association, or returns extra category members. | RFS stage has the same fixture but only positive flag checks. | `tests/test_rfs_stage.py::test_run_rfs_stage_outputs` gains exact category membership, negative flags, and patient association checks. |
| Successful stages leak tool-owned scratch. | Separate tests rerun identical stage setups solely to check cleanup. | Cleanup assertions move into the existing encounter/RFS stage-output integrations. Injected deletion-error regressions remain. |
| Stacked lab feature indexes omit or misname the rule label. | Labs stage already checks actual index labels; shape failures are exercised by final feature ingestion in full pipeline E2E. | Keep the actual-file stage and pipeline assertions; delete the one-row stacked-frame shape unit. |
| Float32 lab rules are accidentally changed to float16. | The richer final-assembly integration already independently checks WBC/BNP final output precision. | Keep `test_final_assembly_enriches_legacy_feature_families`; delete the redundant direct conversion function test. |

Stage tests are **integration tests**, not whole-program E2E tests. Their
file-to-file outputs make them stronger replacements for the duplicated pure
transform checks, but they do not substitute for whole-pipeline acceptance.

## Per-function disposition

116 original functions reviewed: **21 removed, 95 retained**. Existing parametrization adds six cases, giving 101 surviving test cases. No unique scientific assertion was deliberately discarded.

### tests/test_diagnosis_stage.py

| Original function | Disposition and reason |
| --- | --- |
| `test_run_diagnosis_stage_outputs` | Retain file-to-output integration for normalized indicators and overlapping diagnosis families absent from the three-encounter E2E fixture; receives migrated output assertions. |

### tests/test_encounter_stage.py

| Original function | Disposition and reason |
| --- | --- |
| `test_combined_candidate_lookup_matches_patient_or_encounter` | Retain: an encounter-only match with a missing patient ID must survive candidacy. Whole-pipeline E2E has complete IDs and no such candidate. |
| `test_run_encounter_stage_outputs` | Retain file-to-output integration for unsupported types, earliest encounter, missing ED end and negative LOS; receives migrated date/LOS and scratch assertions. |
| `test_encounter_reducer_store_preserves_earliest_encounter` | Retain: later rows arriving before earlier rows and ties across updates can choose the wrong patient/encounter. E2E has no repeated encounter keys. |
| `test_encounter_reducer_same_chunk_ties_keep_first_observed_row` | Retain: a tied key inside one batch must retain its first observed row. E2E has no tied encounter records. |
| `test_encounter_reducer_store_preserves_missing_string_values` | Retain: SQL scratch serialization can turn missing IDs into literal strings. E2E IDs are nonmissing. |
| `test_encounter_reducer_streams_unique_rows_across_batches` | Retain: one-row batch boundaries can skip a retained encounter or retain negative LOS after reduction. E2E lacks these duplicate/negative combinations. |
| `test_encounter_reducer_resolves_cross_setting_ids_globally` | Retain: reducing each setting separately can include an encounter twice or select its wrong setting. E2E has no cross-setting encounter ID. |
| `test_encounter_reducer_reports_cross_setting_conflicts` | Retain: conflicts can silently disappear from the acceptance evidence. E2E contains no conflicting setting rows. |
| `test_run_encounter_stage_removes_reducer_scratch_database` | **Removed.** Identical successful stage rerun consolidated into tests/test_encounter_stage.py::test_run_encounter_stage_outputs with the cleanup assertion retained. |
| `test_encounter_reducer_cleanup_raises_on_delete_error` | Retain fault injection: permission failures must not silently leave private scratch. Normal E2E cannot exercise denied deletion. |

### tests/test_final_assembly.py

| Original function | Disposition and reason |
| --- | --- |
| `test_final_output_columns_match_legacy_schema_fixture` | **Removed.** Independent frozen schema oracle moved to tests/test_pipeline_run.py::test_run_pipeline_end_to_end, which compares actual generated CSV headers to the fixture. |
| `test_recode_base_columns_maps_canonical_ethnicity` | Retain: canonical categories, unknowns and noncanonical aliases have different legacy mappings. E2E contains only Non-Hispanic aliases. |
| `test_final_assembly_enriches_legacy_feature_families` | Retain integration with actual work files and independently asserted final values for multiple clinical families, conversion and precision; full E2E checks few values. |
| `test_legacy_lab_half_dtype_masks_extreme_values_without_warning` | Retain: out-of-range half casting can overflow before missingness masking. E2E labs are small positive values. |
| `test_legacy_lab_float_rules_preserve_float_values` | **Removed.** Float32 versus float16 WBC/BNP output difference already asserted in tests/test_final_assembly.py::test_final_assembly_enriches_legacy_feature_families. |
| `test_lactate_venous_blood_prefers_legacy_converted_code_on_ties` | Retain: equal-date competing lactate codes require a legacy tie preference. E2E has no lactate/ties. |
| `test_previous_vitals_match_executed_notebook_selection_and_int32_output` | Retain multi-file integration: current/future/equal-date and repeated prior encounters must select correct prior vital and preserve integer output. E2E has no prior history. |
| `test_prior_diagnosis_last_date_uses_latest_patient_row` | Retain file integration: future diagnosis dates must not replace the latest eligible prior date. E2E has no past/future repeated diagnosis history. |
| `test_encounter_first_last_features_use_latest_current_date` | Retain file integration: current encounter repeated procedures must preserve both first and last dates. E2E has one procedure date. |
| `test_load_demographics_streams_chunks_and_preserves_output` | Retain: multiple patient files and death YYYYMM parsing must survive chunked loading; E2E only loads one patient file and does not assert death conversion. |
| `test_transform_demographics_restores_legacy_na_without_mutating_source` | Retain: case-sensitive missing tokens must preserve canonical raw data and legacy demographics. Raw-token E2E does not test demographic attributes. |
| `test_load_demographics_detects_duplicate_patient_ids_across_chunks` | Retain: conflicting patients split over files can silently create a join explosion. E2E contains unique patient IDs. |
| `test_load_demographics_lookup_filters_and_cleans_up` | Retain scratch integration: absent lookup keys must be omitted and unrelated patients excluded. E2E has matching patient IDs only. |
| `test_load_demographics_lookup_detects_duplicate_patient_ids_across_chunks` | Retain: SQL-backed loader must reject duplicate IDs and clean scratch on its exception route. E2E IDs are unique. |
| `test_build_final_dataset_matches_demographics_lookup` | Retain adapter equivalence: public final builder accepts frame and disk lookup inputs; an adapter-only field/row mismatch is not caught by whole-pipeline E2E using the lookup path alone. |
| `test_build_final_event_candidates_drops_missing_demographics` | Retain: missing required demographics must not silently include a patient. E2E demographic values are complete. |
| `test_final_event_selection_is_independent_per_setting` | Retain: choosing earliest patient event globally loses a later event in another setting. E2E patients each have only one encounter. |
| `test_streamed_setting_cohort_reduces_earliest_patient_across_partitions` | Retain: cross-partition patient reduction must retain earliest event and its eligibility state. E2E has one event per patient. |
| `test_streamed_event_partitions_are_batched_below_row_limit` | Retain: batching can lose rows or exceed intended working-frame limit at partial boundaries. Tiny E2E does not reach that boundary. |
| `test_current_diagnosis_reduction_uses_earliest_date_and_indicator_priority` | Retain: earliest diagnosis date and independent indicator priority can be incorrectly tied to one source row. E2E has one diagnosis per relevant encounter. |
| `test_inpatient_medication_uses_earliest_date_per_encounter` | Retain: repeated IP medications must select earliest per encounter without mixing patients. E2E has one medication row. |
| `test_outpatient_medication_last_date_validated_independently` | Retain file integration: future prescriptions must not supply prior-medication last date. E2E has no future outpatient medication history. |
| `test_build_final_dataset_matches_encounter_lookup` | Retain adapter equivalence: frame and disk lookup inputs must give the same final records; whole-pipeline E2E exercises the lookup path only. |
| `test_load_data_check_encounter_ids_streams_chunks` | Retain: duplicate and null screen IDs split across chunks must not create invalid allowed keys. E2E has no such supplied screen file. |
| `test_load_data_check_encounter_lookup_filters_and_cleans_up` | Retain scratch integration: lookup must omit unknown screened encounters and deduplicate/null-filter inputs. E2E has no such screen file. |
| `test_data_screen_eligibility_is_precomputed_before_patient_bucketing` | Retain: eligibility must attach to the correct rows before partitioning, while avoiding repeated full-screen scans. E2E does not use the crafted mixed allowed set. |
| `test_precomputed_data_screen_rejects_row_count_drift` | Retain: misaligned precomputed eligibility must fail instead of silently screening the wrong cohort. E2E has no deliberate mismatch. |
| `test_final_output_keeps_data_screen_aligned_after_sorting` | Retain: output sorting can swap eligibility between patients. E2E lacks opposing eligibility on reverse-sorted patients. |
| `test_run_final_assembly_removes_data_check_lookup_scratch` | Retain stage integration: empty cohorts with explicit screen files still must clean every lookup scratch family. Full E2E uses populated cohorts without these files. |
| `test_apply_data_checks_loads_allowed_ids_in_chunks` | Retain legacy API integration: screen-file loading/filtering must preserve original row order under one-row chunks. Whole-pipeline takes the precomputed-screen route. |
| `test_apply_data_checks_reuses_preloaded_allowed_ids` | Retain API branch: supplied screen IDs must work without rereading an unavailable file. Whole-pipeline uses a different precomputed-screen path. |
| `test_load_encounter_streams_work_table_chunks` | Retain legacy loader route: chunk-size propagation and projection must survive an extra input column. Whole-pipeline uses SQL encounter lookup instead. |
| `test_load_encounter_lookup_filters_and_cleans_up` | Retain lookup integration: absent IDs must not create spurious rows or pull unrelated encounters; E2E encounter IDs all match. |
| `test_load_encounter_lookup_detects_duplicate_encounter_ids` | Retain: conflicting duplicate encounter IDs must fail with scratch cleanup rather than multiplying outputs. E2E source is unique. |
| `test_final_event_candidate_store_reduces_by_encounter_only` | Retain: candidate reduction must preserve different encounters of one patient and select earliest duplicate encounter. E2E has one encounter per patient. |
| `test_load_final_event_candidates_cleans_category_scratch_before_return` | Retain pipeline integration: repeated encounters must survive while category scratch is released before next category. E2E lacks repeated encounters and lifecycle boundary inspection. |
| `test_final_event_candidate_store_cleanup_raises_on_delete_error` | Retain fault injection: final event cleanup denial must not be silently swallowed; normal E2E has writable storage. |
| `test_final_encounter_lookup_cleanup_raises_on_delete_error` | Retain fault injection: final encounter cleanup denial must be visible; normal E2E has writable storage. |
| `test_final_lab_candidate_store_cleanup_raises_on_delete_error` | Retain fault injection: lab candidate cleanup denial must be visible; normal E2E has writable storage. |
| `test_final_previous_vital_candidate_store_cleanup_raises_on_delete_error` | Retain fault injection: prior vital cleanup denial must be visible; normal E2E has writable storage. |
| `test_load_rfs_event_streams_parquet_work_table_chunks` | Retain legacy loader route: one-row Parquet batches and column projection must preserve records. Full pipeline uses the streaming candidate-frame route instead. |
| `test_run_final_assembly_reuses_rfs_and_setting_inputs` | Retain bounded-resource orchestration: repeated loading per category/setting or building feature workers after demographics creates large repeated reads/peak allocations that tiny E2E cannot reveal. |

### tests/test_final_feature_sources.py

| Original function | Disposition and reason |
| --- | --- |
| `test_final_feature_sources_scan_once_and_serve_patient_bucket` | Retain subsystem integration: verifies actual per-patient materialization, worker lock transfer and cleanup; global E2E has no lock-transfer oracle. |
| `test_final_feature_source_store_caps_index_chunks` | Retain: ignoring the cap can allocate oversized feature-worker frames on large data; E2E explicitly sets one-row chunks and cannot exercise the default/oversized paths. |
| `test_final_feature_source_worker_failure_cleans_scratch` | Retain failure integration: invalid feature schema must fail and clean partially created scratch. Whole-pipeline happy-path E2E has valid schema. |
| `test_domain_partition_reader_retries_oserror_once_without_threads` | Retain fault injection: transient threaded reads must recover once without retry loops. E2E does not simulate storage failure. |
| `test_domain_partition_reader_persistent_oserror_has_partition_context_only` | Retain privacy fault injection: persistent storage errors must preserve partition context without row values in messages/tracebacks. |
| `test_domain_partition_reader_sanitizes_non_oserror_retry_failure` | Retain privacy fault injection: changing error type on retry must not expose either sensitive underlying error. |
| `test_verified_parquet_read_enables_page_checksum_verification` | Retain integrity control: disabling checksum verification could silently accept storage corruption; E2E writes healthy Parquet. |
| `test_feature_worker_fsyncs_checksummed_bucket_before_complete_metadata` | Retain durability ordering: completion must not precede durable checksummed bytes. Normal E2E cannot emulate power loss. |
| `test_final_feature_bucket_materializes_sources_in_observed_order` | Retain: sorting by storage arrival instead of source row order changes tied clinical selection. E2E has no tied out-of-order feature rows. |

### tests/test_labs_stage.py

| Original function | Disposition and reason |
| --- | --- |
| `test_run_labs_stage_outputs` | Retain file-to-output integration for missing numeric gas, invalid gas unit, feature index and audit counts; receives migrated normalization checks. |
| `test_combined_labs_preserve_raw_na_token_and_transform_it_as_missing` | Retain: raw NULL date must remain in canonical source while legacy normalization treats it as missing. Combined raw-token E2E tests source_id, not a clinical date. |

### tests/test_legacy_na_compatibility.py

| Original function | Disposition and reason |
| --- | --- |
| `test_combined_style_normalizers_restore_legacy_na_semantics` | Retain six-domain compatibility regression: canonical raw tokens must still behave as legacy missing values without mutating raw source. Existing raw-token E2E checks source_id preservation only. |

### tests/test_medications_stage.py

| Original function | Disposition and reason |
| --- | --- |
| `test_run_medications_stage_outputs` | Retain file-to-output integration for historical IP/OP medication groups and missing dates; receives migrated group and normalization checks. |
| `test_combined_stage_captures_ingredient_without_legacy_features` | Retain: minimal-schema ingredient inputs must be captured without contaminating historical feature rows. Standard E2E uses full-schema medication rows. |
| `test_full_schema_ingredient_file_retains_historical_features` | Retain: full-schema ingredient files must retain historical features and additive source candidates. Standard E2E does not cover this file-shape distinction. |

### tests/test_procedure_stage.py

| Original function | Disposition and reason |
| --- | --- |
| `test_run_procedure_stage_outputs` | Retain file-to-output integration for CPAP, TTE, CT, critical-care and SNOMED groups; receives migrated normalization and group assertions. |

### tests/test_rfs_stage.py

| Original function | Disposition and reason |
| --- | --- |
| `test_run_rfs_stage_outputs` | Retain file-to-output integration of the richer RFS fixture; receives exact category membership, entirely negative encounter, patient identity and cleanup assertions. |
| `test_run_rfs_stage_outputs_with_parquet_intermediates` | Retain: fallback reading of existing normalized-domain Parquet files is different from full-pipeline E2E, which uses analysis indexes. |
| `test_rfs_membership_store_builds_flags` | Retain: duplicate and missing membership IDs must not multiply records or activate unrelated flags. Full E2E contains no null membership event. |
| `test_rfs_encounter_store_preserves_first_seen_encounter_row` | Retain: duplicates arriving in different updates must preserve the first patient mapping. Stage duplicate fixture tests one input batch; E2E has no duplicate encounter. |
| `test_run_rfs_stage_removes_bucketed_scratch_directories` | **Removed.** Identical successful stage rerun consolidated into tests/test_rfs_stage.py::test_run_rfs_stage_outputs with both cleanup assertions retained. |
| `test_rfs_membership_store_cleanup_raises_on_delete_error` | Retain fault injection: failed membership-scratch deletion must be visible. Successful E2E cannot cover denial. |
| `test_rfs_encounter_store_cleanup_raises_on_delete_error` | Retain fault injection: failed encounter-scratch deletion must be visible. Successful E2E cannot cover denial. |
| `test_run_rfs_stage_preserves_duplicate_events_and_first_encounter` | Retain file-to-output integration: two qualifying lab events remain two event rows while duplicate encounters retain the original patient. E2E has one event per encounter. |

### tests/test_traditional_catalog.py

| Original function | Disposition and reason |
| --- | --- |
| `test_combined_catalog_preserves_glp1_catalog_and_adds_all_legacy_candidates` | Retain: omissions of unobserved rule families or alteration of pinned Stata source authority can pass populated-row E2E. Checks catalog bridge/provenance independently of observed synthetic rows. |
| `test_source_candidacy_uses_codes_without_legacy_value_or_cohort_gates` | Retain: applying eligibility/value thresholds during candidacy permanently drops future reusable source evidence. E2E does not cover all LOCAL/low-value rule combinations. |
| `test_complete_source_relations_ignore_legacy_candidate_masks` | Retain two-domain writer integration: patient/encounter capture must ignore a restrictive legacy mask. Normal E2E does not explicitly force a false mask on an otherwise complete source row. |

### tests/test_transform_diagnosis.py

| Original function | Disposition and reason |
| --- | --- |
| `test_normalize_diagnosis_chunk_structure` | **Removed.** Output checks migrated to tests/test_diagnosis_stage.py::test_run_diagnosis_stage_outputs (file-to-output integration). |
| `test_split_diagnosis_by_code_groups` | **Removed.** All group output checks consolidated in tests/test_diagnosis_stage.py::test_run_diagnosis_stage_outputs. |
| `test_j46_includes_corrected_j4542_code` | Retain: losing corrected J45.42 silently changes the asthma feature. No existing E2E or stage fixture contains this code. |
| `test_split_diagnosis_preserves_duplicate_overlapping_rows` | Retain: repeated G47.34 must remain in both overlapping groups without deduplication. E2E has no duplicate diagnosis row. |

### tests/test_transform_encounter.py

| Original function | Disposition and reason |
| --- | --- |
| `test_trinetx_datetime_coercion_is_opt_in` | Retain: strict parsing must reject malformed input while opt-in coercion yields missing values. E2E has valid dates only. |
| `test_normalize_encounter_chunk_filters_types` | **Removed.** Output checks migrated to tests/test_encounter_stage.py::test_run_encounter_stage_outputs. |
| `test_finalize_ambulatory_encounters` | **Removed.** Selected ID/start/end/LOS checked in tests/test_encounter_stage.py::test_run_encounter_stage_outputs. |
| `test_filter_encounters_for_types_matches_individual_filters` | **Removed.** Same-implementation self-consistency oracle removed. Actual independently expected selected encounters are checked by tests/test_encounter_stage.py::test_run_encounter_stage_outputs; all settings also flow through tests/test_pipeline_run.py::test_run_pipeline_end_to_end. |
| `test_finalize_emergency_encounters_fill_end_date` | **Removed.** Observed end date/LOS checks consolidated in tests/test_encounter_stage.py::test_run_encounter_stage_outputs. |
| `test_finalize_inpatient_encounters_removes_negative_los` | **Removed.** Selected ID/LOS checks consolidated in tests/test_encounter_stage.py::test_run_encounter_stage_outputs. |

### tests/test_transform_lab_features.py

| Original function | Disposition and reason |
| --- | --- |
| `test_lab_feature_rules_use_exact_codes_and_correct_bounds` | Retain: accepting a code prefix or the excluded pH boundary changes clinical output. E2E does not contain those negative/boundary values. |
| `test_lab_feature_rules_apply_venous_lactate_conversion` | Retain: whitespace-normalized converted code and unconverted code must agree. Whole-pipeline E2E has no lactate, and final-assembly tie fixture tests a different boundary. |
| `test_lab_feature_rules_convert_only_matching_rows` | Retain: converting every lab row for every rule causes repeated large allocations on private data. Small E2E inputs cannot expose this; the probe verifies irrelevant rows never enter the conversion. |
| `test_stacked_lab_feature_rows_carries_rule_name_only` | **Removed.** Actual index labels checked by tests/test_labs_stage.py::test_run_labs_stage_outputs; downstream schema consumption exercised by tests/test_pipeline_run.py::test_run_pipeline_end_to_end_with_parquet_intermediates. Removed one-row frame/constant shape check. |

### tests/test_transform_labs.py

| Original function | Disposition and reason |
| --- | --- |
| `test_normalize_lab_results_chunk_structure` | **Removed.** All output checks migrated to tests/test_labs_stage.py::test_run_labs_stage_outputs; now-empty unit module deleted. |

### tests/test_transform_medications.py

| Original function | Disposition and reason |
| --- | --- |
| `test_normalize_medications_chunk_structure` | **Removed.** Output checks migrated to tests/test_medications_stage.py::test_run_medications_stage_outputs. |
| `test_split_medications_by_code_groups` | **Removed.** All group checks consolidated in tests/test_medications_stage.py::test_run_medications_stage_outputs. |
| `test_split_medications_preserves_duplicate_overlapping_rows` | Retain: duplicated medication belongs to both IP and OP groups without losing multiplicity. E2E medication is a single row. |

### tests/test_transform_procedure.py

| Original function | Disposition and reason |
| --- | --- |
| `test_normalize_procedure_chunk_structure` | **Removed.** Output checks migrated to tests/test_procedure_stage.py::test_run_procedure_stage_outputs. |
| `test_split_procedure_by_code_groups` | **Removed.** All group checks consolidated in tests/test_procedure_stage.py::test_run_procedure_stage_outputs. |
| `test_tte_excludes_legacy_typos_and_non_tte_modalities` | Retain: TEE/stress echo and the legacy typo must not become TTE; no E2E contains these exclusion codes. |
| `test_split_procedure_preserves_duplicate_overlapping_rows` | Retain: duplicate TTE procedure rows must remain duplicated. E2E has one procedure row. |

### tests/test_transform_rfs.py

| Original function | Disposition and reason |
| --- | --- |
| `test_derive_rfs_encounter_sets` | **Removed.** Exact category membership migrated to tests/test_rfs_stage.py::test_run_rfs_stage_outputs; all categories also traverse tests/test_pipeline_run.py::test_run_pipeline_end_to_end. |
| `test_obesity_bmi_rfs_filters_in_float64_before_storage_downcast` | Retain: premature rounding can admit BMI 39.99 or 100.01; extreme values can overflow. E2E BMI is 45. |
| `test_gas_rules_are_specimen_specific_unit_aware_and_strictly_above_45` | Retain: wrong specimen/system/unit and the exact threshold can misclassify legacy RFS. Full E2E has only valid positive gas examples. |
| `test_gas_audit_counts_missing_units_as_rejected` | Retain: NULL unit can escape rejection accounting under three-valued missingness. E2E uses present mmHg units. |
| `test_predisposition_uses_literal_prefixes_not_regex_stars` | Retain: treating code prefixes as regex can include tobacco/insomnia or miss opioid diagnosis. E2E has no such contrastive code set. |
| `test_typed_rules_normalize_codes_and_systems_once` | Retain: mixed-case and padded inputs can lose clinical membership. E2E input uses already-normalized codes/systems. |
| `test_derive_rfs_encounter_flags` | **Removed.** Positive/negative flags, schema and patient association consolidated in tests/test_rfs_stage.py::test_run_rfs_stage_outputs. |

### tests/test_transform_vitals.py

| Original function | Disposition and reason |
| --- | --- |
| `test_normalize_vitals_chunk_structure` | **Removed.** Output checks migrated to tests/test_vitals_stage.py::test_run_vitals_stage_outputs. |
| `test_split_vitals_by_rule_filters` | **Removed.** All value/count checks consolidated in tests/test_vitals_stage.py::test_run_vitals_stage_outputs. |
| `test_new_temperature_preserves_float64_value_before_output_cast` | Retain: early downcasting changes 98.3 prior to final storage. E2E has no temperature and stage fixture value 98.6 does not expose the same rounding. |
| `test_fahrenheit_to_celsius_temperature_uses_legacy_float32_input` | Retain: conversion order can break legacy precision for 98.3 F. E2E has no temperature. |
| `test_new_temperature_drops_extreme_values_without_overflow_warning` | Retain: extreme values can overflow during cast before exclusion. E2E has no extreme temperature. |
| `test_apply_vital_sign_rule_filters_before_float16_downcast` | Retain: premature half rounding admits/excludes wrong BP boundary rows and can overflow. E2E has no BP boundaries. |

### tests/test_vitals_stage.py

| Original function | Disposition and reason |
| --- | --- |
| `test_run_vitals_stage_outputs` | Retain file-to-output integration for Fahrenheit conversion and multiple vital families omitted from full E2E; receives migrated output checks. |

## Verification

The following commands ran in the existing pinned project environment via
`UV_PROJECT_ENVIRONMENT`, with offline dependency reuse:

```bash
uv run --offline --no-sync pytest -q tests/test_transform_*.py tests/test_*_stage.py tests/test_final_feature_sources.py tests/test_final_assembly.py tests/test_legacy_na_compatibility.py tests/test_traditional_catalog.py
uv run --offline --no-sync ruff check tests/test_transform_*.py tests/test_*_stage.py tests/test_final_feature_sources.py tests/test_final_assembly.py tests/test_legacy_na_compatibility.py tests/test_traditional_catalog.py
uv run --offline --no-sync ruff format --check tests/test_transform_*.py tests/test_*_stage.py tests/test_final_feature_sources.py tests/test_final_assembly.py tests/test_legacy_na_compatibility.py tests/test_traditional_catalog.py
git diff --check
```

Results: **101 passed in 11.23 seconds**; Ruff checks passed; all 18 surviving
owned test modules were already formatted; diff whitespace check passed.
The deleted module has no live references outside this historical inventory.
Whole-repository E2E verification and its repeatable artifact are coordinated
in the overall testing review, outside this subtask.

No production code, scientific expectations, accepted input bytes, private
data products, or gate tolerances changed. The real-data readmissions goal
remains blocked. These test results do not satisfy its private acceptance gate.

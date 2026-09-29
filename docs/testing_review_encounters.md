# Encounter and handoff test review

Reviewed 2026-09-25 against the tests present at `8a1185b`. Scope: the eight
files below; `test_encounter_stage.py` belongs to the clinical-stage review.

The review considered every original test function and its parameter cases.
It removed four functions/cases: **79 functions / 119 cases become 75 functions /
115 cases**. No runtime code, scientific expectation, validator assertion,
fixture helper or acceptance requirement changed. No new isolated tests were
written.

## Coverage used for deletion

The global pipeline E2E tests verify CSV/Parquet builds and the 36-file contract,
but do not execute the separate encounter enrichment and return interfaces.
Their small fixtures do not exercise interrupted transactions, deliberately
corrupt receipts, key collisions, mixed precision or unsupported gas units.
Deleting those cases would remove protection against concrete failures that
the current E2E tests miss.

Three removals use more complete existing component integration tests. These
are identified accurately below; they are not described as full source-to-return
E2E tests. The fourth removal asserted process import state without proving an
observable architectural contract.

| Removed function | Existing coverage or reason |
| --- | --- |
| `test_no_analysis_model_dependencies` | Checks only whether `xgboost` and `sklearn` happen to be in the pytest process's `sys.modules`; it neither verifies the dependency graph nor exercises model behavior. It can fail because another test imported a module. It establishes no useful independent product contract. |
| `test_link_evidence_reconciliation_detects_unreported_tampering` | `test_bundle_validation_resume_and_tampering` performs the identical same-day `abg_gt50` alteration in a published Parquet artifact, refreshes manifest/progress hashes and requires `validate_returns` to reject it. The direct SQL query probe adds no distinct corruption. |
| `test_evidence_schema_is_checked_after_refreshing_manifest_identity` | `test_domain_specific_required_fields_cannot_be_removed` invokes the same real bundle validator after refreshing hashes and removes required diagnosis, lab, BP and medication fields individually. The all-but-one-column deletion adds no distinct schema gate. |
| `test_acceptance_receipt_readback_binds_report_manifest_policy_and_variants` | `test_receipt_readback_accepts_actual_synthetic_validator_report` checks the same successful readback against an actual bundle-validator report and both variants. The hand-written successful report adds no distinct binding check. All negative receipt cases remain. |

## Complete function inventory

“Retain” includes component integration, workflow, adversarial and isolated
tests. For each retained isolated case, the last column states the concrete
failure absent from current broader E2E coverage. Parameter cases retain their
original expectations.

### `tests/test_encounter_checkpoints.py`

| Original function | Decision | Failure or coverage |
| --- | --- | --- |
| `test_failed_stage_rolls_back_and_completed_stage_survives_reopen` | Retain | Interrupted transaction must leave no checkpoint/table; reopened cache must reuse completed work and reject row-count tampering. Happy-path enrichment resume never interrupts a transaction. |
| `test_cache_rejects_changed_binding_and_unbound_old_database` | Retain | Prevent reuse after source/code changes or adoption of an unbound old database; broader builds use a valid current binding. |
| `test_checkpoint_fingerprint_detects_same_count_value_or_duplicate_change` | Retain | Catch value edits and duplicate replacement that preserve row count and schema. E2E does not corrupt persistent stage caches this way. |
| `test_checkpoint_fingerprint_preserves_null_dates_and_duplicate_multiplicity` | Retain | Reordered NULL/date/duplicate rows must remain resumable with an identical multiset; avoids invalid rejection after storage reordering. |
| `test_legacy_checkpoint_receipt_requires_explicit_adoption` | Retain | Old receipts without a content fingerprint must not silently authorize cached data. Current successful workflow creates only new receipts. |

### `tests/test_encounter_compatibility.py`

| Original function | Decision | Failure or coverage |
| --- | --- | --- |
| `test_exact_parser_roundtrip` | Retain | Real 36-part import/readback must preserve leading zeros, sentinels, duplicates and rounding exactly, and reject a changed companion database. Canonical CSV export E2E does not exercise this importer. |
| `test_changed_input_fails_before_import` | Retain | Altered authenticated CSV must fail before creating a companion database. A successful roundtrip alone cannot verify pre-write rejection. |
| `test_cleaned_key_collision_fails_before_enrichment` | Retain | Base publication must reject ambiguous concatenated patient/encounter keys; this is a different entry point from enrichment's collision guard. |
| `test_both_legacy_bases_preserve_original_keys` | Retain | Real companion import and two-variant base construction preserve original composite keys, repeated encounters and legacy numeric IDs. |

### `tests/test_encounter_coverage.py`

| Original function | Decision | Failure or coverage |
| --- | --- | --- |
| `test_coverage_corroborates_keys_and_preserves_unavailable` | Retain | Real coverage tables must distinguish unavailable domains, incomplete capture, demographic contradiction and both medication export names; generic E2E lacks this mixed case. |
| `test_complete_linkage_policy_fails_one_unlinked_composite_encounter` | Retain | A linked patient with a missing encounter must fail strict coverage; patient-only success must not substitute for composite linkage. |
| `test_zero_encounter_source_never_passes_as_complete_or_corroborated` | Retain | Empty cohorts must not pass vacuously or fabricate proportions; relaxed policy still requires an exception. |
| `test_nonempty_legacy_population_with_zero_linked_source_fails_exception` | Retain | An exception must not turn wholly absent source linkage into accepted coverage. Distinct from the empty-population case. |
| `test_unrecognized_audit_domain_cannot_hide_observed_records` | Retain | Contradictory domain metadata must fail even for an empty index population; successful source builds have recognized audit names. |
| `test_cli_rejects_linkage_policy_outside_coverage_only` | Retain | Reject a policy option in an inapplicable command mode rather than silently ignore it; no existing E2E invokes that invalid combination. |

### `tests/test_encounter_features.py`

| Original function | Decision | Failure or coverage |
| --- | --- | --- |
| `test_encounter_population_and_imputation` | Retain | Both compatibility variants must consume all 18 inputs, preserve repeated encounters and keys, and apply imputation only to AFTER. Base publication tests do not assert these distinct transformations. |
| `test_no_analysis_model_dependencies` | Remove | Process-global import-state assertion; see deletion rationale above. |
| `test_enrichment_preserves_non_glp1_encounters` | Retain | Real enrichment must not study-filter indexes and must retain unknown evidence; cached rerun must preserve all values without re-extracting completed source stages. |
| `test_ordered_merge_preserves_master_and_fills_only_missing` | Retain | Preserve conflicting master values, fill missing values and retain using-only rows with Stata merge indicators; broad output tests do not assert this conflict fixture. |
| `test_catalog_evidence_time_boundaries_source_keys_and_overlap` | Retain | Actual catalog-evidence pipeline checks inclusive day windows, patient/encounter isolation, duplicate multiplicity, NULL dates, multi-element overlap and partition invariance. |
| `test_source_key_collision_rejected_before_enrichment` | Retain | Enrichment entry point must reject ambiguous keys independently of base publication, before it can join unrelated patients. |
| `test_builder_rejects_existing_output_without_touching_source` | Retain | Public encounter builder must reject an existing destination before reading or modifying source; other builders have separate guards. |
| `test_observability_uses_same_calendar_day_as_features` | Retain | Same-day times and lookback-boundary times must agree with calendar-day feature windows; main enrichment fixture uses ordinary day strings. |
| `test_encounter_context_prunes_unused_keys_without_changing_first_row` | Retain | Partitioned projection must preserve tie selection, NULL handling, patient-scoped shared encounter IDs and left-join multiplicity across 1/7/64 partitions. |
| `test_context_files_ignore_appledouble_and_fail_on_metadata_only` | Retain | macOS sidecars must not be read as Parquet or count as a populated context partition. The element helper is separate code. |
| `test_context_failure_preserves_original_error_and_rolls_back` | Retain | Corrupt Parquet during a cached stage must preserve the original error, avoid a completed checkpoint and preserve recovery evidence. |
| `test_element_partition_sidecars_are_not_data` | Retain | Separate element partition file collector must exclude AppleDouble files and fail on metadata-only directories; normal E2E creates no sidecars here. |
| `test_chunked_wide_output_preserves_join_multiset` | Retain | Partitioned writer must preserve schema, missing joins and exact rows relative to an unpartitioned join. Broader tests do not compare this partial-coverage join fixture. |

### `tests/test_encounter_returns.py`

| Original function | Decision | Failure or coverage |
| --- | --- | --- |
| `test_returns_preserve_union_thresholds_missingness_and_recurrence` | Retain | Partition build writes inspectable evidence/links/summaries with recurrent events, strict/inclusive thresholds, unavailable anchors and rejection reasons. Bundle self-consistency alone is not an independent expected-answer oracle. |
| `test_duplicate_return_link_rejected` | Retain | Duplicate index keys must fail before duplicate return links can be published; successful bundle test contains unique indexes. |
| `test_link_evidence_reconciliation_detects_unreported_tampering` | Remove | Identical mutation is rejected through full return-artifact validation in `test_bundle_validation_resume_and_tampering`. |
| `test_link_geometry_reconciliation_detects_changed_return_time` | Retain | Detect changed linked return time against episode geometry; the broader tampering test changes gas flags and summary metrics, not dates. |
| `test_episode_source_mapping_reconciliation_detects_changed_start` | Retain | Detect source-to-episode start disagreement; broader return test does not corrupt episode-source mappings. |
| `test_ed_index_inpatient_return_is_admission` | Retain | ED-only index must label a subsequent inpatient event admission rather than readmission; broader positive-return fixture has an inpatient index. |
| `test_crossing_episode_is_retained_as_overlap_uncertainty` | Retain | Episode starting before discharge and ending afterward must remain observable uncertainty without increasing confirmed outcomes. |
| `test_reversed_return_dates_cannot_be_confirmed` | Retain | Start-after-end return must be excluded from confirmed counts and reported as invalid chronology; absent from happy-path fixture. |
| `test_missing_canonical_icd_rule_blocks_build` | Retain | Incomplete source-capture rule set must fail, preventing false-negative diagnosis outcomes; canonical E2E uses the complete current catalog. |
| `test_gas_conversion_overflow_is_rejected` | Retain | Finite raw kPa converting to infinity must not qualify as hypercapnia. Ordinary-value E2E cannot catch this numeric failure. |
| `test_wildcard_exact_icd_rule_retains_required_code` | Retain | Exact wildcard capture is sufficient; narrower preflight previously caused a false private-data block. Standard return fixture has explicit ICD10CM rules. |
| `test_derived_index_end_is_unavailable` | Retain | Derived discharge must not authorize time-to-return outcomes. Broad fixture only tests a missing discharge. |
| `test_conflicting_death_month_remains_unknown` | Retain | Contradictory death months must not silently choose one; normal fixture has one value. |
| `test_precise_same_day_kpa_and_derived_return_start` | Retain | Existing timestamp branch, kPa conversion and derived-start exclusion remain behavior under review. Contract repair may replace these expectations only through the approved scientific change. |
| `test_patient_partition_outputs_agree_with_unpartitioned` | Retain | Splitting patients must not change the selected summary outcomes; this is partial partition equivalence, not proof across every artifact/column. |
| `test_bundle_validation_resume_and_tampering` | Retain | Full return-artifact lifecycle verifies variant counts, producing-code/parent identity, rehashed tampering, incomplete progress, stale partition settings, output collisions and resume. External parent/source validation is stubbed, so this is not complete source-to-return E2E. |

### `tests/test_encounter_validation.py`

| Original function | Decision | Failure or coverage |
| --- | --- | --- |
| `test_complete_bundle_requires_element_and_domain_coverage` | Retain | Real validator checks a full two-variant synthetic bundle, evidence counts, normalization reconciliations and sidecar preservation. |
| `test_previous_bundle_format_revalidates_without_mutation` | Retain | Legacy policy representation must remain readable without modifying immutable manifest/coverage bytes. |
| `test_encounter_validation_memory_override_preserves_checks` | Retain | Bounded and original validation paths must produce identical reports; invalid limits must fail instead of silently changing execution policy. |
| `test_bounded_distinct_counts_preserve_duplicates_and_nulls` | Retain | Partitioned exact counts must preserve SQL tuple-NULL and scalar-NULL distinctions plus duplicates; complete parent fixture does not include NULL evidence keys. |
| `test_previous_bundle_incomplete_linkage_requires_explicit_exception` | Retain | Legacy incomplete linkage must fail strict validation and require a documented explicit exception; no automatic fallback. |
| `test_partial_new_policy_declaration_never_falls_back_to_legacy` | Retain | Missing pieces of a new policy declaration must not masquerade as an older contract. |
| `test_versioned_bundle_rejects_conflicting_validation_policy` | Retain | Operator validation options must not override the bundle's declared scientific coverage policy. |
| `test_element_inventory_must_cover_every_required_element` | Retain | Omitting a required catalog element must fail even if remaining artifacts are valid. |
| `test_evidence_schema_is_checked_after_refreshing_manifest_identity` | Remove | Same refreshed-hash schema gate exercised more specifically by `test_domain_specific_required_fields_cannot_be_removed`. |
| `test_changed_selected_summary_value_date_or_unit_fails` | Retain | Rehashed selected value, date or unit corruption must fail independent reconciliation. Happy-path E2E does not corrupt these fields. |
| `test_catalogue_baseline_uses_manifest_window_not_stored_flag` | Retain | Jointly falsified stored eligibility flags and summaries must still fail authoritative time-window checks; exact boundaries must pass. |
| `test_domain_specific_required_fields_cannot_be_removed` | Retain | Rehashed evidence missing diagnosis/lab/BP/medication contract fields must fail the real bundle validator. |
| `test_incompatible_evidence_identifier_type_fails_schema_validation` | Retain | Correct field names with incompatible identifier types must not pass schema checks. |
| `test_typed_empty_evidence_domain_passes_schema_contract` | Retain | Legitimately empty but correctly typed evidence must pass; protects against treating no tests as a malformed domain. |
| `test_qa_missingness_is_recomputed_independently` | Retain | Incorrect missingness totals must fail after hashes are refreshed; hashes cannot certify arithmetic. |
| `test_coverage_totals_are_recomputed_from_typed_coverage_rows` | Retain | Coverage summary totals must agree with row-level evidence rather than trusting a self-consistent receipt alone. |
| `test_strict_policy_rejects_zero_linkage_despite_matching_declared_counts` | Retain | Mutating both linkage rows and declared counts must not turn zero source linkage into strict acceptance. |
| `test_linkage_flags_must_agree_across_coverage_domains` | Retain | A single domain cannot disagree on the same index's source linkage. |
| `test_element_availability_counts_are_recomputed_from_evidence` | Retain | False observed/zero-match counts must fail evidence reconciliation despite refreshed identities. |
| `test_evidence_keys_must_belong_to_the_current_variant` | Retain | Evidence from another variant or index must not attach to the current population. |
| `test_acceptance_receipt_readback_binds_report_manifest_policy_and_variants` | Remove | Successful readback is exercised with a real validator report by the next test. |
| `test_receipt_readback_accepts_actual_synthetic_validator_report` | Retain | Real bundle validator output must produce a verifiable acceptance receipt across both variants; avoids hand-written producer/consumer drift. |
| `test_receipt_and_report_cannot_share_missing_identity` | Retain | Receipt and report both omitting the same identity must fail, rather than pass a simple equality comparison. |
| `test_receipt_rejects_unsupported_report_version` | Retain | A supported receipt must not authenticate an unsupported report contract. |
| `test_acceptance_receipt_rejects_invalid_identity_types` | Retain | NULL variants/hashes and boolean byte/row counts must not pass permissive Python type comparisons. |
| `test_acceptance_receipt_rejects_wrong_or_incomplete_bindings` | Retain | Wrong manifest/policy/variant/producer/report bytes and failed or missing trusted gates must reject acceptance. |
| `test_validate_cli_writes_structured_failure_report` | Retain | CLI must return failure and write machine-readable failure evidence for an unreadable bundle; successful workflows do not exercise this output. |

### `tests/test_encounter_vital_selection.py`

| Original function | Decision | Failure or coverage |
| --- | --- | --- |
| `test_selection_proof_counts_duplicates_nulls_and_inconsistent_membership` | Retain | Fast-path proof must detect inconsistent membership while preserving duplicate/NULL semantics; ordinary E2E uses internally consistent catalog membership. |
| `test_fast_path_requires_exact_current_source_acceptance` | Retain | Reject stale source/catalog/query identities, nonzero differences and missing counts before using the optional optimization. |
| `test_nonexact_catalog_cannot_use_exact_fast_path` | Retain | Future prefix rules must not be processed by an exact-only optimization. Current catalog E2E contains exact vital rules. |
| `test_cli_forwards_optional_receipt_and_cache` | Retain | Optional acceptance/cache arguments must reach the enrichment builder; no current E2E exercises these CLI options. Silent omission changes requested validation/recovery behavior. |
| `test_cli_rejects_vital_optimization_outside_enrichment` | Retain | Reject inapplicable optimization options in legacy/coverage modes instead of silently accepting ineffective requests. |
| `test_vital_projection_preserves_scope_duplicates_and_raw_fields` | Retain | Real original/optimized source projection must retain the same patient scope, duplicate rows and raw fields, and reject use in another domain. |

### `tests/test_handoff_lock.py`

| Original function | Decision | Failure or coverage |
| --- | --- | --- |
| `test_lock_survives_exec_rejects_duplicate_and_releases` | Retain | Actual subprocess execution must inherit the advisory lock, prevent duplicate launch and release on termination without replacing its inode. |
| `test_launcher_holds_controller_lock_through_shells` | Retain | Actual shell launcher adds another process boundary and controller lock; it must still block a concurrent launch and copy the operator instructions. |

## Remaining coverage gaps

The review does not resolve the defects in [RETURN_AUDIT.md](RETURN_AUDIT.md).
In particular, current passing tests do not establish real parent-producer schema
compatibility, source-to-return completeness, correct mixed/NULL precision,
independent evidence conversion, or resumed execution using the real parent
validator. Return partition comparison currently covers selected summary fields,
not the complete output multiset. Those are requirements for the future E2E
repair workflow, not reasons to delete the available protections or declare C3
complete. Scientific decisions D1-D6 are provisionally accepted; this pruning
does not change the runtime contract or relaunch the blocked goal.

## Verification

The eight owned files were collected with the pinned environment before edits:
119 cases. The surviving suite is run with pytest's JUnit XML output outside the
repository so its exact case inventory and results are inspectable. Runtime
artifacts and the receipt are synthetic and do not represent private acceptance.

```bash
uv run --offline --no-sync pytest -q \
  tests/test_encounter_checkpoints.py tests/test_encounter_compatibility.py \
  tests/test_encounter_coverage.py tests/test_encounter_features.py \
  tests/test_encounter_returns.py tests/test_encounter_validation.py \
  tests/test_encounter_vital_selection.py tests/test_handoff_lock.py \
  --junitxml="$TEST_ARTIFACT_DIR/encounter-audit.xml"
uv run --offline --no-sync ruff check \
  tests/test_encounter_features.py tests/test_encounter_returns.py \
  tests/test_encounter_validation.py
uv run --offline --no-sync ruff format --check \
  tests/test_encounter_features.py tests/test_encounter_returns.py \
  tests/test_encounter_validation.py
```

Set `UV_PROJECT_ENVIRONMENT` to the pinned project environment and
`TEST_ARTIFACT_DIR` to an existing external synthetic-test artifact directory.
The surviving tests passed: **115 passed, 238 existing pandas fragmentation
warnings, 425.56 seconds**. The external JUnit report was read back and its case
count checked. Ruff check, format checks and `git diff --check` passed for all
three changed files. An AST inventory check verified that all 79 original
functions appear in the review and that exactly the four listed functions were
removed.

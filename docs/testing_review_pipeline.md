# Pipeline test review

Review date: 2026-09-25. Scope: CLI, complete preprocessing, cohort-source,
configuration, storage, filesystem, hashing, profiling and work-manifest tests.
Production code and acceptance gates are unchanged.

## Failure modes recorded before changing the E2E assertion

The existing full pipeline test compared generated output columns with a constant
imported from the implementation. If both changed together, it could accept an
unapproved compatibility-schema change. Compare each generated CSV schema with
the independent `tests/fixtures/final_output_columns.json` fixture instead. This
moves the existing independent oracle into the real pipeline test; the fixture
and expected columns remain unchanged.

A second existing oracle concerns logical hash keys: a Parquet intermediate must
retain its `.csv` logical name in a baseline manifest. Otherwise a CSV/Parquet
comparison can report artificial differences. Move the existing `RFS_ABG`
logical-key assertion into the full baseline/compare/profile E2E before deleting
the isolated path-normalization checks.

## Review criteria

Remove isolated assertions duplicated by retained workflow tests, trivial
implementation bookkeeping, or helpers with no production call path. Retain
adversarial checks when successful E2E fixtures do not exercise the concrete
failure: corrupted artifacts, source multiplicity, resume identity, unsafe paths,
interrupted publication, failed durability, lock ownership, memory bounds or
clinical-source preservation. A mocked callback is not E2E coverage by itself;
where retained, its bounded failure and the missing E2E scenario are stated.

The inventory below records every original function, including retained
functions. References name exact retained test node IDs rather than claiming
that a happy-path run proves all exceptional behavior.

## Inventory
Original functions: **239**. Removed: **33**. Retained: **206**. Parameterized cases are not counted as separate functions.
Retained isolated checks remain only where the table identifies a concrete condition missing from current E2E fixtures. Future additions follow the failure-first policy.

### `test_cli.py`
| Original function | Decision | Failure rationale / retained workflow evidence |
|---|---|---|
| `test_validate_inputs_accepts_minimal_medication_ingredient_schema` | Retain | Distinct operator boundary/failure: validate inputs accepts minimal medication ingredient schema. It is not exercised by the successful full-run route. |
| `test_validate_inputs_rejects_incomplete_medication_ingredient_schema` | Retain | Distinct operator boundary/failure: validate inputs rejects incomplete medication ingredient schema. It is not exercised by the successful full-run route. |
| `test_run_uses_combined_builder_when_enabled` | Retain | Distinct operator boundary/failure: run uses combined builder when enabled. It is not exercised by the successful full-run route. |
| `test_build_preprocessed_cli_rejects_path_overlap_during_validation` | Retain | Distinct operator boundary/failure: build preprocessed cli rejects path overlap during validation. It is not exercised by the successful full-run route. |
| `test_export_legacy_cli_routes_atomic_replacement_flag` | Retain | Distinct operator boundary/failure: export legacy cli routes atomic replacement flag. It is not exercised by the successful full-run route. |
| `test_export_legacy_cli_reports_expected_lifecycle_failures` | Retain | Distinct operator boundary/failure: export legacy cli reports expected lifecycle failures. It is not exercised by the successful full-run route. |
| `test_validate_preprocessed_cli_guards_scratch_roots_before_validation` | Retain | Distinct operator boundary/failure: validate preprocessed cli guards scratch roots before validation. It is not exercised by the successful full-run route. |
| `test_validate_cohort_source_cli_accepts_repeated_elements_and_json` | Retain | Distinct operator boundary/failure: validate cohort source cli accepts repeated elements and json. It is not exercised by the successful full-run route. |
| `test_validate_preprocessed_cli_rejects_repository_local_database` | Retain | Distinct operator boundary/failure: validate preprocessed cli rejects repository local database. It is not exercised by the successful full-run route. |
| `test_validate_preprocessed_cli_rejects_repository_local_compatibility_root` | Retain | Distinct operator boundary/failure: validate preprocessed cli rejects repository local compatibility root. It is not exercised by the successful full-run route. |
| `test_validate_preprocessed_cli_rejects_repository_local_hash_parent_symlink` | Retain | Distinct operator boundary/failure: validate preprocessed cli rejects repository local hash parent symlink. It is not exercised by the successful full-run route. |
| `test_every_combined_mutating_route_guards_work_and_output` | Retain | Distinct operator boundary/failure: every combined mutating route guards work and output. It is not exercised by the successful full-run route. |
| `test_run_domain_probe_command_returns_none_on_timeout` | Retain | Distinct operator boundary/failure: run domain probe command returns none on timeout. It is not exercised by the successful full-run route. |
| `test_run_domain_probe_command_uses_file_output_and_polling_after_timeout` | Retain | Distinct operator boundary/failure: run domain probe command uses file output and polling after timeout. It is not exercised by the successful full-run route. |
| `test_timeout_inspection_skips_remaining_after_unreleased_probe` | Retain | Distinct operator boundary/failure: timeout inspection skips remaining after unreleased probe. It is not exercised by the successful full-run route. |
| `test_clean_scratch_dry_run_reports_known_artifacts` | Retain | Scratch-cleanup lifecycle dry run reports known artifacts; verifies actual files or an injected deletion fault absent from successful builds. |
| `test_clean_scratch_delete_removes_only_known_artifacts` | Retain | Scratch-cleanup lifecycle delete removes only known artifacts; verifies actual files or an injected deletion fault absent from successful builds. |
| `test_clean_scratch_recognizes_current_partition_stores` | Retain | Scratch-cleanup lifecycle recognizes current partition stores; verifies actual files or an injected deletion fault absent from successful builds. |
| `test_clean_scratch_preserves_persistent_lock_appledouble_sidecars` | Retain | Scratch-cleanup lifecycle preserves persistent lock appledouble sidecars; verifies actual files or an injected deletion fault absent from successful builds. |
| `test_clean_scratch_delete_tolerates_missing_nested_entries` | Retain | Scratch-cleanup lifecycle delete tolerates missing nested entries; verifies actual files or an injected deletion fault absent from successful builds. |
| `test_clean_scratch_delete_propagates_directory_delete_errors` | Retain | Scratch-cleanup lifecycle delete propagates directory delete errors; verifies actual files or an injected deletion fault absent from successful builds. |
| `test_clean_scratch_delete_raises_when_directory_remains` | Retain | Scratch-cleanup lifecycle delete raises when directory remains; verifies actual files or an injected deletion fault absent from successful builds. |
| `test_validate_config_cli` | Retain | Distinct operator boundary/failure: validate config cli. It is not exercised by the successful full-run route. |
| `test_run_encounter_cli` | Retain | Distinct operator boundary/failure: run encounter cli. It is not exercised by the successful full-run route. |
| `test_run_labs_cli` | Retain | Distinct operator boundary/failure: run labs cli. It is not exercised by the successful full-run route. |
| `test_run_final_assembly_cli_with_parquet_intermediates` | Retain | Distinct operator boundary/failure: run final assembly cli with parquet intermediates. It is not exercised by the successful full-run route. |
| `test_inspect_inputs_cli_reports_missing_domains` | Retain | Real CLI input-inspection route reports missing domains; preprocessing E2E does not exercise this operator mode. |
| `test_inspect_inputs_cli_allow_missing_returns_success` | Retain | Real CLI input-inspection route allow missing returns success; preprocessing E2E does not exercise this operator mode. |
| `test_inspect_inputs_cli_json_reports_missing_domains` | Retain | Real CLI input-inspection route json reports missing domains; preprocessing E2E does not exercise this operator mode. |
| `test_inspect_inputs_cli_json_out_writes_status_file` | Retain | Real CLI input-inspection route json out writes status file; preprocessing E2E does not exercise this operator mode. |
| `test_inspect_inputs_cli_json_reports_truncated_match_counts` | Retain | Real CLI input-inspection route json reports truncated match counts; preprocessing E2E does not exercise this operator mode. |
| `test_inspect_inputs_cli_can_filter_domain_and_skip_space_check` | Retain | Real CLI input-inspection route can filter domain and skip space check; preprocessing E2E does not exercise this operator mode. |
| `test_inspect_inputs_cli_domain_timeout_mode_aggregates_json` | Retain | Real CLI input-inspection route domain timeout mode aggregates json; preprocessing E2E does not exercise this operator mode. |
| `test_inspect_inputs_cli_limits_json_path_samples` | Retain | Real CLI input-inspection route limits json path samples; preprocessing E2E does not exercise this operator mode. |
| `test_inspect_inputs_cli_domain_timeout_requires_bounded_scan` | Retain | Real CLI input-inspection route domain timeout requires bounded scan; preprocessing E2E does not exercise this operator mode. |
| `test_inspect_inputs_cli_min_free_gb_fails_low_space_gate` | Retain | Real CLI input-inspection route min free gb fails low space gate; preprocessing E2E does not exercise this operator mode. |
| `test_scaffold_validation_cli_creates_external_layout` | Retain | Distinct operator boundary/failure: scaffold validation cli creates external layout. It is not exercised by the successful full-run route. |
| `test_hash_outputs_cli` | Retain | Distinct operator boundary/failure: hash outputs cli. It is not exercised by the successful full-run route. |
| `test_hash_outputs_cli_final_scope_without_work_dir` | Retain | Distinct operator boundary/failure: hash outputs cli final scope without work dir. It is not exercised by the successful full-run route. |
| `test_compare_manifests_cli` | Retain | Distinct operator boundary/failure: compare manifests cli. It is not exercised by the successful full-run route. |
| `test_compare_manifests_cli_detects_mismatch` | Retain | Distinct operator boundary/failure: compare manifests cli detects mismatch. It is not exercised by the successful full-run route. |
| `test_validation_status_cli_reports_ready_artifacts` | Retain | Real subprocess readiness workflow reports ready artifacts; full successful pipeline does not create this artifact-consistency scenario. |
| `test_validation_status_cli_rejects_artifacts_outside_required_root` | Retain | Real subprocess readiness workflow rejects artifacts outside required root; full successful pipeline does not create this artifact-consistency scenario. |
| `test_required_root_check_rejects_low_free_space` | Retain | Distinct operator boundary/failure: required root check rejects low free space. It is not exercised by the successful full-run route. |
| `test_validation_status_cli_rejects_old_input_status_schema` | Retain | Real subprocess readiness workflow rejects old input status schema; full successful pipeline does not create this artifact-consistency scenario. |
| `test_validation_status_cli_rejects_manifest_without_row_and_column_metadata` | Retain | Real subprocess readiness workflow rejects manifest without row and column metadata; full successful pipeline does not create this artifact-consistency scenario. |
| `test_validation_status_cli_rejects_manifest_missing_scope_metadata` | Retain | Real subprocess readiness workflow rejects manifest missing scope metadata; full successful pipeline does not create this artifact-consistency scenario. |
| `test_validation_status_cli_rejects_manifest_with_wrong_hash_algorithm` | Retain | Real subprocess readiness workflow rejects manifest with wrong hash algorithm; full successful pipeline does not create this artifact-consistency scenario. |
| `test_validation_status_cli_rejects_final_manifest_with_parquet_table` | Retain | Real subprocess readiness workflow rejects final manifest with parquet table; full successful pipeline does not create this artifact-consistency scenario. |
| `test_validation_status_cli_rejects_manifest_with_non_csv_source_path` | Retain | Real subprocess readiness workflow rejects manifest with non csv source path; full successful pipeline does not create this artifact-consistency scenario. |
| `test_validation_status_cli_rejects_manifest_with_mismatched_source_filename` | Retain | Real subprocess readiness workflow rejects manifest with mismatched source filename; full successful pipeline does not create this artifact-consistency scenario. |
| `test_validation_status_cli_rejects_manifest_with_missing_source_file` | Retain | Real subprocess readiness workflow rejects manifest with missing source file; full successful pipeline does not create this artifact-consistency scenario. |
| `test_validation_status_cli_rejects_manifest_with_stale_source_file_stats` | Retain | Real subprocess readiness workflow rejects manifest with stale source file stats; full successful pipeline does not create this artifact-consistency scenario. |
| `test_validation_status_cli_rejects_non_final_scope_manifest` | Retain | Real subprocess readiness workflow rejects non final scope manifest; full successful pipeline does not create this artifact-consistency scenario. |
| `test_validation_status_cli_rejects_capped_input_status` | Retain | Real subprocess readiness workflow rejects capped input status; full successful pipeline does not create this artifact-consistency scenario. |
| `test_validation_status_cli_rejects_missing_free_space_threshold` | Retain | Real subprocess readiness workflow rejects missing free space threshold; full successful pipeline does not create this artifact-consistency scenario. |
| `test_validation_status_cli_rejects_incomplete_profile_provenance` | Retain | Real subprocess readiness workflow rejects incomplete profile provenance; full successful pipeline does not create this artifact-consistency scenario. |
| `test_validation_status_cli_rejects_non_strict_profile_provenance` | Retain | Real subprocess readiness workflow rejects non strict profile provenance; full successful pipeline does not create this artifact-consistency scenario. |
| `test_validation_status_cli_rejects_old_profile_provenance_schema` | Retain | Real subprocess readiness workflow rejects old profile provenance schema; full successful pipeline does not create this artifact-consistency scenario. |
| `test_validation_status_cli_rejects_stale_profile_code_state` | Retain | Real subprocess readiness workflow rejects stale profile code state; full successful pipeline does not create this artifact-consistency scenario. |
| `test_validation_status_cli_rejects_old_comparison_report_schema` | Retain | Real subprocess readiness workflow rejects old comparison report schema; full successful pipeline does not create this artifact-consistency scenario. |
| `test_validation_status_cli_rejects_stale_comparison_report` | Retain | Real subprocess readiness workflow rejects stale comparison report; full successful pipeline does not create this artifact-consistency scenario. |
| `test_validation_status_cli_rejects_stale_comparison_report_contents` | Retain | Real subprocess readiness workflow rejects stale comparison report contents; full successful pipeline does not create this artifact-consistency scenario. |
| `test_validation_status_cli_recomputes_manifest_comparison` | Retain | Real subprocess readiness workflow recomputes manifest comparison; full successful pipeline does not create this artifact-consistency scenario. |
| `test_validation_status_cli_rejects_refactor_outputs_absent_from_profile` | Retain | Real subprocess readiness workflow rejects refactor outputs absent from profile; full successful pipeline does not create this artifact-consistency scenario. |
| `test_validation_status_cli_rejects_profile_outputs_absent_from_manifest` | Retain | Real subprocess readiness workflow rejects profile outputs absent from manifest; full successful pipeline does not create this artifact-consistency scenario. |
| `test_validation_status_cli_rejects_refactor_outputs_outside_configured_output_dir` | Retain | Real subprocess readiness workflow rejects refactor outputs outside configured output dir; full successful pipeline does not create this artifact-consistency scenario. |
| `test_validation_status_cli_rejects_refactor_manifest_key_source_mismatch` | Retain | Real subprocess readiness workflow rejects refactor manifest key source mismatch; full successful pipeline does not create this artifact-consistency scenario. |
| `test_validation_status_cli_rejects_stale_profile_output_inventory` | Retain | Real subprocess readiness workflow rejects stale profile output inventory; full successful pipeline does not create this artifact-consistency scenario. |
| `test_validation_status_cli_rejects_invalid_profile_output_file_metadata` | Retain | Real subprocess readiness workflow rejects invalid profile output file metadata; full successful pipeline does not create this artifact-consistency scenario. |
| `test_validation_status_cli_rejects_stale_profile_output_mtime` | Retain | Real subprocess readiness workflow rejects stale profile output mtime; full successful pipeline does not create this artifact-consistency scenario. |
| `test_validation_status_cli_rejects_mismatched_config_identity` | Retain | Real subprocess readiness workflow rejects mismatched config identity; full successful pipeline does not create this artifact-consistency scenario. |
| `test_validation_status_cli_rejects_mismatched_config_hash` | Retain | Real subprocess readiness workflow rejects mismatched config hash; full successful pipeline does not create this artifact-consistency scenario. |
| `test_validation_status_cli_rejects_stale_config_file_contents` | Retain | Real subprocess readiness workflow rejects stale config file contents; full successful pipeline does not create this artifact-consistency scenario. |
| `test_validation_status_cli_reports_incomplete_artifacts` | Retain | Real subprocess readiness workflow reports incomplete artifacts; full successful pipeline does not create this artifact-consistency scenario. |
| `test_validation_status_cli_reports_timed_out_inputs` | Retain | Real subprocess readiness workflow reports timed out inputs; full successful pipeline does not create this artifact-consistency scenario. |

### `test_cohort_source.py`
| Original function | Decision | Failure rationale / retained workflow evidence |
|---|---|---|
| `test_cohort_source_validates_and_opens_read_only` | Retain | Full product-to-consumer flow, catalog provenance, read-only connection enforcement and external spill cleanup. |
| `test_cohort_source_rejects_tampered_or_incomplete_products` | Retain | Actual product tampering covers missing sidecar, wrong catalog, missing element and incomplete status. |
| `test_cohort_source_rejects_schema_and_required_table_loss` | Retain | Actual database schema/table damage must fail the consumer boundary. |
| `test_cohort_source_guards_default_and_explicit_spill_locations` | Retain | Both configured spill and database directories require location guards; safe E2E cannot detect an omitted guard. |
| `test_cohort_source_returns_unsafe_spill_location_as_invalid_product` | Retain | A path guard failure must yield an invalid consumer result instead of proceeding to row reads. |

### `test_combined_preprocessing.py`
| Original function | Decision | Failure rationale / retained workflow evidence |
|---|---|---|
| `test_combined_run_id_ignores_volatile_work_status` | Retain | Resume identity must remain stable across timestamps/stage-status updates but change with configuration; identical happy builds do not exercise both mutations. |
| `test_combined_resumable_identity_includes_strict_policy` | Retain | Strict and non-strict builds must never share a resumable identity, even if current fixture outputs happen to match. |
| `test_combined_resumable_identity_includes_duckdb_memory_limits` | Retain | Resource-policy changes must invalidate checkpoints so receipts cannot describe limits from a different execution. |
| `test_combined_pipeline_uses_sequential_fresh_phase_workers` | Remove | Mock-only argument/order check duplicates observed phases in actual build; real spawned-process and transferred-lock regressions remain for process semantics. Retained workflow: `tests/test_combined_preprocessing.py::test_combined_build_exports_exact_historical_contract`. `tests/test_combined_preprocessing.py::test_synthetic_example_is_rerunnable`. |
| `test_combined_retry_runs_only_final_assembly_when_prerequisites_are_current` | Retain | Interrupted final assembly must preserve current prerequisites, discard partial final outputs and retry only the incomplete phase. |
| `test_combined_retry_recomputes_final_only_eligibility_after_stale_state_removal` | Retain | A removed stale build-state file must not leave a cached retry decision that unnecessarily restarts valid prerequisite stages. |
| `test_current_pipeline_without_state_fsyncs_before_reconstructed_checkpoint` | Retain | Reconstructing a missing checkpoint must make output bytes durable before recording completion. |
| `test_combined_retry_reruns_pre_final_when_a_prerequisite_is_stale` | Retain | A missing or changed prerequisite must force recomputation instead of adopting current-looking final assembly. |
| `test_isolated_phase_process_runs_target_in_fresh_process` | Retain | An actual different PID proves phase isolation needed to release accumulated process memory; output-only E2E cannot distinguish in-process execution. |
| `test_validation_worker_rechecks_serialized_export_hashes` | Retain | Reloaded baseline/export hashes can disagree even when earlier checkpoint freshness checks pass; the worker must refuse completion. |
| `test_validation_checkpoint_requires_durable_sidecar_directory` | Retain | Injected sidecar-directory fsync failure must prevent a successful validation checkpoint; successful builds cannot simulate failed durability. |
| `test_spawned_worker_retains_canonical_lock_after_parent_descriptor_closes` | Retain | Real spawned worker must keep the canonical lock after the parent closes its copy, then release it on exit. |
| `test_combined_private_artifacts_reject_repository_paths` | Remove | Simple repository-path rejection is exercised at actual validation/evidence boundaries before source scanning. Retained workflow: `tests/test_cli.py::test_validate_preprocessed_cli_rejects_repository_local_database`. `tests/test_combined_preprocessing.py::test_database_evidence_rejects_repository_spill_before_scanning`. |
| `test_combined_private_artifacts_reject_repository_case_alias` | Retain | Case-insensitive aliases must not bypass private-artifact location restrictions. |
| `test_compatibility_evidence_guards_locations_before_hashing` | Remove | Guard-call recording is weaker than retained actual unsafe-location rejections and full evidence capture/re-export comparison. Retained workflow: `tests/test_combined_preprocessing.py::test_compatibility_evidence_rejects_repository_hash_locations`. `tests/test_combined_preprocessing.py::test_combined_build_exports_exact_historical_contract`. |
| `test_compatibility_evidence_rejects_repository_hash_locations` | Retain | Actual direct and symlinked repository destinations must be rejected before hashing creates scratch. |
| `test_database_evidence_rejects_repository_spill_before_scanning` | Retain | Both parity and element-completeness operations must reject unsafe spill/database locations before scanning. |
| `test_filesystem_aliases_share_locks_and_publication_paths` | Retain | Case aliases of an existing destination must map to the same lock and publication journal, preventing concurrent writers. |
| `test_absent_case_aliases_share_locks_and_publication_paths` | Retain | Case aliases of a not-yet-created destination must also share the lock/journal identity. |
| `test_lock_and_publication_identity_survive_parent_creation` | Retain | Creating a destination parent must not change lock identity while a build is in flight. |
| `test_staging_runtime_scratch_rejects_non_directory_entries` | Retain | Files or symlinks bearing a scratch prefix must not be recursively removed as tool-owned directories. |
| `test_lock_opener_rejects_symlink_without_clobbering_target` | Retain | A malicious or accidental lock symlink must fail without altering the target. |
| `test_combined_builder_rejects_path_overlap_before_location_checks` | Retain | Direct builder calls must reject overlapping work/output before cleanup, even if combined.enabled is false. |
| `test_combined_database_session_bounds_runtime_and_cleans_spill` | Retain | Actual DuckDB session must apply thread/memory/order limits and remove created spill after close. |
| `test_combined_encounter_availability_is_exact_and_cleans_partitions` | Retain | Duplicate and NULL source IDs must produce exact availability flags/counts and remove partition scratch. |
| `test_element_capture_preserves_duplicate_source_rows_and_membership` | Retain | Identical source rows must retain distinct record identities and every included membership; date/timestamp precision must survive capture. |
| `test_element_capture_retains_only_rows_with_included_membership` | Retain | Exclude-only rows must not become retained canonical candidates or gas candidates. |
| `test_combined_build_exports_exact_historical_contract` | Retain | Full synthetic source-to-DuckDB/36-CSV build, re-export equality, independent consumer validation and deliberate CSV tampering. |
| `test_combined_source_tables_have_stable_typed_schema` | Retain | Full builds in both storage modes must expose the typed consumer source schema. |
| `test_combined_patient_source_preserves_raw_string_values` | Retain | Full build must retain leading-zero birth/death/source strings rather than coercing them numerically. |
| `test_combined_source_tables_preserve_literal_na_tokens` | Retain | Full canonical build must preserve vendor NA/N/A/NULL strings independently in every clinical domain. |
| `test_failed_replacement_preserves_published_product` | Retain | Injected replacement failure must preserve prior database/output bytes; resume must remove only stale owned scratch and finish. |
| `test_failed_database_session_restarts_incomplete_database` | Retain | Failure during membership materialization must cause incomplete database reconstruction instead of unsafe checkpoint reuse. |
| `test_stale_pre_database_checkpoint_rebuilds_pipeline` | Retain | A pre-database interruption followed by stale work must force a full recomputation. |
| `test_export_checkpoint_recovers_after_database_fingerprint_refresh` | Retain | Failure after database fingerprint refresh but before export checkpoint completion must recover consistent state. |
| `test_legacy_export_rejects_managed_directory_symlink` | Retain | Managed compatibility output directory symlink must not redirect export into an outside location. |
| `test_failed_legacy_export_preserves_existing_generation` | Retain | Injected export generation failure must retain every old compatibility file. |
| `test_legacy_export_recovers_interrupted_hash_scratch` | Retain | Interrupted owned hash scratch must be removed safely before regenerating the complete export. |
| `test_legacy_export_atomically_replaces_complete_compatibility_tree` | Retain | Atomic export replacement must publish all 36 files and leave unrelated sentinel state unchanged. |
| `test_legacy_export_publication_failure_rolls_back_existing_tree` | Retain | Injected rename failure must restore the prior compatibility tree without leftover journal/backup state. |
| `test_legacy_export_rejects_late_unmanaged_destination_mutation` | Retain | User file added after preflight must survive; publication must detect the new unmanaged entry and stop. |
| `test_legacy_export_requires_explicit_replacement` | Retain | Existing generation must not be overwritten without the replacement flag. |
| `test_legacy_export_rejects_in_place_canonical_product_mutation` | Retain | Export to canonical product root must fail without changing source database bytes. |
| `test_legacy_export_rejects_destination_nested_in_canonical_product` | Retain | Nested export directory must not contaminate canonical source product. |
| `test_legacy_export_rejects_case_alias_inside_canonical_product` | Retain | Case aliases must not bypass canonical-product nesting checks. |
| `test_export_checkpoint_durability_barrier_fsyncs_files_and_directories` | Retain | Every file and containing directory must be durable in the required order before checkpoint publication. |
| `test_replacement_rejects_unmanaged_output_entries` | Retain | Unknown files in replace destinations must be preserved and block replacement. |
| `test_replacement_rejects_nested_output_symlinks` | Retain | Nested output symlinks must not allow cleanup/publication to touch external targets. |
| `test_publication_removes_appledouble_sidecars` | Retain | OS metadata sidecars must not contaminate the completed product inventory. |
| `test_publish_rename_failure_rolls_back_existing_product` | Retain | Injected product publication rename failure must retain prior output hashes and recoverable staging/state. |
| `test_combined_build_lock_rejects_overlapping_builds` | Retain | An actual competing canonical lock must prevent overlapping build ownership. |
| `test_publication_journal_recovers_old_product_after_interruption` | Retain | Interrupted product publication must restore the exact prior database and CSVs using its journal. |
| `test_compatibility_publication_recovers_old_tree_without_touching_state` | Retain | Compatibility recovery must restore old files while preserving user-owned state. |
| `test_clean_scratch_preserves_publication_recovery_artifacts` | Retain | Cleanup must preserve backup and journal evidence needed to restore the previous generation. |
| `test_clean_scratch_allows_first_publication_recovery_without_product` | Retain | Cleanup/recovery of an interrupted first publication must handle absence of any prior product. |
| `test_clean_scratch_keeps_missing_prior_publication_fail_closed` | Retain | If the expected prior product is missing, cleanup must retain the journal and recovery must fail closed. |
| `test_compatibility_publication_recovers_through_case_alias` | Retain | Recovery through a case alias must locate the same backup/journal instead of abandoning evidence. |
| `test_synthetic_example_is_rerunnable` | Retain | Real example-script subprocess must complete twice with a canonical database and all 36 compatibility files. |
| `test_confidential_combined_csv_intermediates_are_ignored` | Retain | Git ignore policy must cover each private intermediate family; ordinary E2E does not test accidental publication protection. |
| `test_combined_validation_fails_when_manifest_is_incomplete` | Retain | Actual incomplete database must fail validation and refuse export without creating a new generation. |
| `test_compatibility_manifest_duplicate_key_fails_all_gates` | Retain | Duplicate manifest logical keys must fail every gate even if the apparent manifest length is 36. |
| `test_combined_validation_requires_and_reconciles_product_sidecar` | Retain | Missing or inconsistent sidecar counts must fail actual database validation. |
| `test_combined_validation_rejects_exclude_only_source_elements` | Retain | Actual retained rows/catalog entries with no included rule must fail validation and completeness. |
| `test_element_completeness_bounds_distinct_membership_counts` | Retain | Forced partition path must retain exact distinct counts with duplicates/NULLs and clean scratch; tiny E2E uses direct counts. |
| `test_combined_validation_checks_source_integrity_by_domain` | Retain | Actual orphan/wrong-domain/duplicate source corruption must fail under forced bounded validation paths, without leaking record IDs in errors. |

### `test_combined_scripts.py`
| Original function | Decision | Failure rationale / retained workflow evidence |
|---|---|---|
| `test_monitor_requires_explicit_terminal_success` | Retain | Vanished process or wrong PID cannot establish successful completion; pipeline E2E does not run the monitor. |
| `test_monitor_rejects_unversioned_or_stale_result_schema` | Retain | Old result schemas cannot certify terminal success. |
| `test_benchmark_sums_concurrent_process_family_rss` | Retain | Counting only parent or one child would understate production memory; synthetic builds do not exercise benchmark reporting. |
| `test_benchmark_reports_sampled_family_and_resource_floor` | Retain | Benchmark evidence must preserve both measured memory sources and the method label; no E2E covers the benchmark script. |

### `test_config.py`
| Original function | Decision | Failure rationale / retained workflow evidence |
|---|---|---|
| `test_load_and_validate_config` | Remove | Default config parsing and normal CSV operation are exercised by the full pipeline; the isolated checks add no distinct failing input. Retained workflow: `tests/test_pipeline_run.py::test_run_pipeline_end_to_end`. `tests/test_cli.py::test_validate_config_cli`. |
| `test_load_config_storage_options` | Retain | Nondefault scientific thresholds/storage flags could be silently ignored; default E2Es do not set these overrides. |
| `test_validate_config_rejects_combined_work_output_overlap` | Retain | Equal and both nested path directions can cause work/output clobbering; the CLI overlap case only covers equality. |
| `test_validate_config_rejects_case_alias_overlap` | Retain | Case-insensitive equal/nested path aliases can bypass destructive-overlap rejection. |
| `test_combined_enabled_requires_boolean` | Retain | Quoted false, numeric and null values could activate the combined mutating route accidentally. |
| `test_combined_duckdb_memory_limits_require_positive_integers` | Retain | Zero, negative, boolean or fractional limits can remove resource bounds before a long private build. |
| `test_combined_core_memory_default_respects_lower_general_limit` | Retain | Default core phase could exceed an explicitly lower general memory ceiling. |
| `test_load_config_domain_patterns_list` | Retain | Ingredient inputs must be included while generated medication_NEW files are excluded from raw discovery. |
| `test_validate_config_missing_files` | Retain | Strict config validation must fail on absent inputs; inspect-inputs deliberately supports partial status. |
| `test_inspect_domain_paths_reports_all_domains_without_raising` | Remove | Duplicates real CLI inspection of present and absent domains, including search directories and counts. Retained workflow: `tests/test_cli.py::test_inspect_inputs_cli_json_reports_missing_domains`. |
| `test_inspect_domain_paths_reports_present_empty_search_dir` | Retain | An empty existing directory must not be reported as absent; real CLI missing fixture uses absent directory. |
| `test_vitals_pattern_matches_historical_and_restored_spellings` | Retain | Both vendor filename spellings must be discoverable; baseline fixtures contain only one. |
| `test_inspect_domain_paths_can_cap_matches` | Remove | Duplicates real CLI capped discovery and the explicit inexact-count flag. Retained workflow: `tests/test_cli.py::test_inspect_inputs_cli_json_reports_truncated_match_counts`. |
| `test_inspect_domain_paths_caps_space_containing_domain_dirs` | Retain | Bounded discovery of paths with spaces and AppleDouble metadata is not in the capped CLI fixture. |
| `test_inspect_domain_paths_can_filter_domains` | Remove | Duplicates real CLI domain selection. Retained workflow: `tests/test_cli.py::test_inspect_inputs_cli_can_filter_domain_and_skip_space_check`. |
| `test_load_config_rejects_unknown_storage_format` | Retain | An unsupported format must fail before any pipeline mutation. |

### `test_discovery.py`
| Original function | Decision | Failure rationale / retained workflow evidence |
|---|---|---|
| `test_discover_domain_files_chunked_sorted` | Remove | Unused helper: no production or script caller imports this top-level discovery module. Actual config/source discovery remains covered. No claim of identical unused-helper behavior. Retained workflow: `tests/test_cli.py::test_inspect_inputs_cli_limits_json_path_samples`. `tests/test_pipeline_run.py::test_run_pipeline_end_to_end_with_parquet_intermediates`. |
| `test_discover_domain_files_unchunked` | Remove | Unused helper: actual ingestion uses config and clinical_sources.discovery, not this top-level module. No product behavior changes. Retained workflow: `tests/test_combined_preprocessing.py::test_combined_patient_source_preserves_raw_string_values`. |
| `test_discover_domain_files_prefers_chunked` | Remove | Unused helper has no production caller; its preference is not an existing pipeline acceptance gate. Production helper remains unchanged. Retained workflow: `tests/test_pipeline_run.py::test_run_pipeline_end_to_end_with_parquet_intermediates`. |

### `test_filesystem.py`
| Original function | Decision | Failure rationale / retained workflow evidence |
|---|---|---|
| `test_write_text_atomic_replaces_completed_file` | Remove | Normal atomic replacement is exercised by complete pipeline reruns and repeated publication. Unique failed-replace preservation test remains. Retained workflow: `tests/test_pipeline_run.py::test_run_pipeline_end_to_end`. `tests/test_combined_preprocessing.py::test_synthetic_example_is_rerunnable`. |
| `test_write_text_atomic_preserves_existing_file_when_replace_fails` | Retain | Injected atomic replace failure must leave prior status bytes intact and remove its temporary file. |
| `test_remove_tree_strict_deletes_directory` | Remove | Duplicates full scratch-cleaning command behavior. Retained workflow: `tests/test_cli.py::test_clean_scratch_delete_removes_only_known_artifacts`. |
| `test_remove_tree_strict_tolerates_missing_nested_entries` | Retain | Modern Python onexc callback must tolerate disappearance races; cleanup integration forces legacy onerror. |
| `test_remove_tree_strict_fallback_tolerates_missing_nested_entries` | Remove | The retained cleanup integration injects the same legacy onerror callback and missing nested file. Modern onexc-specific isolation remains. Retained workflow: `tests/test_cli.py::test_clean_scratch_delete_tolerates_missing_nested_entries`. |
| `test_remove_tree_strict_propagates_delete_errors` | Retain | Modern onexc permission failure must propagate; cleanup integration covers legacy callback signature. |
| `test_remove_tree_strict_raises_when_directory_remains` | Remove | Same no-op deletion failure is exercised through actual scratch cleanup. Retained workflow: `tests/test_cli.py::test_clean_scratch_delete_raises_when_directory_remains`. |

### `test_guardrails.py`
| Original function | Decision | Failure rationale / retained workflow evidence |
|---|---|---|
| `test_check_join_multiplier_allows_within_limit` | Remove | Normal joins are exercised by full pipeline fixtures. The unique explosion-rejection test remains. Retained workflow: `tests/test_pipeline_run.py::test_run_pipeline_end_to_end`. `tests/test_combined_preprocessing.py::test_combined_build_exports_exact_historical_contract`. |
| `test_check_join_multiplier_raises_on_explosion` | Retain | Unexpected many-to-many row explosion is absent from happy E2E fixtures. |
| `test_check_required_ids_raises_on_missing_column` | Retain | Missing identifier schema must fail before downstream joins. |
| `test_check_required_ids_raises_on_nulls` | Retain | NULL identifiers can create false cross-row joins despite present columns. |
| `test_check_required_ids_passes` | Remove | Normal required identifiers are exercised by full strict builds. Missing and NULL identifier failures remain. Retained workflow: `tests/test_combined_preprocessing.py::test_combined_build_exports_exact_historical_contract`. |

### `test_imports.py`
| Original function | Decision | Failure rationale / retained workflow evidence |
|---|---|---|
| `test_package_imports` | Remove | Asserting a truthy version duplicates every real CLI import and does not prove wheel installation. The actual module-help route remains. Retained workflow: `tests/test_cli.py::test_run_encounter_cli`. `tests/test_combined_preprocessing.py::test_synthetic_example_is_rerunnable`. |
| `test_module_help` | Retain | Real module-entrypoint help and advertised command route are not verified by direct cli.main pipeline calls. |

### `test_io_csv.py`
| Original function | Decision | Failure rationale / retained workflow evidence |
|---|---|---|
| `test_iter_csv_yields_chunks` | Remove | Full Parquet pipeline runs with one-row batches across all domains, while retained reader/NA regressions cover semantic edge cases. Retained workflow: `tests/test_pipeline_run.py::test_run_pipeline_end_to_end_with_parquet_intermediates`. |
| `test_iter_csv_preserves_literal_na_like_source_tokens` | Remove | Actual canonical builds preserve NA/N/A/NULL per source domain; exhaustive legacy token and nonmutation regression retains blank-token coverage. Retained workflow: `tests/test_combined_preprocessing.py::test_combined_source_tables_preserve_literal_na_tokens`. |
| `test_legacy_na_coercion_matches_default_read_csv_without_mutating_source` | Retain | Exhaustive historical NA spellings/case/whitespace and nonmutation are not covered by three raw source_id tokens in combined E2E. |

### `test_pipeline_run.py`
| Original function | Decision | Failure rationale / retained workflow evidence |
|---|---|---|
| `test_run_pipeline_end_to_end` | Retain | Full CSV pipeline, all compatibility categories/settings, independent frozen output schema and repeatable output bytes. |
| `test_run_pipeline_end_to_end_with_parquet_intermediates` | Retain | Full pipeline with one-row batching, analysis indexes, suppressed legacy intermediates and final artifacts. |
| `test_baseline_compare_profile_end_to_end_with_parquet_intermediates` | Retain | Actual baseline/hash comparison/profile artifacts, provenance and logical Parquet manifest key. |

### `test_profiling_utils.py`
| Original function | Decision | Failure rationale / retained workflow evidence |
|---|---|---|
| `test_stage_timer_records_elapsed` | Remove | Checks only subtraction of two fake clock values. Real profile E2E checks timing artifact presence and valid durations; no unique elapsed-time failure is modeled. Retained workflow: `tests/test_pipeline_run.py::test_baseline_compare_profile_end_to_end_with_parquet_intermediates`. |
| `test_code_state_hash_falls_back_without_git` | Retain | Installed/non-Git code must still produce a digest; checkout E2Es run with Git available. |
| `test_write_provenance_records_config_code_and_outputs` | Retain | Work artifacts and internal output Parquet must be excluded from public CSV inventory; the pipeline profile fixture lacks internal output Parquet. |

### `test_regression.py`
| Original function | Decision | Failure rationale / retained workflow evidence |
|---|---|---|
| `test_normalize_table_sorts_columns_and_rows` | Remove | Intermediate sorting representation duplicates the retained digest ordering invariant. E2E consumes the resulting hashes; the independent reordering hash probe remains because fixtures do not shuffle. Retained workflow: `tests/test_pipeline_run.py::test_baseline_compare_profile_end_to_end_with_parquet_intermediates`. |
| `test_hash_table_is_deterministic_for_ordering` | Retain | Hash parity must be insensitive to row/column order; full fixtures reproduce the same order. |
| `test_hash_csv_matches_table` | Remove | Simple one-batch hash equality is subsumed by retained multichunk quoting/duplicate regression and actual compatibility re-export parity. Retained workflow: `tests/test_combined_preprocessing.py::test_combined_build_exports_exact_historical_contract`. |
| `test_hash_csv_matches_table_across_small_chunks` | Retain | External hash sorting must retain duplicates and quoting across multiple chunks. |
| `test_hash_csv_rejects_invalid_chunk_rows` | Retain | A zero hash chunk size must fail rather than certify empty/incomplete input. |
| `test_hash_parquet_matches_table` | Remove | Simple one-batch hash equality is subsumed by retained multibatch quoting/duplicate regression and the full Parquet baseline workflow. Retained workflow: `tests/test_pipeline_run.py::test_baseline_compare_profile_end_to_end_with_parquet_intermediates`. |
| `test_hash_parquet_matches_table_across_small_batches` | Retain | External Parquet hashing must retain duplicate/quoted rows across row groups. |
| `test_hash_parquet_rejects_invalid_chunk_rows` | Retain | A zero Parquet hash batch size must not silently certify incomplete input. |
| `test_hash_csv_and_parquet_match_for_csv_visible_values` | Retain | Cross-format float/date/null representations must yield equal canonical hashes; pipeline compares each mode against itself. |
| `test_table_hash_entry_uses_chunked_parquet_metadata` | Retain | Chunked metadata must count all row groups and retain schema independently of final digest. |
| `test_collect_directory_hashes_normalizes_parquet_work_keys` | Remove | Logical RFS_ABG CSV key oracle moved into actual Parquet baseline manifest assertion. Retained workflow: `tests/test_pipeline_run.py::test_baseline_compare_profile_end_to_end_with_parquet_intermediates`. |
| `test_collect_directory_hashes_allows_identical_duplicate_logical_keys` | Retain | Dual-format identical copies must be accepted without duplicate logical entries; full fixtures disable companions. |
| `test_collect_directory_hashes_rejects_conflicting_duplicate_logical_keys` | Retain | Conflicting CSV/Parquet copies must fail instead of arbitrarily choosing one. |
| `test_collect_directory_entries_supports_final_scope` | Remove | Normal final-only manifest behavior is exercised through real hash-output CLI and readiness validation; corruption-specific metadata checks remain. Retained workflow: `tests/test_cli.py::test_hash_outputs_cli_final_scope_without_work_dir`. `tests/test_cli.py::test_validation_status_cli_reports_ready_artifacts`. |
| `test_collect_directory_entries_ignores_noise_paths` | Retain | AppleDouble, __MACOSX and stale hash scratch must not become clinical output entries. |
| `test_write_hash_manifest_writes_metadata_and_loads_hashes` | Remove | Normal manifest serialization/consumption repeats full baseline, compare and profile workflow plus real CLI manifests. Legacy-v1 reader coverage remains. Retained workflow: `tests/test_pipeline_run.py::test_baseline_compare_profile_end_to_end_with_parquet_intermediates`. `tests/test_cli.py::test_validation_status_cli_reports_ready_artifacts`. |
| `test_write_hash_manifest_rejects_invalid_scope` | Remove | Only passes a type-ignored invalid enum to an internal writer; CLI restricts accepted scopes and real readiness gate rejects nonfinal scope. Retained workflow: `tests/test_cli.py::test_validation_status_cli_rejects_non_final_scope_manifest`. `tests/test_cli.py::test_validation_status_cli_rejects_manifest_missing_scope_metadata`. |
| `test_load_hash_manifest_entries_reads_v1_hashes` | Retain | Preserved legacy v1 hash-only inputs remain readable; current workflow emits v2. |
| `test_compare_manifest_entries_reports_metadata_mismatches` | Retain | Row-count/schema differences must fail in addition to digest mismatch; actual mismatch CLI fixture alters only digest. |
| `test_compare_manifest_entries_reports_order_only_column_mismatches` | Retain | Column order is a compatibility contract even when order-insensitive contents hash matches. |

### `test_split_csv.py`
| Original function | Decision | Failure rationale / retained workflow evidence |
|---|---|---|
| `test_split_csv_creates_chunks_with_headers` | Retain | Supported standalone split utility must retain headers, bounds and total rows. Pipeline batching does not call this utility. |

### `test_storage.py`
| Original function | Decision | Failure rationale / retained workflow evidence |
|---|---|---|
| `test_write_work_table_parquet_uses_logical_name` | Remove | Simple Parquet naming/round trip is exercised by actual intermediate artifacts and typed source build. Specialized reader projection remains. Retained workflow: `tests/test_pipeline_run.py::test_run_pipeline_end_to_end_with_parquet_intermediates`. `tests/test_combined_preprocessing.py::test_combined_source_tables_have_stable_typed_schema`. |
| `test_write_work_table_can_emit_legacy_csv_companion` | Retain | Dual Parquet/CSV output mode is absent from full-run fixtures that disable CSV companions. |
| `test_work_table_writer_appends_parquet_chunks` | Remove | Full pipeline reads one-row input chunks and retains all expected patient/category outputs; isolated append success adds no distinct case. Retained workflow: `tests/test_pipeline_run.py::test_run_pipeline_end_to_end_with_parquet_intermediates`. `tests/test_combined_preprocessing.py::test_combined_build_exports_exact_historical_contract`. |
| `test_work_table_writer_can_disable_compatibility_output` | Remove | Actual pipeline E2E asserts disabled normalized/group artifacts are absent while analysis indexes and final outputs exist. Retained workflow: `tests/test_pipeline_run.py::test_run_pipeline_end_to_end_with_parquet_intermediates`. |
| `test_find_work_tables_prefers_configured_format` | Retain | Dual-format inputs must not be read twice; full E2E has only one physical intermediate format. |
| `test_iter_work_tables_streams_parquet_batches` | Retain | Reader must honor projected columns, requested string types and bounded row groups; this specific API combination is absent from full fixtures. |
| `test_iter_work_tables_rejects_invalid_parquet_chunksize` | Retain | Zero-sized reader batches must fail rather than silently yielding no data. |
| `test_logical_output_key_normalizes_parquet_work_suffix` | Remove | Existing logical-key oracle moved into actual baseline manifest assertion. Retained workflow: `tests/test_pipeline_run.py::test_baseline_compare_profile_end_to_end_with_parquet_intermediates`. |
| `test_partitioned_parquet_store_round_trips_and_cleans` | Retain | Repeated patient across appended frames must survive partition round trip and scratch cleanup. |
| `test_partitioned_parquet_store_buffers_small_bucket_writes` | Retain | A threshold-flushed bucket plus final partial buffer must retain all rows; tiny E2E buckets do not fill then leave a remainder. |
| `test_partitioned_parquet_store_rejects_invalid_buffer_size` | Retain | Zero buffer configuration must not disable bounded buffering or create an invalid writer. |
| `test_partitioned_parquet_store_rejects_writes_after_read` | Retain | Appending after sealing can silently omit data from already-materialized partitions. |
| `test_partitioned_parquet_store_releases_each_writer_while_sealing` | Retain | References must be released as each writer closes to avoid accumulated writer buffers; small E2E cannot observe production-scale memory pressure. |
| `test_partitioned_parquet_store_releases_unused_memory_once` | Remove | Counts one mocked allocator-release call on an empty store; repeated release is not a product defect and this does not measure memory. The writer-reference-release and resource-bounds regressions remain. Retained workflow: `tests/test_pipeline_run.py::test_run_pipeline_end_to_end_with_parquet_intermediates`. |
| `test_partitioned_key_lookup_queries_and_deduplicates_membership` | Retain | Repeated membership and missing lookup keys must not multiply selected rows. |
| `test_partitioned_key_lookup_rejects_cross_chunk_duplicate_unique_key` | Retain | Conflicting keys split across chunks must fail; successful E2E identifiers are unique. |

### `test_validation.py`
| Original function | Decision | Failure rationale / retained workflow evidence |
|---|---|---|
| `test_require_columns_raises_with_context` | Retain | Missing-column exception must identify both source context and missing field; synthetic full runs only supply valid schemas. |

### `test_work_manifest.py`
| Original function | Decision | Failure rationale / retained workflow evidence |
|---|---|---|
| `test_work_manifest_records_and_requires_completed_stages` | Remove | Normal manifest generation/reuse is exercised by a complete combined build and deterministic pipeline rerun. Every corruption/stale/running checkpoint probe remains. Retained workflow: `tests/test_combined_preprocessing.py::test_combined_build_exports_exact_historical_contract`. `tests/test_pipeline_run.py::test_run_pipeline_end_to_end`. |
| `test_work_manifest_fails_when_rules_change` | Retain | Changing clinical thresholds must invalidate prior staged work. |
| `test_work_manifest_fails_when_behavior_code_changes` | Retain | Changing behavior-code identity must invalidate reuse even if configuration is unchanged. |
| `test_work_manifest_fails_when_combined_catalog_changes` | Retain | Changed source catalog must invalidate work; full fixtures never mutate its fingerprint. |
| `test_work_manifest_rejects_unmanaged_work` | Retain | Unknown work files must not be adopted as valid stages or erased. |
| `test_work_manifest_rejects_changed_completed_artifact` | Retain | Tampered completed artifact must not be reused. |
| `test_work_manifest_running_stage_is_not_reusable` | Retain | A running checkpoint without terminal completion cannot establish reusable output. |
| `test_work_manifest_fingerprints_legacy_data_screen_inputs` | Retain | Legacy screen file mutation must invalidate work even when clinical-domain inputs stay unchanged. |
| `test_work_manifest_requires_both_legacy_data_screen_inputs` | Retain | One missing legacy screen cannot be interpreted as a complete input set. |

## Verification

The following targeted invocation in the pinned environment passed: **80 tests
in 88.30 seconds**. Ruff checks and formatting on all touched test files passed.
Full-suite verification and durable E2E artifact generation are coordinated by
the parent task.

```bash
uv run --offline --no-sync pytest -q \
  tests/test_config.py tests/test_filesystem.py tests/test_guardrails.py \
  tests/test_imports.py tests/test_io_csv.py tests/test_profiling_utils.py \
  tests/test_regression.py tests/test_storage.py tests/test_work_manifest.py \
  tests/test_pipeline_run.py \
  tests/test_combined_preprocessing.py::test_combined_build_exports_exact_historical_contract \
  tests/test_combined_preprocessing.py::test_synthetic_example_is_rerunnable \
  tests/test_cli.py::test_validate_preprocessed_cli_rejects_repository_local_database \
  tests/test_combined_preprocessing.py::test_database_evidence_rejects_repository_spill_before_scanning \
  tests/test_combined_preprocessing.py::test_compatibility_evidence_rejects_repository_hash_locations
```

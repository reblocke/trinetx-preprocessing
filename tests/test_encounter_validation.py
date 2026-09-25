import hashlib
import json

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from trinetx_preprocessing.encounters.builder import EVIDENCE_TABLES, VARIANTS
from trinetx_preprocessing.encounters.compatibility import artifact_inventory
from trinetx_preprocessing.encounters.validation import (
    EVIDENCE_CONTRACTS,
    validate_bundle,
    verify_acceptance_receipt,
)


def _arrow_type(name):
    if name in {
        "index_event_id",
        "patient_id",
        "encounter_id",
        "source_encounter_id",
        "element_id",
        "concept_set_id",
        "source_record_id",
        "source_record_hash",
        "source_file",
        "domain",
        "history_state",
        "event_datetime_precision",
        "code_system",
        "code_system_raw",
        "code_raw",
        "code",
        "timestamp_precision",
        "units_of_measure",
        "normalized_unit",
        "order_status",
        "status",
        "route",
        "brand",
        "strength",
        "specimen",
        "specimen_id",
        "panel_id",
        "text_value",
        "lab_result_text_val",
        "admitting_diagnosis",
        "reason_for_visit",
        "encounter_type",
    } or name.endswith(("_precision", "_state", "_unit", "_type")):
        return pa.string()
    if name in {"index_date", "start_date", "end_date"}:
        return pa.date32()
    if name in {
        "event_datetime",
        "first_event_datetime",
        "last_event_datetime",
    } or name.endswith("_event_datetime"):
        return pa.timestamp("us")
    if name in {
        "in_baseline_window",
        "ordered_pre_index",
        "active_at_index",
        "ordered_post_index",
        "patient_linked",
        "demographics_agree",
        "encounter_linked",
        "anchor_in_encounter",
    }:
        return pa.bool_()
    if name in {
        "numeric_value",
        "raw_numeric_value",
        "normalized_numeric_value",
        "lab_result_num_val",
        "value",
    }:
        return pa.float64()
    return pa.int64()


def _write_evidence(path, fields, *, empty=False, type_overrides=None):
    schema = {name: _arrow_type(name) for name in sorted(fields)}
    schema.update(type_overrides or {})
    values = {}
    for name, kind in schema.items():
        if pa.types.is_string(kind):
            values[name] = [] if empty else ["p-e"]
        elif pa.types.is_date(kind):
            values[name] = [] if empty else [pd.Timestamp("2024-01-01").date()]
        elif pa.types.is_timestamp(kind):
            values[name] = [] if empty else [pd.Timestamp("2024-01-01")]
        elif pa.types.is_boolean(kind):
            values[name] = [] if empty else [True]
        elif pa.types.is_floating(kind):
            values[name] = [] if empty else [1.0]
        else:
            values[name] = [] if empty else [1]
    pq.write_table(pa.Table.from_pydict(values, schema=pa.schema(schema)), path)


def _write_rows(path, fields, rows):
    schema = {name: _arrow_type(name) for name in sorted(fields)}
    values = {name: [row.get(name) for row in rows] for name in schema}
    pq.write_table(pa.Table.from_pydict(values, schema=pa.schema(schema)), path)


def _bundle(root, omit_element=False):
    root.mkdir()
    dictionaries, qa = {}, {}
    for variant in VARIANTS:
        stem = f"encounter_features_{variant.lower()}"
        frame_values = {
            "patient_id": ["p"],
            "encounter_id": ["e"],
            "pat_enc_hash": ["p-e"],
            "source_count": [1],
            "source_element_lab_hba1c_record_count": [4],
            "source_element_lab_hba1c_latest_raw_value": [7.0],
            "source_element_lab_hba1c_latest_date": [pd.Timestamp("2024-01-01")],
            "source_element_lab_hba1c_latest_unit": ["%"],
            "source_element_vital_systolic_bp_record_count": [2],
            "source_element_vital_systolic_bp_latest_raw_value": [120.0],
            "source_element_vital_systolic_bp_latest_date": [
                pd.Timestamp("2024-01-01")
            ],
            "source_element_vital_systolic_bp_latest_unit": ["mmHg"],
            "source_element_lab_egfr_record_count": [1],
            "source_element_lab_egfr_latest_raw_value": [None],
            "source_element_lab_egfr_latest_date": [pd.NaT],
            "source_element_lab_egfr_latest_unit": [None],
            "glp1_lab_a1c_latest": [6.5],
            "glp1_lab_a1c_latest_date": [pd.Timestamp("2024-01-01")],
            "glp1_bp_latest_sbp": [16.0 * 7.5006168270417],
            "glp1_bp_latest_dbp": [80.0],
            "glp1_bp_latest_bp_date": [pd.Timestamp("2024-01-01")],
        }
        frame = pd.DataFrame(frame_values)
        frame.to_parquet(root / (stem + ".parquet"), index=False)
        dictionaries[variant] = [
            {"column": c, "anchor_precision": "calendar day"} for c in frame
        ]
        qa[variant] = {
            "rows": 1,
            "null_counts": {c: int(frame[c].isna().sum()) for c in frame},
        }
        inventory = [
            {
                "element_id": "source.synthetic",
                "columns": ["source_count"],
                "domain": "labs",
                "availability_states": [
                    {
                        "history_state": "unavailable_domain",
                        "observed_matches": 0,
                        "zero_matching_records": 1,
                    }
                ],
            }
        ]
        for element_id, base in (
            ("source.lab.hba1c", "source_element_lab_hba1c"),
            (
                "source.vital.systolic_bp",
                "source_element_vital_systolic_bp",
            ),
            ("source.lab.egfr", "source_element_lab_egfr"),
        ):
            inventory.append(
                {
                    "element_id": element_id,
                    "domain": "vitals" if "systolic" in element_id else "labs",
                    "columns": [
                        f"{base}_record_count",
                        f"{base}_latest_raw_value",
                        f"{base}_latest_date",
                        f"{base}_latest_unit",
                    ],
                    "availability_states": [
                        {
                            "history_state": "unavailable_domain",
                            "observed_matches": 1,
                            "zero_matching_records": 0,
                        }
                    ],
                }
            )
        (root / (stem + "_element_inventory.json")).write_text(
            json.dumps([] if omit_element else inventory)
        )
        for table in EVIDENCE_TABLES:
            target = root / f"{stem}_{table}.parquet"
            if table == "encounter_element_evidence":
                examples = []
                for element_id, domain, value, unit, event, baseline, record_id in (
                    (
                        "source.lab.hba1c",
                        "labs",
                        6.5,
                        "%",
                        "2024-01-01",
                        True,
                        "hba1c-1",
                    ),
                    (
                        "source.lab.hba1c",
                        "labs",
                        7.0,
                        "%",
                        "2024-01-01",
                        True,
                        "hba1c-3",
                    ),
                    (
                        "source.lab.hba1c",
                        "labs",
                        7.0,
                        "%",
                        "2024-01-01",
                        True,
                        "hba1c-3",
                    ),
                    (
                        "source.lab.hba1c",
                        "labs",
                        9.0,
                        "%",
                        "2024-01-02",
                        False,
                        "hba1c-2",
                    ),
                    (
                        "source.vital.systolic_bp",
                        "vitals",
                        120.0,
                        "mmHg",
                        "2024-01-01",
                        True,
                        "sbp-1",
                    ),
                    (
                        "source.vital.systolic_bp",
                        "vitals",
                        150.0,
                        "mmHg",
                        "2024-01-02",
                        False,
                        "sbp-2",
                    ),
                    (
                        "source.lab.egfr",
                        "labs",
                        30.0,
                        "mL/min/1.73m2",
                        "2024-01-02",
                        False,
                        "egfr-1",
                    ),
                ):
                    examples.append(
                        {
                            "index_event_id": "p-e",
                            "index_date": pd.Timestamp("2024-01-01").date(),
                            "element_id": element_id,
                            "source_record_id": record_id,
                            "source_file": "synthetic",
                            "source_row_number": 1,
                            "patient_id": "p",
                            "source_encounter_id": "e",
                            "event_datetime": pd.Timestamp(event),
                            "timestamp_precision": "date_only",
                            "numeric_value": value,
                            "units_of_measure": unit,
                            "code_system_raw": "LOINC",
                            "code_raw": "synthetic",
                            "domain": domain,
                            "in_baseline_window": baseline,
                        }
                    )
                _write_rows(target, EVIDENCE_CONTRACTS[table], examples)
            elif table == "component_lab_evidence":
                _write_rows(
                    target,
                    EVIDENCE_CONTRACTS[table],
                    [
                        {
                            "index_event_id": "p-e",
                            "index_date": pd.Timestamp("2024-01-01").date(),
                            "concept_set_id": "hba1c",
                            "patient_id": "p",
                            "encounter_id": "e",
                            "code_system": "LOINC",
                            "code": "4548-4",
                            "source_record_hash": "lab-hash",
                            "source_file": "synthetic",
                            "event_datetime": pd.Timestamp("2024-01-01"),
                            "event_datetime_precision": "date_only",
                            "days_before_index": 0,
                            "lab_result_num_val": 6.5,
                            "raw_numeric_value": 6.5,
                            "normalized_numeric_value": 6.5,
                            "normalized_unit": "%",
                            "units_of_measure": "%",
                        }
                    ],
                )
            elif table == "component_bp_evidence":
                _write_rows(
                    target,
                    EVIDENCE_CONTRACTS[table],
                    [
                        {
                            "index_event_id": "p-e",
                            "index_date": pd.Timestamp("2024-01-01").date(),
                            "concept_set_id": "systolic_bp",
                            "patient_id": "p",
                            "encounter_id": "e",
                            "code_system": "LOINC",
                            "code": "8480-6",
                            "source_record_hash": "bp-hash",
                            "source_file": "synthetic",
                            "event_datetime": pd.Timestamp("2024-01-01"),
                            "encounter_type": "AMB",
                            "raw_numeric_value": 16.0,
                            "normalized_numeric_value": 16.0 * 7.5006168270417,
                            "units_of_measure": "kPa",
                        },
                        {
                            "index_event_id": "p-e",
                            "index_date": pd.Timestamp("2024-01-01").date(),
                            "concept_set_id": "diastolic_bp",
                            "patient_id": "p",
                            "encounter_id": "e",
                            "code_system": "LOINC",
                            "code": "8462-4",
                            "source_record_hash": "dbp-hash",
                            "source_file": "synthetic",
                            "event_datetime": pd.Timestamp("2024-01-01"),
                            "encounter_type": "AMB",
                            "raw_numeric_value": 80.0,
                            "normalized_numeric_value": 80.0,
                            "units_of_measure": "mmHg",
                        },
                    ],
                )
            else:
                _write_evidence(target, EVIDENCE_CONTRACTS[table])
        domains = ["diagnosis", "labs", "vitals", "medications", "procedure"]
        coverage_values = {
            "index_event_id": ["p-e"] * 5,
            "patient_id": ["p"] * 5,
            "encounter_id": ["e"] * 5,
            "domain": domains,
            "baseline_lookback_days": [730, 365, 365, 730, 730],
            "patient_linked": [True] * 5,
            "demographics_agree": [True] * 5,
            "encounter_linked": [True] * 5,
            "anchor_in_encounter": [True] * 5,
            "first_event_datetime": [None] * 5,
            "last_event_datetime": [None] * 5,
            "captured_patient_record_count": [0] * 5,
            "history_state": ["unavailable_domain"] * 5,
        }
        coverage_schema = pa.schema(
            {name: _arrow_type(name) for name in coverage_values}
        )
        pq.write_table(
            pa.Table.from_pydict(coverage_values, schema=coverage_schema),
            root / f"{stem}_encounter_source_coverage.parquet",
        )
    (root / "data_dictionary.json").write_text(json.dumps(dictionaries))
    (root / "quality_summary.json").write_text(json.dumps(qa))
    (root / "source_coverage.json").write_text(
        json.dumps(
            {
                "pass": True,
                "source": {"test": True},
                "contract_version": "1.0",
                "policy_version": "1.0",
                "policy": "complete_linkage",
                "exception": None,
                "variants": {
                    name: {
                        "pass": True,
                        "policy": "complete_linkage",
                        "policy_version": "1.0",
                        "exception": None,
                        "contradictions_pass": True,
                        "rows": 1,
                        "linkage_complete": True,
                        "patient_linked": 1,
                        "patient_unlinked": 0,
                        "patient_linked_proportion": 1.0,
                        "encounter_linked": 1,
                        "encounter_unlinked": 0,
                        "encounter_linked_proportion": 1.0,
                        "demographic_disagreements": 0,
                        "anchor_disagreements": 0,
                        "history_states": [
                            {"domain": d, "state": "unavailable_domain", "rows": 1}
                            for d in [
                                "diagnosis",
                                "labs",
                                "medications",
                                "procedure",
                                "vitals",
                            ]
                        ],
                    }
                    for name in VARIANTS
                },
            }
        )
    )
    sidecars = [root / "._data_dictionary.json", root / "._features.parquet"]
    for sidecar in sidecars:
        sidecar.write_bytes(b"synthetic filesystem metadata")
    manifest = {
        "schema_version": "2.0",
        "status": "complete",
        "kind": "encounter_features",
        "feature_contract_version": "1.0",
        "source": {"test": True},
        "compatibility": {"test": "synthetic companion"},
        "code_sha256": "a" * 64,
        "windows": {
            "lookback_days": 730,
            "measurement_lookback_days": 365,
            "medication_lookback_days": 730,
            "followup_days": 365,
        },
        "required_source_elements": [item["element_id"] for item in inventory],
        "outputs": artifact_inventory(root),
    }
    (root / "manifest.json").write_text(json.dumps(manifest))
    return sidecars


def _refresh_manifest(root):
    manifest = json.loads((root / "manifest.json").read_text())
    manifest["outputs"] = {
        name: item
        for name, item in artifact_inventory(root).items()
        if name != "manifest.json"
    }
    (root / "manifest.json").write_text(json.dumps(manifest))


def _legacy_coverage(root):
    path = root / "source_coverage.json"
    coverage = json.loads(path.read_text())
    for field in ("policy", "policy_version", "exception"):
        coverage.pop(field)
    for report in coverage["variants"].values():
        for field in (
            "policy",
            "policy_version",
            "exception",
            "patient_unlinked",
            "patient_linked_proportion",
            "encounter_unlinked",
            "encounter_linked_proportion",
            "contradictions_pass",
            "linkage_complete",
        ):
            report.pop(field)
    path.write_text(json.dumps(coverage))
    _refresh_manifest(root)


def _add_unlinked_encounter(root):
    qa_path = root / "quality_summary.json"
    qa = json.loads(qa_path.read_text())
    coverage_path = root / "source_coverage.json"
    coverage = json.loads(coverage_path.read_text())
    for variant in VARIANTS:
        stem = f"encounter_features_{variant.lower()}"
        feature_path = root / f"{stem}.parquet"
        frame = pd.read_parquet(feature_path)
        missing = frame.iloc[0].to_dict()
        missing["patient_id"] = "q"
        missing["encounter_id"] = "z"
        missing["pat_enc_hash"] = "q-z"
        for column in frame:
            if column.endswith("_record_count") or column == "source_count":
                missing[column] = 0
            elif column.startswith("glp1_") or column.endswith(
                ("_latest_raw_value", "_latest_date", "_latest_unit")
            ):
                missing[column] = None
        original = pq.read_table(feature_path)
        appended = pa.Table.from_pylist([missing], schema=original.schema)
        pq.write_table(pa.concat_tables([original, appended]), feature_path)
        frame = pd.read_parquet(feature_path)
        qa[variant]["rows"] = 2
        qa[variant]["null_counts"] = {
            column: int(frame[column].isna().sum()) for column in frame
        }
        domain_path = root / f"{stem}_encounter_source_coverage.parquet"
        domain_rows = pd.read_parquet(domain_path)
        unlinked = domain_rows.copy()
        unlinked["index_event_id"] = "q-z"
        unlinked["patient_id"] = "q"
        unlinked["encounter_id"] = "z"
        for column in (
            "patient_linked",
            "demographics_agree",
            "encounter_linked",
            "anchor_in_encounter",
        ):
            unlinked[column] = False
        pd.concat([domain_rows, unlinked], ignore_index=True).to_parquet(
            domain_path, index=False
        )
        inventory_path = root / f"{stem}_element_inventory.json"
        inventory = json.loads(inventory_path.read_text())
        for item in inventory:
            item["availability_states"][0]["zero_matching_records"] += 1
        inventory_path.write_text(json.dumps(inventory))
        declared = coverage["variants"][variant]
        declared.update(rows=2, patient_linked=1, encounter_linked=1)
        for state in declared["history_states"]:
            state["rows"] = 2
    qa_path.write_text(json.dumps(qa))
    coverage_path.write_text(json.dumps(coverage))
    _refresh_manifest(root)


def test_complete_bundle_requires_element_and_domain_coverage(tmp_path):
    root = tmp_path / "bundle"
    sidecars = _bundle(root)
    result = validate_bundle(bundle=root, work_dir=tmp_path / "work")
    assert result["pass"]
    for variant in VARIANTS:
        checks = result["summary_reconciliations"][variant]
        assert checks[0]["future_same_encounter_context_rows"] == 1
        assert checks[0]["future_context_baseline_rows"] == 0
        assert (
            checks[2]["encounters_without_eligible_baseline_with_retained_evidence"]
            == 1
        )
        assert checks[3]["lab"]["raw_to_normalized_unit_mismatches"] == 0
        assert checks[3]["vital"]["raw_to_normalized_unit_mismatches"] == 0
        assert result["variants"][variant]["evidence_rows"][
            "encounter_element_evidence"
        ] == {
            "retained_rows": 7,
            "distinct_encounter_element_memberships": 3,
            "distinct_source_record_ids": 6,
        }
    assert all(p.read_bytes() == b"synthetic filesystem metadata" for p in sidecars)


def test_previous_bundle_format_revalidates_without_mutation(tmp_path):
    root = tmp_path / "bundle"
    _bundle(root)
    _legacy_coverage(root)
    manifest_before = (root / "manifest.json").read_bytes()
    coverage_before = (root / "source_coverage.json").read_bytes()
    report = validate_bundle(bundle=root, work_dir=tmp_path / "work")
    assert report["pass"]
    assert report["coverage_policy"] == "complete_linkage"
    assert report["coverage_policy_origin"] == "legacy_default"
    assert report["coverage_results"]["FULL_DATA"]["linkage_complete"]
    assert (root / "manifest.json").read_bytes() == manifest_before
    assert (root / "source_coverage.json").read_bytes() == coverage_before


def test_previous_bundle_incomplete_linkage_requires_explicit_exception(tmp_path):
    root = tmp_path / "bundle"
    _bundle(root)
    _add_unlinked_encounter(root)
    _legacy_coverage(root)
    with pytest.raises(ValueError, match="linkage totals differ|fails complete"):
        validate_bundle(bundle=root, work_dir=tmp_path / "strict")
    with pytest.raises(ValueError, match="documented exception"):
        validate_bundle(
            bundle=root,
            work_dir=tmp_path / "missing-exception",
            linkage_policy="permit_incomplete_linkage",
        )
    report = validate_bundle(
        bundle=root,
        work_dir=tmp_path / "permitted",
        linkage_policy="permit_incomplete_linkage",
        linkage_exception="synthetic missing encounter",
    )
    assert report["pass"]
    assert report["coverage_policy_origin"] == "legacy_explicit"
    assert report["coverage_results"]["FULL_DATA"]["encounter_unlinked"] == 1


@pytest.mark.parametrize("missing", ["policy", "policy_version", "exception"])
def test_partial_new_policy_declaration_never_falls_back_to_legacy(tmp_path, missing):
    root = tmp_path / "bundle"
    _bundle(root)
    path = root / "source_coverage.json"
    coverage = json.loads(path.read_text())
    coverage.pop(missing)
    path.write_text(json.dumps(coverage))
    _refresh_manifest(root)
    with pytest.raises(ValueError, match="partial policy declaration"):
        validate_bundle(bundle=root, work_dir=tmp_path / "work")


def test_versioned_bundle_rejects_conflicting_validation_policy(tmp_path):
    root = tmp_path / "bundle"
    _bundle(root)
    with pytest.raises(ValueError, match="differs from bundle"):
        validate_bundle(
            bundle=root,
            work_dir=tmp_path / "work",
            linkage_policy="permit_incomplete_linkage",
            linkage_exception="not the bundle policy",
        )


def test_element_inventory_must_cover_every_required_element(tmp_path):
    root = tmp_path / "bundle"
    _bundle(root, omit_element=True)
    with pytest.raises(ValueError, match="omits required"):
        validate_bundle(bundle=root, work_dir=tmp_path / "work")


def test_evidence_schema_is_checked_after_refreshing_manifest_identity(tmp_path):
    root = tmp_path / "bundle"
    _bundle(root)
    path = root / "encounter_features_full_data_diagnosis_component_evidence.parquet"
    pq.write_table(pa.table({"index_event_id": ["p-e"]}), path)
    _refresh_manifest(root)
    with pytest.raises(ValueError, match="evidence schema missing required fields"):
        validate_bundle(bundle=root, work_dir=tmp_path / "work")


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("source_element_lab_hba1c_latest_raw_value", 8.0),
        ("source_element_lab_hba1c_latest_date", pd.Timestamp("2023-12-31")),
        ("source_element_lab_hba1c_latest_unit", "mmol/mol"),
    ],
)
def test_changed_selected_summary_value_date_or_unit_fails(tmp_path, column, value):
    root = tmp_path / "bundle"
    _bundle(root)
    path = root / "encounter_features_full_data.parquet"
    frame = pd.read_parquet(path)
    frame.loc[0, column] = value
    frame.to_parquet(path, index=False)
    _refresh_manifest(root)
    with pytest.raises(ValueError, match="catalogue summary reconciliation failed"):
        validate_bundle(bundle=root, work_dir=tmp_path / "work")


@pytest.mark.parametrize(
    ("event", "valid"),
    [
        ("2020-01-01", False),
        ("2022-12-31", False),
        ("2023-01-01", True),
        ("2024-01-01", True),
    ],
)
def test_catalogue_baseline_uses_manifest_window_not_stored_flag(
    tmp_path, event, valid
):
    root = tmp_path / "bundle"
    _bundle(root)
    evidence_path = root / (
        "encounter_features_full_data_encounter_element_evidence.parquet"
    )
    evidence = pd.read_parquet(evidence_path)
    selected = evidence["element_id"] == "source.lab.egfr"
    evidence.loc[selected, "event_datetime"] = pd.Timestamp(event)
    evidence.loc[selected, "in_baseline_window"] = True
    evidence.to_parquet(evidence_path, index=False)
    feature_path = root / "encounter_features_full_data.parquet"
    features = pd.read_parquet(feature_path)
    features["source_element_lab_egfr_latest_raw_value"] = 30.0
    features["source_element_lab_egfr_latest_date"] = pd.Timestamp(event)
    features["source_element_lab_egfr_latest_unit"] = "mL/min/1.73m2"
    features.to_parquet(feature_path, index=False)
    qa_path = root / "quality_summary.json"
    qa = json.loads(qa_path.read_text())
    qa["FULL_DATA"]["null_counts"] = {
        column: int(features[column].isna().sum()) for column in features
    }
    qa_path.write_text(json.dumps(qa))
    _refresh_manifest(root)
    if valid:
        assert validate_bundle(bundle=root, work_dir=tmp_path / "work")["pass"]
    else:
        with pytest.raises(ValueError, match="baseline_flag_mismatches=1"):
            validate_bundle(bundle=root, work_dir=tmp_path / "work")


@pytest.mark.parametrize(
    ("table", "column"),
    [
        ("diagnosis_component_evidence", "event_datetime"),
        ("component_lab_evidence", "normalized_unit"),
        ("component_bp_evidence", "normalized_numeric_value"),
        ("medication_component_evidence", "source_record_hash"),
    ],
)
def test_domain_specific_required_fields_cannot_be_removed(tmp_path, table, column):
    root = tmp_path / "bundle"
    _bundle(root)
    path = root / f"encounter_features_full_data_{table}.parquet"
    _write_evidence(path, EVIDENCE_CONTRACTS[table] - {column})
    _refresh_manifest(root)
    with pytest.raises(ValueError, match=f"missing required fields.*{column}"):
        validate_bundle(bundle=root, work_dir=tmp_path / "work")


def test_incompatible_evidence_identifier_type_fails_schema_validation(tmp_path):
    root = tmp_path / "bundle"
    _bundle(root)
    table = "diagnosis_component_evidence"
    path = root / f"encounter_features_full_data_{table}.parquet"
    _write_evidence(
        path, EVIDENCE_CONTRACTS[table], type_overrides={"index_event_id": pa.int64()}
    )
    _refresh_manifest(root)
    with pytest.raises(ValueError, match="incompatible required field types"):
        validate_bundle(bundle=root, work_dir=tmp_path / "work")


def test_typed_empty_evidence_domain_passes_schema_contract(tmp_path):
    root = tmp_path / "bundle"
    _bundle(root)
    path = root / "encounter_features_full_data_diagnosis_component_evidence.parquet"
    _write_evidence(
        path, EVIDENCE_CONTRACTS["diagnosis_component_evidence"], empty=True
    )
    _refresh_manifest(root)
    assert validate_bundle(bundle=root, work_dir=tmp_path / "work")["pass"]


def test_qa_missingness_is_recomputed_independently(tmp_path):
    root = tmp_path / "bundle"
    _bundle(root)
    path = root / "quality_summary.json"
    qa = json.loads(path.read_text())
    qa["FULL_DATA"]["null_counts"]["source_count"] = 1
    path.write_text(json.dumps(qa))
    _refresh_manifest(root)
    with pytest.raises(ValueError, match="missingness discrepancy"):
        validate_bundle(bundle=root, work_dir=tmp_path / "work")


def test_coverage_totals_are_recomputed_from_typed_coverage_rows(tmp_path):
    root = tmp_path / "bundle"
    _bundle(root)
    path = root / "source_coverage.json"
    report = json.loads(path.read_text())
    report["variants"]["FULL_DATA"]["patient_linked"] = 0
    path.write_text(json.dumps(report))
    _refresh_manifest(root)
    with pytest.raises(ValueError, match="linkage totals differ"):
        validate_bundle(bundle=root, work_dir=tmp_path / "work")


def test_strict_policy_rejects_zero_linkage_despite_matching_declared_counts(tmp_path):
    root = tmp_path / "bundle"
    _bundle(root)
    path = root / "encounter_features_full_data_encounter_source_coverage.parquet"
    frame = pd.read_parquet(path)
    for column in (
        "patient_linked",
        "demographics_agree",
        "encounter_linked",
        "anchor_in_encounter",
    ):
        frame[column] = False
    frame.to_parquet(path, index=False)
    coverage_path = root / "source_coverage.json"
    coverage = json.loads(coverage_path.read_text())
    coverage["variants"]["FULL_DATA"].update(
        patient_linked=0,
        patient_unlinked=1,
        patient_linked_proportion=0.0,
        encounter_linked=0,
        encounter_unlinked=1,
        encounter_linked_proportion=0.0,
    )
    coverage_path.write_text(json.dumps(coverage))
    _refresh_manifest(root)
    with pytest.raises(ValueError, match="linkage totals differ"):
        validate_bundle(bundle=root, work_dir=tmp_path / "work")


def test_linkage_flags_must_agree_across_coverage_domains(tmp_path):
    root = tmp_path / "bundle"
    _bundle(root)
    path = root / "encounter_features_full_data_encounter_source_coverage.parquet"
    frame = pd.read_parquet(path)
    frame.loc[frame["domain"] == "medications", "encounter_linked"] = False
    frame.to_parquet(path, index=False)
    _refresh_manifest(root)
    with pytest.raises(ValueError, match="linkage flags differ across domains"):
        validate_bundle(bundle=root, work_dir=tmp_path / "work")


def test_element_availability_counts_are_recomputed_from_evidence(tmp_path):
    root = tmp_path / "bundle"
    _bundle(root)
    path = root / "encounter_features_full_data_element_inventory.json"
    inventory = json.loads(path.read_text())
    entry = next(item for item in inventory if item["element_id"] == "source.lab.hba1c")
    entry["availability_states"][0]["observed_matches"] = 0
    entry["availability_states"][0]["zero_matching_records"] = 1
    path.write_text(json.dumps(inventory))
    _refresh_manifest(root)
    with pytest.raises(ValueError, match="availability totals differ"):
        validate_bundle(bundle=root, work_dir=tmp_path / "work")


def test_evidence_keys_must_belong_to_the_current_variant(tmp_path):
    root = tmp_path / "bundle"
    _bundle(root)
    path = root / "encounter_features_full_data_diagnosis_component_evidence.parquet"
    frame = pd.read_parquet(path)
    frame.loc[0, "index_event_id"] = "other-z"
    frame.to_parquet(path, index=False)
    _refresh_manifest(root)
    with pytest.raises(ValueError, match="Evidence has keys outside"):
        validate_bundle(bundle=root, work_dir=tmp_path / "work")


def _receipt_pair():
    manifest_hash = "a" * 64
    report = {
        "pass": True,
        "validation_contract_version": "1.0",
        "bundle_manifest_sha256": manifest_hash,
        "coverage_policy": "complete_linkage",
        "coverage_policy_origin": "bundle",
        "coverage_exception": None,
        "covered_variants": ["FULL_DATA"],
        "output_identities": {"features.parquet": {"sha256": "b" * 64, "bytes": 10}},
        "product_kind": "encounter_features",
        "schema_version": "2.0",
        "feature_contract_version": "1.0",
        "source_identities": {
            "canonical": {"test": "canonical"},
            "compatibility": {"test": "companion"},
        },
        "historical_producer_code_sha256": "c" * 64,
        "validator_revision": {"encounter_package_code_sha256": "d" * 64},
        "coverage_results": {"FULL_DATA": {"pass": True, "rows": 1}},
    }
    return report, _receipt_for_report(report)


def _receipt_for_report(report):
    receipt = {
        "schema": "trinetx.encounter.acceptance-receipt",
        "validation_contract_version": "1.0",
        "bundle_manifest_sha256": report["bundle_manifest_sha256"],
        "coverage_policy": report["coverage_policy"],
        "covered_variants": report["covered_variants"],
        "validation_report_sha256": hashlib.sha256(
            json.dumps(report).encode()
        ).hexdigest(),
        "output_identities": report["output_identities"],
        "product_kind": report["product_kind"],
        "schema_version": report["schema_version"],
        "feature_contract_version": report["feature_contract_version"],
        "source_identities": report["source_identities"],
        "historical_producer_code_sha256": report["historical_producer_code_sha256"],
        "validator_revision": report["validator_revision"],
        "coverage_policy_origin": report["coverage_policy_origin"],
        "coverage_results": report["coverage_results"],
        "coverage_exception": report["coverage_exception"],
        "reference_comparison": {"status": "not_performed"},
        "producer_revision": None,
        "consumer_revision": None,
        "exceptions": [],
        "limitations": ["synthetic fixture"],
        "required_gates": ["artifact_validation"],
        "gates": {"artifact_validation": "pass", "build_completion": "pass"},
    }
    return receipt


def test_acceptance_receipt_readback_binds_report_manifest_policy_and_variants():
    report, receipt = _receipt_pair()
    manifest_hash = report["bundle_manifest_sha256"]
    report_bytes = json.dumps(report).encode()
    receipt["validation_report_sha256"] = hashlib.sha256(report_bytes).hexdigest()
    assert verify_acceptance_receipt(
        receipt,
        expected_manifest_sha256=manifest_hash,
        expected_policy="complete_linkage",
        expected_variants=["FULL_DATA"],
        expected_required_gates=["artifact_validation"],
        validation_report_bytes=report_bytes,
    )["pass"]


def test_receipt_readback_accepts_actual_synthetic_validator_report(tmp_path):
    root = tmp_path / "bundle"
    _bundle(root)
    report = validate_bundle(bundle=root, work_dir=tmp_path / "work")
    report_bytes = json.dumps(report).encode()
    receipt = _receipt_for_report(report)
    assert verify_acceptance_receipt(
        receipt,
        expected_manifest_sha256=report["bundle_manifest_sha256"],
        expected_policy="complete_linkage",
        expected_variants=list(VARIANTS),
        expected_required_gates=["artifact_validation"],
        validation_report_bytes=report_bytes,
    )["pass"]


@pytest.mark.parametrize(
    "missing",
    [
        "product_kind",
        "schema_version",
        "output_identities",
        "source_identities",
        "historical_producer_code_sha256",
        "validator_revision",
        "coverage_policy_origin",
        "coverage_exception",
        "coverage_results",
    ],
)
def test_receipt_and_report_cannot_share_missing_identity(tmp_path, missing):
    report, receipt = _receipt_pair()
    report.pop(missing)
    receipt.pop(missing)
    report_bytes = json.dumps(report).encode()
    receipt["validation_report_sha256"] = hashlib.sha256(report_bytes).hexdigest()
    with pytest.raises(ValueError, match="Validation report"):
        verify_acceptance_receipt(
            receipt,
            expected_manifest_sha256="a" * 64,
            expected_policy="complete_linkage",
            expected_variants=["FULL_DATA"],
            expected_required_gates=["artifact_validation"],
            validation_report_bytes=report_bytes,
        )


def test_receipt_rejects_unsupported_report_version():
    report, receipt = _receipt_pair()
    report["validation_contract_version"] = "9.0"
    report_bytes = json.dumps(report).encode()
    receipt["validation_report_sha256"] = hashlib.sha256(report_bytes).hexdigest()
    with pytest.raises(ValueError, match="Unsupported validation report contract"):
        verify_acceptance_receipt(
            receipt,
            expected_manifest_sha256="a" * 64,
            expected_policy="complete_linkage",
            expected_variants=["FULL_DATA"],
            expected_required_gates=["artifact_validation"],
            validation_report_bytes=report_bytes,
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("covered_variants", None),
        ("output_identities", {"artifact": {"sha256": "b" * 64, "bytes": True}}),
        ("validator_revision", {"encounter_package_code_sha256": None}),
        ("coverage_results", {"FULL_DATA": {"pass": True, "rows": True}}),
    ],
)
def test_acceptance_receipt_rejects_invalid_identity_types(field, value):
    report, receipt = _receipt_pair()
    receipt[field] = value
    report_bytes = json.dumps(report).encode()
    with pytest.raises(ValueError, match="variant scope|invalid report identities"):
        verify_acceptance_receipt(
            receipt,
            expected_manifest_sha256=report["bundle_manifest_sha256"],
            expected_policy="complete_linkage",
            expected_variants=["FULL_DATA"],
            expected_required_gates=["artifact_validation"],
            validation_report_bytes=report_bytes,
        )


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("manifest", "manifest identity"),
        ("policy", "coverage policy"),
        ("variant", "variant scope"),
        ("gate", "Required acceptance gates"),
        ("report_bytes", "report bytes"),
        ("unsupported", "Unsupported validation contract"),
        ("complete_only", "trusted required gates"),
        ("producer", "does not bind"),
    ],
)
def test_acceptance_receipt_rejects_wrong_or_incomplete_bindings(mutation, message):
    report, receipt = _receipt_pair()
    manifest_hash = report["bundle_manifest_sha256"]
    report_bytes = json.dumps(report).encode()
    if mutation == "manifest":
        receipt["bundle_manifest_sha256"] = "c" * 64
    expected_manifest = manifest_hash
    if mutation == "policy":
        receipt["coverage_policy"] = "permit_incomplete_linkage"
    if mutation == "variant":
        receipt["covered_variants"] = ["AFTER_EXCLUSION"]
    if mutation == "gate":
        receipt["gates"]["artifact_validation"] = "failed"
    if mutation == "report_bytes":
        report_bytes += b" "
    if mutation == "unsupported":
        receipt["validation_contract_version"] = "9.0"
    if mutation == "complete_only":
        receipt["required_gates"] = ["build_completion"]
        receipt["gates"] = {"build_completion": "pass"}
    if mutation == "producer":
        receipt["historical_producer_code_sha256"] = "e" * 64
    if mutation != "report_bytes":
        receipt["validation_report_sha256"] = hashlib.sha256(report_bytes).hexdigest()
    with pytest.raises(ValueError, match=message):
        verify_acceptance_receipt(
            receipt,
            expected_manifest_sha256=expected_manifest,
            expected_policy="complete_linkage",
            expected_variants=["FULL_DATA"],
            expected_required_gates=["artifact_validation"],
            validation_report_bytes=report_bytes,
        )


def test_validate_cli_writes_structured_failure_report(tmp_path):
    from trinetx_preprocessing.encounters.cli import validate_main

    report_path = tmp_path / "validation.json"
    result = validate_main(
        [
            "--bundle",
            str(tmp_path / "missing-bundle"),
            "--work-dir",
            str(tmp_path / "work"),
            "--report",
            str(report_path),
        ]
    )
    report = json.loads(report_path.read_text())
    assert result == 1
    assert report["pass"] is False
    assert report["failure"]["artifact"] == "encounter_bundle"
    assert report["failure"]["invariant"] == "validation_contract"
    assert "FileNotFoundError" in report["failure"]["discrepancy"]

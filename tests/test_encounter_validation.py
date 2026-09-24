import json
from datetime import datetime

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from trinetx_preprocessing.encounters.acceptance import load_artifact_contract
from trinetx_preprocessing.encounters.builder import EVIDENCE_TABLES, VARIANTS
from trinetx_preprocessing.encounters.cli import validate_main
from trinetx_preprocessing.encounters.compatibility import artifact_inventory, digest
from trinetx_preprocessing.encounters.validation import validate_bundle


def _arrow_type(name):
    if name == "date32[day]":
        return pa.date32()
    if name == "timestamp[us]":
        return pa.timestamp("us")
    duckdb_types = {
        "FLOAT": pa.float32(),
        "BIGINT": pa.int64(),
        "DOUBLE": pa.float64(),
        "VARCHAR": pa.string(),
        "TIMESTAMP": pa.timestamp("us"),
        "BOOLEAN": pa.bool_(),
        "TINYINT": pa.int8(),
        "DATE": pa.date32(),
        "INTEGER": pa.int32(),
    }
    if name in duckdb_types:
        return duckdb_types[name]
    return pa.type_for_alias(name)


def _typed_evidence(table, keys, domains=None):
    columns = {}
    for name, dtype in load_artifact_contract()["tables"][table].items():
        values = keys if name == "index_event_id" else [None] * len(keys)
        if name == "domain" and domains is not None:
            values = domains
        if table == "encounter_source_coverage" and name == "history_state":
            values = ["unknown"] * len(keys)
        if table == "component_lab_evidence":
            if name == "concept_set_id":
                values = ["hba1c"]
            elif name == "normalized_numeric_value":
                values = [6.5]
            elif name == "event_datetime":
                values = [datetime(2020, 1, 1)]
            elif name == "source_record_hash":
                values = ["lab-1"]
        if table == "encounter_element_evidence":
            if name == "element_id":
                values = ["source.hba1c", "source.bmi"]
            elif name == "domain":
                values = ["labs", "vitals"]
            elif name == "in_baseline_window":
                values = [False, False]
        columns[name] = pa.array(values, type=_arrow_type(dtype))
    return pa.table(columns)


def _make_bundle(tmp_path, *, omit_element=False):
    root = tmp_path / "bundle"
    root.mkdir()
    dictionaries, qa = {}, {}
    for variant in VARIANTS:
        stem = f"encounter_features_{variant.lower()}"
        schema = load_artifact_contract()["features"][variant]
        populated = {
            "patient_id": "p",
            "encounter_id": "e",
            "pat_enc_hash": "p-e",
            "source_element_hba1c_record_count": 1,
            "source_element_bmi_record_count": 1,
            "glp1_lab_a1c_latest": 6.5,
            "glp1_lab_a1c_latest_date": datetime(2020, 1, 1),
        }
        pq.write_table(
            pa.table(
                {
                    name: pa.array([populated.get(name)], type=_arrow_type(dtype))
                    for name, dtype in schema.items()
                }
            ),
            root / (stem + ".parquet"),
        )
        dictionaries[variant] = [
            {
                "column": c,
                "dtype": dtype,
                "anchor_precision": "calendar day",
            }
            for c, dtype in schema.items()
        ]
        qa[variant] = {
            "rows": 1,
            "null_counts": {name: int(name not in populated) for name in schema},
        }
        inventory = [
            {
                "element_id": element,
                "domain": domain,
                "columns": [
                    f"source_element_{label}_record_count",
                    f"source_element_{label}_latest_raw_value",
                    f"source_element_{label}_latest_date",
                    f"source_element_{label}_latest_unit",
                ],
                "availability_states": [
                    {
                        "history_state": "unknown",
                        "observed_matches": 1,
                        "zero_matching_records": 0,
                    }
                ],
            }
            for element, label, domain in (
                ("source.hba1c", "hba1c", "labs"),
                ("source.bmi", "bmi", "vitals"),
            )
        ]
        (root / (stem + "_element_inventory.json")).write_text(
            json.dumps([] if omit_element else inventory)
        )
        for table in EVIDENCE_TABLES:
            pq.write_table(
                _typed_evidence(
                    table,
                    []
                    if table == "component_bp_evidence"
                    else ["p-e", "p-e"]
                    if table == "encounter_element_evidence"
                    else ["p-e"],
                ),
                root / f"{stem}_{table}.parquet",
            )
        pq.write_table(
            _typed_evidence(
                "encounter_source_coverage",
                ["p-e"] * 5,
                ["diagnosis", "labs", "vitals", "medications", "procedure"],
            ),
            root / f"{stem}_encounter_source_coverage.parquet",
        )
    (root / "data_dictionary.json").write_text(json.dumps(dictionaries))
    (root / "quality_summary.json").write_text(json.dumps(qa))
    (root / "source_coverage.json").write_text(
        json.dumps({"pass": True, "source": {"test": True}})
    )
    # The private macOS output volume creates these alongside real products.
    # They must not turn the exact analytical-artifact contract into a false fail.
    sidecars = [root / "._data_dictionary.json", root / "._features.parquet"]
    for sidecar in sidecars:
        sidecar.write_bytes(b"synthetic filesystem metadata")
    manifest = {
        "schema_version": "2.0",
        "status": "complete",
        "kind": "encounter_features",
        "feature_contract_version": "1.0",
        "source": {"test": True},
        "required_source_elements": ["source.hba1c", "source.bmi"],
        "outputs": artifact_inventory(root),
    }
    (root / "manifest.json").write_text(json.dumps(manifest))
    return root, sidecars


def _refresh_manifest(root):
    path = root / "manifest.json"
    manifest = json.loads(path.read_text())
    manifest["outputs"] = {
        name: {"sha256": digest(root / name), "bytes": (root / name).stat().st_size}
        for name in manifest["outputs"]
    }
    path.write_text(json.dumps(manifest))


@pytest.mark.parametrize("omit_element", [False, True])
def test_complete_bundle_requires_element_and_domain_coverage(tmp_path, omit_element):
    root, sidecars = _make_bundle(tmp_path, omit_element=omit_element)
    if omit_element:
        with pytest.raises(ValueError, match="omits required"):
            validate_bundle(bundle=root, work_dir=tmp_path / "work")
    else:
        assert validate_bundle(bundle=root, work_dir=tmp_path / "work")["pass"]
    assert all(p.read_bytes() == b"synthetic filesystem metadata" for p in sidecars)


@pytest.mark.parametrize(
    "table,field,wrong_type",
    [
        ("diagnosis_component_evidence", "event_datetime", False),
        ("component_lab_evidence", "normalized_numeric_value", False),
        ("component_bp_evidence", "units_of_measure", False),
        ("medication_component_evidence", "source_record_hash", False),
        ("procedure_component_evidence", "code_system", True),
        ("encounter_source_coverage", "history_state", False),
    ],
)
def test_evidence_schema_mutation_fails_after_checksum_refresh(
    tmp_path, table, field, wrong_type
):
    root, _ = _make_bundle(tmp_path)
    path = root / f"encounter_features_full_data_{table}.parquet"
    table_data = pq.read_table(path)
    if wrong_type:
        index = table_data.schema.get_field_index(field)
        table_data = table_data.set_column(
            index, field, pa.array([1] * len(table_data), type=pa.int64())
        )
    else:
        table_data = table_data.drop([field])
    pq.write_table(table_data, path)
    _refresh_manifest(root)
    with pytest.raises(ValueError, match=rf"schema differs.*{field}"):
        validate_bundle(bundle=root, work_dir=tmp_path / "work")


def test_qa_null_count_mutation_fails_after_checksum_refresh(tmp_path):
    root, _ = _make_bundle(tmp_path)
    path = root / "quality_summary.json"
    summary = json.loads(path.read_text())
    summary["FULL_DATA"]["null_counts"]["source_element_bmi_record_count"] = 1
    path.write_text(json.dumps(summary))
    _refresh_manifest(root)
    with pytest.raises(ValueError, match="QA null counts differ"):
        validate_bundle(bundle=root, work_dir=tmp_path / "work")


def test_validation_cli_writes_structured_failure_and_nonzero_exit(tmp_path):
    root, _ = _make_bundle(tmp_path)
    path = root / "quality_summary.json"
    qa = json.loads(path.read_text())
    qa["FULL_DATA"]["null_counts"]["source_element_bmi_record_count"] = 1
    path.write_text(json.dumps(qa))
    _refresh_manifest(root)
    report = tmp_path / "failure.json"
    assert (
        validate_main(
            [
                "--bundle",
                str(root),
                "--work-dir",
                str(tmp_path / "work"),
                "--report",
                str(report),
            ]
        )
        == 1
    )
    failure = json.loads(report.read_text())
    assert failure["pass"] is False
    assert failure["failures"][0]["artifact"] == "quality_summary.json"
    assert failure["failures"][0]["invariant"] == "feature_null_counts"
    assert "QA null counts differ" in failure["failures"][0]["aggregate_discrepancy"]


def _replace_column(path, name, values, dtype):
    table = pq.read_table(path)
    index = table.schema.get_field_index(name)
    pq.write_table(table.set_column(index, name, pa.array(values, type=dtype)), path)


def test_source_record_count_mutation_fails_after_checksum_refresh(tmp_path):
    root, _ = _make_bundle(tmp_path)
    path = root / "encounter_features_full_data.parquet"
    _replace_column(path, "source_element_bmi_record_count", [2], pa.int64())
    _refresh_manifest(root)
    with pytest.raises(ValueError, match="source-record count differs: source.bmi"):
        validate_bundle(bundle=root, work_dir=tmp_path / "work")


def test_availability_metadata_mutation_fails_after_checksum_refresh(tmp_path):
    root, _ = _make_bundle(tmp_path)
    path = root / "encounter_features_full_data_element_inventory.json"
    inventory = json.loads(path.read_text())
    state = inventory[0]["availability_states"][0]
    state.update(observed_matches=0, zero_matching_records=1)
    path.write_text(json.dumps(inventory))
    _refresh_manifest(root)
    with pytest.raises(ValueError, match="Element availability differs"):
        validate_bundle(bundle=root, work_dir=tmp_path / "work")


def test_latest_triplet_mutation_fails_after_checksum_refresh(tmp_path):
    root, _ = _make_bundle(tmp_path)
    path = root / "encounter_features_full_data.parquet"
    _replace_column(path, "source_element_bmi_latest_raw_value", [35.0], pa.float64())
    qa_path = root / "quality_summary.json"
    qa = json.loads(qa_path.read_text())
    qa["FULL_DATA"]["null_counts"]["source_element_bmi_latest_raw_value"] = 0
    qa_path.write_text(json.dumps(qa))
    _refresh_manifest(root)
    with pytest.raises(
        ValueError, match="latest raw value/date/unit differs: source.bmi"
    ):
        validate_bundle(bundle=root, work_dir=tmp_path / "work")


def test_later_context_measurement_does_not_enter_baseline(tmp_path):
    root, _ = _make_bundle(tmp_path)
    path = root / "encounter_features_full_data_encounter_element_evidence.parquet"
    _replace_column(
        path,
        "event_datetime",
        [datetime(2027, 1, 1), datetime(2027, 1, 1)],
        pa.timestamp("us"),
    )
    _replace_column(path, "numeric_value", [6.2, 35.0], pa.float64())
    _replace_column(path, "units_of_measure", ["percent", "kg/m2"], pa.string())
    _refresh_manifest(root)
    assert validate_bundle(bundle=root, work_dir=tmp_path / "work")["pass"]


def test_normalized_lab_summary_mutation_fails(tmp_path):
    root, _ = _make_bundle(tmp_path)
    path = root / "encounter_features_full_data.parquet"
    _replace_column(path, "glp1_lab_a1c_latest", [7.0], pa.float64())
    _refresh_manifest(root)
    with pytest.raises(ValueError, match="Normalized HBA1c latest value/date differs"):
        validate_bundle(bundle=root, work_dir=tmp_path / "work")


def _add_kpa_bp(root, *, normalized=None, wide=None):
    expected = 16.0 * 7.5006168270417
    evidence_path = root / "encounter_features_full_data_component_bp_evidence.parquet"
    values = {
        "index_event_id": "p-e",
        "concept_set_id": "systolic_bp",
        "raw_numeric_value": 16.0,
        "unit_key": "kpa",
        "normalized_numeric_value": expected if normalized is None else normalized,
        "event_datetime": datetime(2020, 1, 1),
        "source_record_hash": "bp-1",
        "encounter_type": "AMB",
    }
    schema = load_artifact_contract()["tables"]["component_bp_evidence"]
    pq.write_table(
        pa.table(
            {
                name: pa.array([values.get(name)], type=_arrow_type(dtype))
                for name, dtype in schema.items()
            }
        ),
        evidence_path,
    )
    feature_path = root / "encounter_features_full_data.parquet"
    _replace_column(
        feature_path,
        "glp1_bp_latest_sbp",
        [expected if wide is None else wide],
        pa.float64(),
    )
    qa_path = root / "quality_summary.json"
    qa = json.loads(qa_path.read_text())
    qa["FULL_DATA"]["null_counts"]["glp1_bp_latest_sbp"] = 0
    qa_path.write_text(json.dumps(qa))
    _refresh_manifest(root)


def test_kpa_bp_normalization_and_summary_reconciliation(tmp_path):
    root, _ = _make_bundle(tmp_path)
    _add_kpa_bp(root)
    assert validate_bundle(bundle=root, work_dir=tmp_path / "pass-work")["pass"]
    _add_kpa_bp(root, normalized=999.0)
    with pytest.raises(ValueError, match="normalized value/unit differs"):
        validate_bundle(bundle=root, work_dir=tmp_path / "unit-work")
    _add_kpa_bp(root, wide=130.0)
    with pytest.raises(ValueError, match="systolic BP latest value differs"):
        validate_bundle(bundle=root, work_dir=tmp_path / "summary-work")

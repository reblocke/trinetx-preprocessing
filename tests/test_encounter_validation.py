import json

import pandas as pd
import pytest

from trinetx_preprocessing.encounters.builder import EVIDENCE_TABLES, VARIANTS
from trinetx_preprocessing.encounters.compatibility import artifact_inventory
from trinetx_preprocessing.encounters.validation import validate_bundle


@pytest.mark.parametrize("omit_element", [False, True])
def test_complete_bundle_requires_element_and_domain_coverage(tmp_path, omit_element):
    root = tmp_path / "bundle"
    root.mkdir()
    dictionaries, qa = {}, {}
    for variant in VARIANTS:
        stem = f"encounter_features_{variant.lower()}"
        frame = pd.DataFrame(
            {
                "patient_id": ["p"],
                "encounter_id": ["e"],
                "pat_enc_hash": ["p-e"],
                "source_count": [1],
            }
        )
        frame.to_parquet(root / (stem + ".parquet"), index=False)
        dictionaries[variant] = [
            {"column": c, "anchor_precision": "calendar day"} for c in frame
        ]
        qa[variant] = {"rows": 1, "null_counts": {c: 0 for c in frame}}
        inventory = [
            {
                "element_id": "source.synthetic",
                "columns": ["source_count"],
                "availability_states": [
                    {"observed_matches": 1, "zero_matching_records": 0}
                ],
            }
        ]
        (root / (stem + "_element_inventory.json")).write_text(
            json.dumps([] if omit_element else inventory)
        )
        for table in EVIDENCE_TABLES:
            pd.DataFrame({"index_event_id": ["p-e"]}).to_parquet(
                root / f"{stem}_{table}.parquet", index=False
            )
        pd.DataFrame(
            {
                "index_event_id": ["p-e"] * 5,
                "domain": ["diagnosis", "labs", "vitals", "medications", "procedure"],
            }
        ).to_parquet(root / f"{stem}_encounter_source_coverage.parquet", index=False)
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
        "required_source_elements": ["source.synthetic"],
        "outputs": artifact_inventory(root),
    }
    (root / "manifest.json").write_text(json.dumps(manifest))
    if omit_element:
        with pytest.raises(ValueError, match="omits required"):
            validate_bundle(bundle=root, work_dir=tmp_path / "work")
    else:
        assert validate_bundle(bundle=root, work_dir=tmp_path / "work")["pass"]
    assert all(p.read_bytes() == b"synthetic filesystem metadata" for p in sidecars)

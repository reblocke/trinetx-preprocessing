"""The authenticated import preserves the accepted parser's exact input frames."""

import json

import duckdb
import pandas as pd
import pytest

from trinetx_preprocessing.combined_preprocessing.contract import compatibility_outputs
from trinetx_preprocessing.encounters.compatibility import (
    CSV_OPTIONS,
    digest,
    import_compatibility,
    read_frame,
    validate_companion,
)
from trinetx_preprocessing.encounters.legacy.raw_schema import load_schema


def inputs(tmp_path):
    root = tmp_path / "inputs"
    receipt = {"input_root": str(root), "inputs": {}}
    columns = [c.raw_name for c in load_schema().columns]
    frame = pd.DataFrame("", index=range(4), columns=columns)
    # Boundary includes empty/all-empty fields, duplicate rows, leading zeros,
    # numeric-looking strings, sentinels, timestamps and float-rounding inputs.
    frame.iloc[:, 0] = ["00001", "00001", "NA", "NULL"]
    frame.iloc[:, 1] = ["001.0", "001.0", "N/A", "none"]
    frame.iloc[:, 2] = ["45.00000000000001", "45.00000000000001", "", "-0"]
    frame.iloc[:, 3] = ["2022-01-01", "2022-01-01", ".", "2022-01-01 12:00:00"]
    for part in compatibility_outputs():
        path = root / part.relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        frame.to_csv(path, index=False)
        receipt["inputs"][part.key] = {
            "sha256": digest(path),
            "accepted_match": True,
            "unchanged": True,
        }
    identity = tmp_path / "identity.json"
    identity.write_text(json.dumps(receipt))
    return root, identity


def test_exact_parser_roundtrip(tmp_path):
    root, identity = inputs(tmp_path)
    database = tmp_path / "companion.duckdb"
    import_compatibility(
        input_root=root, identity_receipt=identity, database=database, chunk_rows=2
    )
    assert len(validate_companion(database)["partitions"]) == 36
    with duckdb.connect(str(database), read_only=True) as db:
        for part in compatibility_outputs():
            expected = pd.read_csv(root / part.relative_path, **CSV_OPTIONS)
            pd.testing.assert_frame_equal(
                read_frame(db, part.key), expected, check_exact=True
            )
    with database.open("ab") as stream:
        stream.write(b"changed")
    with pytest.raises(ValueError, match="identity"):
        validate_companion(database)


def test_changed_input_fails_before_import(tmp_path):
    root, identity = inputs(tmp_path)
    with (root / compatibility_outputs()[0].relative_path).open("a") as stream:
        stream.write("bad\n")
    output = tmp_path / "companion.duckdb"
    with pytest.raises(ValueError, match="accepted identity"):
        import_compatibility(
            input_root=root, identity_receipt=identity, database=output
        )
    assert not output.exists()


def test_cleaned_key_collision_fails_before_enrichment(tmp_path):
    from trinetx_preprocessing.encounters.base import publish_keyed_base

    with duckdb.connect() as db:
        db.execute(
            "CREATE TABLE cleaned_source_keys AS SELECT 'a-b-c' pat_enc_hash, "
            "'a-b' patient_id, 'c' encounter_id UNION ALL SELECT 'a-b-c','a','b-c'"
        )
        with pytest.raises(ValueError, match="uniquely identify"):
            publish_keyed_base(db, tmp_path / "unused", tmp_path / "output")


def test_both_legacy_bases_preserve_original_keys(tmp_path):
    from pathlib import Path

    from trinetx_preprocessing.encounters.base import build_legacy_bases

    root = Path(__file__).parent / "fixtures/encounter_compatibility"
    identity = tmp_path / "fixture_identity.json"
    identity.write_text(
        json.dumps(
            {
                "input_root": str(root),
                "inputs": {
                    o.key: {
                        "sha256": digest(root / o.relative_path),
                        "accepted_match": True,
                        "unchanged": True,
                    }
                    for o in compatibility_outputs()
                },
            }
        )
    )
    companion = tmp_path / "fixture.duckdb"
    import_compatibility(input_root=root, identity_receipt=identity, database=companion)
    bundle = tmp_path / "base"
    result = build_legacy_bases(compatibility_database=companion, output_dir=bundle)
    assert result["kind"] == "legacy_base"
    for variant in ("FULL_DATA", "AFTER_EXCLUSION"):
        frame = pd.read_parquet(
            bundle / f"encounter_features_{variant.lower()}.parquet"
        )
        assert frame.pat_enc_hash.eq(frame.patient_id + "-" + frame.encounter_id).all()
        assert frame[["patient_id", "encounter_id"]].duplicated().sum() == 0
        assert frame.patient_id.nunique() < len(frame)
        assert frame.legacy_patient_id.dtype.kind in "iu"

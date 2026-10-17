"""New encounter mapping with independently specified source-to-product results."""

import hashlib
import json

import duckdb
import pytest


def test_calendar_covariates_source_product_and_reader(tmp_path):
    from trinetx_preprocessing.encounters.calendar_covariates import (
        build_calendar_covariates,
        read_calendar_covariates,
        write_calendar_covariates,
    )

    with duckdb.connect() as c:
        c.execute(
            "CREATE TABLE candidates(patient_id VARCHAR,encounter_id VARCHAR,"
            "encounter_start_date DATE,encounter_type VARCHAR,year_of_birth INTEGER)"
        )
        c.execute(
            "INSERT INTO candidates VALUES "
            "('p','a','2022-01-01','EMER',1980),('p','b','2022-02-01','IMP',1980),"
            "('q','c','2022-01-01','EMER',1970),('r','d','2022-01-01','IMP',1960),"
            "('s','e','2022-01-01','EMER',1990),('t','f','2022-01-01','EMER',1990),"
            "('u','g','2022-01-01','EMER',1990),('v','h','2022-01-01','EMER',1990)"
        )
        c.execute(
            "CREATE TABLE source_patient(patient_id VARCHAR,sex VARCHAR,race VARCHAR,"
            "ethnicity VARCHAR,patient_regional_location VARCHAR)"
        )
        c.execute(
            "INSERT INTO source_patient SELECT DISTINCT patient_id,'F','White',"
            "'Not Hispanic or Latino','West' FROM candidates"
        )
        c.execute(
            "CREATE TABLE source_vital_measurement(source_record_id VARCHAR,"
            "patient_id VARCHAR,encounter_id VARCHAR,code_system VARCHAR,code VARCHAR,"
            "event_datetime TIMESTAMP,timestamp_precision VARCHAR,value VARCHAR,"
            "numeric_value DOUBLE,text_value VARCHAR,units_of_measure VARCHAR)"
        )
        records = [
            ("bmi1", "p", "a", "39156-5", "2022-01-01", 31.2, "kg/m2"),
            ("bmi2", "p", "b", "39156-5", "2022-02-01", 36.4, "kg/m2"),
            ("old", "q", "old", "39156-5", "2021-12-01", 32.6, "kg/m2"),
            ("future", "q", "future", "39156-5", "2022-02-01", 45.0, "kg/m2"),
            ("w", "r", "d", "29463-7", "2022-01-01", 200.0, "lb"),
            ("h", "r", "old", "8302-2", "2021-12-01", 65.0, "[in_us]"),
            ("mask", "s", "e", "39156-5", "2022-01-01", 50.1, "kg/m2"),
            ("tie1", "t", "f", "39156-5", "2022-01-01", 35.0, "kg/m2"),
            ("tie2", "t", "f", "39156-5", "2022-01-01", 36.0, "kg/m2"),
            ("undated", "u", "g", "39156-5", None, 33.0, "kg/m2"),
        ]
        for record, patient, encounter, code, day, value, unit in records:
            c.execute(
                "INSERT INTO source_vital_measurement VALUES (?,?,?,'LOINC',?,?,"
                "'date_only',?,?,NULL,?)",
                [record, patient, encounter, code, day, str(value), value, unit],
            )
        c.execute(
            "INSERT INTO candidates VALUES "
            "('x','i','2022-01-01','EMER',1980), "
            "('y','j','2022-01-01','EMER',1980), "
            "('z','k','2022-01-01','EMER',1980)"
        )
        c.execute(
            "INSERT INTO source_patient VALUES "
            "('x','F','White','Not Hispanic or Latino','West'), "
            "('y','F','White','Not Hispanic or Latino','West'), "
            "('z','F','White','Not Hispanic or Latino','West')"
        )
        for record, patient, encounter, code, value, unit in [
            ("fraction", "x", "i", "39156-5", 30.04, "kg/m2"),
            ("fraction-w", "y", "j", "29463-7", 200.49, "lb"),
            ("fraction-h", "y", "j", "8302-2", 65, "[in_us]"),
            ("limit-w", "z", "k", "29463-7", 200, "lb"),
            ("limit-h", "z", "k", "8302-2", 84, "[in_us]"),
        ]:
            c.execute(
                "INSERT INTO source_vital_measurement VALUES "
                "(?,?,?,'LOINC',?,'2022-01-01','date_only',?,?,NULL,?)",
                [record, patient, encounter, code, str(value), value, unit],
            )
        result = build_calendar_covariates(
            c, candidate_relation="candidates", vital_capture_available=True
        )
        # These values are the independent scientific oracle, not derived by the mapper.
        actual = c.execute(
            f"SELECT encounter_id,round(bmi::DOUBLE,1),bmi_method,bmi_evidence_state,"
            f"age_at_encounter,sex,race_ethnicity,location FROM {result}"
            " ORDER BY encounter_id"
        ).fetchall()
        assert actual == [
            ("a", 31.2, "current", "valid", 42, "0", "0", "3"),
            ("b", 36.4, "current", "valid", 42, "0", "0", "3"),
            ("c", 32.6, "prior", "valid", 52, "0", "0", "3"),
            ("d", 33.3, "calculated", "valid", 62, "0", "0", "3"),
            ("e", None, "none", "missing", 32, "0", "0", "3"),
            ("f", None, "none", "unresolved", 32, "0", "0", "3"),
            ("g", None, "none", "unresolved", 32, "0", "0", "3"),
            ("h", None, "none", "missing", 32, "0", "0", "3"),
            # Legacy float16 -> CSV 30.05 -> Stata float32 30.049999...
            # precedes round(..., .1), so this is exactly BMI 30.
            ("i", 30.0, "current", "valid", 42, "0", "0", "3"),
            ("j", 33.4, "calculated", "valid", 42, "0", "0", "3"),
            ("k", None, "none", "missing", 42, "0", "0", "3"),
        ]
        out = tmp_path / "mapping"
        receipt = write_calendar_covariates(
            c, result, out, source_identity={"synthetic": True}
        )
        read = read_calendar_covariates(out, expected_manifest_sha256=receipt)
        assert len(read) == 11
        assert list(read.encounter_id) == list("abcdefghijk")
        manifest = json.loads((out / "manifest.json").read_text())
        assert manifest["clinical_results_qualified"] is False
        (out / "covariates.parquet").write_bytes(b"corrupted")
        with pytest.raises(ValueError, match="hash"):
            read_calendar_covariates(out, expected_manifest_sha256=receipt)


def _small_source(c):
    c.execute(
        "CREATE TABLE candidates(patient_id VARCHAR,encounter_id VARCHAR,"
        "encounter_start_date DATE,encounter_end_date DATE,"
        "encounter_type VARCHAR,year_of_birth INTEGER)"
    )
    c.execute(
        "INSERT INTO candidates VALUES ('p','a','2022-01-01','2022-01-03','EMER',1980)"
    )
    c.execute(
        "CREATE TABLE source_patient(patient_id VARCHAR,sex VARCHAR,race VARCHAR,"
        "ethnicity VARCHAR,patient_regional_location VARCHAR)"
    )
    c.execute(
        "INSERT INTO source_patient VALUES "
        "('p','F','White','Not Hispanic or Latino','West')"
    )
    c.execute(
        "CREATE TABLE source_vital_measurement(source_record_id VARCHAR,"
        "patient_id VARCHAR,encounter_id VARCHAR,code_system VARCHAR,code VARCHAR,"
        "event_datetime TIMESTAMP,timestamp_precision VARCHAR,value VARCHAR,"
        "numeric_value DOUBLE,text_value VARCHAR,units_of_measure VARCHAR)"
    )
    c.execute(
        "INSERT INTO source_vital_measurement VALUES "
        "('v','p','a','LOINC','39156-5','2022-01-01','date_only',"
        "'31.2',31.2,NULL,'kg/m2')"
    )


def _digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.parametrize(
    "scenario",
    [
        "chosen",
        "ChOsEn",
        "typed",
        "TyPeD",
        "output_candidates",
        "output_vitals",
        "output_people",
        "blank_record",
        "space_record",
        "reversed_dates",
        "timestamp_start",
        "unknown_start",
        "unknown_precision",
        "timestamp_precision",
        "after_end",
        "capture_unavailable",
        "metric_components",
        "missing_demographics",
        "conflicting_demographics",
        "category_precedence",
        "version",
        "missing_column",
        "null_key",
        "duplicate_key",
        "existing_directory",
        "symlink_directory",
        "query_failure",
    ],
)
def test_calendar_covariates_adversarial_roundtrip(tmp_path, scenario):
    from trinetx_preprocessing.encounters.calendar_covariates import (
        build_calendar_covariates,
        read_calendar_covariates,
        write_calendar_covariates,
    )

    with duckdb.connect() as c:
        _small_source(c)
        kwargs = {"candidate_relation": "candidates", "vital_capture_available": True}
        if scenario in ("chosen", "ChOsEn", "typed", "TyPeD"):
            c.execute(f'ALTER TABLE candidates RENAME TO "{scenario}"')
            kwargs["candidate_relation"] = scenario
        if scenario.startswith("output_"):
            kwargs["output_relation"] = {
                "output_candidates": "CANDIDATES",
                "output_vitals": "SOURCE_VITAL_MEASUREMENT",
                "output_people": "SOURCE_PATIENT",
            }[scenario]
        if scenario in ("blank_record", "space_record"):
            c.execute(
                "UPDATE source_vital_measurement SET source_record_id=?",
                ["" if scenario == "blank_record" else "  "],
            )
        if scenario == "reversed_dates":
            c.execute("UPDATE candidates SET encounter_end_date='2021-12-31'")
        if scenario == "timestamp_start":
            c.execute(
                "ALTER TABLE candidates ALTER encounter_start_date TYPE TIMESTAMP"
            )
        if scenario == "unknown_start":
            c.execute("UPDATE candidates SET encounter_start_date=NULL")
        if scenario in ("unknown_precision", "timestamp_precision"):
            c.execute(
                "UPDATE source_vital_measurement SET timestamp_precision=?",
                [None if scenario == "unknown_precision" else "timestamp"],
            )
        if scenario == "after_end":
            c.execute("UPDATE source_vital_measurement SET event_datetime='2022-01-04'")
        if scenario == "capture_unavailable":
            kwargs["vital_capture_available"] = False
        if scenario == "metric_components":
            c.execute("DELETE FROM source_vital_measurement")
            c.execute(
                "INSERT INTO source_vital_measurement VALUES "
                "('h','p','a','LOINC','8302-2','2022-01-01','date_only',"
                "'165.1',165.1,NULL,'cm'),"
                "('w','p','a','LOINC','29463-7','2022-01-01','date_only',"
                "'90.7184',90.7184,NULL,'kg')"
            )
        if scenario == "query_failure":
            c.execute("ALTER TABLE source_vital_measurement DROP COLUMN numeric_value")
        if scenario == "missing_demographics":
            c.execute(
                "UPDATE source_patient SET sex=NULL,race=NULL,ethnicity=NULL,"
                "patient_regional_location=NULL"
            )
        if scenario == "conflicting_demographics":
            c.execute(
                "INSERT INTO source_patient VALUES ('p','M','Black','Hispanic','South')"
            )
        if scenario == "category_precedence":
            c.execute("UPDATE source_patient SET race='Black',ethnicity='Hispanic'")
        sources = (
            kwargs["candidate_relation"],
            "source_vital_measurement",
            "source_patient",
        )
        before = {
            name: c.execute(f'SELECT * FROM "{name}"').fetchall() for name in sources
        }
        rejected_input = scenario.startswith("output_") or scenario in {
            "blank_record",
            "space_record",
            "reversed_dates",
            "timestamp_start",
            "query_failure",
        }
        if rejected_input:
            with pytest.raises((ValueError, duckdb.Error)):
                build_calendar_covariates(c, **kwargs)
            for name, rows in before.items():
                assert c.execute(f'SELECT * FROM "{name}"').fetchall() == rows
            assert not c.execute(
                "SELECT table_name FROM duckdb_tables() "
                "WHERE temporary AND table_name LIKE '_cov_%'"
            ).fetchall()
            assert not c.execute(
                "SELECT function_name FROM duckdb_functions() "
                "WHERE function_name LIKE '_cov_%'"
            ).fetchall()
            return

        result = build_calendar_covariates(c, **kwargs)
        demographics = ("0", "0", "3")
        if scenario in ("missing_demographics", "conflicting_demographics"):
            demographics = (None, None, None)
        elif scenario == "category_precedence":
            demographics = ("0", "1", "3")
        assert (
            c.execute(f'SELECT sex,race_ethnicity,location FROM "{result}"').fetchone()
            == demographics
        )
        expected = (31.2, "current", "valid")
        if scenario in (
            "unknown_start",
            "unknown_precision",
            "timestamp_precision",
            "capture_unavailable",
        ):
            expected = (None, "none", "unresolved")
        elif scenario == "after_end":
            expected = (None, "none", "missing")
        elif scenario == "metric_components":
            expected = (33.3, "calculated", "valid")
        assert (
            c.execute(
                "SELECT round(bmi::DOUBLE,1),bmi_method,bmi_evidence_state "
                f'FROM "{result}"'
            ).fetchone()
            == expected
        )
        out = tmp_path / "mapping"
        trusted = write_calendar_covariates(
            c, result, out, source_identity={"synthetic": True}
        )
        assert len(read_calendar_covariates(out, expected_manifest_sha256=trusted)) == 1
        for name, rows in before.items():
            assert c.execute(f'SELECT * FROM "{name}"').fetchall() == rows
        if scenario in ("existing_directory", "symlink_directory"):
            destination = out
            if scenario == "symlink_directory":
                destination = tmp_path / "linked"
                destination.symlink_to(out, target_is_directory=True)
            saved = {p.name: p.read_bytes() for p in out.iterdir()}
            with pytest.raises((ValueError, OSError)):
                write_calendar_covariates(
                    c, result, destination, source_identity={"synthetic": True}
                )
            assert {p.name: p.read_bytes() for p in out.iterdir()} == saved
            if destination.is_symlink():
                destination.unlink()  # Retain the checked product, not a fixture link.
        elif scenario in ("version", "missing_column", "null_key", "duplicate_key"):
            manifest = out / "manifest.json"
            record = json.loads(manifest.read_text())
            product = out / "covariates.parquet"
            if scenario == "version":
                record["schema_version"] = 99
            else:
                selection = {
                    "missing_column": "SELECT * EXCLUDE(bmi) FROM ",
                    "null_key": "SELECT * REPLACE(NULL::VARCHAR AS patient_id) FROM ",
                    "duplicate_key": "SELECT * FROM ",
                }[scenario] + f'"{result}"'
                if scenario == "duplicate_key":
                    selection += f' UNION ALL SELECT * FROM "{result}"'
                    record["rows"] = 2
                product.unlink()
                c.execute(f"COPY ({selection}) TO '{product}' (FORMAT PARQUET)")
                record["files"][product.name] = _digest(product)
            manifest.write_text(json.dumps(record) + "\n")
            with pytest.raises(ValueError):
                read_calendar_covariates(
                    out, expected_manifest_sha256=_digest(manifest)
                )

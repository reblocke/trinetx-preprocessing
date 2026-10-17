"""Available encounter/prior BMI and inherited adjustment on caller-owned keys.

Call on a validated read-only canonical source session. No index, BMI cohort,
gas or model-completeness selection is performed here.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any
from uuid import uuid4

import duckdb
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from ..combined_preprocessing.builder import require_safe_output_location
from ..transform.lab_features import legacy_csv_visible_numeric_series
from .compatibility import no_symlinks

POLICY_ID = "available_encounter_or_prior_bmi_v1"
POLICY = {
    "id": POLICY_ID,
    "hierarchy": "valid current; valid prior; observed height/weight calculation",
    "current": "earliest valid date at exact encounter; no later than known end",
    "prior": "latest valid date strictly before each candidate start",
    "ties": "different values on selected calendar day remain unresolved",
    "recorded_bmi": "10 < BMI < 50.1; inherited TriNetX masking exclusion",
    "height_inches": "raw 54 <= inches < 84, legacy cleaning, integer rounding",
    "weight_pounds": "raw 10 <= pounds < 450, legacy cleaning, integer rounding",
    "calculated": "round((pounds*0.453592)/(inches*0.0254)^2,0.1); no 50.1 cap",
    "imputation": "none",
    "numeric_transport": (
        "legacy float16/CSV decimals; float32 source and intermediate storage; "
        "Stata floor(x/unit+0.5)*unit; float32 BMI"
    ),
    "age": "encounter_start_year minus captured birth_year",
    "missing": "complete available search without usable BMI",
    "unresolved": "unavailable capture, unknown start or relevant date/value conflict",
}
CODES = {
    "bmi": ("39156-5",),
    "height": ("8302-2", "8306-3", "8301-4", "3138-5", "8308-9", "8305-5", "3137-7"),
    "weight": ("29463-7", "3141-9", "3142-7", "8335-2"),
}
_PRODUCT_SCHEMA = pa.schema(
    [
        ("patient_id", pa.string()),
        ("encounter_id", pa.string()),
        ("encounter_date", pa.date32()),
        ("encounter_type", pa.string()),
        ("age_at_encounter", pa.int64()),
        ("sex", pa.string()),
        ("location", pa.string()),
        ("race_ethnicity", pa.string()),
        ("bmi", pa.float32()),
        ("bmi_evidence_state", pa.string()),
        ("bmi_method", pa.string()),
        ("reported_bmi", pa.float32()),
        ("reported_date", pa.date32()),
        ("height_date", pa.date32()),
        ("weight_date", pa.date32()),
        ("height_inches", pa.float32()),
        ("weight_pounds", pa.float32()),
        ("bmi_reason", pa.string()),
    ]
)


def _identifier(name: str) -> str:
    if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
        raise ValueError("Expected simple relation identifier")
    return '"' + name + '"'


def _sha(path: str | Path) -> str:
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _literal(value: object) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _check_schema(schema: pa.Schema) -> None:
    if not schema.equals(_PRODUCT_SCHEMA, check_metadata=False):
        raise ValueError("Unsupported calendar covariate columns or types")


def _check_keys(connection: duckdb.DuckDBPyConnection, relation: str) -> None:
    if connection.execute(
        f"SELECT count(*) FROM {relation} WHERE patient_id IS NULL "
        "OR encounter_id IS NULL OR trim(patient_id)='' OR trim(encounter_id)=''"
    ).fetchone()[0]:
        raise ValueError("Invalid original keys")
    if connection.execute(
        f"SELECT count(*) FROM (SELECT patient_id,encounter_id FROM {relation} "
        "GROUP BY 1,2 HAVING count(*)<>1)"
    ).fetchone()[0]:
        raise ValueError("Duplicate candidate keys")


def build_calendar_covariates(
    connection: duckdb.DuckDBPyConnection,
    *,
    candidate_relation: str,
    vital_capture_available: bool,
    vital_relation: str = "source_vital_measurement",
    output_relation: str = "calendar_covariates",
    unit_defaults: dict[str, str] | None = None,
) -> str:
    """Build one temporary covariate row per supplied original encounter key.

    Unit defaults require caller-authenticated source metadata. Unknown units
    are unusable. The input needs patient_id, encounter_id, encounter_start_date,
    encounter_type, year_of_birth; optional encounter_end_date bounds current BMI.
    """
    c = connection
    keys, vitals, output = map(
        _identifier, (candidate_relation, vital_relation, output_relation)
    )
    if output_relation.casefold() in {
        name.casefold()
        for name in (candidate_relation, vital_relation, "source_patient")
    }:
        raise ValueError("Output cannot replace source relations")
    if c.execute(
        "SELECT count(*) FROM (SELECT table_name AS name FROM duckdb_tables() "
        "UNION ALL SELECT view_name AS name FROM duckdb_views()) "
        "WHERE lower(name)=lower(?)",
        [output_relation],
    ).fetchone()[0]:
        raise ValueError("Output relation already exists")
    if type(vital_capture_available) is not bool:
        raise ValueError("Explicit captured vital availability required")
    columns = {
        name: kind for name, kind, *_ in c.execute(f"DESCRIBE {keys}").fetchall()
    }
    if any(
        columns.get(name) != kind
        for name, kind in {
            "patient_id": "VARCHAR",
            "encounter_id": "VARCHAR",
            "encounter_start_date": "DATE",
            "encounter_type": "VARCHAR",
        }.items()
    ) or columns.get("year_of_birth") not in {
        "TINYINT",
        "SMALLINT",
        "INTEGER",
        "BIGINT",
    }:
        raise ValueError(
            "Candidate keys require calendar dates and typed source fields"
        )
    if "encounter_end_date" in columns and columns["encounter_end_date"] != "DATE":
        raise ValueError("Candidate encounter end must be a calendar date")
    _check_keys(c, keys)
    if (
        "encounter_end_date" in columns
        and c.execute(
            f"SELECT count(*) FROM {keys} WHERE encounter_end_date<encounter_start_date"
        ).fetchone()[0]
    ):
        raise ValueError("Candidate encounter end precedes start")
    end = "k.encounter_end_date" if "encounter_end_date" in columns else "NULL::DATE"
    prefix = "_cov_" + uuid4().hex
    temps = []

    def legacy_half_csv(values: pa.ChunkedArray) -> pa.Array:
        series = pd.Series(values.to_numpy(zero_copy_only=False), dtype="float16")
        numeric = legacy_csv_visible_numeric_series(series).to_numpy(
            dtype=np.float64, na_value=np.nan
        )
        return pa.array(numeric, from_pandas=True)

    function = prefix + "_half_csv"
    c.create_function(
        function,
        legacy_half_csv,
        ["DOUBLE"],
        "DOUBLE",
        type="arrow",
        null_handling="special",
    )

    def stage(suffix: str, sql: str) -> str:
        name = _identifier(prefix + suffix)
        c.execute(f"CREATE TEMP TABLE {name} AS {sql}")
        temps.append(name)
        return name

    try:
        people = stage(
            "people",
            "SELECT p.patient_id,"
            + ",".join(
                f"CASE WHEN count(DISTINCT coalesce(p.{field},'__MISSING__'))=1 "
                f"THEN min(p.{field}) END AS {field}"
                for field in ("sex", "race", "ethnicity", "patient_regional_location")
            )
            + f" FROM source_patient p SEMI JOIN {keys} k USING(patient_id) GROUP BY 1",
        )
        expressions = []
        for kind, codes in CODES.items():
            expressions.append(
                "WHEN code IN (" + ",".join(map(_literal, codes)) + f") THEN '{kind}'"
            )
        unit = (
            "lower(replace(replace(trim(coalesce(units_of_measure,'')),"
            "' ',''),'²','2'))"
        )
        defaults = unit_defaults or {}
        for kind, value in defaults.items():
            if kind not in CODES or not isinstance(value, str):
                raise ValueError("Unreviewed vital unit default")
        raw = stage(
            "raw",
            "SELECT v.*,CASE " + " ".join(expressions) + " END AS kind,"
            f"{unit} AS unit FROM {vitals} v SEMI JOIN {keys} k USING(patient_id) "
            "WHERE code_system='LOINC' AND code IN ("
            + ",".join(_literal(code) for codes in CODES.values() for code in codes)
            + ")",
        )
        if c.execute(
            f"SELECT count(*) FROM (SELECT source_record_id FROM {raw} "
            "GROUP BY 1 HAVING count(*)>1 OR source_record_id IS NULL "
            "OR trim(source_record_id)='')"
        ).fetchone()[0]:
            raise ValueError("Duplicate or missing captured vital source-record keys")
        default_sql = (
            "CASE kind "
            + " ".join(
                f"WHEN '{k}' THEN {_literal(v.lower().replace(' ', ''))}"
                for k, v in defaults.items()
            )
            + " ELSE '' END"
            if defaults
            else "''"
        )
        converted = stage(
            "converted",
            "SELECT patient_id,encounter_id,kind,CASE WHEN "
            "timestamp_precision='date_only' "
            "THEN cast(event_datetime AS DATE) END AS day,CASE "
            "WHEN regexp_matches(coalesce(value,'')||' "
            "'||coalesce(text_value,''),'[<>≤≥]') "
            "OR NOT isfinite(numeric_value) THEN NULL "
            "WHEN kind='bmi' AND u IN "
            "('kg/m2','kg/m^2','kg/m**2','kg/m²') THEN numeric_value "
            "WHEN kind='height' AND u IN "
            "('in','[in_i]','[in_us]','inch','inches') THEN "
            "numeric_value "
            "WHEN kind='height' AND u IN "
            "('cm','centimeter','centimeters') THEN "
            "numeric_value/2.54 "
            "WHEN kind='height' AND u='m' THEN numeric_value/0.0254 "
            "WHEN kind='weight' AND u IN "
            "('lb','lbs','[lb_av]','pound','pounds') THEN "
            "numeric_value "
            "WHEN kind='weight' AND u IN "
            "('kg','kilogram','kilograms') THEN "
            "numeric_value/0.453592 "
            "WHEN kind='weight' AND u='g' THEN numeric_value/453.592 END AS converted "
            f"FROM (SELECT *,coalesce(nullif(unit,''),{default_sql}) AS u FROM {raw})",
        )
        screened = stage(
            "screened",
            "SELECT *,CASE "
            "WHEN kind='bmi' AND converted>=10 AND converted<100 THEN converted "
            "WHEN kind='height' AND converted>=54 AND converted<84 THEN converted "
            "WHEN kind='weight' AND converted>=10 AND converted<450 THEN converted "
            f"END AS screened_value FROM {converted}",
        )
        normalized = stage(
            "normalized",
            f"SELECT *,{function}(screened_value) AS legacy_numeric FROM {screened}",
        )
        valid = stage(
            "valid",
            "SELECT patient_id,encounter_id,kind,day,cast(CASE "
            "WHEN kind='bmi' AND legacy_numeric>10 AND "
            "legacy_numeric<50.1 THEN legacy_numeric "
            "WHEN kind='height' AND legacy_numeric>50 AND "
            "legacy_numeric<90 THEN legacy_numeric "
            "WHEN kind='weight' AND legacy_numeric>50 AND legacy_numeric<500 "
            "THEN legacy_numeric END AS FLOAT) AS usable "
            f"FROM {normalized}",
        )
        for table in (raw, converted, screened, normalized):
            c.execute(f"DROP TABLE {table}")
            temps.remove(table)
        selected = []
        for kind in CODES:
            daily = stage(
                kind + "daily",
                "SELECT patient_id,day,min(usable) AS lo,max(usable) AS hi "
                f"FROM {valid} WHERE kind='{kind}' AND usable IS NOT NULL "
                "AND day IS NOT NULL GROUP BY 1,2",
            )
            prior = stage(
                kind + "prior",
                f"SELECT k.patient_id,k.encounter_id,v.day,v.lo,v.hi "
                f"FROM {keys} k ASOF LEFT JOIN {daily} v ON k.patient_id=v.patient_id "
                "AND k.encounter_start_date>v.day",
            )
            current = stage(
                kind + "current",
                "SELECT patient_id,encounter_id,day,lo,hi FROM ("
                "SELECT k.patient_id,k.encounter_id,v.day,min(v.usable) "
                "AS lo,max(v.usable) AS hi,"
                "row_number() OVER(PARTITION BY "
                "k.patient_id,k.encounter_id ORDER BY v.day) AS rn "
                f"FROM {keys} k JOIN {valid} v USING(patient_id,encounter_id) "
                f"WHERE v.kind='{kind}' AND v.usable IS NOT NULL AND "
                f"v.day>=k.encounter_start_date "
                f"AND ({end} IS NULL OR v.day<={end}) GROUP BY 1,2,3) WHERE rn=1",
            )
            undated = stage(
                kind + "undated",
                f"SELECT patient_id,count(*) AS n FROM {valid} "
                f"WHERE kind='{kind}' AND usable IS NOT NULL AND day IS "
                "NULL GROUP BY 1",
            )
            choice = stage(
                kind + "choice",
                "SELECT k.patient_id,k.encounter_id,"
                "CASE WHEN cur.day IS NOT NULL AND cur.lo=cur.hi THEN cur.lo "
                "WHEN cur.day IS NULL AND coalesce(u.n,0)=0 AND "
                "prev.lo=prev.hi THEN prev.lo END AS val,"
                "coalesce(cur.day,prev.day) AS day,"
                "CASE WHEN cur.day IS NOT NULL THEN 'current' ELSE "
                "'prior' END AS method,"
                "CASE WHEN cur.day IS NOT NULL THEN cur.lo<>cur.hi "
                "ELSE coalesce(u.n,0)>0 OR "
                "coalesce(prev.lo<>prev.hi,false) END AS uncertain "
                f"FROM {keys} k LEFT JOIN {current} cur USING(patient_id,encounter_id) "
                f"LEFT JOIN {prior} prev USING(patient_id,encounter_id) "
                f"LEFT JOIN {undated} u USING(patient_id)",
            )
            selected.append(choice)
            for table in (daily, prior, current, undated):
                c.execute(f"DROP TABLE {table}")
                temps.remove(table)
        bm, ht, wt = selected
        c.execute(
            f"CREATE TEMP TABLE {output} AS WITH chosen AS (SELECT k.*,"
            "b.val AS reported_bmi,b.method AS reported_method,b.day AS reported_date,"
            "cast(floor(cast(b.val AS DOUBLE)/0.1+0.5)*0.1 AS FLOAT) AS working_bmi,"
            "h.val AS height_inches,w.val AS weight_pounds,h.day AS "
            "height_date,w.day AS weight_date,"
            "b.uncertain AS bmi_uncertain,h.uncertain OR w.uncertain "
            "AS calculation_uncertain,"
            "cast(floor(((floor(cast(w.val AS DOUBLE)+0.5)*0.453592)/"
            "pow(floor(cast(h.val AS DOUBLE)+0.5)*0.0254,2))/0.1+0.5)*0.1 "
            "AS FLOAT) AS calculated_bmi,"
            "p.sex AS raw_sex,p.race AS raw_race,p.ethnicity AS raw_ethnicity,"
            "p.patient_regional_location AS raw_location "
            f"FROM {keys} k LEFT JOIN {bm} b USING(patient_id,encounter_id) "
            f"LEFT JOIN {ht} h USING(patient_id,encounter_id) LEFT "
            f"JOIN {wt} w USING(patient_id,encounter_id) "
            f"LEFT JOIN {people} p USING(patient_id)), typed AS (SELECT *,"
            "CASE WHEN raw_sex='F' THEN '0' WHEN raw_sex='M' THEN '1' "
            "WHEN raw_sex='Unknown' THEN '2' END AS sex,"
            "CASE WHEN raw_race='White' THEN '0' WHEN raw_race IN "
            "('Black','Black or African American') THEN '1' "
            "WHEN raw_race='Unknown' THEN '2' WHEN raw_race='Asian' THEN '3' "
            "WHEN raw_race='American Indian or Alaska Native' THEN '4' "
            "WHEN raw_race='Native Hawaiian or Other Pacific "
            "Islander' THEN '5' END AS race,"
            "CASE WHEN raw_ethnicity IN ('Not Hispanic or "
            "Latino','Non-Hispanic') THEN '0' "
            "WHEN raw_ethnicity IN ('Hispanic or Latino','Hispanic') "
            "THEN '1' WHEN raw_ethnicity='Unknown' THEN '2' END AS "
            "ethnicity,"
            "CASE raw_location WHEN 'South' THEN '0' WHEN 'Northeast' "
            "THEN '1' WHEN 'Midwest' THEN '2' WHEN 'West' THEN '3' "
            "END AS location,"
            f"CASE WHEN NOT {str(vital_capture_available).lower()} OR "
            f"encounter_start_date IS NULL OR bmi_uncertain "
            "OR (reported_bmi IS NULL AND calculation_uncertain) THEN 'unresolved' "
            "WHEN reported_bmi IS NOT NULL OR calculated_bmi IS NOT "
            "NULL THEN 'valid' ELSE 'missing' END AS "
            "bmi_evidence_state "
            "FROM chosen) SELECT "
            "patient_id,encounter_id,encounter_start_date AS "
            "encounter_date,encounter_type,"
            "year(encounter_start_date)-year_of_birth AS age_at_encounter,sex,location,"
            "CASE WHEN race IN ('1','3','4','5') THEN race WHEN race "
            "IS NULL OR ethnicity IS NULL THEN NULL "
            "WHEN ethnicity='1' THEN '2' WHEN race='2' THEN '6' ELSE "
            "'0' END AS race_ethnicity,"
            "CASE WHEN bmi_evidence_state='valid' THEN "
            "cast(floor(cast(coalesce(working_bmi,calculated_bmi) AS DOUBLE)"
            "/0.1+0.5)*0.1 AS FLOAT) END AS "
            "bmi,"
            "bmi_evidence_state,CASE WHEN bmi_evidence_state<>'valid' THEN 'none' "
            "WHEN reported_bmi IS NOT NULL THEN reported_method ELSE "
            "'calculated' END AS bmi_method,"
            "reported_bmi,reported_date,height_date,weight_date,"
            "height_inches,weight_pounds,CASE "
            f"WHEN NOT {str(vital_capture_available).lower()} THEN "
            f"'capture_unavailable' "
            "WHEN encounter_start_date IS NULL THEN 'unknown_encounter_start' "
            "WHEN bmi_uncertain THEN 'reported_time_or_value_uncertain' "
            "WHEN reported_bmi IS NULL AND calculation_uncertain "
            "THEN 'component_time_or_value_uncertain' "
            "WHEN bmi_evidence_state='valid' THEN 'observed_or_calculated' "
            "ELSE 'no_usable_BMI_after_search' END AS bmi_reason FROM typed"
        )
        if (
            c.execute(f"SELECT count(*) FROM {output}").fetchone()[0]
            != c.execute(f"SELECT count(*) FROM {keys}").fetchone()[0]
        ):
            raise ValueError("Covariate rows do not reconcile to candidate keys")
        return output_relation
    finally:
        for table in reversed(temps):
            c.execute(f"DROP TABLE {table}")
        c.remove_function(function)


def write_calendar_covariates(
    connection: duckdb.DuckDBPyConnection,
    relation: str,
    output_dir: str | Path,
    *,
    source_identity: dict[str, Any],
) -> str:
    """Claim a fresh external directory and publish a hash-bound mapping."""
    output = no_symlinks(output_dir)
    require_safe_output_location(output, artifact_label="calendar covariate mapping")
    table = _identifier(relation)
    _check_schema(
        connection.execute(f"SELECT * FROM {table} LIMIT 0").fetch_arrow_table().schema
    )
    _check_keys(connection, table)
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    product = output / "covariates.parquet"
    connection.execute(
        f"COPY (SELECT * FROM {table} ORDER BY patient_id,encounter_id) "
        f"TO {_literal(product)} (FORMAT PARQUET, COMPRESSION ZSTD)"
    )
    product.chmod(0o600)
    manifest = {
        "schema_version": 1,
        "product": "calendar_encounter_covariates_v1",
        "policy": POLICY,
        "source_identity": source_identity,
        "producer_source_sha256": _sha(__file__),
        "rows": connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0],
        "files": {product.name: _sha(product)},
        "clinical_results_qualified": False,
    }
    path = output / "manifest.json"
    path.write_text(json.dumps(manifest, indent=2) + "\n")
    path.chmod(0o600)
    return _sha(path)


def read_calendar_covariates(
    output_dir: str | Path, *, expected_manifest_sha256: str
) -> pd.DataFrame:
    """Read an authenticated v1 product; this does not accept a study population."""
    root = no_symlinks(output_dir)
    path = root / "manifest.json"
    if path.is_symlink() or _sha(path) != expected_manifest_sha256:
        raise ValueError("Mapping manifest hash mismatch")
    manifest = json.loads(path.read_text())
    if (
        type(manifest.get("schema_version")) is not int
        or manifest["schema_version"] != 1
        or manifest.get("policy") != POLICY
        or manifest.get("product") != "calendar_encounter_covariates_v1"
    ):
        raise ValueError("Unreviewed calendar covariate policy")
    if set(manifest["files"]) != {"covariates.parquet"}:
        raise ValueError("Unexpected mapping products")
    product = root / "covariates.parquet"
    if product.is_symlink() or _sha(product) != manifest["files"][product.name]:
        raise ValueError("Mapping product hash mismatch")
    _check_schema(pq.read_schema(product))
    data = pd.read_parquet(product)
    if (
        len(data) != manifest["rows"]
        or data.duplicated(["patient_id", "encounter_id"]).any()
        or any(
            data[name].isna().any() or data[name].str.strip().eq("").any()
            for name in ("patient_id", "encounter_id")
        )
    ):
        raise ValueError("Mapping key/row reconciliation failure")
    return data

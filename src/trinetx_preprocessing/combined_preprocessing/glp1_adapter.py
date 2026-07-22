"""Adapter exposing combined source tables to the GLP-1 derivation code."""

from __future__ import annotations

from pathlib import Path

import duckdb

from ..glp1_eligibility.config import GLP1Config
from ..glp1_eligibility.sql_helpers import inclusive_lookback_start_sql

_GAS_ELEMENT_IDS = (
    "source.arterial_pco2",
    "source.venous_pco2",
    "source.unspecified_blood_pco2",
)

_SOURCE_HASH_COLUMNS = {
    "source_lab_measurement": (
        "patient_id",
        "encounter_id",
        "date",
        "code_system_raw",
        "code_raw",
        "lab_result_num_val",
        "lab_result_text_val",
        "units_of_measure_raw",
        "specimen",
        "specimen_id",
        "panel_id",
        "derived_by_TriNetX",
        "source_id",
    ),
    "source_encounter": (
        "encounter_id",
        "patient_id",
        "start_date",
        "end_date",
        "type",
        "start_date_derived_by_TriNetX",
        "end_date_derived_by_TriNetX",
        "derived_by_TriNetX",
        "source_id",
    ),
    "source_patient": (
        "patient_id",
        "sex",
        "race",
        "ethnicity",
        "year_of_birth",
        "month_year_death",
        "patient_regional_location",
        "source_id",
    ),
    "source_vital_measurement": (
        "patient_id",
        "encounter_id",
        "date",
        "code_system_raw",
        "code_raw",
        "value",
        "text_value",
        "units_of_measure_raw",
        "derived_by_TriNetX",
        "source_id",
    ),
    "source_diagnosis": (
        "patient_id",
        "encounter_id",
        "date",
        "code_system_raw",
        "code_raw",
        "principal_diagnosis_indicator",
        "admitting_diagnosis",
        "reason_for_visit",
        "derived_by_TriNetX",
        "source_id",
    ),
    "source_procedure": (
        "patient_id",
        "encounter_id",
        "date",
        "code_system_raw",
        "code_raw",
        "principal_procedure_indicator",
        "derived_by_TriNetX",
        "source_id",
    ),
    "source_medication": (
        "patient_id",
        "encounter_id",
        "unique_id",
        "code_system_raw",
        "code_raw",
        "medication_text",
        "start_date",
        "end_date",
        "order_status",
        "status",
        "route",
        "brand",
        "strength",
        "derived_by_TriNetX",
        "source_id",
    ),
}


def materialize_glp1_sources_from_preprocessed(
    connection: duckdb.DuckDBPyConnection,
    database_path: Path,
    *,
    config: GLP1Config,
) -> dict[str, int]:
    """Materialize the current GLP-1 source contract without raw CSV scans."""

    _attach_preprocessed(connection, database_path)
    try:
        _create_lab_source(connection)
        _create_gas_candidate_ids(connection)
        _create_candidate_membership(connection)
        _create_encounter_source(connection)
        _create_patient_source(connection)
        _create_patient_concept_source(connection, "source_vital_measurement")
        _create_patient_concept_source(connection, "source_diagnosis")
        _create_patient_concept_source(connection, "source_procedure")
        _create_patient_concept_source(connection, "source_medication")
        _create_source_cohort_flow_base(connection, config)
        return {
            table: int(
                connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            )
            for table in _SOURCE_HASH_COLUMNS
        }
    finally:
        connection.execute("DETACH preprocessed")


def materialize_glp1_observability_from_preprocessed(
    connection: duckdb.DuckDBPyConnection,
    database_path: Path,
) -> None:
    """Build current index-level raw-observability tables from compact aggregates."""

    _attach_preprocessed(connection, database_path)
    try:
        specifications = (
            ("diagnosis", "diagnosis", 730),
            ("labs", "labs", 365),
            ("vitals", "vitals", None),
            ("procedure", "procedure", None),
            ("medication", "medications", 730),
        )
        for output_domain, stored_domain, lookback_days in specifications:
            _create_observability_table(
                connection,
                output_domain=output_domain,
                stored_domain=stored_domain,
                lookback_days=lookback_days,
            )
    finally:
        connection.execute("DETACH preprocessed")


def _create_lab_source(connection: duckdb.DuckDBPyConnection) -> None:
    connection.execute(
        f"""
        CREATE OR REPLACE TABLE source_lab_measurement AS
        SELECT
            cast(patient_id AS VARCHAR) AS patient_id,
            cast(encounter_id AS VARCHAR) AS encounter_id,
            date,
            code_system_raw AS code_system,
            code_raw AS code,
            lab_result_num_val,
            lab_result_text_val,
            units_of_measure_raw AS units_of_measure,
            specimen,
            specimen_id,
            panel_id,
            derived_by_TriNetX,
            source_id,
            event_datetime,
            source_file,
            {_source_hash_sql("source_lab_measurement")} AS source_record_hash
        FROM preprocessed.source_lab_measurement
        """
    )


def _create_gas_candidate_ids(connection: duckdb.DuckDBPyConnection) -> None:
    element_ids = ", ".join(_sql_string(value) for value in _GAS_ELEMENT_IDS)
    connection.execute(
        f"""
        CREATE OR REPLACE TABLE gas_candidate_id AS
        SELECT DISTINCT
            cast(source.patient_id AS VARCHAR) AS patient_id,
            cast(source.encounter_id AS VARCHAR) AS encounter_id
        FROM preprocessed.source_lab_measurement AS source
        JOIN preprocessed.element_membership AS membership
          USING (source_record_id)
        WHERE membership.element_id IN ({element_ids})
          AND membership.include
        """
    )


def _create_candidate_membership(connection: duckdb.DuckDBPyConnection) -> None:
    connection.execute(
        """
        CREATE OR REPLACE TEMP TABLE gas_candidate_patient AS
        SELECT DISTINCT patient_id
        FROM gas_candidate_id
        WHERE patient_id IS NOT NULL
        """
    )
    connection.execute(
        """
        CREATE OR REPLACE TEMP TABLE gas_candidate_encounter AS
        SELECT DISTINCT encounter_id
        FROM gas_candidate_id
        WHERE encounter_id IS NOT NULL
        """
    )


def _create_encounter_source(connection: duckdb.DuckDBPyConnection) -> None:
    connection.execute(
        f"""
        CREATE OR REPLACE TABLE source_encounter AS
        SELECT
            cast(encounter_id AS VARCHAR) AS encounter_id,
            cast(patient_id AS VARCHAR) AS patient_id,
            cast(start_date AS VARCHAR) AS start_date,
            cast(end_date AS VARCHAR) AS end_date,
            cast(type AS VARCHAR) AS type,
            cast(start_date_derived_by_TriNetX AS VARCHAR)
                AS start_date_derived_by_TriNetX,
            cast(end_date_derived_by_TriNetX AS VARCHAR)
                AS end_date_derived_by_TriNetX,
            cast(derived_by_TriNetX AS VARCHAR) AS derived_by_TriNetX,
            cast(source_id AS VARCHAR) AS source_id,
            start_datetime AS encounter_start,
            end_datetime AS encounter_end,
            end_timestamp_precision AS encounter_end_precision,
            source_file,
            {_source_hash_sql("source_encounter")} AS source_record_hash
        FROM preprocessed.source_encounter
        WHERE cast(patient_id AS VARCHAR) IN (
                SELECT patient_id FROM gas_candidate_patient
              )
           OR cast(encounter_id AS VARCHAR) IN (
                SELECT encounter_id FROM gas_candidate_encounter
              )
        """
    )


def _create_patient_source(connection: duckdb.DuckDBPyConnection) -> None:
    connection.execute(
        f"""
        CREATE OR REPLACE TABLE source_patient AS
        SELECT
            cast(patient_id AS VARCHAR) AS patient_id,
            sex,
            race,
            ethnicity,
            year_of_birth,
            month_year_death,
            patient_regional_location,
            source_id,
            source_file,
            {_source_hash_sql("source_patient")} AS source_record_hash
        FROM preprocessed.source_patient
        WHERE cast(patient_id AS VARCHAR) IN (
            SELECT patient_id FROM gas_candidate_patient
        )
        """
    )


def _create_patient_concept_source(
    connection: duckdb.DuckDBPyConnection,
    table_name: str,
) -> None:
    source_columns = {
        "source_vital_measurement": (
            "cast(patient_id AS VARCHAR) AS patient_id",
            "cast(encounter_id AS VARCHAR) AS encounter_id",
            "date",
            "code_system_raw AS code_system",
            "code_raw AS code",
            "value",
            "text_value",
            "units_of_measure_raw AS units_of_measure",
            "derived_by_TriNetX",
            "source_id",
            "event_datetime",
        ),
        "source_diagnosis": (
            "cast(patient_id AS VARCHAR) AS patient_id",
            "cast(encounter_id AS VARCHAR) AS encounter_id",
            "date",
            "code_system_raw AS code_system",
            "code_raw AS code",
            "principal_diagnosis_indicator",
            "admitting_diagnosis",
            "reason_for_visit",
            "derived_by_TriNetX",
            "source_id",
            "event_datetime",
        ),
        "source_procedure": (
            "cast(patient_id AS VARCHAR) AS patient_id",
            "cast(encounter_id AS VARCHAR) AS encounter_id",
            "date",
            "code_system_raw AS code_system",
            "code_raw AS code",
            "principal_procedure_indicator",
            "derived_by_TriNetX",
            "source_id",
            "event_datetime",
        ),
        "source_medication": (
            "cast(patient_id AS VARCHAR) AS patient_id",
            "cast(encounter_id AS VARCHAR) AS encounter_id",
            "unique_id",
            "code_system_raw AS code_system",
            "code_raw AS code",
            "medication_text",
            "start_date",
            "end_date",
            "order_status",
            "status",
            "route",
            "brand",
            "strength",
            "derived_by_TriNetX",
            "source_id",
            "event_datetime",
            "end_datetime",
        ),
    }[table_name]
    connection.execute(
        f"""
        CREATE OR REPLACE TABLE {table_name} AS
        SELECT
            {", ".join(source_columns)},
            source_file,
            {_source_hash_sql(table_name)} AS source_record_hash
        FROM preprocessed.{table_name}
        WHERE cast(patient_id AS VARCHAR) IN (
            SELECT patient_id FROM gas_candidate_patient
        )
        """
    )


def _create_source_cohort_flow_base(
    connection: duckdb.DuckDBPyConnection,
    config: GLP1Config,
) -> None:
    encounter_types = ", ".join(
        _sql_string(value) for value in config.study.index_encounter_types
    )
    start_condition = (
        "TRUE"
        if config.study.study_start is None
        else "encounter_start::DATE >= DATE "
        + _sql_string(config.study.study_start.isoformat())
    )
    end_condition = (
        "TRUE"
        if config.study.study_end is None
        else "encounter_start::DATE <= DATE "
        + _sql_string(config.study.study_end.isoformat())
    )
    start_condition = start_condition.replace(
        "encounter_start",
        "encounter.start_datetime",
    )
    end_condition = end_condition.replace(
        "encounter_start",
        "encounter.start_datetime",
    )
    connection.execute(
        f"""
        CREATE OR REPLACE TABLE source_cohort_flow_base AS
        WITH patient AS (
            SELECT patient_id, min(try_cast(year_of_birth AS INTEGER)) AS year_of_birth
            FROM preprocessed.source_patient
            WHERE patient_id IS NOT NULL
            GROUP BY patient_id
        ), adult_candidate AS (
            SELECT encounter.encounter_id, encounter.patient_id
            FROM preprocessed.source_encounter_flow AS encounter
            JOIN patient USING (patient_id)
            WHERE encounter.encounter_id IS NOT NULL
              AND encounter.start_datetime IS NOT NULL
              AND year(encounter.start_datetime) - patient.year_of_birth
                    >= {config.study.adult_age_min}
              AND upper(trim(cast(encounter.type AS VARCHAR))) IN ({encounter_types})
              AND {start_condition}
              AND {end_condition}
        )
        SELECT 1 AS stage_order, count(*)::BIGINT AS row_count,
               count(*)::BIGINT AS unique_patient_count
        FROM patient
        UNION ALL
        SELECT 2, count(DISTINCT (patient_id, encounter_id))::BIGINT,
               count(DISTINCT patient_id)::BIGINT
        FROM adult_candidate
        """
    )


def _create_observability_table(
    connection: duckdb.DuckDBPyConnection,
    *,
    output_domain: str,
    stored_domain: str,
    lookback_days: int | None,
) -> None:
    if lookback_days is None:
        event_count = "NULL::BIGINT AS event_count"
    else:
        lower_bound = inclusive_lookback_start_sql(
            "event.event_datetime",
            "event.timestamp_precision",
            "analysis.index_date",
            lookback_days,
        )
        event_count = (
            "sum(event.event_count) FILTER (WHERE "
            "event.event_datetime <= analysis.index_date AND "
            f"{lower_bound})::BIGINT AS event_count"
        )
    connection.execute(
        f"""
        CREATE OR REPLACE TABLE raw_{output_domain}_observability AS
        SELECT
            analysis.index_event_id,
            min(event.event_datetime) FILTER (
                WHERE event.event_datetime <= analysis.index_date
            ) AS first_observed_event_date,
            {event_count}
        FROM analysis_glp1_eligibility AS analysis
        JOIN preprocessed.source_observability_event AS event
          ON analysis.patient_id = event.patient_id
         AND event.logical_domain = {_sql_string(stored_domain)}
        GROUP BY analysis.index_event_id
        """
    )


def _source_hash_sql(table_name: str) -> str:
    values = ", ".join(
        f"coalesce(cast({column} AS VARCHAR), '')"
        for column in _SOURCE_HASH_COLUMNS[table_name]
    )
    return f"sha256(concat_ws(chr(31), source_file, {values}))"


def _attach_preprocessed(
    connection: duckdb.DuckDBPyConnection,
    database_path: Path,
) -> None:
    path = Path(database_path).resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    connection.execute(f"ATTACH {_sql_string(str(path))} AS preprocessed (READ_ONLY)")


def _sql_string(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"

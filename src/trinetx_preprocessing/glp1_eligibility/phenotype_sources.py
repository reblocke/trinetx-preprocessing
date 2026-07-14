"""Temporal component evidence summaries for GLP-1 eligibility phenotypes."""

from __future__ import annotations

import duckdb

from .config import GLP1Config

DIAGNOSIS_COMPONENTS = (
    "type_2_diabetes",
    "prediabetes",
    "prior_mi",
    "ischemic_stroke",
    "pad",
    "symptomatic_pad",
    "ckd_any",
    "ckd_stage_3a_plus",
    "eskd",
    "obstructive_sleep_apnea",
    "mash",
    "masld",
    "liver_fibrosis",
    "cirrhosis",
    "heart_failure",
    "hfpef",
    "hypertension",
    "ohs",
    "pcos",
    "knee_osteoarthritis",
    "alcohol_use_disorder",
    "iih",
    "binge_eating",
    "metabolic_syndrome",
    "dyslipidemia",
    "copd",
    "emphysema",
    "asthma",
    "neuromuscular_disease",
    "chest_wall_disease",
    "pneumonia_lri",
    "cardiac_arrest",
    "pregnancy",
)

PROCEDURE_COMPONENTS = (
    "echocardiography",
    "polysomnography",
    "home_sleep_apnea_test",
    "pap_titration",
    "liver_biopsy",
    "transient_elastography",
    "invasive_ventilation",
    "dialysis",
    "bariatric_surgery",
    "lower_extremity_revascularization",
)


def build_component_source_summaries(
    connection: duckdb.DuckDBPyConnection,
    config: GLP1Config,
) -> None:
    """Build index-keyed source evidence and aggregate component summaries."""

    _build_diagnosis_evidence(connection)
    _build_procedure_evidence(connection)
    _build_normalized_component_labs(connection)
    _build_lab_summary(connection, config)
    _build_blood_pressure_summary(connection)
    _build_medication_evidence(connection, config)


def _build_diagnosis_evidence(connection: duckdb.DuckDBPyConnection) -> None:
    connection.execute(
        f"""
        CREATE OR REPLACE TABLE diagnosis_component_evidence AS
        SELECT
            analysis.index_event_id,
            analysis.index_date,
            concept.concept_set_id,
            diagnosis.* EXCLUDE (event_datetime),
            diagnosis.event_datetime,
            datediff('day', diagnosis.event_datetime, analysis.index_date)
                AS days_before_index
        FROM analysis_glp1_eligibility AS analysis
        JOIN source_diagnosis AS diagnosis
          ON diagnosis.patient_id = analysis.patient_id
         AND diagnosis.event_datetime <= analysis.index_date
        JOIN concept_set AS concept
          ON concept.domain = 'diagnosis'
         AND concept.include
         AND {_code_system_sql('diagnosis.code_system')} = concept.code_system
         AND {_concept_match_sql('diagnosis.code')}
        """
    )
    expressions = ",\n            ".join(
        f"bool_or(concept_set_id = {_sql_string(component)}) AS {component}"
        for component in DIAGNOSIS_COMPONENTS
    )
    connection.execute(
        f"""
        CREATE OR REPLACE TABLE diagnosis_component_summary AS
        SELECT index_event_id,
            {expressions}
        FROM diagnosis_component_evidence
        GROUP BY index_event_id
        """
    )


def _build_procedure_evidence(connection: duckdb.DuckDBPyConnection) -> None:
    connection.execute(
        f"""
        CREATE OR REPLACE TABLE procedure_component_evidence AS
        SELECT
            analysis.index_event_id,
            analysis.index_date,
            concept.concept_set_id,
            procedure.* EXCLUDE (event_datetime),
            procedure.event_datetime,
            datediff('day', procedure.event_datetime, analysis.index_date)
                AS days_before_index
        FROM analysis_glp1_eligibility AS analysis
        JOIN source_procedure AS procedure
          ON procedure.patient_id = analysis.patient_id
         AND procedure.event_datetime <= analysis.index_date
        JOIN concept_set AS concept
          ON concept.domain = 'procedure'
         AND concept.include
         AND {_code_system_sql('procedure.code_system')} = concept.code_system
         AND {_concept_match_sql('procedure.code')}
        """
    )
    expressions = ",\n            ".join(
        f"bool_or(concept_set_id = {_sql_string(component)}) AS {component}"
        for component in PROCEDURE_COMPONENTS
    )
    connection.execute(
        f"""
        CREATE OR REPLACE TABLE procedure_component_summary AS
        SELECT index_event_id,
            {expressions}
        FROM procedure_component_evidence
        GROUP BY index_event_id
        """
    )


def _build_normalized_component_labs(
    connection: duckdb.DuckDBPyConnection,
) -> None:
    connection.execute(
        f"""
        CREATE OR REPLACE TABLE normalized_component_lab AS
        WITH matched AS (
            SELECT
                lab.*,
                concept.concept_set_id,
                try_cast(lab.lab_result_num_val AS DOUBLE) AS raw_numeric_value,
                lower(trim(coalesce(lab.units_of_measure, ''))) AS unit_key
            FROM source_lab_measurement AS lab
            JOIN concept_set AS concept
              ON concept.domain = 'lab'
             AND concept.include
             AND concept.concept_set_id IN (
                 'hba1c', 'egfr', 'uacr', 'ahi', 'lvef',
                 'bnp', 'nt_probnp', 'fasting_glucose', 'random_glucose',
                 'ast', 'alt', 'platelets', 'albumin', 'inr', 'bilirubin'
             )
             AND {_code_system_sql('lab.code_system')} = concept.code_system
             AND {_concept_match_sql('lab.code')}
        )
        SELECT
            *,
            CASE
                WHEN concept_set_id = 'hba1c' AND unit_key IN ('%', 'percent')
                THEN raw_numeric_value
                WHEN concept_set_id = 'egfr'
                     AND regexp_matches(unit_key, 'ml/min|ml/minute')
                THEN raw_numeric_value
                WHEN concept_set_id = 'uacr'
                     AND unit_key IN ('mg/g', 'mg/gm', 'mcg/mg', 'ug/mg')
                THEN raw_numeric_value
                WHEN concept_set_id = 'ahi'
                     AND unit_key IN ('events/hour', 'events/hr', '/h', '1/h')
                THEN raw_numeric_value
                WHEN concept_set_id = 'lvef' AND unit_key IN ('%', 'percent')
                THEN raw_numeric_value
                WHEN concept_set_id IN ('bnp', 'nt_probnp')
                     AND unit_key IN ('pg/ml', 'pg/milliliter')
                THEN raw_numeric_value
                WHEN concept_set_id IN ('fasting_glucose', 'random_glucose')
                     AND unit_key IN ('mg/dl', 'mg/dl.')
                THEN raw_numeric_value
                WHEN concept_set_id IN ('ast', 'alt')
                     AND unit_key IN ('u/l', 'iu/l')
                THEN raw_numeric_value
                WHEN concept_set_id = 'platelets'
                     AND unit_key IN ('10^9/l', 'k/ul', '10*3/ul')
                THEN raw_numeric_value
                WHEN concept_set_id = 'albumin' AND unit_key = 'g/dl'
                THEN raw_numeric_value
                WHEN concept_set_id = 'inr' AND unit_key IN ('', '1', 'ratio')
                THEN raw_numeric_value
                WHEN concept_set_id = 'bilirubin' AND unit_key = 'mg/dl'
                THEN raw_numeric_value
                ELSE NULL
            END AS normalized_numeric_value,
            CASE
                WHEN concept_set_id = 'hba1c' THEN '%'
                WHEN concept_set_id = 'egfr' THEN 'mL/min/1.73m2'
                WHEN concept_set_id = 'uacr' THEN 'mg/g'
                WHEN concept_set_id = 'ahi' THEN 'events/hour'
                WHEN concept_set_id = 'lvef' THEN '%'
                WHEN concept_set_id IN ('bnp', 'nt_probnp') THEN 'pg/mL'
                WHEN concept_set_id IN ('fasting_glucose', 'random_glucose')
                THEN 'mg/dL'
                WHEN concept_set_id IN ('ast', 'alt') THEN 'U/L'
                WHEN concept_set_id = 'platelets' THEN '10^9/L'
                WHEN concept_set_id = 'albumin' THEN 'g/dL'
                WHEN concept_set_id = 'inr' THEN 'ratio'
                WHEN concept_set_id = 'bilirubin' THEN 'mg/dL'
            END AS normalized_unit
        FROM matched
        """
    )


def _build_lab_summary(
    connection: duckdb.DuckDBPyConnection,
    config: GLP1Config,
) -> None:
    lookback = config.study.lookback_days
    measurement_lookback = config.study.measurement_lookback_days
    connection.execute(
        f"""
        CREATE OR REPLACE TABLE component_lab_evidence AS
        SELECT
            analysis.index_event_id,
            analysis.index_date,
            lab.* EXCLUDE (event_datetime),
            lab.event_datetime,
            datediff('day', lab.event_datetime, analysis.index_date)
                AS days_before_index
        FROM analysis_glp1_eligibility AS analysis
        JOIN normalized_component_lab AS lab
          ON lab.patient_id = analysis.patient_id
         AND lab.event_datetime <= analysis.index_date
         AND lab.event_datetime >= analysis.index_date - INTERVAL {lookback} DAY
        WHERE lab.normalized_numeric_value IS NOT NULL
        """
    )
    connection.execute(
        f"""
        CREATE OR REPLACE TABLE component_lab_summary AS
        SELECT
            index_event_id,
            arg_max(normalized_numeric_value, event_datetime)
                FILTER (WHERE concept_set_id = 'hba1c'
                        AND days_before_index <= {measurement_lookback})
                AS a1c_latest,
            max(event_datetime)
                FILTER (WHERE concept_set_id = 'hba1c'
                        AND days_before_index <= {measurement_lookback})
                AS a1c_latest_date,
            count(DISTINCT event_datetime::DATE)
                FILTER (WHERE concept_set_id = 'hba1c'
                        AND normalized_numeric_value >= 6.5)
                AS diabetes_range_a1c_dates,
            arg_max(normalized_numeric_value, event_datetime)
                FILTER (WHERE concept_set_id = 'egfr') AS egfr_latest,
            max(event_datetime)
                FILTER (WHERE concept_set_id = 'egfr') AS egfr_latest_date,
            min(normalized_numeric_value)
                FILTER (WHERE concept_set_id = 'egfr') AS egfr_minimum,
            min(event_datetime::DATE)
                FILTER (WHERE concept_set_id = 'egfr'
                        AND normalized_numeric_value < 60) AS egfr_low_first_date,
            max(event_datetime::DATE)
                FILTER (WHERE concept_set_id = 'egfr'
                        AND normalized_numeric_value < 60) AS egfr_low_last_date,
            arg_max(normalized_numeric_value, event_datetime)
                FILTER (WHERE concept_set_id = 'uacr') AS uacr_latest,
            arg_max(normalized_numeric_value, event_datetime)
                FILTER (WHERE concept_set_id = 'ahi') AS ahi_rei_value,
            max(event_datetime)
                FILTER (WHERE concept_set_id = 'ahi') AS ahi_rei_date,
            arg_max(normalized_numeric_value, event_datetime)
                FILTER (WHERE concept_set_id = 'lvef') AS lvef,
            max(event_datetime)
                FILTER (WHERE concept_set_id = 'lvef') AS lvef_date,
            arg_max(normalized_numeric_value, event_datetime)
                FILTER (WHERE concept_set_id IN ('bnp', 'nt_probnp'))
                AS bnp_ntprobnp_latest
        FROM component_lab_evidence
        GROUP BY index_event_id
        """
    )


def _build_blood_pressure_summary(
    connection: duckdb.DuckDBPyConnection,
) -> None:
    connection.execute(
        f"""
        CREATE OR REPLACE TABLE component_bp_evidence AS
        SELECT
            analysis.index_event_id,
            analysis.index_date,
            concept.concept_set_id,
            vital.event_datetime,
            try_cast(vital.value AS DOUBLE) AS numeric_value,
            encounter.type AS encounter_type,
            vital.source_file,
            vital.source_record_hash
        FROM analysis_glp1_eligibility AS analysis
        JOIN source_vital_measurement AS vital
          ON vital.patient_id = analysis.patient_id
         AND vital.event_datetime <= analysis.index_date
         AND vital.event_datetime >= analysis.index_date - INTERVAL 180 DAY
        LEFT JOIN source_encounter AS encounter
          ON encounter.encounter_id = vital.encounter_id
        JOIN concept_set AS concept
          ON concept.domain = 'vital'
         AND concept.include
         AND concept.concept_set_id IN ('systolic_bp', 'diastolic_bp')
         AND {_code_system_sql('vital.code_system')} = concept.code_system
         AND {_concept_match_sql('vital.code')}
        WHERE try_cast(vital.value AS DOUBLE) BETWEEN 30 AND 300
        """
    )
    connection.execute(
        """
        CREATE OR REPLACE TABLE component_bp_summary AS
        WITH ranked AS (
            SELECT *,
                row_number() OVER (
                    PARTITION BY index_event_id, concept_set_id
                    ORDER BY CASE WHEN upper(trim(encounter_type)) = 'AMB'
                                      THEN 0 ELSE 1 END,
                             event_datetime DESC,
                             source_record_hash
                ) AS result_order
            FROM component_bp_evidence
        )
        SELECT
            index_event_id,
            max(numeric_value) FILTER (
                WHERE concept_set_id = 'systolic_bp' AND result_order = 1
            ) AS latest_sbp,
            max(numeric_value) FILTER (
                WHERE concept_set_id = 'diastolic_bp' AND result_order = 1
            ) AS latest_dbp,
            max(event_datetime) FILTER (WHERE result_order = 1) AS latest_bp_date,
            arg_max(encounter_type, event_datetime)
                FILTER (WHERE result_order = 1) AS latest_bp_setting
        FROM ranked
        GROUP BY index_event_id
        """
    )


def _build_medication_evidence(
    connection: duckdb.DuckDBPyConnection,
    config: GLP1Config,
) -> None:
    lookback = config.study.medication_lookback_days
    followup = config.study.followup_days
    connection.execute(
        f"""
        CREATE OR REPLACE TABLE medication_component_evidence AS
        SELECT
            analysis.index_event_id,
            analysis.index_date,
            concept.concept_set_id,
            medication.* EXCLUDE (event_datetime),
            medication.event_datetime,
            datediff('day', medication.event_datetime, analysis.index_date)
                AS days_before_index,
            medication.event_datetime <= analysis.index_date
                AND medication.event_datetime >=
                    analysis.index_date - INTERVAL {lookback} DAY
                AS ordered_pre_index,
            medication.event_datetime <= analysis.index_date
                AND (medication.end_datetime IS NULL
                     OR medication.end_datetime >= analysis.index_date)
                AS active_at_index,
            medication.event_datetime > analysis.index_date
                AND medication.event_datetime <=
                    analysis.index_date + INTERVAL {followup} DAY
                AS ordered_post_index
        FROM analysis_glp1_eligibility AS analysis
        JOIN source_medication AS medication
          ON medication.patient_id = analysis.patient_id
         AND medication.event_datetime <=
             analysis.index_date + INTERVAL {followup} DAY
        JOIN concept_set AS concept
          ON concept.domain = 'medication'
         AND concept.include
         AND {_code_system_sql('medication.code_system')} = concept.code_system
         AND {_concept_match_sql('medication.code')}
        """
    )
    connection.execute(
        """
        CREATE OR REPLACE TABLE medication_component_summary AS
        SELECT
            index_event_id,
            count(DISTINCT code) FILTER (
                WHERE active_at_index
                  AND starts_with(concept_set_id, 'antihypertensive_')
            ) AS active_antihypertensive_ingredient_count,
            bool_or(active_at_index AND concept_set_id IN ('clozapine', 'olanzapine'))
                AS clozapine_or_olanzapine_active,
            bool_or(active_at_index AND concept_set_id IN ('clozapine', 'olanzapine'))
                AS antipsychotic_active,
            bool_or(active_at_index AND starts_with(concept_set_id, 'opioid_'))
                AS opioid_active_at_index,
            bool_or(active_at_index AND starts_with(concept_set_id, 'benzodiazepine_'))
                AS benzodiazepine_active_at_index,
            bool_or(active_at_index AND starts_with(concept_set_id, 'loop_diuretic_'))
                AS loop_diuretic_active_at_index,
            bool_or(ordered_pre_index AND starts_with(concept_set_id, 'glp1_'))
                AS glp1_ever_ordered_pre_index,
            bool_or(active_at_index AND starts_with(concept_set_id, 'glp1_'))
                AS glp1_active_at_index,
            min(event_datetime) FILTER (
                WHERE ordered_pre_index AND starts_with(concept_set_id, 'glp1_')
            ) AS glp1_first_order_date,
            max(event_datetime) FILTER (
                WHERE ordered_pre_index AND starts_with(concept_set_id, 'glp1_')
            ) AS glp1_last_pre_index_order_date,
            arg_max(concept_set_id, event_datetime) FILTER (
                WHERE active_at_index AND starts_with(concept_set_id, 'glp1_')
            ) AS glp1_ingredient_at_index,
            arg_max(coalesce(brand, code), event_datetime) FILTER (
                WHERE active_at_index AND starts_with(concept_set_id, 'glp1_')
            ) AS glp1_product_at_index,
            bool_or(ordered_post_index AND days_before_index >= -30
                    AND starts_with(concept_set_id, 'glp1_')) AS glp1_new_order_30d,
            bool_or(ordered_post_index AND days_before_index >= -90
                    AND starts_with(concept_set_id, 'glp1_')) AS glp1_new_order_90d,
            bool_or(ordered_post_index AND days_before_index >= -365
                    AND starts_with(concept_set_id, 'glp1_')) AS glp1_new_order_365d
        FROM medication_component_evidence
        GROUP BY index_event_id
        """
    )


def _code_system_sql(expression: str) -> str:
    return (
        f"regexp_replace(upper(trim({expression})), "
        "'[^A-Z0-9]', '', 'g')"
    )


def _concept_match_sql(code_expression: str) -> str:
    return f"""
        (
               (concept.match_type = 'exact'
                AND upper(trim({code_expression})) = concept.code)
            OR (concept.match_type = 'prefix'
                AND starts_with(upper(trim({code_expression})), concept.code))
            OR (concept.match_type = 'regex'
                AND regexp_matches(upper(trim({code_expression})), concept.code))
        )
    """


def _sql_string(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"

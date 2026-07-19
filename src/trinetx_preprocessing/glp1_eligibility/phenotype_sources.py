"""Temporal component evidence summaries for GLP-1 eligibility phenotypes."""

from __future__ import annotations

import duckdb

from .config import GLP1Config
from .sql_helpers import (
    inclusive_datetime_end_sql,
    inclusive_lookback_start_sql,
    raw_date_is_date_only_sql,
    timestamp_precision_sql,
)

DIAGNOSIS_COMPONENTS = (
    "obesity",
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

ALL_HISTORY_DIAGNOSIS_COMPONENTS = frozenset(
    {"prior_mi", "ischemic_stroke", "pad", "symptomatic_pad"}
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

ALL_HISTORY_PROCEDURE_COMPONENTS = frozenset(
    {
        "bariatric_surgery",
        "liver_biopsy",
        "lower_extremity_revascularization",
        "transient_elastography",
    }
)

SLEEP_STUDY_LOOKBACK_DAYS = 5 * 365


def build_component_source_summaries(
    connection: duckdb.DuckDBPyConnection,
    config: GLP1Config,
) -> None:
    """Build index-keyed source evidence and aggregate component summaries."""

    _build_diagnosis_evidence(connection, config)
    _build_procedure_evidence(connection, config)
    _build_index_context(connection)
    _build_normalized_component_labs(connection)
    _build_lab_summary(connection, config)
    _build_blood_pressure_summary(connection, config)
    _build_medication_evidence(connection, config)
    _build_observability_summary(connection)


def _build_index_context(connection: duckdb.DuckDBPyConnection) -> None:
    connection.execute(
        f"""
        CREATE OR REPLACE TABLE index_diagnosis_context AS
        SELECT
            cohort.index_event_id,
            bool_or(concept.concept_set_id = 'cardiac_arrest')
                AS cardiac_arrest_context,
            bool_or(concept.concept_set_id = 'major_trauma')
                AS major_trauma_context,
            bool_or(concept.concept_set_id = 'pneumonia_lri')
                AS pneumonia_lri_at_index,
            bool_or(concept.concept_set_id = 'heart_failure')
                AS heart_failure_at_index
        FROM cohort_hypercapnia_encounter AS cohort
        JOIN source_diagnosis AS diagnosis
          ON diagnosis.patient_id = cohort.patient_id
         AND diagnosis.encounter_id = cohort.encounter_id
         AND {_encounter_context_window_sql(
             'diagnosis.event_datetime', 'diagnosis.date'
         )}
        JOIN concept_set AS concept
          ON concept.domain = 'diagnosis'
         AND concept.include
         AND concept.concept_set_id IN (
             'cardiac_arrest', 'major_trauma',
             'pneumonia_lri', 'heart_failure'
         )
         AND {_code_system_sql('diagnosis.code_system')} = concept.code_system
         AND {_concept_match_sql('diagnosis.code')}
        GROUP BY cohort.index_event_id
        """
    )
    connection.execute(
        f"""
        CREATE OR REPLACE TABLE index_procedure_context AS
        SELECT
            cohort.index_event_id,
            bool_or(concept.concept_set_id = 'invasive_ventilation')
                AS invasive_ventilation_at_index,
            bool_or(
                concept.concept_set_id IN (
                    'procedural_sedation', 'anesthesia_procedure'
                )
                AND procedure.event_datetime <= cohort.abg_datetime
            ) AS procedure_sedation_context,
            bool_or(
                concept.concept_set_id = 'anesthesia_procedure'
                AND procedure.event_datetime <= cohort.abg_datetime
            ) AS postoperative_context
        FROM cohort_hypercapnia_encounter AS cohort
        JOIN source_procedure AS procedure
          ON procedure.patient_id = cohort.patient_id
         AND procedure.encounter_id = cohort.encounter_id
         AND {_encounter_context_window_sql(
             'procedure.event_datetime', 'procedure.date'
         )}
        JOIN concept_set AS concept
          ON concept.domain = 'procedure'
         AND concept.include
         AND concept.concept_set_id IN (
             'invasive_ventilation', 'procedural_sedation',
             'anesthesia_procedure'
         )
         AND {_code_system_sql('procedure.code_system')} = concept.code_system
         AND {_concept_match_sql('procedure.code')}
        GROUP BY cohort.index_event_id
        """
    )
    for table in (
        "cohort_hypercapnia_encounter",
        "cohort_hypercapnia_patient_index",
        "analysis_glp1_eligibility",
    ):
        connection.execute(
            f"""
            UPDATE {table} AS target
            SET cardiac_arrest_context = context.cardiac_arrest_context,
                major_trauma_context = context.major_trauma_context
            FROM index_diagnosis_context AS context
            WHERE target.index_event_id = context.index_event_id
            """
        )
        connection.execute(
            f"""
            UPDATE {table} AS target
            SET procedure_sedation_context = context.procedure_sedation_context,
                postoperative_context = context.postoperative_context
            FROM index_procedure_context AS context
            WHERE target.index_event_id = context.index_event_id
            """
        )


def _build_diagnosis_evidence(
    connection: duckdb.DuckDBPyConnection,
    config: GLP1Config,
) -> None:
    lookback = config.study.lookback_days
    all_history = ", ".join(
        _sql_string(component)
        for component in sorted(ALL_HISTORY_DIAGNOSIS_COMPONENTS)
    )
    in_lookback = inclusive_lookback_start_sql(
        "diagnosis.event_datetime",
        timestamp_precision_sql("diagnosis.date"),
        "analysis.index_date",
        lookback,
    )
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
        WHERE concept.concept_set_id IN ({all_history})
           OR {in_lookback}
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


def _build_procedure_evidence(
    connection: duckdb.DuckDBPyConnection,
    config: GLP1Config,
) -> None:
    lookback = config.study.lookback_days
    all_history = ", ".join(
        _sql_string(component)
        for component in sorted(ALL_HISTORY_PROCEDURE_COMPONENTS)
    )
    in_lookback = inclusive_lookback_start_sql(
        "procedure.event_datetime",
        timestamp_precision_sql("procedure.date"),
        "analysis.index_date",
        lookback,
    )
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
        WHERE concept.concept_set_id IN ({all_history})
           OR {in_lookback}
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
                 'ast', 'alt', 'platelets', 'albumin', 'inr', 'bilirubin',
                 'fibrosis_stage'
             )
             AND {_code_system_sql('lab.code_system')} = concept.code_system
             AND {_concept_match_sql('lab.code')}
        )
        SELECT
            *,
            CASE
                WHEN concept_set_id = 'fibrosis_stage'
                 AND regexp_matches(
                    upper(trim(coalesce(
                        nullif(lab_result_text_val, ''),
                        nullif(lab_result_num_val, '')
                    ))),
                    '[0-4]'
                 )
                THEN 'F' || regexp_extract(
                    upper(trim(coalesce(
                        nullif(lab_result_text_val, ''),
                        nullif(lab_result_num_val, '')
                    ))),
                    '([0-4])', 1
                )
                ELSE NULL
            END AS fibrosis_stage_value,
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
                WHEN concept_set_id = 'fibrosis_stage' THEN 'stage'
            END AS normalized_unit
        FROM matched
        """
    )


def _build_lab_summary(
    connection: duckdb.DuckDBPyConnection,
    config: GLP1Config,
) -> None:
    measurement_lookback = config.study.measurement_lookback_days
    history_lookback = config.study.lookback_days
    measurement_in_lookback = inclusive_lookback_start_sql(
        "event_datetime",
        "event_datetime_precision",
        "index_date",
        measurement_lookback,
    )
    history_in_lookback = inclusive_lookback_start_sql(
        "event_datetime",
        "event_datetime_precision",
        "index_date",
        history_lookback,
    )
    sleep_study_in_lookback = inclusive_lookback_start_sql(
        "event_datetime",
        "event_datetime_precision",
        "index_date",
        SLEEP_STUDY_LOOKBACK_DAYS,
    )
    connection.execute(
        f"""
        CREATE OR REPLACE TABLE component_lab_evidence AS
        WITH candidate AS (
        SELECT
            analysis.index_event_id,
            analysis.index_date,
            lab.* EXCLUDE (event_datetime),
            lab.event_datetime,
            {timestamp_precision_sql('lab.date')} AS event_datetime_precision,
            datediff('day', lab.event_datetime, analysis.index_date)
                AS days_before_index
        FROM analysis_glp1_eligibility AS analysis
        JOIN normalized_component_lab AS lab
          ON lab.patient_id = analysis.patient_id
         AND lab.event_datetime <= analysis.index_date
        WHERE lab.normalized_numeric_value IS NOT NULL
           OR lab.fibrosis_stage_value IS NOT NULL
        ), windowed AS (
            SELECT *,
                {measurement_in_lookback} AS in_measurement_lookback,
                {history_in_lookback} AS in_history_lookback,
                {sleep_study_in_lookback} AS in_sleep_study_lookback
            FROM candidate
        )
        SELECT * EXCLUDE (
            in_measurement_lookback,
            in_history_lookback,
            in_sleep_study_lookback
        )
        FROM windowed
        WHERE concept_set_id = 'fibrosis_stage'
           OR (
                concept_set_id = 'ahi'
                AND in_sleep_study_lookback
           )
           OR (
                concept_set_id IN ('egfr', 'uacr', 'lvef', 'bnp', 'nt_probnp')
                AND in_history_lookback
           )
           OR (
                concept_set_id NOT IN (
                    'ahi', 'egfr', 'uacr', 'lvef', 'bnp', 'nt_probnp',
                    'fibrosis_stage'
                )
                AND in_measurement_lookback
           )
        """
    )
    connection.execute(
        """
        CREATE OR REPLACE TABLE component_lab_summary AS
        SELECT
            index_event_id,
            first(
                normalized_numeric_value
                ORDER BY event_datetime DESC, source_record_hash DESC
            )
                FILTER (WHERE concept_set_id = 'hba1c')
                AS a1c_latest,
            max(event_datetime)
                FILTER (WHERE concept_set_id = 'hba1c')
                AS a1c_latest_date,
            count(DISTINCT event_datetime::DATE)
                FILTER (WHERE concept_set_id = 'hba1c'
                        AND normalized_numeric_value >= 6.5)
                AS diabetes_range_a1c_dates,
            first(
                normalized_numeric_value
                ORDER BY event_datetime DESC, source_record_hash DESC
            )
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
            first(
                normalized_numeric_value
                ORDER BY event_datetime DESC, source_record_hash DESC
            )
                FILTER (WHERE concept_set_id = 'uacr') AS uacr_latest,
            first(
                normalized_numeric_value
                ORDER BY event_datetime DESC, source_record_hash DESC
            )
                FILTER (WHERE concept_set_id = 'ahi') AS ahi_rei_value,
            max(event_datetime)
                FILTER (WHERE concept_set_id = 'ahi') AS ahi_rei_date,
            first(
                normalized_numeric_value
                ORDER BY event_datetime DESC, source_record_hash DESC
            )
                FILTER (WHERE concept_set_id = 'lvef') AS lvef,
            max(event_datetime)
                FILTER (WHERE concept_set_id = 'lvef') AS lvef_date,
            first(
                normalized_numeric_value
                ORDER BY event_datetime DESC, source_record_hash DESC
            )
                FILTER (WHERE concept_set_id IN ('bnp', 'nt_probnp'))
                AS bnp_ntprobnp_latest,
            first(
                fibrosis_stage_value
                ORDER BY event_datetime DESC, source_record_hash DESC
            )
                FILTER (WHERE concept_set_id = 'fibrosis_stage')
                AS fibrosis_stage,
            max(event_datetime)
                FILTER (WHERE concept_set_id = 'fibrosis_stage')
                AS fibrosis_stage_date,
            first(
                normalized_numeric_value
                ORDER BY event_datetime DESC, source_record_hash DESC
            )
                FILTER (WHERE concept_set_id = 'ast') AS ast_latest,
            first(
                normalized_numeric_value
                ORDER BY event_datetime DESC, source_record_hash DESC
            )
                FILTER (WHERE concept_set_id = 'alt') AS alt_latest,
            first(
                normalized_numeric_value
                ORDER BY event_datetime DESC, source_record_hash DESC
            )
                FILTER (WHERE concept_set_id = 'platelets') AS platelets_latest
        FROM component_lab_evidence
        GROUP BY index_event_id
        """
    )


def _build_blood_pressure_summary(
    connection: duckdb.DuckDBPyConnection,
    config: GLP1Config,
) -> None:
    measurement_lookback = config.study.measurement_lookback_days
    in_lookback = inclusive_lookback_start_sql(
        "vital.event_datetime",
        timestamp_precision_sql("vital.date"),
        "analysis.index_date",
        measurement_lookback,
    )
    connection.execute(
        f"""
        CREATE OR REPLACE TABLE component_bp_evidence AS
        WITH matched AS (
        SELECT
            analysis.index_event_id,
            analysis.index_date,
            concept.concept_set_id,
            vital.patient_id,
            vital.encounter_id,
            vital.code_system,
            vital.code,
            vital.text_value,
            vital.units_of_measure,
            vital.event_datetime,
            try_cast(vital.value AS DOUBLE) AS raw_numeric_value,
            lower(trim(coalesce(vital.units_of_measure, ''))) AS unit_key,
            encounter.type AS encounter_type,
            vital.source_file,
            vital.source_record_hash
        FROM analysis_glp1_eligibility AS analysis
        JOIN source_vital_measurement AS vital
         ON vital.patient_id = analysis.patient_id
         AND vital.event_datetime <= analysis.index_date
         AND {in_lookback}
        LEFT JOIN glp1_encounter AS encounter
          ON encounter.patient_id = vital.patient_id
         AND encounter.encounter_id = vital.encounter_id
        JOIN concept_set AS concept
          ON concept.domain = 'vital'
         AND concept.include
         AND concept.concept_set_id IN ('systolic_bp', 'diastolic_bp')
         AND {_code_system_sql('vital.code_system')} = concept.code_system
         AND {_concept_match_sql('vital.code')}
        ), normalized AS (
            SELECT
                *,
                CASE
                    WHEN unit_key IN (
                        'mmhg', 'mm hg', 'mm_hg', 'mm[hg]', 'torr'
                    ) THEN raw_numeric_value
                    WHEN unit_key = 'kpa'
                    THEN raw_numeric_value * 7.5006168270417
                    ELSE NULL
                END AS normalized_numeric_value
            FROM matched
        )
        SELECT *
        FROM normalized
        WHERE normalized_numeric_value BETWEEN 30 AND 300
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
                             source_record_hash DESC
                ) AS result_order
            FROM component_bp_evidence
        )
        SELECT
            index_event_id,
            max(normalized_numeric_value) FILTER (
                WHERE concept_set_id = 'systolic_bp' AND result_order = 1
            ) AS latest_sbp,
            max(normalized_numeric_value) FILTER (
                WHERE concept_set_id = 'diastolic_bp' AND result_order = 1
            ) AS latest_dbp,
            max(event_datetime) FILTER (WHERE result_order = 1) AS latest_bp_date,
            first(
                encounter_type
                ORDER BY event_datetime DESC, source_record_hash DESC
            )
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
    in_lookback = inclusive_lookback_start_sql(
        "medication.event_datetime",
        timestamp_precision_sql("medication.start_date"),
        "analysis.index_date",
        lookback,
    )
    medication_end = inclusive_datetime_end_sql(
        "medication.end_datetime",
        timestamp_precision_sql("medication.end_date"),
        "NULL",
    )
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
                AND (
                    starts_with(concept.concept_set_id, 'glp1_')
                    OR {in_lookback}
                )
                AS ordered_pre_index,
            medication.event_datetime <= analysis.index_date
                AND {in_lookback}
                AND (medication.end_datetime IS NULL
                     OR {medication_end} >= analysis.index_date)
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
        WHERE {in_lookback}
           OR (
                starts_with(concept.concept_set_id, 'glp1_')
                AND medication.event_datetime <= analysis.index_date
           )
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
            first(
                replace(concept_set_id, 'glp1_', '')
                ORDER BY event_datetime DESC, source_record_hash DESC
            ) FILTER (
                WHERE active_at_index AND starts_with(concept_set_id, 'glp1_')
            ) AS glp1_ingredient_at_index,
            first(
                coalesce(brand, code)
                ORDER BY event_datetime DESC, source_record_hash DESC
            ) FILTER (
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


def _build_observability_summary(connection: duckdb.DuckDBPyConnection) -> None:
    encounter_in_lookback = inclusive_lookback_start_sql(
        "encounter.encounter_start",
        timestamp_precision_sql("encounter.start_date"),
        "analysis.index_date",
        365,
    )
    connection.execute(
        f"""
        CREATE OR REPLACE TABLE component_observability_summary AS
        WITH encounter AS (
            SELECT
                analysis.index_event_id,
                min(encounter.encounter_start) FILTER (
                    WHERE encounter.encounter_start <= analysis.index_date
                ) AS first_observed_event_date,
                count(DISTINCT encounter.encounter_id) FILTER (
                    WHERE encounter.encounter_start <= analysis.index_date
                      AND {encounter_in_lookback}
                ) AS event_count
            FROM analysis_glp1_eligibility AS analysis
            JOIN source_encounter AS encounter USING (patient_id)
            GROUP BY analysis.index_event_id
        ), combined AS (
            SELECT
                analysis.index_event_id,
                analysis.index_date,
                least(
                    encounter.first_observed_event_date,
                    diagnosis.first_observed_event_date,
                    lab.first_observed_event_date,
                    vital.first_observed_event_date,
                    procedure.first_observed_event_date,
                    medication.first_observed_event_date
                ) AS first_observed_event_date,
                coalesce(encounter.event_count, 0) AS encounter_count_365d,
                coalesce(diagnosis.event_count, 0)
                    AS diagnosis_event_count_730d,
                coalesce(lab.event_count, 0) AS lab_event_count_365d,
                coalesce(medication.event_count, 0)
                    AS medication_event_count_730d
            FROM analysis_glp1_eligibility AS analysis
            LEFT JOIN encounter USING (index_event_id)
            LEFT JOIN raw_diagnosis_observability AS diagnosis
                USING (index_event_id)
            LEFT JOIN raw_labs_observability AS lab USING (index_event_id)
            LEFT JOIN raw_vitals_observability AS vital USING (index_event_id)
            LEFT JOIN raw_procedure_observability AS procedure
                USING (index_event_id)
            LEFT JOIN raw_medication_observability AS medication
                USING (index_event_id)
        )
        SELECT
            index_event_id,
            first_observed_event_date,
            datediff(
                'day', first_observed_event_date, index_date
            ) AS lookback_observation_days,
            encounter_count_365d,
            diagnosis_event_count_730d,
            lab_event_count_365d,
            medication_event_count_730d
        FROM combined
        """
    )


def _code_system_sql(expression: str) -> str:
    return (
        f"regexp_replace(upper(trim({expression})), "
        "'[^A-Z0-9]', '', 'g')"
    )


def _encounter_context_window_sql(
    event_datetime: str,
    raw_date: str,
) -> str:
    """Match precise timestamps or date-only events within encounter dates."""

    encounter_end = inclusive_datetime_end_sql(
        "cohort.encounter_end",
        "cohort.encounter_end_precision",
        "cohort.encounter_start + INTERVAL 1 DAY",
    )
    return f"""(
        {event_datetime} BETWEEN cohort.encounter_start AND {encounter_end}
        OR (
            {raw_date_is_date_only_sql(raw_date)}
            AND {event_datetime}::DATE BETWEEN cohort.encounter_start::DATE
                AND {encounter_end}::DATE
        )
    )"""


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

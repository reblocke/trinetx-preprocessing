"""Hypercapnia and obesity cohort construction in DuckDB."""

from __future__ import annotations

from dataclasses import dataclass

import duckdb

from .config import GLP1Config


@dataclass(frozen=True)
class CoreCohortCounts:
    """Aggregate row counts from the core cohort build."""

    hypercapnia_encounters: int
    patient_index_events: int
    primary_obesity_hypercapnia: int
    evidence_rows: int


def build_core_cohort(
    connection: duckdb.DuckDBPyConnection,
    *,
    config: GLP1Config,
    run_id: str,
    git_sha: str,
) -> CoreCohortCounts:
    """Build gas, index-event, BMI, evidence, and flow tables."""

    _build_normalized_gas(connection, config)
    _build_hypercapnia_encounters(connection, config, run_id)
    _build_patient_index(connection, config)
    _build_normalized_anthropometrics(connection, config)
    _build_analysis_table(connection, config, git_sha)
    _build_evidence_table(connection, run_id)
    _build_views(connection, config)
    return CoreCohortCounts(
        hypercapnia_encounters=_count(connection, "cohort_hypercapnia_encounter"),
        patient_index_events=_count(connection, "cohort_hypercapnia_patient_index"),
        primary_obesity_hypercapnia=int(
            connection.execute(
                "SELECT COUNT(*) FROM analysis_primary_obesity_hypercapnia"
            ).fetchone()[0]
        ),
        evidence_rows=_count(connection, "eligibility_evidence_long"),
    )


def _build_normalized_gas(
    connection: duckdb.DuckDBPyConnection, config: GLP1Config
) -> None:
    hypercapnia = config.hypercapnia
    connection.execute(
        f"""
        CREATE OR REPLACE TABLE normalized_gas_measurement AS
        WITH matched AS (
            SELECT
                lab.*,
                concept.concept_set_id,
                try_cast(lab.lab_result_num_val AS DOUBLE) AS raw_numeric_value,
                lower(trim(coalesce(lab.units_of_measure, ''))) AS unit_key,
                CASE
                    WHEN regexp_full_match(trim(lab.date), '\\d{{4}}-\\d{{2}}-\\d{{2}}')
                    THEN 'date_only'
                    ELSE 'timestamp'
                END AS timestamp_precision
            FROM source_lab_measurement AS lab
            JOIN concept_set AS concept
              ON concept.domain = 'lab'
             AND concept.include
             AND concept.concept_set_id IN (
                 'arterial_pco2', 'venous_pco2',
                 'unspecified_blood_pco2', 'arterial_total_co2',
                 'arterial_ph', 'venous_ph', 'arterial_hco3',
                 'arterial_po2', 'arterial_sao2'
             )
             AND regexp_replace(
                    upper(trim(lab.code_system)), '[^A-Z0-9]', '', 'g'
                 ) = concept.code_system
             AND (
                    (concept.match_type = 'exact'
                     AND upper(trim(lab.code)) = concept.code)
                 OR (concept.match_type = 'prefix'
                     AND starts_with(upper(trim(lab.code)), concept.code))
                 OR (concept.match_type = 'regex'
                     AND regexp_matches(upper(trim(lab.code)), concept.code))
             )
        ), normalized AS (
            SELECT
                *,
                CASE
                    WHEN concept_set_id IN (
                        'arterial_pco2', 'venous_pco2',
                        'unspecified_blood_pco2'
                    ) AND unit_key IN ('mmhg', 'mm hg', 'mm_hg', 'torr')
                    THEN raw_numeric_value
                    WHEN concept_set_id IN (
                        'arterial_pco2', 'venous_pco2',
                        'unspecified_blood_pco2'
                    ) AND unit_key = 'kpa'
                    THEN raw_numeric_value * 7.5006168270417
                    WHEN concept_set_id IN ('arterial_ph', 'venous_ph')
                         AND unit_key IN ('', 'ph', '1', 'unitless')
                    THEN raw_numeric_value
                    WHEN concept_set_id = 'arterial_hco3'
                         AND unit_key IN (
                             'mmol/l', 'mmol/liter', 'mmol/litre',
                             'meq/l', 'meq/liter', 'meq/litre'
                         )
                    THEN raw_numeric_value
                    WHEN concept_set_id = 'arterial_po2'
                         AND unit_key IN ('mmhg', 'mm hg', 'mm_hg', 'torr')
                    THEN raw_numeric_value
                    WHEN concept_set_id = 'arterial_po2' AND unit_key = 'kpa'
                    THEN raw_numeric_value * 7.5006168270417
                    WHEN concept_set_id = 'arterial_sao2'
                         AND unit_key IN ('%', 'percent')
                    THEN raw_numeric_value
                    WHEN concept_set_id = 'arterial_sao2'
                         AND unit_key IN ('1', 'fraction')
                         AND raw_numeric_value BETWEEN 0 AND 1
                    THEN raw_numeric_value * 100
                    ELSE NULL
                END AS normalized_numeric_value,
                CASE
                    WHEN concept_set_id IN (
                        'arterial_pco2', 'venous_pco2',
                        'unspecified_blood_pco2'
                    ) THEN 'mm Hg'
                    WHEN concept_set_id IN ('arterial_ph', 'venous_ph')
                    THEN 'pH'
                    WHEN concept_set_id = 'arterial_hco3' THEN 'mmol/L'
                    WHEN concept_set_id = 'arterial_po2' THEN 'mm Hg'
                    WHEN concept_set_id = 'arterial_sao2' THEN '%'
                    ELSE units_of_measure
                END AS normalized_unit
            FROM matched
        )
        SELECT
            *,
            normalized_numeric_value IS NOT NULL AS unit_usable,
            CASE
                WHEN concept_set_id IN (
                    'arterial_pco2', 'venous_pco2', 'unspecified_blood_pco2'
                ) THEN normalized_numeric_value BETWEEN
                    {hypercapnia.pco2_plausible_min_mm_hg}
                    AND {hypercapnia.pco2_plausible_max_mm_hg}
                WHEN concept_set_id IN ('arterial_ph', 'venous_ph')
                THEN normalized_numeric_value BETWEEN
                    {hypercapnia.ph_plausible_min}
                    AND {hypercapnia.ph_plausible_max}
                WHEN concept_set_id = 'arterial_hco3'
                THEN normalized_numeric_value BETWEEN
                    {hypercapnia.hco3_plausible_min_mmol_l}
                    AND {hypercapnia.hco3_plausible_max_mmol_l}
                WHEN concept_set_id = 'arterial_po2'
                THEN normalized_numeric_value BETWEEN
                    {hypercapnia.po2_plausible_min_mm_hg}
                    AND {hypercapnia.po2_plausible_max_mm_hg}
                WHEN concept_set_id = 'arterial_sao2'
                THEN normalized_numeric_value BETWEEN
                    {hypercapnia.sao2_plausible_min_percent}
                    AND {hypercapnia.sao2_plausible_max_percent}
                ELSE normalized_numeric_value IS NOT NULL
            END AS plausible_value
        FROM normalized
        """
    )


def _build_hypercapnia_encounters(
    connection: duckdb.DuckDBPyConnection,
    config: GLP1Config,
    run_id: str,
) -> None:
    hypercapnia = config.hypercapnia
    study = config.study
    encounter_types = ", ".join(
        _sql_string(value) for value in study.index_encounter_types
    )
    start_condition = (
        "TRUE"
        if study.study_start is None
        else (
            "encounter_start::DATE >= DATE "
            + _sql_string(study.study_start.isoformat())
        )
    )
    end_condition = (
        "TRUE"
        if study.study_end is None
        else f"encounter_start::DATE <= DATE {_sql_string(study.study_end.isoformat())}"
    )
    window_hours = hypercapnia.index_window_hours
    pair_minutes = hypercapnia.pair_tolerance_minutes
    pco2_threshold = hypercapnia.pco2_gt_mm_hg
    sensitivity_50, sensitivity_52 = (
        hypercapnia.pco2_sensitivity_thresholds_mm_hg
    )

    include_vbg = "TRUE" if hypercapnia.include_vbg_secondary_cohort else "FALSE"
    connection.execute(
        """
        CREATE OR REPLACE TEMP TABLE glp1_encounter AS
        SELECT * EXCLUDE (observed_order)
        FROM (
            SELECT
                encounter.*,
                row_number() OVER (
                    PARTITION BY encounter_id
                    ORDER BY encounter_start, source_record_hash
                ) AS observed_order
            FROM source_encounter AS encounter
            WHERE encounter_id IS NOT NULL AND patient_id IS NOT NULL
        )
        WHERE observed_order = 1
        """
    )
    connection.execute(
        """
        CREATE OR REPLACE TEMP TABLE glp1_patient AS
        SELECT * EXCLUDE (observed_order)
        FROM (
            SELECT
                patient.*,
                row_number() OVER (
                    PARTITION BY patient_id
                    ORDER BY source_record_hash
                ) AS observed_order
            FROM source_patient AS patient
            WHERE patient_id IS NOT NULL
        )
        WHERE observed_order = 1
        """
    )
    connection.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE gas_in_index_window AS
        SELECT gas.*
        FROM normalized_gas_measurement AS gas
        JOIN glp1_encounter AS encounter USING (encounter_id, patient_id)
        WHERE gas.concept_set_id IN (
            'arterial_pco2', 'venous_pco2', 'unspecified_blood_pco2'
        )
          AND (
                gas.event_datetime BETWEEN encounter.encounter_start
                    AND encounter.encounter_start + INTERVAL {window_hours} HOUR
             OR (
                    gas.timestamp_precision = 'date_only'
                AND gas.event_datetime::DATE BETWEEN encounter.encounter_start::DATE
                    AND (encounter.encounter_start
                         + INTERVAL {window_hours} HOUR)::DATE
             )
          )
        """
    )
    connection.execute(
        """
        CREATE OR REPLACE TEMP TABLE first_arterial_pco2 AS
        SELECT * EXCLUDE (result_order)
        FROM (
            SELECT
                gas.*,
                row_number() OVER (
                    PARTITION BY encounter_id
                    ORDER BY event_datetime, source_record_hash
                ) AS result_order
            FROM gas_in_index_window AS gas
            WHERE concept_set_id = 'arterial_pco2'
        )
        WHERE result_order = 1
        """
    )
    connection.execute(
        """
        CREATE OR REPLACE TEMP TABLE arterial_pco2_max AS
        SELECT
            encounter.encounter_id,
            max(gas.normalized_numeric_value) AS maximum_pco2
        FROM glp1_encounter AS encounter
        JOIN normalized_gas_measurement AS gas
          ON gas.encounter_id = encounter.encounter_id
         AND gas.patient_id = encounter.patient_id
        WHERE gas.concept_set_id = 'arterial_pco2'
          AND gas.unit_usable
          AND gas.plausible_value
          AND (
                gas.event_datetime BETWEEN encounter.encounter_start
                    AND coalesce(
                        encounter.encounter_end,
                        encounter.encounter_start + INTERVAL 1 DAY
                    )
             OR (
                    gas.timestamp_precision = 'date_only'
                AND gas.event_datetime::DATE BETWEEN encounter.encounter_start::DATE
                    AND coalesce(
                        encounter.encounter_end,
                        encounter.encounter_start + INTERVAL 1 DAY
                    )::DATE
             )
          )
        GROUP BY encounter.encounter_id
        """
    )
    connection.execute(
        """
        CREATE OR REPLACE TEMP TABLE first_venous_pco2 AS
        SELECT * EXCLUDE (result_order)
        FROM (
            SELECT
                gas.*,
                row_number() OVER (
                    PARTITION BY encounter_id
                    ORDER BY event_datetime, source_record_hash
                ) AS result_order
            FROM gas_in_index_window AS gas
            WHERE concept_set_id = 'venous_pco2'
        )
        WHERE result_order = 1
        """
    )
    connection.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE paired_arterial_measurement AS
        WITH candidates AS (
            SELECT
                arterial.source_record_hash AS reference_source_record_hash,
                candidate.*,
                CASE
                    WHEN (
                        (arterial.specimen_id IS NOT NULL
                         AND arterial.specimen_id != ''
                         AND arterial.specimen_id = candidate.specimen_id)
                        OR
                        (arterial.panel_id IS NOT NULL
                         AND arterial.panel_id != ''
                         AND arterial.panel_id = candidate.panel_id)
                    ) THEN 'same_specimen_or_panel'
                    WHEN arterial.event_datetime = candidate.event_datetime
                    THEN 'exact_timestamp'
                    WHEN abs(datediff(
                        'minute', arterial.event_datetime, candidate.event_datetime
                    )) <= {pair_minutes}
                    THEN 'nearest_within_tolerance'
                    ELSE 'same_date_date_only'
                END AS pairing_method,
                abs(datediff(
                    'minute', arterial.event_datetime, candidate.event_datetime
                )) AS pairing_time_difference_minutes,
                CASE
                    WHEN (
                        (arterial.specimen_id IS NOT NULL
                         AND arterial.specimen_id != ''
                         AND arterial.specimen_id = candidate.specimen_id)
                        OR
                        (arterial.panel_id IS NOT NULL
                         AND arterial.panel_id != ''
                         AND arterial.panel_id = candidate.panel_id)
                    ) THEN 'highest'
                    WHEN arterial.event_datetime = candidate.event_datetime
                    THEN 'high'
                    WHEN abs(datediff(
                        'minute', arterial.event_datetime, candidate.event_datetime
                    )) <= {pair_minutes}
                    THEN 'moderate'
                    ELSE 'date_only'
                END AS pairing_quality,
                CASE
                    WHEN (
                        (arterial.specimen_id IS NOT NULL
                         AND arterial.specimen_id != ''
                         AND arterial.specimen_id = candidate.specimen_id)
                        OR
                        (arterial.panel_id IS NOT NULL
                         AND arterial.panel_id != ''
                         AND arterial.panel_id = candidate.panel_id)
                    ) THEN 1
                    WHEN arterial.event_datetime = candidate.event_datetime THEN 2
                    WHEN abs(datediff(
                        'minute', arterial.event_datetime, candidate.event_datetime
                    )) <= {pair_minutes} THEN 3
                    ELSE 4
                END AS pairing_rank
            FROM first_arterial_pco2 AS arterial
            JOIN normalized_gas_measurement AS candidate
              ON candidate.patient_id = arterial.patient_id
             AND candidate.encounter_id = arterial.encounter_id
            WHERE candidate.concept_set_id IN (
                    'arterial_ph', 'arterial_hco3',
                    'arterial_po2', 'arterial_sao2'
                  )
              AND candidate.unit_usable
              AND candidate.plausible_value
              AND (
                    (
                        (arterial.specimen_id IS NOT NULL
                         AND arterial.specimen_id != ''
                         AND arterial.specimen_id = candidate.specimen_id)
                        OR
                        (arterial.panel_id IS NOT NULL
                         AND arterial.panel_id != ''
                         AND arterial.panel_id = candidate.panel_id)
                    )
                 OR arterial.event_datetime = candidate.event_datetime
                 OR abs(datediff(
                        'minute', arterial.event_datetime, candidate.event_datetime
                    )) <= {pair_minutes}
                 OR (
                        {str(hypercapnia.allow_date_only_pairing).upper()}
                    AND (
                           arterial.timestamp_precision = 'date_only'
                        OR candidate.timestamp_precision = 'date_only'
                    )
                    AND arterial.event_datetime::DATE = candidate.event_datetime::DATE
                 )
              )
        ), ranked AS (
            SELECT
                *,
                row_number() OVER (
                    PARTITION BY reference_source_record_hash, concept_set_id
                    ORDER BY pairing_rank,
                             pairing_time_difference_minutes,
                             source_record_hash
                ) AS pair_order
            FROM candidates
        )
        SELECT * EXCLUDE (pair_order, pairing_rank)
        FROM ranked
        WHERE pair_order = 1
        """
    )
    connection.execute(
        """
        CREATE OR REPLACE TEMP TABLE arterial_with_ph AS
        SELECT
            arterial.*,
            ph.event_datetime AS paired_ph_datetime,
            ph.normalized_numeric_value AS paired_ph_value,
            ph.code AS paired_ph_code,
            ph.source_record_hash AS paired_ph_source_record_hash,
            ph.source_file AS paired_ph_source_file,
            ph.pairing_method,
            ph.pairing_time_difference_minutes,
            ph.pairing_quality
        FROM first_arterial_pco2 AS arterial
        LEFT JOIN paired_arterial_measurement AS ph
          ON ph.reference_source_record_hash = arterial.source_record_hash
         AND ph.concept_set_id = 'arterial_ph'
        """
    )
    connection.execute(
        """
        CREATE OR REPLACE TEMP TABLE arterial_supplemental AS
        SELECT
            reference_source_record_hash,
            max(normalized_numeric_value)
                FILTER (WHERE concept_set_id = 'arterial_hco3') AS abg_hco3,
            max(normalized_numeric_value)
                FILTER (WHERE concept_set_id = 'arterial_po2') AS abg_po2,
            max(normalized_numeric_value)
                FILTER (WHERE concept_set_id = 'arterial_sao2') AS abg_sao2
        FROM paired_arterial_measurement
        WHERE concept_set_id IN (
            'arterial_hco3', 'arterial_po2', 'arterial_sao2'
        )
        GROUP BY reference_source_record_hash
        """
    )
    connection.execute(
        f"""
        CREATE OR REPLACE TABLE cohort_hypercapnia_encounter AS
        WITH candidate AS (
            SELECT
                {_sql_string(run_id)} AS run_id,
                sha256(concat_ws(
                    chr(31), 'glp1-index-v1', encounter.patient_id,
                    encounter.encounter_id,
                    cast(encounter.encounter_start AS VARCHAR)
                )) AS index_event_id,
                encounter.patient_id,
                encounter.encounter_id,
                encounter.type AS encounter_type,
                encounter.encounter_start,
                encounter.encounter_end,
                encounter.encounter_start AS index_date,
                try_cast(patient.year_of_birth AS INTEGER) AS year_of_birth,
                year(encounter.encounter_start)
                    - try_cast(patient.year_of_birth AS INTEGER) AS age_at_index,
                patient.sex,
                patient.race,
                patient.ethnicity,
                patient.patient_regional_location,
                patient.month_year_death,
                arterial.event_datetime AS abg_datetime,
                arterial.lab_result_num_val AS abg_pco2_raw,
                arterial.units_of_measure AS abg_pco2_raw_unit,
                arterial.normalized_numeric_value AS abg_pco2_mm_hg,
                arterial.code AS abg_pco2_code,
                arterial.code_system AS abg_pco2_code_system,
                arterial.source_file AS abg_source_file,
                arterial.source_record_hash AS abg_source_record_hash,
                arterial.paired_ph_value AS abg_ph,
                arterial.paired_ph_code AS abg_ph_code,
                supplemental.abg_hco3,
                supplemental.abg_po2,
                supplemental.abg_sao2,
                arterial.pairing_method AS abg_pairing_method,
                arterial.pairing_time_difference_minutes
                    AS abg_pairing_time_difference_minutes,
                arterial.timestamp_precision AS abg_timestamp_precision,
                arterial.pairing_quality AS abg_pairing_quality,
                arterial.paired_ph_value IS NOT NULL AS abg_ph_available,
                coalesce(arterial.unit_usable, FALSE)
                    AS abg_pco2_unit_usable,
                coalesce(arterial.plausible_value, FALSE)
                    AS abg_pco2_plausible,
                arterial.source_record_hash IS NOT NULL
                    AS first_arterial_pco2_in_window,
                maximum.maximum_pco2 AS maximum_pco2_in_encounter,
                coalesce(
                    arterial.unit_usable
                    AND arterial.plausible_value
                    AND arterial.normalized_numeric_value > {pco2_threshold},
                    FALSE
                )
                    AS hypercapnia_gt45,
                coalesce(
                    arterial.unit_usable
                    AND arterial.plausible_value
                    AND arterial.normalized_numeric_value >= {sensitivity_50},
                    FALSE
                )
                    AS hypercapnia_ge50,
                coalesce(
                    arterial.unit_usable
                    AND arterial.plausible_value
                    AND arterial.normalized_numeric_value >= {sensitivity_52},
                    FALSE
                )
                    AS hypercapnia_ge52,
                coalesce(arterial.paired_ph_value <
                    {hypercapnia.acute_acidemia_ph_lt}, FALSE) AS acute_acidemia,
                coalesce(
                    arterial.normalized_numeric_value > {pco2_threshold}
                    AND arterial.paired_ph_value BETWEEN
                        {hypercapnia.acute_acidemia_ph_lt}
                        AND {hypercapnia.ph_max},
                    FALSE
                ) AS compensated_hypercapnia,
                coalesce(
                    arterial.normalized_numeric_value > {pco2_threshold}
                    AND arterial.paired_ph_value IS NULL,
                    FALSE
                ) AS pco2_only_sensitivity_case,
                coalesce(
                    arterial.unit_usable
                    AND arterial.plausible_value
                    AND arterial.normalized_numeric_value <= {pco2_threshold}
                    AND maximum.maximum_pco2 > {pco2_threshold},
                    FALSE
                ) AS later_hypercapnia_sensitivity_case,
                coalesce(
                    arterial.encounter_id IS NULL
                    AND venous.unit_usable
                    AND venous.plausible_value
                    AND venous.normalized_numeric_value > {pco2_threshold},
                    FALSE
                ) AS vbg_only_sensitivity_case,
                FALSE AS cardiac_arrest_context,
                FALSE AS major_trauma_context,
                FALSE AS procedure_sedation_context,
                FALSE AS postoperative_context,
                regexp_matches(
                    lower(trim(coalesce(arterial.specimen, ''))),
                    'venous|vein|vbg'
                ) AS probable_venous_specimen,
                coalesce(
                    arterial.source_record_hash IS NOT NULL
                    AND (
                        NOT coalesce(arterial.unit_usable, FALSE)
                        OR NOT coalesce(arterial.plausible_value, FALSE)
                    ),
                    FALSE
                ) AS implausible_value,
                coalesce(
                    year_of_birth IS NOT NULL
                    AND age_at_index >= {study.adult_age_min}
                    AND upper(trim(encounter.type)) IN ({encounter_types})
                    AND ({start_condition})
                    AND ({end_condition}),
                    FALSE
                ) AS index_encounter_eligible,
                CASE
                    WHEN year_of_birth IS NULL THEN 'excluded'
                    WHEN age_at_index < {study.adult_age_min} THEN 'excluded'
                    WHEN upper(trim(encounter.type)) NOT IN ({encounter_types})
                    THEN 'excluded'
                    WHEN NOT ({start_condition}) OR NOT ({end_condition})
                    THEN 'excluded'
                    WHEN arterial.encounter_id IS NULL THEN 'excluded'
                    WHEN NOT coalesce(arterial.unit_usable, FALSE) THEN 'excluded'
                    WHEN NOT coalesce(arterial.plausible_value, FALSE) THEN 'excluded'
                    WHEN arterial.normalized_numeric_value <= {pco2_threshold}
                    THEN 'excluded'
                    WHEN arterial.paired_ph_value IS NULL THEN 'excluded'
                    WHEN arterial.paired_ph_value > {hypercapnia.ph_max}
                    THEN 'excluded'
                    ELSE 'included'
                END AS primary_cohort_status,
                CASE
                    WHEN year_of_birth IS NULL THEN 'missing_age'
                    WHEN age_at_index < {study.adult_age_min} THEN 'age_under_minimum'
                    WHEN upper(trim(encounter.type)) NOT IN ({encounter_types})
                    THEN 'encounter_type_out_of_scope'
                    WHEN NOT ({start_condition}) OR NOT ({end_condition})
                    THEN 'outside_study_period'
                    WHEN arterial.encounter_id IS NULL THEN 'no_arterial_pco2'
                    WHEN NOT coalesce(arterial.unit_usable, FALSE)
                    THEN 'first_arterial_pco2_unit_unusable'
                    WHEN NOT coalesce(arterial.plausible_value, FALSE)
                    THEN 'first_arterial_pco2_implausible'
                    WHEN arterial.normalized_numeric_value <= {pco2_threshold}
                    THEN 'first_arterial_pco2_not_elevated'
                    WHEN arterial.paired_ph_value IS NULL THEN 'missing_paired_ph'
                    WHEN arterial.paired_ph_value > {hypercapnia.ph_max}
                    THEN 'paired_ph_above_maximum'
                    ELSE NULL
                END AS primary_cohort_exclusion_reason
            FROM glp1_encounter AS encounter
            LEFT JOIN glp1_patient AS patient USING (patient_id)
            LEFT JOIN arterial_with_ph AS arterial USING (patient_id, encounter_id)
            LEFT JOIN arterial_supplemental AS supplemental
              ON supplemental.reference_source_record_hash =
                 arterial.source_record_hash
            LEFT JOIN arterial_pco2_max AS maximum USING (encounter_id)
            LEFT JOIN first_venous_pco2 AS venous USING (patient_id, encounter_id)
            WHERE arterial.source_record_hash IS NOT NULL
               OR (
                    {include_vbg}
                    AND venous.unit_usable
                    AND venous.plausible_value
                    AND venous.normalized_numeric_value > {pco2_threshold}
               )
        ), first_primary AS (
            SELECT patient_id, index_event_id
            FROM candidate
            WHERE primary_cohort_status = 'included'
            QUALIFY row_number() OVER (
                PARTITION BY patient_id
                ORDER BY encounter_start, index_event_id
            ) = 1
        )
        SELECT
            candidate.*,
            candidate.index_event_id = first_primary.index_event_id
                AS is_first_patient_index_event
        FROM candidate
        LEFT JOIN first_primary USING (patient_id)
        """
    )


def _build_patient_index(
    connection: duckdb.DuckDBPyConnection, config: GLP1Config
) -> None:
    minimum, maximum = config.hypercapnia.repeat_window_days
    threshold = config.hypercapnia.pco2_gt_mm_hg
    connection.execute(
        f"""
        CREATE OR REPLACE TABLE cohort_hypercapnia_patient_index AS
        SELECT
            cohort.*,
            repeat.event_datetime AS repeat_pco2_date,
            repeat.concept_set_id AS repeat_pco2_type,
            repeat.normalized_numeric_value AS repeat_pco2_value,
            coalesce(repeat.normalized_numeric_value > {threshold}, FALSE)
                AS persistent_hypercapnia_14_84d
        FROM cohort_hypercapnia_encounter AS cohort
        LEFT JOIN LATERAL (
            SELECT gas.*
            FROM normalized_gas_measurement AS gas
            WHERE gas.patient_id = cohort.patient_id
              AND gas.concept_set_id = 'arterial_pco2'
              AND gas.unit_usable
              AND gas.plausible_value
              AND gas.normalized_numeric_value > {threshold}
              AND (
                    (
                        gas.timestamp_precision = 'date_only'
                        AND gas.event_datetime::DATE >=
                            (cohort.index_date::DATE + INTERVAL {minimum} DAY)::DATE
                        AND gas.event_datetime::DATE <=
                            (cohort.index_date::DATE + INTERVAL {maximum} DAY)::DATE
                    )
                    OR (
                        gas.timestamp_precision <> 'date_only'
                        AND gas.event_datetime >=
                            cohort.index_date + INTERVAL {minimum} DAY
                        AND gas.event_datetime <=
                            cohort.index_date + INTERVAL {maximum} DAY
                    )
              )
            ORDER BY gas.event_datetime, gas.source_record_hash
            LIMIT 1
        ) AS repeat ON TRUE
        WHERE cohort.primary_cohort_status = 'included'
          AND cohort.is_first_patient_index_event
        """
    )


def _build_normalized_anthropometrics(
    connection: duckdb.DuckDBPyConnection, config: GLP1Config
) -> None:
    obesity = config.obesity
    connection.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE normalized_anthropometric AS
        WITH matched AS (
            SELECT
                vital.*,
                concept.concept_set_id,
                try_cast(vital.value AS DOUBLE) AS raw_numeric_value,
                lower(trim(coalesce(vital.units_of_measure, ''))) AS unit_key
            FROM source_vital_measurement AS vital
            JOIN concept_set AS concept
              ON concept.domain = 'vital'
             AND concept.include
             AND concept.concept_set_id IN ('bmi', 'height', 'weight')
             AND regexp_replace(
                    upper(trim(vital.code_system)), '[^A-Z0-9]', '', 'g'
                 ) = concept.code_system
             AND (
                    (concept.match_type = 'exact'
                     AND upper(trim(vital.code)) = concept.code)
                 OR (concept.match_type = 'prefix'
                     AND starts_with(upper(trim(vital.code)), concept.code))
             )
        )
        SELECT
            *,
            CASE
                WHEN concept_set_id = 'bmi'
                     AND unit_key IN (
                         'kg/m2', 'kg/m^2', 'kg/m²', 'kg per m2', 'kg/meter2'
                     )
                THEN raw_numeric_value
                WHEN concept_set_id = 'weight'
                     AND unit_key IN ('kg', 'kilogram', 'kilograms')
                THEN raw_numeric_value
                WHEN concept_set_id = 'weight'
                     AND unit_key IN ('lb', 'lbs', 'pound', 'pounds')
                THEN raw_numeric_value * 0.45359237
                WHEN concept_set_id = 'height'
                     AND unit_key IN ('m', 'meter', 'meters')
                THEN raw_numeric_value
                WHEN concept_set_id = 'height'
                     AND unit_key IN ('cm', 'centimeter', 'centimeters')
                THEN raw_numeric_value / 100.0
                WHEN concept_set_id = 'height'
                     AND unit_key IN ('in', 'inch', 'inches')
                THEN raw_numeric_value * 0.0254
                ELSE NULL
            END AS normalized_numeric_value,
            CASE
                WHEN concept_set_id = 'bmi' THEN 'kg/m2'
                WHEN concept_set_id = 'weight' THEN 'kg'
                WHEN concept_set_id = 'height' THEN 'm'
            END AS normalized_unit,
            CASE
                WHEN concept_set_id = 'bmi' THEN
                    normalized_numeric_value BETWEEN {obesity.bmi_min_kg_m2}
                        AND {obesity.bmi_max_kg_m2}
                WHEN concept_set_id = 'weight' THEN
                    normalized_numeric_value BETWEEN {obesity.weight_min_kg}
                        AND {obesity.weight_max_kg}
                WHEN concept_set_id = 'height' THEN
                    normalized_numeric_value BETWEEN {obesity.height_min_m}
                        AND {obesity.height_max_m}
                ELSE FALSE
            END AS plausible_value
        FROM matched
        """
    )
    connection.execute(
        """
        CREATE OR REPLACE TEMP TABLE calculated_bmi AS
        SELECT
            weight.patient_id,
            weight.encounter_id,
            greatest(weight.event_datetime, height.event_datetime) AS event_datetime,
            weight.normalized_numeric_value
                / power(height.normalized_numeric_value, 2) AS bmi_value,
            weight.normalized_numeric_value AS weight_kg,
            height.normalized_numeric_value AS height_m,
            weight.source_record_hash || ':' || height.source_record_hash
                AS source_record_hash,
            weight.source_file || ';' || height.source_file AS source_file
        FROM normalized_anthropometric AS weight
        JOIN normalized_anthropometric AS height
          ON height.patient_id = weight.patient_id
         AND coalesce(height.encounter_id, '') = coalesce(weight.encounter_id, '')
         AND abs(datediff(
             'hour', weight.event_datetime, height.event_datetime
         )) <= 24
        WHERE weight.concept_set_id = 'weight' AND weight.plausible_value
          AND height.concept_set_id = 'height' AND height.plausible_value
          AND weight.normalized_numeric_value
                / power(height.normalized_numeric_value, 2)
              BETWEEN 10 AND 100
        QUALIFY row_number() OVER (
            PARTITION BY weight.source_record_hash
            ORDER BY abs(datediff(
                'second', weight.event_datetime, height.event_datetime
            )), height.source_record_hash
        ) = 1
        """
    )


def _build_analysis_table(
    connection: duckdb.DuckDBPyConnection,
    config: GLP1Config,
    git_sha: str,
) -> None:
    obesity = config.obesity
    fallback = str(obesity.same_encounter_fallback).upper()
    connection.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE bmi_candidate AS
        SELECT
            cohort.index_event_id,
            bmi.event_datetime AS bmi_datetime,
            bmi.normalized_numeric_value AS bmi_value,
            'measured_pre_index' AS bmi_source,
            bmi.units_of_measure AS bmi_raw_unit,
            NULL::DOUBLE AS height_m,
            NULL::DOUBLE AS weight_kg,
            bmi.source_file,
            bmi.source_record_hash,
            1 AS source_rank
        FROM cohort_hypercapnia_patient_index AS cohort
        JOIN normalized_anthropometric AS bmi
          ON bmi.patient_id = cohort.patient_id
         AND bmi.concept_set_id = 'bmi'
         AND bmi.plausible_value
         AND bmi.event_datetime BETWEEN
             cohort.index_date - INTERVAL {obesity.bmi_pre_index_days} DAY
             AND cohort.index_date
        UNION ALL
        SELECT
            cohort.index_event_id,
            calculated.event_datetime,
            calculated.bmi_value,
            'calculated_height_weight',
            'calculated',
            calculated.height_m,
            calculated.weight_kg,
            calculated.source_file,
            calculated.source_record_hash,
            2
        FROM cohort_hypercapnia_patient_index AS cohort
        JOIN calculated_bmi AS calculated
          ON calculated.patient_id = cohort.patient_id
         AND calculated.event_datetime BETWEEN
             cohort.index_date - INTERVAL {obesity.bmi_pre_index_days} DAY
             AND cohort.index_date
        UNION ALL
        SELECT
            cohort.index_event_id,
            bmi.event_datetime,
            bmi.normalized_numeric_value,
            'measured_index_encounter',
            bmi.units_of_measure,
            NULL::DOUBLE,
            NULL::DOUBLE,
            bmi.source_file,
            bmi.source_record_hash,
            3
        FROM cohort_hypercapnia_patient_index AS cohort
        JOIN normalized_anthropometric AS bmi
          ON bmi.patient_id = cohort.patient_id
         AND bmi.encounter_id = cohort.encounter_id
         AND bmi.concept_set_id = 'bmi'
         AND bmi.plausible_value
         AND bmi.event_datetime > cohort.index_date
         AND bmi.event_datetime <= coalesce(
                cohort.encounter_end,
                cohort.index_date + INTERVAL 1 DAY
             )
        WHERE {fallback}
        """
    )
    connection.execute(
        f"""
        CREATE OR REPLACE TABLE analysis_glp1_eligibility AS
        WITH selected_bmi AS (
            SELECT * EXCLUDE (selection_order, source_rank)
            FROM (
                SELECT
                    candidate.*,
                    row_number() OVER (
                        PARTITION BY candidate.index_event_id
                        ORDER BY candidate.source_rank,
                                 abs(datediff(
                                     'second', candidate.bmi_datetime,
                                     cohort.index_date
                                 )),
                                 candidate.source_record_hash
                    ) AS selection_order
                FROM bmi_candidate AS candidate
                JOIN cohort_hypercapnia_patient_index AS cohort
                  USING (index_event_id)
            )
            WHERE selection_order = 1
        )
        SELECT
            cohort.run_id,
            cohort.index_event_id,
            cohort.patient_id,
            cohort.encounter_id,
            cohort.index_date,
            cohort.encounter_start,
            cohort.encounter_end,
            cohort.encounter_type,
            cohort.age_at_index,
            cohort.sex,
            cohort.race,
            cohort.ethnicity,
            cohort.patient_regional_location,
            NULL::VARCHAR AS source_hco,
            cohort.month_year_death AS death_year_month,
            cohort.abg_datetime,
            cohort.abg_pco2_mm_hg,
            cohort.abg_ph,
            cohort.abg_hco3,
            cohort.abg_po2,
            cohort.abg_sao2,
            cohort.abg_pco2_code,
            cohort.abg_ph_code,
            cohort.abg_pairing_method,
            cohort.abg_pairing_quality,
            cohort.hypercapnia_gt45,
            cohort.hypercapnia_ge50,
            cohort.hypercapnia_ge52,
            cohort.acute_acidemia,
            cohort.compensated_hypercapnia,
            cohort.persistent_hypercapnia_14_84d,
            cohort.primary_cohort_status,
            cohort.cardiac_arrest_context,
            cohort.major_trauma_context,
            cohort.procedure_sedation_context,
            cohort.postoperative_context,
            cohort.probable_venous_specimen,
            cohort.implausible_value,
            bmi.bmi_value,
            bmi.bmi_datetime,
            bmi.bmi_source,
            bmi.bmi_raw_unit,
            datediff('day', cohort.index_date, bmi.bmi_datetime)
                AS bmi_days_from_index,
            bmi.bmi_value IS NOT NULL AS bmi_valid,
            CASE WHEN bmi.bmi_value IS NULL THEN NULL
                 ELSE bmi.bmi_value >= 27 END AS bmi_ge27,
            CASE WHEN bmi.bmi_value IS NULL THEN NULL
                 ELSE bmi.bmi_value >= 30 END AS bmi_ge30,
            CASE WHEN bmi.bmi_value IS NULL THEN NULL
                 ELSE bmi.bmi_value >= 35 END AS bmi_ge35,
            CASE WHEN bmi.bmi_value IS NULL THEN NULL
                 ELSE bmi.bmi_value >= 40 END AS bmi_ge40,
            CASE
                WHEN bmi.bmi_value IS NULL THEN NULL
                WHEN bmi.bmi_value >= 40 THEN 'class_III'
                WHEN bmi.bmi_value >= 35 THEN 'class_II'
                WHEN bmi.bmi_value >= 30 THEN 'class_I'
                ELSE 'not_obese'
            END AS obesity_class,
            bmi.height_m,
            bmi.weight_kg,
            CASE
                WHEN bmi.bmi_value IS NULL THEN 'indeterminate'
                WHEN bmi.bmi_value >= 30 THEN 'met'
                ELSE 'not_met'
            END AS obesity_status,
            CASE
                WHEN bmi.bmi_value IS NULL THEN 'not_applicable'
                ELSE 'strict'
            END AS obesity_certainty,
            cohort.abg_ph IS NOT NULL AS has_valid_abg_pair,
            bmi.bmi_value IS NOT NULL AS has_valid_bmi,
            {_sql_string(config.rule_set_version)} AS rule_set_version,
            {_sql_string(git_sha)} AS pipeline_git_sha,
            bmi.source_file AS bmi_source_file,
            bmi.source_record_hash AS bmi_source_record_hash,
            cohort.abg_source_file,
            cohort.abg_source_record_hash
        FROM cohort_hypercapnia_patient_index AS cohort
        LEFT JOIN selected_bmi AS bmi USING (index_event_id)
        """
    )


def _build_evidence_table(
    connection: duckdb.DuckDBPyConnection, run_id: str
) -> None:
    connection.execute(
        f"""
        CREATE OR REPLACE TABLE eligibility_evidence_long AS
        SELECT
            {_sql_string(run_id)} AS run_id,
            analysis.index_event_id,
            analysis.patient_id,
            'primary_hypercapnia' AS rule_id,
            'cohort' AS evidence_tier,
            'hypercapnia' AS phenotype,
            'first_available_arterial_pco2' AS component,
            'met' AS status,
            'strict' AS certainty,
            analysis.abg_datetime AS event_date,
            'lab' AS source_domain,
            'source_lab_measurement' AS source_table,
            analysis.abg_source_file AS source_file,
            analysis.abg_source_record_hash AS source_record_hash,
            analysis.encounter_id AS source_encounter_id,
            'LOINC' AS code_system,
            analysis.abg_pco2_code AS code,
            'Arterial PCO2' AS code_description,
            analysis.abg_pco2_mm_hg AS raw_numeric_value,
            NULL::VARCHAR AS raw_text_value,
            'mm Hg' AS raw_unit,
            analysis.abg_pco2_mm_hg AS normalized_numeric_value,
            'mm Hg' AS normalized_unit,
            datediff('day', analysis.index_date, analysis.abg_datetime)
                AS days_from_index,
            analysis.abg_datetime <= analysis.index_date AS is_pre_index,
            1 AS evidence_rank,
            json_object('pairing_method', analysis.abg_pairing_method)
                AS provenance_json
        FROM analysis_glp1_eligibility AS analysis
        UNION ALL
        SELECT
            {_sql_string(run_id)},
            analysis.index_event_id,
            analysis.patient_id,
            'measured_obesity',
            'component',
            'obesity',
            'bmi',
            analysis.obesity_status,
            analysis.obesity_certainty,
            analysis.bmi_datetime,
            'vital',
            'source_vital_measurement',
            analysis.bmi_source_file,
            analysis.bmi_source_record_hash,
            analysis.encounter_id,
            'LOINC',
            '39156-5',
            'Body mass index',
            analysis.bmi_value,
            NULL::VARCHAR,
            analysis.bmi_raw_unit,
            analysis.bmi_value,
            'kg/m2',
            analysis.bmi_days_from_index,
            analysis.bmi_days_from_index <= 0,
            1,
            json_object('bmi_source', analysis.bmi_source)
        FROM analysis_glp1_eligibility AS analysis
        WHERE analysis.bmi_value IS NOT NULL
        """
    )


def _build_views(
    connection: duckdb.DuckDBPyConnection,
    config: GLP1Config,
) -> None:
    cleaned_conditions = "\n          AND ".join(
        f"NOT coalesce({column}, FALSE)"
        for column in config.exclusions.cleaned_view_excludes
    )
    cleaned_filter = (
        f"\n          AND {cleaned_conditions}" if cleaned_conditions else ""
    )
    connection.execute(
        f"""
        CREATE OR REPLACE VIEW analysis_primary_obesity_hypercapnia AS
        SELECT * EXCLUDE (
            bmi_source_file, bmi_source_record_hash,
            abg_source_file, abg_source_record_hash
        )
        FROM analysis_glp1_eligibility
        WHERE primary_cohort_status = 'included' AND bmi_ge30
        ;

        CREATE OR REPLACE VIEW analysis_primary_cleaned_obesity_hypercapnia AS
        SELECT *
        FROM analysis_primary_obesity_hypercapnia
        WHERE TRUE{cleaned_filter}
        """
    )


def build_cohort_flow(
    connection: duckdb.DuckDBPyConnection,
    config: GLP1Config,
) -> None:
    """Publish the complete endpoint cohort-flow contract after phenotyping."""

    context_filter = " AND ".join(
        f"NOT coalesce({column}, FALSE)"
        for column in config.exclusions.cleaned_view_excludes
    )
    context_filter = context_filter or "TRUE"
    connection.execute(
        f"""
        CREATE OR REPLACE TABLE cohort_flow AS
        WITH stages AS (
            SELECT base.stage_order,
                   CASE base.stage_order
                       WHEN 1 THEN 'source_patients'
                       ELSE 'adult_candidate_emergency_inpatient_encounters'
                   END AS stage,
                   base.row_count,
                   base.unique_patient_count,
                   CASE base.stage_order
                       WHEN 1 THEN 'all source patients'
                       ELSE 'age, encounter type, or study-period restriction'
                   END AS reason_for_loss
            FROM source_cohort_flow_base AS base
            UNION ALL
            SELECT 3, 'arterial_pco2_first_24h', count(*),
                   count(DISTINCT patient_id),
                   'no arterial PaCO2 in first 24 hours'
            FROM cohort_hypercapnia_encounter
            WHERE index_encounter_eligible
              AND first_arterial_pco2_in_window
            UNION ALL
            SELECT 4, 'valid_arterial_pco2_units', count(*),
                   count(DISTINCT patient_id),
                   'missing, incompatible, or nonnumeric PaCO2 value/unit'
            FROM cohort_hypercapnia_encounter
            WHERE index_encounter_eligible
              AND first_arterial_pco2_in_window
              AND abg_pco2_unit_usable
            UNION ALL
            SELECT 5, 'paired_ph', count(*), count(DISTINCT patient_id),
                   'no valid paired arterial pH'
            FROM cohort_hypercapnia_encounter
            WHERE index_encounter_eligible
              AND first_arterial_pco2_in_window
              AND abg_pco2_unit_usable
              AND abg_ph_available
            UNION ALL
            SELECT 6, 'first_pco2_gt45_ph_le7_45', count(*),
                   count(DISTINCT patient_id),
                   'first PaCO2 not elevated, implausible, or pH above 7.45'
            FROM cohort_hypercapnia_encounter
            WHERE primary_cohort_status = 'included'
            UNION ALL
            SELECT 7, 'post_context_exclusions', count(*),
                   count(DISTINCT patient_id),
                   'cardiac arrest, trauma, procedure, specimen, or value context'
            FROM cohort_hypercapnia_encounter
            WHERE primary_cohort_status = 'included' AND {context_filter}
            UNION ALL
            SELECT 8, 'unique_patients', count(*), count(*),
                   'later qualifying encounter for the same patient'
            FROM analysis_glp1_eligibility
            WHERE primary_cohort_status = 'included' AND {context_filter}
            UNION ALL
            SELECT 9, 'valid_bmi', count(*), count(*),
                   'no valid measured or calculated BMI'
            FROM analysis_glp1_eligibility
            WHERE primary_cohort_status = 'included' AND {context_filter}
              AND bmi_valid
            UNION ALL
            SELECT 10, 'bmi_ge30', count(*), count(*),
                   'BMI below 30 kg/m2'
            FROM analysis_glp1_eligibility
            WHERE primary_cohort_status = 'included' AND {context_filter}
              AND bmi_ge30
            UNION ALL
            SELECT 11, 'disease_specific_fda_documented', count(*), count(*),
                   'no disease-specific FDA indication documented'
            FROM analysis_glp1_eligibility
            WHERE primary_cohort_status = 'included' AND {context_filter}
              AND bmi_ge30 AND ind_fda_disease_specific_any
            UNION ALL
            SELECT 12, 'guideline_society_documented', count(*), count(*),
                   'no configured guideline/society phenotype documented'
            FROM analysis_glp1_eligibility
            WHERE primary_cohort_status = 'included' AND {context_filter}
              AND bmi_ge30 AND ind_guideline_any
            UNION ALL
            SELECT 13, 'rct_supported_documented', count(*), count(*),
                   'no configured RCT-supported phenotype documented'
            FROM analysis_glp1_eligibility
            WHERE primary_cohort_status = 'included' AND {context_filter}
              AND bmi_ge30 AND ind_rct_any
            UNION ALL
            SELECT 14, 'existing_glp1_order', count(*), count(*),
                   'no GLP-1 order before index'
            FROM analysis_glp1_eligibility
            WHERE primary_cohort_status = 'included' AND {context_filter}
              AND bmi_ge30 AND glp1_ever_ordered_pre_index
            UNION ALL
            SELECT 15, 'payer_route_categories', count(*), count(*),
                   'modeled payer route assigned for BMI >=30 denominator'
            FROM analysis_glp1_eligibility
            WHERE primary_cohort_status = 'included' AND {context_filter}
              AND bmi_ge30 AND payer_route_model IS NOT NULL
        ), measured AS (
            SELECT
                *,
                lag(row_count) OVER (ORDER BY stage_order) AS previous_count,
                first_value(row_count) OVER (ORDER BY stage_order) AS source_count
            FROM stages
        )
        SELECT
            stage_order,
            stage,
            row_count,
            unique_patient_count,
            CASE WHEN previous_count IS NULL OR previous_count = 0 THEN NULL
                 ELSE 100.0 * row_count / previous_count END
                AS percent_of_previous_stage,
            CASE WHEN source_count = 0 THEN NULL
                 ELSE 100.0 * row_count / source_count END
                AS percent_of_source_cohort,
            reason_for_loss
        FROM measured
        ORDER BY stage_order
        """
    )


def _count(connection: duckdb.DuckDBPyConnection, table: str) -> int:
    return int(connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])


def _sql_string(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"

"""Canonical phenotype statuses and GLP-1 eligibility tier derivation."""

from __future__ import annotations

import duckdb

from .config import GLP1Config
from .phenotype_sources import build_component_source_summaries


def build_eligibility_phenotypes(
    connection: duckdb.DuckDBPyConnection,
    config: GLP1Config,
) -> None:
    """Add component, indication, payer-route, and exposure fields."""

    build_component_source_summaries(connection, config)
    _build_wide_analysis(connection)
    _append_component_evidence(connection)
    _replace_primary_view(connection)


def _build_wide_analysis(connection: duckdb.DuckDBPyConnection) -> None:
    diagnosis_columns = _table_columns(connection, "diagnosis_component_summary")
    procedure_columns = _table_columns(connection, "procedure_component_summary")

    def dx(name: str) -> str:
        if name not in diagnosis_columns:
            return "FALSE"
        return f"coalesce(diagnosis.{name}, FALSE)"

    def procedure(name: str) -> str:
        if name not in procedure_columns:
            return "FALSE"
        return f"coalesce(procedure.{name}, FALSE)"

    connection.execute(
        """
        CREATE OR REPLACE TEMP MACRO glp1_status(flag) AS
            CASE WHEN flag THEN 'met' ELSE 'indeterminate' END
        """
    )

    connection.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE glp1_component_feature AS
        SELECT
            analysis.index_event_id,
            {dx('type_2_diabetes')} AS dx_t2d,
            {dx('prediabetes')} AS dx_prediabetes,
            {dx('prior_mi')} AS dx_prior_mi,
            {dx('ischemic_stroke')} AS dx_ischemic_stroke,
            {dx('pad')} AS dx_pad,
            {dx('symptomatic_pad')} AS dx_symptomatic_pad,
            {dx('ckd_any')} AS dx_ckd_any,
            {dx('ckd_stage_3a_plus')} AS dx_ckd_stage_3a_plus,
            {dx('eskd')} AS dx_eskd,
            {dx('obstructive_sleep_apnea')} AS dx_osa,
            {dx('mash')} AS dx_mash,
            {dx('masld')} AS dx_masld,
            {dx('liver_fibrosis')} AS dx_liver_fibrosis,
            {dx('cirrhosis')} AS dx_cirrhosis,
            {dx('heart_failure')} AS dx_heart_failure,
            {dx('hfpef')} AS dx_hfpef,
            {dx('hypertension')} AS dx_hypertension,
            {dx('ohs')} AS dx_ohs,
            {dx('pcos')} AS dx_pcos,
            {dx('knee_osteoarthritis')} AS dx_knee_oa,
            {dx('alcohol_use_disorder')} AS dx_aud,
            {dx('iih')} AS dx_iih,
            {dx('binge_eating')} AS dx_binge_eating,
            {dx('metabolic_syndrome')} AS dx_metabolic_syndrome,
            {dx('dyslipidemia')} AS dx_dyslipidemia,
            ({dx('copd')} OR {dx('emphysema')}) AS dx_copd,
            {dx('asthma')} AS dx_asthma,
            {dx('neuromuscular_disease')} AS dx_neuromuscular,
            {dx('chest_wall_disease')} AS dx_chest_wall,
            {dx('pneumonia_lri')} AS dx_pneumonia_lri,
            {procedure('polysomnography')} AS proc_polysomnography,
            {procedure('home_sleep_apnea_test')} AS proc_hsat,
            {procedure('pap_titration')} AS proc_pap,
            {procedure('echocardiography')} AS proc_echo,
            {procedure('liver_biopsy')} AS proc_liver_biopsy,
            {procedure('transient_elastography')} AS proc_elastography,
            {procedure('invasive_ventilation')} AS proc_invasive_ventilation,
            {procedure('dialysis')} AS proc_dialysis,
            {procedure('bariatric_surgery')} AS proc_bariatric,
            {procedure('lower_extremity_revascularization')}
                AS proc_lower_revascularization,
            lab.a1c_latest,
            lab.a1c_latest_date,
            coalesce(lab.diabetes_range_a1c_dates, 0)
                AS diabetes_range_a1c_dates,
            lab.egfr_latest,
            lab.egfr_latest_date,
            lab.egfr_minimum,
            lab.egfr_low_first_date,
            lab.egfr_low_last_date,
            lab.uacr_latest,
            lab.ahi_rei_value,
            lab.ahi_rei_date,
            lab.lvef,
            lab.lvef_date,
            lab.bnp_ntprobnp_latest,
            bp.latest_sbp,
            bp.latest_dbp,
            bp.latest_bp_date,
            bp.latest_bp_setting,
            coalesce(medication.active_antihypertensive_ingredient_count, 0)
                AS active_antihypertensive_ingredient_count,
            coalesce(medication.antipsychotic_active, FALSE)
                AS antipsychotic_active,
            coalesce(medication.clozapine_or_olanzapine_active, FALSE)
                AS clozapine_or_olanzapine_active,
            coalesce(medication.opioid_active_at_index, FALSE)
                AS opioid_active_at_index,
            coalesce(medication.benzodiazepine_active_at_index, FALSE)
                AS benzodiazepine_active_at_index,
            coalesce(medication.loop_diuretic_active_at_index, FALSE)
                AS loop_diuretic_active_at_index,
            coalesce(medication.glp1_ever_ordered_pre_index, FALSE)
                AS glp1_ever_ordered_pre_index,
            coalesce(medication.glp1_active_at_index, FALSE)
                AS glp1_active_at_index,
            medication.glp1_first_order_date,
            medication.glp1_last_pre_index_order_date,
            medication.glp1_ingredient_at_index,
            medication.glp1_product_at_index,
            coalesce(medication.glp1_new_order_30d, FALSE) AS glp1_new_order_30d,
            coalesce(medication.glp1_new_order_90d, FALSE) AS glp1_new_order_90d,
            coalesce(medication.glp1_new_order_365d, FALSE)
                AS glp1_new_order_365d
        FROM analysis_glp1_eligibility AS analysis
        LEFT JOIN diagnosis_component_summary AS diagnosis USING (index_event_id)
        LEFT JOIN procedure_component_summary AS procedure USING (index_event_id)
        LEFT JOIN component_lab_summary AS lab USING (index_event_id)
        LEFT JOIN component_bp_summary AS bp USING (index_event_id)
        LEFT JOIN medication_component_summary AS medication USING (index_event_id)
        """
    )
    connection.execute(
        """
        CREATE OR REPLACE TABLE analysis_glp1_eligibility_next AS
        WITH status AS (
            SELECT
                analysis.*,
                feature.* EXCLUDE (index_event_id),
                feature.dx_t2d AS t2d_documented,
                feature.diabetes_range_a1c_dates >= 2 AS t2d_probable,
                CASE
                    WHEN feature.dx_t2d THEN 'met'
                    WHEN feature.diabetes_range_a1c_dates >= 2 THEN 'met'
                    ELSE 'indeterminate'
                END AS t2d_status,
                CASE
                    WHEN feature.dx_t2d THEN 'strict'
                    WHEN feature.diabetes_range_a1c_dates >= 2 THEN 'probable'
                    ELSE 'not_applicable'
                END AS t2d_certainty,
                CASE
                    WHEN feature.dx_t2d OR feature.diabetes_range_a1c_dates >= 2
                    THEN 'not_met'
                    WHEN feature.dx_prediabetes
                         OR feature.a1c_latest BETWEEN 5.7 AND 6.4
                    THEN 'met'
                    WHEN feature.a1c_latest < 5.7 THEN 'not_met'
                    ELSE 'indeterminate'
                END AS prediabetes_status,
                glp1_status(feature.dx_prior_mi) AS prior_mi_status,
                glp1_status(feature.dx_ischemic_stroke)
                    AS prior_ischemic_stroke_status,
                glp1_status(feature.dx_pad) AS pad_status,
                glp1_status(
                    feature.dx_symptomatic_pad
                    OR feature.proc_lower_revascularization
                ) AS symptomatic_pad_status,
                glp1_status(
                    feature.dx_prior_mi OR feature.dx_ischemic_stroke
                    OR feature.dx_pad OR feature.proc_lower_revascularization
                ) AS established_cvd_any_status,
                CASE
                    WHEN feature.egfr_low_first_date IS NOT NULL
                     AND datediff(
                         'day', feature.egfr_low_first_date,
                         feature.egfr_low_last_date
                     ) >= 90 THEN 'met'
                    WHEN feature.dx_ckd_any OR feature.dx_eskd THEN 'met'
                    ELSE 'indeterminate'
                END AS ckd_any_status,
                CASE
                    WHEN feature.dx_eskd THEN 'ESKD'
                    WHEN feature.dx_ckd_stage_3a_plus THEN '3a_plus'
                    ELSE NULL
                END AS ckd_stage,
                CASE
                    WHEN feature.dx_ckd_stage_3a_plus OR feature.dx_eskd
                    THEN 'met'
                    WHEN feature.egfr_low_first_date IS NOT NULL
                     AND datediff(
                         'day', feature.egfr_low_first_date,
                         feature.egfr_low_last_date
                     ) >= 90 THEN 'met'
                    ELSE 'indeterminate'
                END AS ckd_stage_3a_plus_status,
                feature.egfr_low_first_date IS NOT NULL
                    AND datediff(
                        'day', feature.egfr_low_first_date,
                        feature.egfr_low_last_date
                    ) >= 90 AS egfr_persistent_lt60,
                glp1_status(feature.dx_osa) AS osa_any_status,
                CASE
                    WHEN feature.ahi_rei_value >= 15 THEN 'met'
                    WHEN feature.ahi_rei_value < 15 THEN 'not_met'
                    ELSE 'indeterminate'
                END AS osa_moderate_severe_status,
                CASE
                    WHEN feature.ahi_rei_value >= 30 THEN 'severe'
                    WHEN feature.ahi_rei_value >= 15 THEN 'moderate'
                    WHEN feature.ahi_rei_value >= 5 THEN 'mild'
                    WHEN feature.ahi_rei_value IS NOT NULL THEN 'none'
                    ELSE 'indeterminate'
                END AS osa_severity,
                feature.proc_pap AS pap_evidence,
                glp1_status(feature.dx_mash) AS mash_status,
                'indeterminate' AS mash_f2_f3_status,
                'not_applicable' AS mash_f2_f3_certainty,
                NULL::VARCHAR AS fibrosis_stage,
                CASE
                    WHEN feature.proc_liver_biopsy THEN 'biopsy_without_stage'
                    WHEN feature.proc_elastography THEN 'elastography_without_stage'
                    ELSE NULL
                END AS fibrosis_method,
                glp1_status(feature.dx_cirrhosis) AS cirrhosis_status,
                NULL::DOUBLE AS fib4_latest,
                glp1_status(feature.dx_heart_failure) AS heart_failure_status,
                CASE
                    WHEN feature.dx_heart_failure AND feature.lvef >= 50 THEN 'met'
                    WHEN feature.lvef < 50 THEN 'not_met'
                    WHEN feature.dx_hfpef THEN 'met'
                    ELSE 'indeterminate'
                END AS hfpef_status,
                CASE
                    WHEN feature.dx_heart_failure AND feature.lvef >= 50 THEN 'strict'
                    WHEN feature.dx_hfpef THEN 'code_only'
                    ELSE 'not_applicable'
                END AS hfpef_certainty,
                glp1_status(feature.dx_hypertension) AS hypertension_status,
                CASE
                    WHEN feature.latest_sbp IS NULL AND feature.latest_dbp IS NULL
                    THEN 'indeterminate'
                    WHEN (feature.latest_sbp > 140 OR feature.latest_dbp > 90)
                     AND feature.active_antihypertensive_ingredient_count >= 2
                    THEN 'met'
                    ELSE 'not_met'
                END AS uncontrolled_hypertension_two_meds_status,
                glp1_status(feature.dx_ohs) AS ohs_documented_status,
                CASE
                    WHEN analysis.bmi_ge30
                     AND (analysis.compensated_hypercapnia
                          OR analysis.persistent_hypercapnia_14_84d)
                     AND (feature.dx_osa OR feature.proc_polysomnography
                          OR feature.proc_hsat)
                     AND NOT feature.dx_neuromuscular
                     AND NOT feature.dx_chest_wall
                    THEN 'met'
                    ELSE 'indeterminate'
                END AS probable_ohs_status,
                glp1_status(feature.dx_pcos) AS pcos_status,
                glp1_status(feature.dx_knee_oa) AS knee_oa_status,
                glp1_status(feature.dx_aud) AS aud_status,
                glp1_status(feature.dx_iih) AS iih_status,
                glp1_status(feature.dx_binge_eating) AS binge_eating_status,
                CASE
                    WHEN feature.antipsychotic_active
                     AND (analysis.bmi_ge27
                          OR feature.a1c_latest >= 5.7
                          OR feature.dx_metabolic_syndrome)
                    THEN 'met'
                    WHEN feature.antipsychotic_active THEN 'not_met'
                    ELSE 'indeterminate'
                END AS metabolic_dysfunction_status,
                glp1_status(feature.dx_masld) AS masld_status,
                glp1_status(feature.dx_dyslipidemia) AS dyslipidemia_status,
                glp1_status(feature.dx_metabolic_syndrome)
                    AS metabolic_syndrome_status,
                glp1_status(feature.dx_copd) AS copd_status,
                glp1_status(feature.dx_asthma) AS asthma_status,
                glp1_status(feature.dx_neuromuscular)
                    AS neuromuscular_disease_status,
                glp1_status(feature.dx_chest_wall)
                    AS chest_wall_disease_status,
                feature.dx_pneumonia_lri AS pneumonia_lri_at_index,
                feature.dx_heart_failure AS heart_failure_at_index,
                feature.proc_pap AS niv_or_pap_pre_index,
                feature.proc_invasive_ventilation AS invasive_ventilation_at_index,
                feature.proc_bariatric AS bariatric_surgery_history
            FROM analysis_glp1_eligibility AS analysis
            JOIN glp1_component_feature AS feature USING (index_event_id)
        ), indication AS (
            SELECT
                status.*,
                CASE
                    WHEN bmi_ge30 THEN TRUE
                    WHEN bmi_ge27 AND (
                        t2d_status = 'met' OR prediabetes_status = 'met'
                        OR hypertension_status = 'met'
                        OR dyslipidemia_status = 'met'
                        OR osa_any_status = 'met'
                        OR established_cvd_any_status = 'met'
                    ) THEN TRUE
                    WHEN bmi_valid THEN FALSE
                    ELSE NULL
                END AS ind_fda_weight_management,
                CASE WHEN bmi_valid THEN 'strict' ELSE 'not_applicable' END
                    AS ind_fda_weight_management_certainty,
                CASE WHEN t2d_status = 'met' THEN TRUE ELSE NULL END AS ind_fda_t2d,
                CASE WHEN bmi_ge27 AND established_cvd_any_status = 'met'
                     THEN TRUE ELSE NULL END AS ind_fda_obesity_established_cvd,
                CASE WHEN t2d_status = 'met' AND ckd_any_status = 'met'
                     THEN TRUE ELSE NULL END AS ind_fda_t2d_ckd,
                CASE WHEN bmi_ge30 AND osa_moderate_severe_status = 'met'
                     THEN TRUE ELSE NULL END AS ind_fda_moderate_severe_osa,
                CASE WHEN bmi_ge27 AND mash_f2_f3_status = 'met'
                          AND cirrhosis_status != 'met'
                     THEN TRUE ELSE NULL END AS ind_fda_noncirrhotic_mash_f2_f3,
                CASE WHEN bmi_ge30 AND probable_ohs_status = 'met'
                     THEN TRUE ELSE NULL END
                    AS ind_guideline_weight_loss_for_probable_ohs,
                CASE WHEN bmi_ge30 AND hfpef_status = 'met'
                     THEN TRUE ELSE NULL END AS ind_guideline_obesity_related_hfpef,
                CASE WHEN bmi_ge27 AND pcos_status = 'met'
                     THEN TRUE ELSE NULL END
                    AS ind_guideline_pcos_with_overweight_obesity,
                CASE WHEN bmi_ge30 AND hfpef_status = 'met'
                     THEN TRUE ELSE NULL END AS ind_rct_obesity_related_hfpef,
                CASE WHEN t2d_status = 'met' AND symptomatic_pad_status = 'met'
                     THEN TRUE ELSE NULL END AS ind_rct_symptomatic_pad_t2d,
                CASE WHEN bmi_ge30 AND knee_oa_status = 'met'
                     THEN TRUE ELSE NULL END AS ind_rct_knee_oa_obesity,
                CASE WHEN aud_status = 'met' THEN TRUE ELSE NULL END
                    AS ind_rct_alcohol_use_disorder,
                CASE WHEN bmi_ge27 AND iih_status = 'met'
                     THEN TRUE ELSE NULL END
                    AS ind_rct_idiopathic_intracranial_hypertension,
                CASE WHEN metabolic_dysfunction_status = 'met'
                     THEN TRUE ELSE NULL END AS ind_rct_antipsychotic_metabolic,
                CASE WHEN bmi_ge27 AND pcos_status = 'met'
                     THEN TRUE ELSE NULL END AS ind_rct_pcos_obesity
            FROM status
        ), aggregate_tiers AS (
            SELECT
                indication.*,
                coalesce(
                    ind_fda_t2d, ind_fda_obesity_established_cvd,
                    ind_fda_t2d_ckd, ind_fda_moderate_severe_osa,
                    ind_fda_noncirrhotic_mash_f2_f3
                ) AS ind_fda_disease_specific_any,
                cast(coalesce(ind_fda_t2d, FALSE) AS INTEGER)
                    + cast(coalesce(ind_fda_obesity_established_cvd, FALSE) AS INTEGER)
                    + cast(coalesce(ind_fda_t2d_ckd, FALSE) AS INTEGER)
                    + cast(coalesce(ind_fda_moderate_severe_osa, FALSE) AS INTEGER)
                    + cast(coalesce(ind_fda_noncirrhotic_mash_f2_f3, FALSE) AS INTEGER)
                    AS num_fda_indication_groups,
                concat_ws(';',
                    CASE WHEN ind_fda_t2d THEN 't2d' END,
                    CASE WHEN ind_fda_obesity_established_cvd
                         THEN 'obesity_established_cvd' END,
                    CASE WHEN ind_fda_t2d_ckd THEN 't2d_ckd' END,
                    CASE WHEN ind_fda_moderate_severe_osa
                         THEN 'moderate_severe_osa' END,
                    CASE WHEN ind_fda_noncirrhotic_mash_f2_f3
                         THEN 'mash_f2_f3' END
                ) AS fda_indication_group_list,
                coalesce(
                    ind_guideline_weight_loss_for_probable_ohs,
                    ind_guideline_obesity_related_hfpef,
                    ind_guideline_pcos_with_overweight_obesity
                ) AS ind_guideline_any,
                coalesce(
                    ind_rct_obesity_related_hfpef,
                    ind_rct_symptomatic_pad_t2d,
                    ind_rct_knee_oa_obesity,
                    ind_rct_alcohol_use_disorder,
                    ind_rct_idiopathic_intracranial_hypertension,
                    ind_rct_antipsychotic_metabolic,
                    ind_rct_pcos_obesity
                ) AS ind_rct_any
            FROM indication
        )
        SELECT *
        FROM aggregate_tiers
        """
    )
    _add_tier_aggregates_and_routes(connection)
    connection.execute("DROP TABLE analysis_glp1_eligibility")
    connection.execute(
        "ALTER TABLE analysis_glp1_eligibility_next RENAME TO analysis_glp1_eligibility"
    )


def _add_tier_aggregates_and_routes(
    connection: duckdb.DuckDBPyConnection,
) -> None:
    connection.execute(
        """
        ALTER TABLE analysis_glp1_eligibility_next
        ADD COLUMN num_guideline_indication_groups INTEGER DEFAULT 0;
        ALTER TABLE analysis_glp1_eligibility_next
        ADD COLUMN guideline_indication_group_list VARCHAR;
        ALTER TABLE analysis_glp1_eligibility_next
        ADD COLUMN num_rct_indication_groups INTEGER DEFAULT 0;
        ALTER TABLE analysis_glp1_eligibility_next
        ADD COLUMN rct_indication_group_list VARCHAR;
        ALTER TABLE analysis_glp1_eligibility_next
        ADD COLUMN bridge_clinical_criteria_status VARCHAR;
        ALTER TABLE analysis_glp1_eligibility_next
        ADD COLUMN bridge_qualifying_branch VARCHAR;
        ALTER TABLE analysis_glp1_eligibility_next
        ADD COLUMN bridge_qualifying_components VARCHAR;
        ALTER TABLE analysis_glp1_eligibility_next
        ADD COLUMN bridge_certainty VARCHAR;
        ALTER TABLE analysis_glp1_eligibility_next
        ADD COLUMN part_d_disease_route_status VARCHAR;
        ALTER TABLE analysis_glp1_eligibility_next
        ADD COLUMN bridge_partd_exclusion_status VARCHAR;
        ALTER TABLE analysis_glp1_eligibility_next
        ADD COLUMN payer_route_model VARCHAR;
        ALTER TABLE analysis_glp1_eligibility_next
        ADD COLUMN payer_data_available BOOLEAN DEFAULT FALSE;
        ALTER TABLE analysis_glp1_eligibility_next
        ADD COLUMN part_d_enrollment_at_index BOOLEAN;
        ALTER TABLE analysis_glp1_eligibility_next
        ADD COLUMN actual_bridge_eligibility_status VARCHAR;
        ALTER TABLE analysis_glp1_eligibility_next
        ADD COLUMN has_a1c BOOLEAN;
        ALTER TABLE analysis_glp1_eligibility_next
        ADD COLUMN has_egfr_history BOOLEAN;
        ALTER TABLE analysis_glp1_eligibility_next
        ADD COLUMN has_uacr BOOLEAN;
        ALTER TABLE analysis_glp1_eligibility_next
        ADD COLUMN has_ahi_rei BOOLEAN;
        ALTER TABLE analysis_glp1_eligibility_next
        ADD COLUMN has_lvef BOOLEAN;
        ALTER TABLE analysis_glp1_eligibility_next
        ADD COLUMN has_liver_fibrosis_staging BOOLEAN DEFAULT FALSE;
        ALTER TABLE analysis_glp1_eligibility_next
        ADD COLUMN has_medication_history BOOLEAN;
        ALTER TABLE analysis_glp1_eligibility_next
        ADD COLUMN has_payer_data BOOLEAN DEFAULT FALSE;
        ALTER TABLE analysis_glp1_eligibility_next
        ADD COLUMN lookback_observation_days INTEGER;
        ALTER TABLE analysis_glp1_eligibility_next
        ADD COLUMN encounter_count_365d BIGINT;
        ALTER TABLE analysis_glp1_eligibility_next
        ADD COLUMN diagnosis_event_count_730d BIGINT;
        ALTER TABLE analysis_glp1_eligibility_next
        ADD COLUMN lab_event_count_365d BIGINT;
        ALTER TABLE analysis_glp1_eligibility_next
        ADD COLUMN medication_event_count_730d BIGINT;
        ALTER TABLE analysis_glp1_eligibility_next
        ADD COLUMN code_set_version VARCHAR;
        """
    )
    connection.execute(
        """
        UPDATE analysis_glp1_eligibility_next
        SET
            num_guideline_indication_groups =
                cast(coalesce(ind_guideline_weight_loss_for_probable_ohs, FALSE)
                     AS INTEGER)
                + cast(coalesce(ind_guideline_obesity_related_hfpef, FALSE)
                       AS INTEGER)
                + cast(coalesce(ind_guideline_pcos_with_overweight_obesity, FALSE)
                       AS INTEGER),
            guideline_indication_group_list = concat_ws(';',
                CASE WHEN ind_guideline_weight_loss_for_probable_ohs
                     THEN 'probable_ohs' END,
                CASE WHEN ind_guideline_obesity_related_hfpef
                     THEN 'obesity_hfpef' END,
                CASE WHEN ind_guideline_pcos_with_overweight_obesity
                     THEN 'pcos_obesity' END),
            num_rct_indication_groups =
                cast(coalesce(ind_rct_obesity_related_hfpef, FALSE) AS INTEGER)
                + cast(coalesce(ind_rct_symptomatic_pad_t2d, FALSE) AS INTEGER)
                + cast(coalesce(ind_rct_knee_oa_obesity, FALSE) AS INTEGER)
                + cast(coalesce(ind_rct_alcohol_use_disorder, FALSE) AS INTEGER)
                + cast(coalesce(
                    ind_rct_idiopathic_intracranial_hypertension, FALSE
                  ) AS INTEGER)
                + cast(coalesce(ind_rct_antipsychotic_metabolic, FALSE) AS INTEGER)
                + cast(coalesce(ind_rct_pcos_obesity, FALSE) AS INTEGER),
            rct_indication_group_list = concat_ws(';',
                CASE WHEN ind_rct_obesity_related_hfpef THEN 'obesity_hfpef' END,
                CASE WHEN ind_rct_symptomatic_pad_t2d THEN 'symptomatic_pad_t2d' END,
                CASE WHEN ind_rct_knee_oa_obesity THEN 'knee_oa_obesity' END,
                CASE WHEN ind_rct_alcohol_use_disorder THEN 'alcohol_use_disorder' END,
                CASE WHEN ind_rct_idiopathic_intracranial_hypertension
                     THEN 'iih' END,
                CASE WHEN ind_rct_antipsychotic_metabolic
                     THEN 'antipsychotic_metabolic' END,
                CASE WHEN ind_rct_pcos_obesity THEN 'pcos_obesity' END),
            bridge_clinical_criteria_status = CASE
                WHEN bmi_ge35 THEN 'met'
                WHEN bmi_ge30 AND (
                    hfpef_status = 'met'
                    OR uncontrolled_hypertension_two_meds_status = 'met'
                    OR ckd_stage_3a_plus_status = 'met'
                ) THEN 'met'
                WHEN bmi_ge27 AND (
                    prediabetes_status = 'met' OR prior_mi_status = 'met'
                    OR prior_ischemic_stroke_status = 'met'
                    OR symptomatic_pad_status = 'met'
                ) THEN 'met'
                WHEN bmi_valid THEN 'indeterminate'
                ELSE 'indeterminate'
            END,
            bridge_qualifying_branch = CASE
                WHEN bmi_ge35 THEN 'bmi_ge35'
                WHEN bmi_ge30 AND (
                    hfpef_status = 'met'
                    OR uncontrolled_hypertension_two_meds_status = 'met'
                    OR ckd_stage_3a_plus_status = 'met'
                ) THEN 'bmi_ge30_comorbidity'
                WHEN bmi_ge27 AND (
                    prediabetes_status = 'met' OR prior_mi_status = 'met'
                    OR prior_ischemic_stroke_status = 'met'
                    OR symptomatic_pad_status = 'met'
                ) THEN 'bmi_ge27_comorbidity'
            END,
            bridge_qualifying_components = concat_ws(';',
                CASE WHEN hfpef_status = 'met' THEN 'hfpef' END,
                CASE WHEN uncontrolled_hypertension_two_meds_status = 'met'
                     THEN 'uncontrolled_hypertension_two_meds' END,
                CASE WHEN ckd_stage_3a_plus_status = 'met' THEN 'ckd_3a_plus' END,
                CASE WHEN prediabetes_status = 'met' THEN 'prediabetes' END,
                CASE WHEN prior_mi_status = 'met' THEN 'prior_mi' END,
                CASE WHEN prior_ischemic_stroke_status = 'met' THEN 'prior_stroke' END,
                CASE WHEN symptomatic_pad_status = 'met' THEN 'symptomatic_pad' END),
            bridge_certainty = CASE
                WHEN bridge_clinical_criteria_status = 'met' THEN 'strict'
                ELSE 'not_applicable' END,
            part_d_disease_route_status = CASE
                WHEN ind_fda_disease_specific_any THEN 'met'
                ELSE 'indeterminate' END,
            bridge_partd_exclusion_status = CASE
                WHEN ind_fda_disease_specific_any THEN 'met'
                WHEN bridge_clinical_criteria_status = 'met' THEN 'not_met'
                ELSE 'indeterminate' END,
            payer_route_model = CASE
                WHEN ind_fda_disease_specific_any THEN 'part_d_disease_route'
                WHEN bridge_clinical_criteria_status = 'met'
                THEN 'bridge_clinical_route'
                WHEN bridge_clinical_criteria_status = 'indeterminate'
                THEN 'potential_bridge_but_indeterminate'
                WHEN ind_fda_weight_management THEN 'weight_label_only'
                ELSE 'no_documented_route' END,
            has_a1c = a1c_latest IS NOT NULL,
            has_egfr_history = egfr_latest IS NOT NULL,
            has_uacr = uacr_latest IS NOT NULL,
            has_ahi_rei = ahi_rei_value IS NOT NULL,
            has_lvef = lvef IS NOT NULL,
            has_medication_history =
                glp1_ever_ordered_pre_index
                OR active_antihypertensive_ingredient_count > 0,
            code_set_version = rule_set_version
        """
    )


def _append_component_evidence(connection: duckdb.DuckDBPyConnection) -> None:
    connection.execute(
        """
        INSERT INTO eligibility_evidence_long
        SELECT
            analysis.run_id,
            evidence.index_event_id,
            evidence.patient_id,
            evidence.concept_set_id,
            'component',
            evidence.concept_set_id,
            'diagnosis_code',
            'met',
            'code_only',
            evidence.event_datetime,
            'diagnosis',
            'source_diagnosis',
            evidence.source_file,
            evidence.source_record_hash,
            evidence.encounter_id,
            evidence.code_system,
            evidence.code,
            NULL,
            NULL,
            NULL,
            NULL,
            NULL,
            NULL,
            -evidence.days_before_index,
            TRUE,
            1,
            json_object('source', 'diagnosis_component_evidence')
        FROM diagnosis_component_evidence AS evidence
        JOIN analysis_glp1_eligibility AS analysis USING (index_event_id)
        """
    )


def _replace_primary_view(connection: duckdb.DuckDBPyConnection) -> None:
    connection.execute(
        """
        CREATE OR REPLACE VIEW analysis_primary_obesity_hypercapnia AS
        SELECT * EXCLUDE (
            bmi_source_file, bmi_source_record_hash,
            abg_source_file, abg_source_record_hash,
            dx_t2d, dx_prediabetes, dx_prior_mi, dx_ischemic_stroke,
            dx_pad, dx_symptomatic_pad, dx_ckd_any, dx_ckd_stage_3a_plus,
            dx_eskd, dx_osa, dx_mash, dx_masld, dx_liver_fibrosis,
            dx_cirrhosis, dx_heart_failure, dx_hfpef, dx_hypertension,
            dx_ohs, dx_pcos, dx_knee_oa, dx_aud, dx_iih, dx_binge_eating,
            dx_metabolic_syndrome, dx_dyslipidemia, dx_copd, dx_asthma,
            dx_neuromuscular, dx_chest_wall, dx_pneumonia_lri,
            proc_polysomnography, proc_hsat, proc_pap, proc_echo,
            proc_liver_biopsy, proc_elastography, proc_invasive_ventilation,
            proc_dialysis, proc_bariatric, proc_lower_revascularization,
            diabetes_range_a1c_dates, egfr_minimum,
            egfr_low_first_date, egfr_low_last_date,
            loop_diuretic_active_at_index
        )
        FROM analysis_glp1_eligibility
        WHERE primary_cohort_status = 'included' AND bmi_ge30
        """
    )


def _table_columns(
    connection: duckdb.DuckDBPyConnection, table: str
) -> frozenset[str]:
    return frozenset(
        row[0]
        for row in connection.execute(
            """
            SELECT column_name FROM information_schema.columns
            WHERE table_schema = 'main' AND table_name = ?
            """,
            [table],
        ).fetchall()
    )

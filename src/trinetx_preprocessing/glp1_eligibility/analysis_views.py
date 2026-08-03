"""Study-ready aggregate and patient-level analysis views."""

from __future__ import annotations

import duckdb

from .evidence import INDICATION_RULES

MISSINGNESS_FIELDS = (
    "has_valid_abg_pair",
    "has_valid_bmi",
    "has_a1c",
    "has_egfr_history",
    "has_uacr",
    "has_ahi_rei",
    "has_lvef",
    "has_liver_fibrosis_staging",
    "has_medication_history",
    "has_payer_data",
)


def build_analysis_views(connection: duckdb.DuckDBPyConnection) -> None:
    """Create all views required for study summaries and smoke queries."""

    _build_primary_view(connection)
    _build_prevalence_views(connection)
    _build_overlap_view(connection)
    _build_treatment_gap_view(connection)
    _build_missingness_view(connection)


def _build_primary_view(connection: duckdb.DuckDBPyConnection) -> None:
    connection.execute(
        """
        CREATE OR REPLACE VIEW analysis_primary_obesity_hypercapnia AS
        SELECT * EXCLUDE (
            bmi_source_file, bmi_source_record_hash,
            abg_source_file, abg_source_record_hash,
            dx_obesity, dx_t2d, dx_prediabetes, dx_prior_mi, dx_ischemic_stroke,
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
            loop_diuretic_active_at_index,
            context_pneumonia_lri_at_index,
            context_heart_failure_at_index,
            context_invasive_ventilation_at_index
        )
        FROM analysis_glp1_eligibility
        WHERE primary_cohort_status = 'included' AND bmi_ge30
        """
    )


def _build_prevalence_views(connection: duckdb.DuckDBPyConnection) -> None:
    documented = []
    evaluable = []
    for rule in INDICATION_RULES:
        documented.append(
            f"""
            SELECT
                {_sql_string(rule.tier)} AS evidence_tier,
                {_sql_string(rule.phenotype)} AS indication,
                count(*) FILTER (WHERE {rule.column}) AS met_n,
                count(*) AS total_n,
                100.0 * count(*) FILTER (WHERE {rule.column})
                    / nullif(count(*), 0) AS documented_percent
            FROM analysis_primary_obesity_hypercapnia
            """
        )
        evaluable.append(
            f"""
            SELECT
                {_sql_string(rule.tier)} AS evidence_tier,
                {_sql_string(rule.phenotype)} AS indication,
                count(*) FILTER (WHERE {rule.column}) AS met_n,
                count(*) FILTER (WHERE NOT {rule.column}) AS not_met_n,
                count(*) FILTER (WHERE {rule.column} IS NULL) AS indeterminate_n,
                count(*) FILTER (WHERE {rule.column} IS NOT NULL) AS evaluable_n,
                100.0 * count(*) FILTER (WHERE {rule.column})
                    / nullif(
                        count(*) FILTER (WHERE {rule.column} IS NOT NULL), 0
                      ) AS evaluable_percent,
                100.0 * count(*) FILTER (WHERE {rule.column} IS NULL)
                    / nullif(count(*), 0) AS indeterminate_percent
            FROM analysis_primary_obesity_hypercapnia
            """
        )
    connection.execute(
        "CREATE OR REPLACE VIEW analysis_documented_indication_prevalence AS "
        + " UNION ALL ".join(documented)
    )
    connection.execute(
        "CREATE OR REPLACE VIEW analysis_evaluable_indication_prevalence AS "
        + " UNION ALL ".join(evaluable)
    )


def _build_overlap_view(connection: duckdb.DuckDBPyConnection) -> None:
    individual_rules = tuple(
        rule for rule in INDICATION_RULES if not rule.column.endswith("_any")
    )
    membership_values = ",\n                ".join(
        f"CASE WHEN {rule.column} THEN {_sql_string(rule.phenotype)} END"
        for rule in individual_rules
    )
    count_expression = " + ".join(
        f"cast(coalesce({rule.column}, FALSE) AS INTEGER)" for rule in individual_rules
    )
    connection.execute(
        f"""
        CREATE OR REPLACE VIEW analysis_indication_overlap AS
        SELECT
            index_event_id,
            patient_id,
            {count_expression} AS indication_count,
            concat_ws('|',
                {membership_values}
            ) AS indication_membership_key
        FROM analysis_primary_obesity_hypercapnia
        """
    )


def _build_treatment_gap_view(connection: duckdb.DuckDBPyConnection) -> None:
    connection.execute(
        """
        CREATE OR REPLACE VIEW analysis_treatment_gap AS
        SELECT
            index_event_id,
            patient_id,
            ind_fda_disease_specific_any,
            ind_guideline_any,
            ind_rct_any,
            payer_route_model,
            glp1_ever_ordered_pre_index,
            glp1_active_at_index,
            coalesce(ind_fda_disease_specific_any, FALSE)
                AND NOT glp1_ever_ordered_pre_index AS disease_eligible_without_order
        FROM analysis_primary_obesity_hypercapnia
        """
    )


def _build_missingness_view(connection: duckdb.DuckDBPyConnection) -> None:
    selects = [
        f"""
        SELECT
            {_sql_string(field)} AS field,
            count(*) FILTER (WHERE coalesce({field}, FALSE)) AS observed_n,
            count(*) FILTER (WHERE NOT coalesce({field}, FALSE)) AS missing_n,
            count(*) AS total_n,
            100.0 * count(*) FILTER (WHERE NOT coalesce({field}, FALSE))
                / nullif(count(*), 0) AS missing_percent
        FROM analysis_primary_obesity_hypercapnia
        """
        for field in MISSINGNESS_FIELDS
    ]
    connection.execute(
        "CREATE OR REPLACE VIEW analysis_missingness AS " + " UNION ALL ".join(selects)
    )


def _sql_string(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"

"""Long-form source and derived evidence for GLP-1 eligibility rules."""

from __future__ import annotations

from dataclasses import dataclass

import duckdb

EVIDENCE_COLUMNS = (
    "run_id",
    "index_event_id",
    "patient_id",
    "rule_id",
    "evidence_tier",
    "phenotype",
    "component",
    "status",
    "certainty",
    "event_date",
    "source_domain",
    "source_table",
    "source_file",
    "source_record_hash",
    "source_encounter_id",
    "code_system",
    "code",
    "code_description",
    "raw_numeric_value",
    "raw_text_value",
    "raw_unit",
    "normalized_numeric_value",
    "normalized_unit",
    "days_from_index",
    "is_pre_index",
    "evidence_rank",
    "provenance_json",
)


@dataclass(frozen=True)
class StatusRule:
    """Map one canonical wide status to its long-form rule row."""

    column: str
    phenotype: str
    certainty_sql: str


@dataclass(frozen=True)
class IndicationRule:
    """Map one nullable indication flag to its long-form rule row."""

    column: str
    tier: str
    phenotype: str


DEFAULT_CERTAINTY = (
    "CASE WHEN {status} IN ('met', 'not_met') THEN 'strict' ELSE 'not_applicable' END"
)
CODE_CERTAINTY = "CASE WHEN {status} = 'met' THEN 'code_only' ELSE 'not_applicable' END"
PROBABLE_CERTAINTY = (
    "CASE WHEN {status} = 'met' THEN 'probable' ELSE 'not_applicable' END"
)


STATUS_RULES = (
    StatusRule("obesity_status", "obesity", "obesity_certainty"),
    StatusRule("t2d_status", "type_2_diabetes", "t2d_certainty"),
    StatusRule("prediabetes_status", "prediabetes", DEFAULT_CERTAINTY),
    StatusRule("prior_mi_status", "prior_mi", CODE_CERTAINTY),
    StatusRule("prior_ischemic_stroke_status", "prior_ischemic_stroke", CODE_CERTAINTY),
    StatusRule("pad_status", "peripheral_artery_disease", CODE_CERTAINTY),
    StatusRule("symptomatic_pad_status", "symptomatic_pad", CODE_CERTAINTY),
    StatusRule("established_cvd_any_status", "established_cvd", CODE_CERTAINTY),
    StatusRule("ckd_any_status", "chronic_kidney_disease", DEFAULT_CERTAINTY),
    StatusRule("ckd_stage_3a_plus_status", "ckd_stage_3a_plus", DEFAULT_CERTAINTY),
    StatusRule("osa_any_status", "obstructive_sleep_apnea", CODE_CERTAINTY),
    StatusRule("osa_moderate_severe_status", "moderate_severe_osa", DEFAULT_CERTAINTY),
    StatusRule("mash_status", "mash", CODE_CERTAINTY),
    StatusRule("mash_f2_f3_status", "mash_f2_f3", "mash_f2_f3_certainty"),
    StatusRule("cirrhosis_status", "cirrhosis", CODE_CERTAINTY),
    StatusRule("heart_failure_status", "heart_failure", CODE_CERTAINTY),
    StatusRule("hfpef_status", "hfpef", "hfpef_certainty"),
    StatusRule("hypertension_status", "hypertension", CODE_CERTAINTY),
    StatusRule(
        "uncontrolled_hypertension_two_meds_status",
        "uncontrolled_hypertension_two_medications",
        DEFAULT_CERTAINTY,
    ),
    StatusRule("ohs_documented_status", "documented_ohs", CODE_CERTAINTY),
    StatusRule("probable_ohs_status", "probable_ohs", PROBABLE_CERTAINTY),
    StatusRule("pcos_status", "pcos", CODE_CERTAINTY),
    StatusRule("knee_oa_status", "knee_osteoarthritis", CODE_CERTAINTY),
    StatusRule("aud_status", "alcohol_use_disorder", CODE_CERTAINTY),
    StatusRule("iih_status", "idiopathic_intracranial_hypertension", CODE_CERTAINTY),
    StatusRule("binge_eating_status", "binge_eating_disorder", CODE_CERTAINTY),
    StatusRule(
        "metabolic_dysfunction_status",
        "antipsychotic_metabolic_dysfunction",
        DEFAULT_CERTAINTY,
    ),
    StatusRule("masld_status", "masld", CODE_CERTAINTY),
    StatusRule("dyslipidemia_status", "dyslipidemia", CODE_CERTAINTY),
    StatusRule("metabolic_syndrome_status", "metabolic_syndrome", CODE_CERTAINTY),
    StatusRule("copd_status", "copd", CODE_CERTAINTY),
    StatusRule("asthma_status", "asthma", CODE_CERTAINTY),
    StatusRule("neuromuscular_disease_status", "neuromuscular_disease", CODE_CERTAINTY),
    StatusRule("chest_wall_disease_status", "chest_wall_disease", CODE_CERTAINTY),
)

INDICATION_RULES = (
    IndicationRule("ind_fda_weight_management", "fda", "weight_management"),
    IndicationRule("ind_fda_t2d", "fda", "type_2_diabetes"),
    IndicationRule("ind_fda_obesity_established_cvd", "fda", "obesity_established_cvd"),
    IndicationRule("ind_fda_t2d_ckd", "fda", "type_2_diabetes_ckd"),
    IndicationRule("ind_fda_moderate_severe_osa", "fda", "moderate_severe_osa"),
    IndicationRule("ind_fda_noncirrhotic_mash_f2_f3", "fda", "noncirrhotic_mash_f2_f3"),
    IndicationRule("ind_fda_disease_specific_any", "fda", "disease_specific_any"),
    IndicationRule(
        "ind_guideline_weight_loss_for_probable_ohs",
        "guideline",
        "weight_loss_probable_ohs",
    ),
    IndicationRule(
        "ind_guideline_obesity_related_hfpef",
        "guideline",
        "obesity_related_hfpef",
    ),
    IndicationRule(
        "ind_guideline_pcos_with_overweight_obesity",
        "guideline",
        "pcos_overweight_obesity",
    ),
    IndicationRule("ind_guideline_any", "guideline", "guideline_any"),
    IndicationRule("ind_rct_obesity_related_hfpef", "rct", "obesity_related_hfpef"),
    IndicationRule("ind_rct_symptomatic_pad_t2d", "rct", "symptomatic_pad_t2d"),
    IndicationRule("ind_rct_knee_oa_obesity", "rct", "knee_oa_obesity"),
    IndicationRule("ind_rct_alcohol_use_disorder", "rct", "alcohol_use_disorder"),
    IndicationRule("ind_rct_idiopathic_intracranial_hypertension", "rct", "iih"),
    IndicationRule("ind_rct_antipsychotic_metabolic", "rct", "antipsychotic_metabolic"),
    IndicationRule("ind_rct_pcos_obesity", "rct", "pcos_obesity"),
    IndicationRule("ind_rct_any", "rct", "rct_any"),
)


def append_eligibility_evidence(connection: duckdb.DuckDBPyConnection) -> None:
    """Append source-level evidence and canonical derived rule rows."""

    _append_diagnosis_evidence(connection)
    _append_procedure_evidence(connection)
    _append_lab_evidence(connection)
    _append_blood_pressure_evidence(connection)
    _append_medication_evidence(connection)
    _append_status_evidence(connection)
    _append_indication_evidence(connection)


def _append_diagnosis_evidence(connection: duckdb.DuckDBPyConnection) -> None:
    _insert(
        connection,
        """
        SELECT
            analysis.run_id, evidence.index_event_id, evidence.patient_id,
            'source:' || evidence.concept_set_id, 'component',
            evidence.concept_set_id, 'diagnosis_code', 'met', 'code_only',
            evidence.event_datetime, 'diagnosis', 'source_diagnosis',
            evidence.source_file, evidence.source_record_hash,
            evidence.encounter_id, evidence.code_system, evidence.code,
            NULL, NULL, NULL, NULL, NULL, NULL,
            -evidence.days_before_index, TRUE,
            row_number() OVER (
                PARTITION BY evidence.index_event_id, evidence.concept_set_id
                ORDER BY evidence.event_datetime, evidence.source_record_hash
            ),
            json_object('source', 'diagnosis_component_evidence')
        FROM diagnosis_component_evidence AS evidence
        JOIN analysis_glp1_eligibility AS analysis USING (index_event_id)
        """,
    )


def _append_procedure_evidence(connection: duckdb.DuckDBPyConnection) -> None:
    _insert(
        connection,
        """
        SELECT
            analysis.run_id, evidence.index_event_id, evidence.patient_id,
            'source:' || evidence.concept_set_id, 'component',
            evidence.concept_set_id, 'procedure_code', 'met', 'code_only',
            evidence.event_datetime, 'procedure', 'source_procedure',
            evidence.source_file, evidence.source_record_hash,
            evidence.encounter_id, evidence.code_system, evidence.code,
            NULL, NULL, NULL, NULL, NULL, NULL,
            -evidence.days_before_index, TRUE,
            row_number() OVER (
                PARTITION BY evidence.index_event_id, evidence.concept_set_id
                ORDER BY evidence.event_datetime, evidence.source_record_hash
            ),
            json_object('source', 'procedure_component_evidence')
        FROM procedure_component_evidence AS evidence
        JOIN analysis_glp1_eligibility AS analysis USING (index_event_id)
        """,
    )


def _append_lab_evidence(connection: duckdb.DuckDBPyConnection) -> None:
    _insert(
        connection,
        """
        SELECT
            analysis.run_id, evidence.index_event_id, evidence.patient_id,
            'source:' || evidence.concept_set_id, 'component',
            evidence.concept_set_id, 'measurement', 'met', 'strict',
            evidence.event_datetime, 'lab', 'source_lab_measurement',
            evidence.source_file, evidence.source_record_hash,
            evidence.encounter_id, evidence.code_system, evidence.code,
            NULL, evidence.raw_numeric_value, evidence.lab_result_text_val,
            evidence.units_of_measure, evidence.normalized_numeric_value,
            evidence.normalized_unit, -evidence.days_before_index, TRUE,
            row_number() OVER (
                PARTITION BY evidence.index_event_id, evidence.concept_set_id
                ORDER BY evidence.event_datetime, evidence.source_record_hash
            ),
            json_object(
                'source', 'component_lab_evidence',
                'fibrosis_stage', evidence.fibrosis_stage_value
            )
        FROM component_lab_evidence AS evidence
        JOIN analysis_glp1_eligibility AS analysis USING (index_event_id)
        """,
    )


def _append_blood_pressure_evidence(
    connection: duckdb.DuckDBPyConnection,
) -> None:
    _insert(
        connection,
        """
        SELECT
            analysis.run_id, evidence.index_event_id, evidence.patient_id,
            'source:' || evidence.concept_set_id, 'component',
            evidence.concept_set_id, 'measurement', 'met', 'strict',
            evidence.event_datetime, 'vital', 'source_vital_measurement',
            evidence.source_file, evidence.source_record_hash,
            evidence.encounter_id, evidence.code_system, evidence.code,
            NULL, evidence.raw_numeric_value, evidence.text_value,
            evidence.units_of_measure, evidence.normalized_numeric_value, 'mm Hg',
            datediff('day', analysis.index_date, evidence.event_datetime), TRUE,
            row_number() OVER (
                PARTITION BY evidence.index_event_id, evidence.concept_set_id
                ORDER BY evidence.event_datetime, evidence.source_record_hash
            ),
            json_object(
                'source', 'component_bp_evidence',
                'encounter_type', evidence.encounter_type
            )
        FROM component_bp_evidence AS evidence
        JOIN analysis_glp1_eligibility AS analysis USING (index_event_id)
        """,
    )


def _append_medication_evidence(connection: duckdb.DuckDBPyConnection) -> None:
    _insert(
        connection,
        """
        SELECT
            analysis.run_id, evidence.index_event_id, evidence.patient_id,
            'source:' || evidence.concept_set_id, 'component',
            evidence.concept_set_id, 'medication_order', 'met', 'strict',
            evidence.event_datetime, 'medication', 'source_medication',
            evidence.source_file, evidence.source_record_hash,
            evidence.encounter_id, evidence.code_system, evidence.code,
            NULL, NULL, evidence.brand, evidence.strength, NULL, NULL,
            -evidence.days_before_index,
            evidence.event_datetime <= analysis.index_date,
            row_number() OVER (
                PARTITION BY evidence.index_event_id, evidence.concept_set_id
                ORDER BY evidence.event_datetime, evidence.source_record_hash
            ),
            json_object(
                'source', 'medication_component_evidence',
                'active_at_index', evidence.active_at_index,
                'ordered_post_index', evidence.ordered_post_index
            )
        FROM medication_component_evidence AS evidence
        JOIN analysis_glp1_eligibility AS analysis USING (index_event_id)
        """,
    )


def _append_status_evidence(connection: duckdb.DuckDBPyConnection) -> None:
    selects = [
        f"""
        SELECT
            run_id, index_event_id, patient_id,
            {_sql_string("status:" + rule.column)}, 'component',
            {_sql_string(rule.phenotype)}, 'derived_status', {rule.column},
            {rule.certainty_sql.format(status=rule.column)}, index_date, 'derived',
            'analysis_glp1_eligibility', NULL, NULL, encounter_id,
            NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL,
            0, TRUE, 1,
            json_object('status_column', {_sql_string(rule.column)})
        FROM analysis_glp1_eligibility
        """
        for rule in STATUS_RULES
    ]
    _insert(connection, " UNION ALL ".join(selects))


def _append_indication_evidence(connection: duckdb.DuckDBPyConnection) -> None:
    selects = [
        f"""
        SELECT
            run_id, index_event_id, patient_id,
            {_sql_string(rule.column)}, {_sql_string(rule.tier)},
            {_sql_string(rule.phenotype)}, 'derived_rule',
            CASE WHEN {rule.column} THEN 'met' ELSE 'not_met' END,
            'strict', index_date, 'derived', 'analysis_glp1_eligibility',
            NULL, NULL, encounter_id, NULL, NULL, NULL, NULL, NULL, NULL,
            NULL, NULL, 0, TRUE, 1,
            json_object('indication_column', {_sql_string(rule.column)})
        FROM analysis_glp1_eligibility
        WHERE {rule.column} IS NOT NULL
        """
        for rule in INDICATION_RULES
    ]
    _insert(connection, " UNION ALL ".join(selects))


def _insert(connection: duckdb.DuckDBPyConnection, select_sql: str) -> None:
    columns = ", ".join(EVIDENCE_COLUMNS)
    connection.execute(
        f"INSERT INTO eligibility_evidence_long ({columns}) {select_sql}"
    )


def _sql_string(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"

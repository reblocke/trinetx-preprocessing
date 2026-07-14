"""Ticket-level acceptance tests for the committed 20-case GLP-1 fixture."""

from __future__ import annotations

from pathlib import Path

import duckdb

from trinetx_preprocessing.glp1_eligibility.builder import build_glp1_eligibility
from trinetx_preprocessing.glp1_eligibility.discovery import validate_export

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "glp1_synthetic"
CONFIG = ROOT / "config" / "glp1_eligibility.yml"


def test_twenty_case_fixture_satisfies_ticket_acceptance(tmp_path: Path) -> None:
    report = validate_export(FIXTURE)
    assert report.valid is True

    output = tmp_path / "glp1_eligibility"
    result = build_glp1_eligibility(
        input_root=FIXTURE,
        output_dir=output,
        config_path=CONFIG,
    )
    assert result.counts.hypercapnia_encounters == 19
    assert result.counts.patient_index_events == 17
    assert result.counts.primary_obesity_hypercapnia == 14

    connection = duckdb.connect(
        str(output / "glp1_hypercapnia.duckdb"), read_only=True
    )
    try:
        sensitivity = {
            row[0]: row[1:]
            for row in connection.execute(
                """
                SELECT patient_id, primary_cohort_status,
                       later_hypercapnia_sensitivity_case,
                       vbg_only_sensitivity_case
                FROM cohort_hypercapnia_encounter
                """
            ).fetchall()
        }
        assert sensitivity["case01"] == ("excluded", True, False)
        assert "case02" not in sensitivity
        assert sensitivity["case16"] == ("excluded", False, True)

        cursor = connection.execute("SELECT * FROM analysis_glp1_eligibility")
        columns = [column[0] for column in cursor.description]
        rows = {
            row[columns.index("patient_id")]: dict(zip(columns, row, strict=True))
            for row in cursor.fetchall()
        }
        assert len(rows) == 17

        assert rows["case03"]["bridge_qualifying_branch"] == "bmi_ge35"
        assert rows["case03"]["ind_fda_weight_management"] is True

        assert rows["case04"]["hfpef_status"] == "met"
        assert rows["case04"]["hfpef_certainty"] == "strict"
        assert rows["case04"]["bridge_qualifying_branch"] == "bmi_ge30_comorbidity"

        assert rows["case05"]["uncontrolled_hypertension_two_meds_status"] == (
            "not_met"
        )
        assert rows["case06"]["uncontrolled_hypertension_two_meds_status"] == "met"

        assert rows["case07"]["prediabetes_status"] == "met"
        assert rows["case07"]["bridge_qualifying_branch"] == "bmi_ge27_comorbidity"

        assert rows["case08"]["t2d_status"] == "met"
        assert rows["case08"]["ind_fda_t2d"] is True
        assert rows["case08"]["payer_route_model"] == "part_d_disease_route"

        assert rows["case09"]["osa_moderate_severe_status"] == "met"
        assert rows["case09"]["ind_fda_moderate_severe_osa"] is True
        assert rows["case10"]["osa_any_status"] == "met"
        assert rows["case10"]["osa_moderate_severe_status"] == "indeterminate"
        assert rows["case10"]["ind_fda_moderate_severe_osa"] is None

        assert rows["case11"]["mash_f2_f3_status"] == "met"
        assert rows["case11"]["ind_fda_noncirrhotic_mash_f2_f3"] is True
        assert rows["case12"]["mash_f2_f3_status"] == "not_met"
        assert rows["case12"]["ind_fda_noncirrhotic_mash_f2_f3"] is None
        assert rows["case13"]["mash_f2_f3_status"] == "indeterminate"

        assert rows["case14"]["egfr_persistent_lt60"] is False
        assert rows["case14"]["ckd_stage_3a_plus_status"] == "indeterminate"
        assert rows["case15"]["egfr_persistent_lt60"] is True
        assert rows["case15"]["ckd_stage_3a_plus_status"] == "met"

        assert rows["case17"]["t2d_status"] == "indeterminate"
        assert rows["case18"]["bmi_valid"] is False
        assert rows["case18"]["obesity_status"] == "indeterminate"
        assert rows["case18"]["ind_fda_weight_management"] is None

        assert rows["case19"]["metabolic_dysfunction_status"] == "not_met"
        assert rows["case19"]["ind_rct_antipsychotic_metabolic"] is None
        assert rows["case20"]["metabolic_dysfunction_status"] == "met"
        assert rows["case20"]["ind_rct_antipsychotic_metabolic"] is True
    finally:
        connection.close()

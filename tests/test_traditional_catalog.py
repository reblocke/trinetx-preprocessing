from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from trinetx_preprocessing.combined_preprocessing.elements import (
    SOURCE_TABLE_BY_DOMAIN,
    ElementCaptureWriter,
    _classify_memberships,
    catalog_rows,
    glp1_catalog_sha256,
    load_combined_catalog,
    load_glp1_catalog,
)
from trinetx_preprocessing.combined_preprocessing.traditional_catalog import (
    SOURCE_CANDIDACY_NOTE,
    traditional_concept_id,
    traditional_concepts,
)
from trinetx_preprocessing.config import (
    ChunkingConfig,
    CohortConfig,
    CombinedPreprocessingConfig,
    Config,
    DataScreenConfig,
    GuardrailConfig,
    RfsConfig,
    StorageConfig,
)
from trinetx_preprocessing.transform.diagnosis import DIAGNOSIS_CODE_GROUPS
from trinetx_preprocessing.transform.lab_features import LAB_VALUE_RULES
from trinetx_preprocessing.transform.medications import MEDICATION_CODE_GROUPS
from trinetx_preprocessing.transform.procedure import PROCEDURE_CODE_GROUPS
from trinetx_preprocessing.transform.vitals import VITAL_SIGN_RULES

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
CONCEPT_SETS_DIR = REPOSITORY_ROOT / "config" / "concept_sets"


def test_combined_catalog_preserves_glp1_catalog_and_adds_all_legacy_candidates(
    tmp_path: Path,
) -> None:
    config = _combined_config(tmp_path)

    glp1_catalog = load_glp1_catalog(config)
    combined_catalog = load_combined_catalog(config)
    traditional = traditional_concepts()

    assert glp1_catalog_sha256(config) == glp1_catalog.sha256
    assert combined_catalog.concepts[: len(glp1_catalog.concepts)] == (
        glp1_catalog.concepts
    )
    assert combined_catalog.sha256 != glp1_catalog.sha256
    assert {concept.concept_set_id for concept in traditional} == _expected_rule_ids()
    assert len(
        {
            (
                concept.concept_set_id,
                concept.code_system,
                concept.code,
                concept.match_type,
                concept.include,
            )
            for concept in traditional
        }
    ) == len(traditional)
    assert all(concept.include for concept in traditional)
    assert all(concept.notes == SOURCE_CANDIDACY_NOTE for concept in traditional)

    source_element_ids = {
        row["element_id"]
        for row in catalog_rows(combined_catalog)
        if row["element_kind"] == "source_concept"
    }
    assert "source.arterial_pco2" in source_element_ids
    assert {
        f"source.{concept_id}" for concept_id in _expected_rule_ids()
    } <= source_element_ids


def test_source_candidacy_uses_codes_without_legacy_value_or_cohort_gates(
    tmp_path: Path,
) -> None:
    catalog = load_combined_catalog(_combined_config(tmp_path))

    lab_memberships = _memberships(
        catalog,
        "labs",
        pd.DataFrame(
            {
                "code_system": ["LOCAL", "LOINC"],
                "code": ["2019-8", "2019-8"],
                # Both values are below legacy lab/RFS thresholds. Source
                # candidacy must still retain the corresponding code matches.
                "lab_result_num_val": ["1", "1"],
            }
        ),
    )
    assert _element_ids_for(lab_memberships, "row-0") == {
        "source.traditional.lab.value_20198"
    }
    assert {
        "source.arterial_pco2",
        "source.traditional.lab.rfs_abg",
        "source.traditional.lab.value_20198",
    } <= _element_ids_for(lab_memberships, "row-1")

    vital_memberships = _memberships(
        catalog,
        "vitals",
        pd.DataFrame(
            {
                "code_system": ["LOCAL"],
                "code": ["39156-5"],
                # This is below the historical RFS obesity threshold.
                "value": ["20"],
            }
        ),
    )
    assert {
        "source.traditional.vital.value_bmi",
        "source.traditional.vital.rfs_obesity_bmi",
    } <= _element_ids_for(vital_memberships, "row-0")

    diagnosis_memberships = _memberships(
        catalog,
        "diagnosis",
        pd.DataFrame({"code_system": ["LOCAL"], "code": ["E66.2"]}),
    )
    diagnosis_ids = _element_ids_for(diagnosis_memberships, "row-0")
    assert "source.traditional.diagnosis.has_e662" in diagnosis_ids
    assert "source.traditional.diagnosis.rfs_respfail" in diagnosis_ids
    assert "source.ohs" not in diagnosis_ids


@pytest.mark.parametrize(
    ("domain", "source_name", "frame"),
    [
        (
            "encounter",
            "Encounter/encounter.csv",
            pd.DataFrame(
                {
                    "patient_id": ["P1", "P2"],
                    "encounter_id": ["E1", "E2"],
                    "type": ["AMB", "EMER"],
                    "start_date": ["2022-01-01", "2022-01-02"],
                    "end_date": ["2022-01-02", "2022-01-03"],
                }
            ),
        ),
        (
            "patient",
            "Patient/patient.csv",
            pd.DataFrame(
                {
                    "patient_id": ["P1", "P2"],
                    "sex": ["F", "M"],
                    "year_of_birth": ["1980", "1981"],
                }
            ),
        ),
    ],
)
def test_complete_source_relations_ignore_legacy_candidate_masks(
    tmp_path: Path,
    domain: str,
    source_name: str,
    frame: pd.DataFrame,
) -> None:
    config = _combined_config(tmp_path)
    source_path = config.data_dir / source_name
    source_path.parent.mkdir(parents=True)

    with ElementCaptureWriter(config, domain, include_all=True) as writer:
        writer.add_chunk(
            frame,
            source_path=source_path,
            retain_mask=pd.Series([True, False], index=frame.index),
        )

    source = pd.read_parquet(
        config.work_dir / f"combined_{SOURCE_TABLE_BY_DOMAIN[domain]}.parquet"
    )
    assert source["source_record_id"].tolist() == [
        f"{source_name}#1",
        f"{source_name}#2",
    ]


def _expected_rule_ids() -> set[str]:
    return {
        *(
            traditional_concept_id("diagnosis", rule.name)
            for rule in DIAGNOSIS_CODE_GROUPS
        ),
        *(
            traditional_concept_id("procedure", rule.name)
            for rule in PROCEDURE_CODE_GROUPS
        ),
        *(
            traditional_concept_id("medication", rule.name)
            for rule in MEDICATION_CODE_GROUPS
        ),
        *(traditional_concept_id("lab", rule.name) for rule in LAB_VALUE_RULES),
        *(traditional_concept_id("vital", rule.name) for rule in VITAL_SIGN_RULES),
        "traditional.lab.rfs_abg",
        "traditional.lab.rfs_vbg",
        "traditional.diagnosis.rfs_respfail",
        "traditional.diagnosis.rfs_obesity_diagnosis",
        "traditional.vital.rfs_obesity_bmi",
        "traditional.procedure.rfs_ventsupport",
        "traditional.diagnosis.rfs_predisposition",
    }


def _memberships(
    catalog: object,
    domain: str,
    frame: pd.DataFrame,
) -> pd.DataFrame:
    record_ids = pd.Series(
        [f"row-{index}" for index in range(len(frame))],
        index=frame.index,
        dtype="string",
    )
    return _classify_memberships(
        frame,
        domain=domain,
        record_ids=record_ids,
        catalog=catalog,
    )


def _element_ids_for(memberships: pd.DataFrame, source_record_id: str) -> set[str]:
    return set(
        memberships.loc[
            memberships["source_record_id"] == source_record_id,
            "element_id",
        ]
    )


def _combined_config(tmp_path: Path) -> Config:
    data_dir = tmp_path / "data"
    work_dir = tmp_path / "work"
    output_dir = tmp_path / "output"
    for path in (data_dir, work_dir, output_dir):
        path.mkdir(exist_ok=True)
    return Config(
        data_dir=data_dir,
        work_dir=work_dir,
        output_dir=output_dir,
        domains={},
        chunking=ChunkingConfig(),
        rfs=RfsConfig(),
        guardrails=GuardrailConfig(),
        storage=StorageConfig(intermediate_format="parquet"),
        cohort=CohortConfig(),
        data_screen=DataScreenConfig(),
        combined=CombinedPreprocessingConfig(
            enabled=True,
            concept_sets_dir=CONCEPT_SETS_DIR,
        ),
    )

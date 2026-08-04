from __future__ import annotations

from collections.abc import Callable
from io import StringIO
from pathlib import Path

import pandas as pd
import pytest

from trinetx_preprocessing.transform.diagnosis import normalize_diagnosis_chunk
from trinetx_preprocessing.transform.encounter import normalize_encounter_chunk
from trinetx_preprocessing.transform.labs import normalize_lab_results_chunk
from trinetx_preprocessing.transform.medications import normalize_medications_chunk
from trinetx_preprocessing.transform.procedure import normalize_procedure_chunk
from trinetx_preprocessing.transform.vitals import normalize_vitals_chunk

Normalizer = Callable[[pd.DataFrame], pd.DataFrame]
FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures"


@pytest.mark.parametrize(
    ("normalizer", "fixture_path", "date_columns", "string_column"),
    [
        (
            normalize_lab_results_chunk,
            FIXTURE_ROOT / "labs/lab_results0001.csv",
            ("date",),
            "code_system",
        ),
        (
            normalize_diagnosis_chunk,
            FIXTURE_ROOT / "diagnosis/diagnosis0001.csv",
            ("date",),
            "principal_diagnosis_indicator",
        ),
        (
            normalize_medications_chunk,
            FIXTURE_ROOT / "medications/medication0001.csv",
            ("start_date",),
            "code_system",
        ),
        (
            normalize_procedure_chunk,
            FIXTURE_ROOT / "procedure/procedure0001.csv",
            ("date",),
            "code_system",
        ),
        (
            normalize_vitals_chunk,
            FIXTURE_ROOT / "vitals/vital_signs0001.csv",
            ("date",),
            "units_of_measure",
        ),
        (
            normalize_encounter_chunk,
            FIXTURE_ROOT / "encounter/encounter0001.csv",
            ("start_date", "end_date"),
            "patient_id",
        ),
    ],
    ids=("labs", "diagnosis", "medications", "procedure", "vitals", "encounter"),
)
def test_combined_style_normalizers_restore_legacy_na_semantics(
    normalizer: Normalizer,
    fixture_path: Path,
    date_columns: tuple[str, ...],
    string_column: str,
) -> None:
    source = pd.read_csv(
        fixture_path,
        dtype="string",
        keep_default_na=False,
        na_values=[""],
    )
    date_tokens = ("NULL", "N/A")
    for column, token in zip(
        date_columns,
        date_tokens[: len(date_columns)],
        strict=True,
    ):
        source.loc[0, column] = token
    source.loc[0, string_column] = "None"
    source_before = source.copy(deep=True)
    legacy_source = pd.read_csv(StringIO(source.to_csv(index=False)), dtype="string")

    normalized = normalizer(source)
    expected = normalizer(legacy_source)

    pd.testing.assert_frame_equal(normalized, expected)
    for column in date_columns:
        assert pd.isna(normalized.loc[0, column])
    assert pd.isna(normalized.loc[0, string_column])
    pd.testing.assert_frame_equal(source, source_before)

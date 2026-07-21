from __future__ import annotations

import pandas as pd
import pytest

from trinetx_preprocessing.transform import lab_features as lab_features_module
from trinetx_preprocessing.transform.lab_features import (
    classify_lab_feature_rows,
    stack_lab_feature_rows,
)


def _labs(rows: list[tuple[str, float]]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "patient_id": f"P{index}",
                "encounter_id": f"E{index}",
                "code": code,
                "date": "2022-01-01",
                "lab_result_num_val": value,
            }
            for index, (code, value) in enumerate(rows, start=1)
        ]
    )


def test_lab_feature_rules_use_exact_codes_and_correct_bounds() -> None:
    grouped = classify_lab_feature_rows(
        _labs(
            [
                ("6298-4", 1.8),
                ("6298-40", 4.0),
                ("2744-1", 6.5),
                ("2744-1", 6.6),
            ]
        )
    )

    assert grouped["value_potassium"]["encounter_id"].tolist() == ["E1"]
    assert grouped["value_27441"]["encounter_id"].tolist() == ["E4"]


def test_lab_feature_rules_apply_venous_lactate_conversion() -> None:
    grouped = classify_lab_feature_rows(
        _labs([(" 30241-4 ", 90.08), ("2519-7", 10.0)])
    )

    values = grouped["value_Lactate_Venous_Blood"]["lab_result_num_val"].tolist()
    assert values == pytest.approx([10.0, 10.0], rel=1e-3)


def test_lab_feature_rules_convert_only_matching_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = lab_features_module.legacy_lab_feature_values
    calls: list[tuple[str, int]] = []

    def tracked_conversion(rule, codes, values):
        calls.append((rule.name, len(values)))
        return original(rule, codes, values)

    monkeypatch.setattr(
        lab_features_module,
        "legacy_lab_feature_values",
        tracked_conversion,
    )
    rows = [("not-a-feature", 1.0)] * 100 + [("2019-8", 55.0)]

    grouped = classify_lab_feature_rows(_labs(rows))

    assert list(grouped) == ["value_20198"]
    assert calls == [("value_20198", 1)]


def test_stacked_lab_feature_rows_carries_rule_name_only() -> None:
    stacked = stack_lab_feature_rows(
        classify_lab_feature_rows(_labs([("2019-8", 55.0)]))
    )

    assert stacked["source_name"].tolist() == ["value_20198"]
    assert list(stacked.columns) == [
        "source_name",
        "patient_id",
        "encounter_id",
        "code",
        "date",
        "lab_result_num_val",
    ]

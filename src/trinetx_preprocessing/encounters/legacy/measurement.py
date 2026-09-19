"""Accepted measurement derivation and saturation imputation; no propensity models."""

from __future__ import annotations

import copy
import math
from collections.abc import Mapping

import numpy as np
import pandas as pd

from .per_file_cleaning import CleaningMetadata
from .pipeline import PipelineResult, PreprocessingPipelineError

RECODE_VALUE_LABELS: dict[str, tuple[str, dict[int, str]]] = {
    "has_vbg_and_cat": (
        "has_vbg_and_cat_val",
        {
            0: "No VBG",
            1: "VBG with normal PCO2",
            2: "VBG with indeterminant PCO2",
            3: "VBG with elevated PCO2",
        },
    ),
    "has_bmi_and_cat": (
        "has_bmi_and_cat_lab",
        {
            0: "No BMI",
            1: "Underweight",
            2: "Normal BMI",
            3: "Overweight",
            4: "Obesity Class 1",
            5: "Obesity Class 2",
            6: "Obesity Class 3",
        },
    ),
    "has_weight_and_cat": (
        "has_weight_and_cat_lab",
        {
            0: "No Weight",
            1: "<100lb",
            2: "100-150lb",
            3: "150-200lb",
            4: "200-250lb",
            5: "250-300lb",
            6: "300+lb",
        },
    ),
    "has_height_and_cat": (
        "has_height_and_cat_lab",
        {
            0: "No Height",
            1: "60 inch",
            2: "60-64inch",
            3: "64-68inch",
            4: "68-72 inch",
            5: "72-76inch",
            6: "76+ inch",
        },
    ),
    "has_hr_and_cat": (
        "has_hr_and_cat_lab",
        {0: "No HR", 1: "Bradycardic", 2: "Normal HR", 3: "Tachycardic"},
    ),
    "has_sbp_and_cat": (
        "has_sbp_and_cat_lab",
        {0: "No SBP", 1: "Low SBP", 2: "Normal SBP", 3: "High SBP"},
    ),
    "has_rr_and_cat": (
        "has_rr_and_cat_lab",
        {0: "No RR", 1: "Bradypnea", 2: "Normal RR", 3: "Tachypnea"},
    ),
    "has_temp_and_cat": (
        "has_temp_and_cat_lab",
        {0: "No Temp", 1: "Hypothermic", 2: "Normal Temp", 3: "Hyperthermic"},
    ),
    "has_spo2_and_cat": (
        "has_spo2_and_cat_lab",
        {0: "No SpO2", 1: "Hypoxic by SpO2", 2: "Normoxic by SpO2"},
    ),
    "has_cl_and_cat": (
        "has_cl_and_cat_lab",
        {
            0: "No Cl",
            1: "Hypochloremia",
            2: "Normal Chloride",
            3: "Hyperchloremia",
        },
    ),
    "has_k_and_cat": (
        "has_k_and_cat_lab",
        {
            0: "No K",
            1: "Hypokalemia",
            2: "Low Normal Potassium",
            3: "High Normal Potassium",
            4: "Hyperkalemia",
        },
    ),
    "has_hco3_and_cat": (
        "has_hco3_and_cat_lab",
        {
            0: "No HCO3",
            1: "Low HCO3",
            2: "Low Normal HCO3",
            3: "High Normal HCO3",
            4: "Hyper HCO3",
            5: "Very high HCO3",
        },
    ),
    "has_lactate_and_cat": (
        "has_lactate_and_cat_lab",
        {0: "No Lactate", 1: "Normal Lactate", 2: "Lactate Elevated"},
    ),
    "has_na_and_cat": (
        "has_na_and_cat_lab",
        {0: "No Na", 1: "HypoNa", 2: "NormoNa", 3: "HyperNa"},
    ),
    "has_cr_and_cat": (
        "has_cr_and_cat_lab",
        {0: "No sCr", 1: "Normal sCr", 2: "Mild sCr elev", 3: "Sev sCr elev"},
    ),
    "has_hgb_and_cat": (
        "has_hgb_and_cat_lab",
        {
            0: "No Hgb",
            1: "Critical Anemia",
            2: "Severe Anemia",
            3: "Mild Anemia",
            4: "Normal Hgb",
            5: "Polycythemia",
        },
    ),
    "has_wbc_and_cat": (
        "has_wbc_and_cat_lab",
        {
            0: "No WBC",
            1: "Hypo WBC",
            2: "Normal WBC",
            3: "High WBC",
            4: "Very High WBC",
        },
    ),
    "has_plt_and_cat": (
        "has_plt_and_cat_lab",
        {
            0: "No WBC",
            1: "Sever Thrombocytopenia",
            2: "Mild Thrombocytopenia",
            3: "Normal Plt",
            4: "Thrombocytosis",
        },
    ),
    "has_bnp_and_cat": (
        "has_bnp_and_cat_lab",
        {
            0: "No BNP",
            1: "Normal BNP",
            2: "Mild BNP elevation",
            3: "Very elevated BNP",
        },
    ),
    "has_phos_and_cat": (
        "has_phos_and_cat_lab",
        {0: "No Phos", 1: "Low Phos", 2: "Normal Phos", 3: "High Phos"},
    ),
    "has_ca_and_cat": (
        "has_ca_and_cat_lab",
        {0: "No Ca", 1: "Low Ca", 2: "Normal Ca", 3: "High Ca"},
    ),
    "has_alb_and_cat": (
        "has_alb_and_cat_lab",
        {0: "No Alb", 1: "Very Low Alb", 2: "Low albumin", 3: "Normal Albumin"},
    ),
    "has_tprot_and_cat": (
        "has_tprot_and_cat_lab",
        {
            0: "No T Prot",
            1: "Low T Prot",
            2: "Normal T Prot",
            3: "High T Prot",
        },
    ),
}


def _float(values: object, index: pd.Index) -> pd.Series:
    return pd.Series(values, index=index, dtype=np.float32)


def _add(
    frame: pd.DataFrame,
    metadata: CleaningMetadata,
    name: str,
    values: object,
    *,
    label: str | None = None,
) -> None:
    if name in frame:
        raise PreprocessingPipelineError(f"generated variable already exists: {name}")
    frame[name] = _float(values, frame.index)
    metadata.storage_types[name] = "float"
    metadata.display_formats[name] = "%9.0g"
    if label is not None:
        metadata.variable_labels[name] = label


def _attach_value_labels(
    metadata: CleaningMetadata,
    variable: str,
    label_name: str,
    definition: Mapping[int, str],
) -> None:
    metadata.variable_value_labels[variable] = label_name
    metadata.value_label_definitions[label_name] = dict(definition)
    metadata.display_formats[variable] = (
        f"%{max(9, *(len(label) for label in definition.values()))}.0g"
    )


def _rowmax(frame: pd.DataFrame, columns: tuple[str, ...]) -> pd.Series:
    return frame.loc[:, columns].max(axis=1, skipna=True)


def _stata_numeric_local(value: float) -> float:
    """Round-trip a numeric expression through Stata's scalar-local text."""

    return float(format(float(value), ".16g"))


def _stata_centile(values: pd.Series, percentile: float) -> float:
    """Return the default nonparametric centile used by Stata 18 ``centile``."""

    if not 0 <= percentile <= 100:
        raise ValueError("Stata centile requires a percentile between 0 and 100")
    observed = np.sort(values.dropna().to_numpy(dtype=np.float64))
    if not len(observed):
        return math.nan
    quantile = _stata_numeric_local(percentile / 100)
    rank = _stata_numeric_local((len(observed) + 1) * quantile)
    lower_rank = int(rank)
    fraction = _stata_numeric_local(rank - lower_rank)
    if lower_rank >= len(observed):
        return float(observed[-1])
    if lower_rank < 1:
        return float(observed[0])
    return _stata_numeric_local(
        observed[lower_rank - 1]
        + fraction * (observed[lower_rank] - observed[lower_rank - 1])
    )


def _restricted_cubic_basis(values: np.ndarray, knots: np.ndarray) -> np.ndarray:
    x = values.astype(np.float32).astype(np.float64)
    columns = [x]
    last_left = knots[-2]
    last = knots[-1]
    denominator = last - last_left
    scale = (last - knots[0]) ** 2
    for knot in knots[:-2]:
        # mkspline stores each truncated linear component as float before
        # constructing the cubic basis.
        left = (
            np.maximum(np.asarray(x - knot, dtype=np.float32), 0.0).astype(np.float64)
            ** 3
        )
        middle = (
            np.maximum(
                np.asarray(x - last_left, dtype=np.float32),
                0.0,
            ).astype(np.float64)
            ** 3
        )
        right = (
            np.maximum(np.asarray(x - last, dtype=np.float32), 0.0).astype(np.float64)
            ** 3
        )
        weight = (last - knot) / denominator
        columns.append((left - weight * middle + (weight - 1.0) * right) / scale)
    return np.asarray(np.column_stack(columns), dtype=np.float32)


def _fixed_order_sum(values: np.ndarray) -> float:
    total = 0.0
    for value in values:
        total += float(value)
    return total


def _fixed_order_dot(left: np.ndarray, right: np.ndarray) -> float:
    total = 0.0
    for index in range(len(left)):
        total += float(left[index]) * float(right[index])
    return total


def _solve_full_rank_system(matrix: np.ndarray, rhs: np.ndarray) -> np.ndarray:
    coefficients = np.asarray(matrix, dtype=np.float64).copy()
    values = np.asarray(rhs, dtype=np.float64).copy()
    size = len(values)
    for column in range(size):
        pivot = max(
            range(column, size),
            key=lambda row: (abs(coefficients[row, column]), -row),
        )
        if coefficients[pivot, column] == 0:
            raise PreprocessingPipelineError(
                "spline regression design is rank deficient"
            )
        if pivot != column:
            coefficients[[column, pivot]] = coefficients[[pivot, column]]
            values[[column, pivot]] = values[[pivot, column]]
        for row in range(column + 1, size):
            factor = coefficients[row, column] / coefficients[column, column]
            coefficients[row, column] = 0
            for trailing in range(column + 1, size):
                coefficients[row, trailing] -= factor * coefficients[column, trailing]
            values[row] -= factor * values[column]

    solution = np.empty(size, dtype=np.float64)
    for row in range(size - 1, -1, -1):
        residual = values[row]
        for column in range(row + 1, size):
            residual -= coefficients[row, column] * solution[column]
        solution[row] = residual / coefficients[row, row]
    return solution


def _stata_linear_regression(
    design: np.ndarray,
    outcome: np.ndarray,
) -> tuple[np.ndarray, float]:
    design_values = np.asarray(design, dtype=np.float32).astype(np.float64)
    outcome_values = np.asarray(outcome, dtype=np.float32).astype(np.float64)
    row_count, column_count = design_values.shape
    if row_count <= column_count:
        raise PreprocessingPipelineError(
            "spline regression requires more complete rows than predictors"
        )
    predictor_means = np.asarray(
        [
            _fixed_order_sum(design_values[:, column]) / row_count
            for column in range(column_count)
        ],
        dtype=np.float64,
    )
    outcome_mean = _fixed_order_sum(outcome_values) / row_count
    cross_products = np.zeros((column_count, column_count), dtype=np.float64)
    predictor_outcome = np.zeros(column_count, dtype=np.float64)
    for row in range(row_count):
        centered_predictors = design_values[row] - predictor_means
        centered_outcome = outcome_values[row] - outcome_mean
        for left in range(column_count):
            predictor_outcome[left] += centered_predictors[left] * centered_outcome
            for right in range(left, column_count):
                cross_products[left, right] += (
                    centered_predictors[left] * centered_predictors[right]
                )
    for left in range(column_count):
        for right in range(left):
            cross_products[left, right] = cross_products[right, left]
    slopes = _solve_full_rank_system(cross_products, predictor_outcome)
    intercept = outcome_mean - _fixed_order_dot(predictor_means, slopes)
    return slopes, intercept


def _stata_predict(
    design: np.ndarray,
    slopes: np.ndarray,
    intercept: float,
) -> np.ndarray:
    design_values = np.asarray(design, dtype=np.float32).astype(np.float64)
    predicted = np.empty(len(design_values), dtype=np.float32)
    for row, values in enumerate(design_values):
        fitted = intercept
        for column in range(len(slopes)):
            fitted += float(values[column]) * float(slopes[column])
        predicted[row] = fitted
    return predicted


def _spline_impute(
    frame: pd.DataFrame,
    *,
    predictor: str,
    outcome: str,
    knot_percentiles: tuple[float, ...],
) -> tuple[pd.Series, tuple[float, ...]]:
    knots = tuple(_stata_centile(frame[predictor], value) for value in knot_percentiles)
    knot_array = np.asarray(knots, dtype=np.float64)
    complete = frame[predictor].notna() & frame[outcome].notna()
    design = _restricted_cubic_basis(
        frame.loc[complete, predictor].to_numpy(dtype=np.float64),
        knot_array,
    )
    slopes, intercept = _stata_linear_regression(
        design,
        frame.loc[complete, outcome].to_numpy(dtype=np.float64),
    )
    predicted = pd.Series(np.nan, index=frame.index, dtype=np.float32)
    usable = frame[predictor].notna()
    prediction_design = _restricted_cubic_basis(
        frame.loc[usable, predictor].to_numpy(dtype=np.float64),
        knot_array,
    )
    predicted.loc[usable] = _stata_predict(prediction_design, slopes, intercept)
    calculated = _float(
        frame[outcome].where(frame[outcome].notna(), predicted),
        frame.index,
    )
    fallback_mean = np.mean(
        calculated.dropna().to_numpy(dtype=np.float32),
        dtype=np.float64,
    )
    calculated = calculated.fillna(np.float32(fallback_mean))
    return _float(calculated, frame.index), knots


def _stata_vbg_co2_correction(
    vbg_co2: pd.Series,
    vbg_o2sat_calc: pd.Series,
) -> np.ndarray:
    """Evaluate Stata's correction expression in double before float storage."""

    co2 = vbg_co2.to_numpy(dtype=np.float64, na_value=np.nan)
    saturation = vbg_o2sat_calc.to_numpy(dtype=np.float64, na_value=np.nan)
    copy_through = np.isnan(saturation) | (saturation >= 90.0)
    return np.where(
        copy_through,
        co2,
        co2 - np.float64(0.2) * (np.float64(92.0) - saturation),
    )


def _recode(
    values: pd.Series,
    rules: tuple[tuple[float | None, float | None, int], ...],
    *,
    missing: int = 0,
) -> pd.Series:
    result = pd.Series(missing, index=values.index, dtype=np.int8)
    observed = values.notna()
    unmatched = observed.copy()
    for lower, upper, code in rules:
        selected = unmatched.copy()
        if lower is not None:
            selected &= values.ge(lower)
        if upper is not None:
            selected &= values.le(upper)
        result.loc[selected] = code
        unmatched &= ~selected
    if unmatched.any():
        raise PreprocessingPipelineError(
            "recode left observed values outside its frozen ranges"
        )
    return result


def _tabulate_generate(
    frame: pd.DataFrame,
    metadata: CleaningMetadata,
    source: str,
    prefix: str,
) -> None:
    levels = sorted(int(value) for value in frame[source].dropna().unique())
    label_name = metadata.variable_value_labels.get(source)
    label_definition = (
        metadata.value_label_definitions.get(label_name, {}) if label_name else {}
    )
    for ordinal, level in enumerate(levels, start=1):
        level_label = label_definition.get(level, str(level))
        generated = f"{prefix}{ordinal}"
        _add(
            frame,
            metadata,
            generated,
            frame[source].eq(level).astype(np.int8),
            label=f"{source}=={level_label}",
        )
        metadata.display_formats[generated] = "%8.0g"


def apply_pre_model_transformations(
    base: PipelineResult,
    *,
    take_ownership: bool = False,
) -> PipelineResult:
    """Apply frozen post-merge transformations through ``pre_abg_checkpoint``.

    ``take_ownership`` is reserved for the sequential production runner, which
    discards ``base`` immediately after this call.
    """

    frame = base.frame if take_ownership else base.frame.copy(deep=True)
    metadata = base.metadata if take_ownership else copy.deepcopy(base.metadata)
    has_neither_abg_vbg = frame.pop("has_neither_abg_vbg")

    paco2 = frame.paco2.astype(np.float64)
    serum_hco3 = frame.serum_hco3.astype(np.float64)
    abg_ph = frame.abg_ph.astype(np.float64)
    vbg_ph = frame.vbg_ph.astype(np.float64)
    _add(frame, metadata, "max_hco3_or_its_met_alk", ((paco2 - 40) / 0.7) + 26)
    _add(
        frame,
        metadata,
        "prim_met_alk",
        np.where(
            frame.paco2_flag.eq(1),
            (
                serum_hco3.notna()
                & frame.max_hco3_or_its_met_alk.astype(np.float64).lt(serum_hco3)
            ).astype(float),
            np.nan,
        ),
    )
    _add(frame, metadata, "max_hco3_or_its_comb_met_alk", 0.4 * (paco2 - 40) + 26)
    _add(
        frame,
        metadata,
        "combo_met_alk",
        np.where(
            frame.paco2_flag.eq(1),
            (
                serum_hco3.notna()
                & frame.max_hco3_or_its_comb_met_alk.astype(np.float64).lt(serum_hco3)
            ).astype(float),
            np.nan,
        ),
    )
    _add(
        frame,
        metadata,
        "alkalemia",
        np.where(
            abg_ph.notna() | vbg_ph.notna(),
            (
                (abg_ph.notna() & abg_ph.ge(7.45)) | (vbg_ph.notna() & vbg_ph.ge(7.45))
            ).astype(float),
            np.nan,
        ),
    )
    _add(
        frame,
        metadata,
        "paco2_flag_and_alk",
        np.where(frame.paco2_flag.eq(1), 0.0, np.nan),
    )
    _add(
        frame,
        metadata,
        "paco2_50_flag",
        np.where(paco2.notna(), paco2.ge(50).astype(float), np.nan),
        label="PaCO2 >= 50 mmHg Day-1 of Encounter",
    )
    frame.loc[
        paco2.notna() & paco2.ge(50) & frame.prim_met_alk.eq(1),
        "paco2_50_flag",
    ] = np.float32(0)
    _attach_value_labels(
        metadata,
        "paco2_50_flag",
        "paco2_50_flag_lab",
        {0: "All PaCO2 < 50 mmHg", 1: "PaCO2 >= 50 mmHg"},
    )

    for target, suffix, label in (
        (
            "hypercap_dx_adm_flag",
            "adm",
            "Hypercapnic Resp Failure Dx Code is Admitting",
        ),
        (
            "hypercap_dx_pcpl_flag",
            "pcpl",
            "Hypercapnic Resp Failure Dx Code is Principal",
        ),
        (
            "hypercap_dx_vr_flag",
            "vr",
            "Hypercapnic Resp Failure Dx Code is Visit Reason",
        ),
    ):
        columns = tuple(
            f"{code}_{suffix}" for code in ("j9612", "j9622", "j9602", "j9692", "e662")
        )
        _add(frame, metadata, target, _rowmax(frame, columns), label=label)

    _add(
        frame,
        metadata,
        "hypercap_on_abg",
        frame.paco2_flag.eq(1).astype(np.int8),
        label="Is there an day 0 ABG that shows hypercapnia?",
    )
    _add(
        frame,
        metadata,
        "hypercap_on_vbg",
        frame.vbg_co2_flag.eq(1).astype(np.int8),
        label="Is there an day 0 VBG that shows hypercapnia (co2>50)?",
    )
    _add(
        frame,
        metadata,
        "has_both_abg_vbg",
        (frame.has_abg + frame.has_vbg).eq(2).astype(np.int8),
        label="Received Both ABG and VBG Assessment of CO2 Status?",
    )
    _attach_value_labels(
        metadata,
        "has_both_abg_vbg",
        "has_both_abg_vbg_lab",
        {0: "Either no ABG or VBG Obtained", 1: "Both ABG and VBG Obtained"},
    )
    frame["has_neither_abg_vbg"] = has_neither_abg_vbg
    _add(
        frame,
        metadata,
        "vbg_or_abg_co2_flag",
        (frame.hypercap_on_abg.eq(1) | frame.hypercap_on_vbg.eq(1)).astype(np.int8),
        label="Day-1 PCO2 >= 45 (ABG) or 50 (VBG) mmHg",
    )
    _attach_value_labels(
        metadata,
        "vbg_or_abg_co2_flag",
        "vbg_or_abg_co2_flag_lab",
        {0: "Neither ABG >= 45 or VBG >= 50", 1: "Either ABG >= 45 or VBG >= 50"},
    )
    _add(
        frame,
        metadata,
        "dx_hypercap_on_abg",
        np.where(
            frame.hypercap_resp_failure.eq(1),
            (frame.paco2_flag.eq(1) & frame.hypercap_resp_failure.eq(1)).astype(float),
            np.nan,
        ),
        label="ICD of Hypercapnia rendered in presence of admission ABG showing hypercapnia",
    )
    _add(
        frame,
        metadata,
        "sugg_hypercap_dx_on_vbg",
        np.where(
            frame.hypercap_resp_failure.eq(1),
            (frame.vbg_co2_flag.eq(1) & frame.hypercap_resp_failure.eq(1)).astype(
                float
            ),
            np.nan,
        ),
        label="ICD of Hypercapnia rendered in presence of admission VBG suggesting hypercapnia",
    )
    _add(
        frame,
        metadata,
        "dx_hypercap_on_vbg",
        np.where(
            frame.hypercap_resp_failure.eq(1),
            (
                frame.vbg_co2_flag.eq(1)
                & frame.hypercap_resp_failure.eq(1)
                & ~frame.dx_hypercap_on_abg.eq(1)
            ).astype(float),
            np.nan,
        ),
        label="ICD of Hypercapnia rendered in presence of admission of ONLY VBG suggesting hype",
    )

    vbg_o2sat_calc, _ = _spline_impute(
        frame,
        predictor="vbg_po2",
        outcome="vbg_o2sat",
        knot_percentiles=(5, 27.5, 50, 72.5, 95),
    )
    _add(frame, metadata, "vbg_o2sat_calc", vbg_o2sat_calc)
    abg_o2sat_calc, abg_knots = _spline_impute(
        frame,
        predictor="abg_po2",
        outcome="abg_o2sat",
        knot_percentiles=(5, 23, 41, 59, 77, 95),
    )
    _add(frame, metadata, "abg_o2sat_calc", abg_o2sat_calc)
    _add(
        frame,
        metadata,
        "corr_vbg_co2",
        _stata_vbg_co2_correction(frame.vbg_co2, frame.vbg_o2sat_calc),
    )
    _add(
        frame,
        metadata,
        "corr_vbg_co2_flag",
        np.where(
            frame.corr_vbg_co2.notna(),
            frame.corr_vbg_co2.ge(45).astype(float),
            np.nan,
        ),
        label="Corrected VBG (Farkas) CO2 >= 45 mmHg w/n 24h of admission?",
    )
    _attach_value_labels(
        metadata,
        "corr_vbg_co2_flag",
        "corr_vbg_co2_flag_lab",
        {0: "All Corr VBG CO2 < 45 mmHg", 1: "Corr VBG CO2 >= 45 mmHg"},
    )
    _add(
        frame,
        metadata,
        "corr_hypercap_on_vbg",
        frame.corr_vbg_co2_flag.eq(1).astype(np.int8),
        label="Is there an day 0 VBG that shows hypercapnia (co2>45 after adjusting for O2)?",
    )

    race_ethnicity = pd.Series(0, index=frame.index, dtype=np.int8)
    race_ethnicity.loc[frame.race.eq(2)] = 6
    race_ethnicity.loc[frame.ethnicity.eq(1)] = 2
    race_ethnicity.loc[frame.race.eq(1)] = 1
    race_ethnicity.loc[frame.race.eq(3)] = 3
    race_ethnicity.loc[frame.race.eq(4)] = 4
    race_ethnicity.loc[frame.race.eq(5)] = 5
    _add(
        frame,
        metadata,
        "race_ethnicity",
        race_ethnicity,
        label="Race/Ethnicity",
    )
    _attach_value_labels(
        metadata,
        "race_ethnicity",
        "race_ethnicity_lab",
        {
            0: "Non-Hispanic White",
            1: "Black",
            2: "Hispanic/Latino",
            3: "Asian",
            4: "AI/AN",
            5: "NH/PI",
            6: "Unknown",
        },
    )

    recodes = {
        "has_vbg_and_cat": ("vbg_co2", ((None, 45, 1), (45, 50, 2), (50, None, 3))),
        "has_bmi_and_cat": (
            "bmi",
            (
                (None, 18.5, 1),
                (18.5, 25, 2),
                (25, 30, 3),
                (30, 35, 4),
                (35, 40, 5),
                (40, None, 6),
            ),
        ),
        "has_weight_and_cat": (
            "weight",
            (
                (None, 100, 1),
                (100, 150, 2),
                (150, 200, 3),
                (200, 250, 4),
                (250, 300, 5),
                (300, None, 6),
            ),
        ),
        "has_height_and_cat": (
            "height",
            (
                (None, 60, 1),
                (60, 64, 2),
                (64, 68, 3),
                (68, 72, 4),
                (72, 76, 5),
                (76, None, 6),
            ),
        ),
        "has_hr_and_cat": ("hr", ((None, 60, 1), (60, 110, 2), (110, None, 3))),
        "has_sbp_and_cat": ("sbp", ((None, 90, 1), (90, 140, 2), (140, None, 3))),
        "has_rr_and_cat": ("rr", ((None, 11.99, 1), (12, 18, 2), (18, None, 3))),
        "has_temp_and_cat": (
            "temp_new",
            ((None, 97, 1), (97, 100.4, 2), (100.4, None, 3)),
        ),
        "has_spo2_and_cat": ("spo2", ((None, 90, 1), (90, None, 2))),
        "has_cl_and_cat": ("serum_cl", ((None, 96, 1), (96, 106, 2), (106, None, 3))),
        "has_k_and_cat": (
            "serum_k",
            ((None, 3.5, 1), (3.5, 4.35, 2), (4.35, 5.2, 3), (5.2, None, 4)),
        ),
        "has_hco3_and_cat": (
            "serum_hco3",
            ((None, 20, 1), (20, 24, 2), (24, 27, 3), (27, 30, 4), (30, None, 5)),
        ),
        "has_lactate_and_cat": ("serum_lac", ((None, 2, 1), (2, None, 2))),
        "has_na_and_cat": ("sodium", ((None, 135, 1), (135, 145, 2), (145, None, 3))),
        "has_cr_and_cat": ("serum_cr", ((None, 1.2, 1), (1.2, 3, 2), (3, None, 3))),
        "has_hgb_and_cat": (
            "hgb",
            ((None, 7, 1), (7, 10, 2), (10, 12.5, 3), (12.5, 16, 4), (16, None, 5)),
        ),
        "has_wbc_and_cat": (
            "wbc",
            ((None, 4.5, 1), (4.5, 10, 2), (10, 20, 3), (20, None, 4)),
        ),
        "has_plt_and_cat": (
            "plt",
            ((None, 75, 1), (75, 150, 2), (150, 450, 3), (450, None, 4)),
        ),
        "has_bnp_and_cat": ("bnp", ((None, 125, 1), (125, 650, 2), (650, None, 3))),
        "has_phos_and_cat": (
            "serum_phos",
            ((None, 3.5, 1), (3.5, 4.5, 2), (4.5, None, 3)),
        ),
        "has_ca_and_cat": (
            "serum_ca",
            ((None, 8.5, 1), (8.5, 10.2, 2), (10.2, None, 3)),
        ),
        "has_alb_and_cat": (
            "serum_albumin",
            ((None, 2.75, 1), (2.75, 3.5, 2), (3.5, None, 3)),
        ),
        "has_tprot_and_cat": (
            "serum_tprot",
            ((None, 6, 1), (6, 8.3, 2), (8.3, None, 3)),
        ),
    }
    for target, (source, rules) in recodes.items():
        source_label = metadata.variable_labels.get(source)
        if source_label is None:
            raise PreprocessingPipelineError(
                f"recode source lacks its frozen variable label: {source}"
            )
        _add(
            frame,
            metadata,
            target,
            _recode(frame[source], rules),
            label=f"RECODE of {source} ({source_label})"[:80],
        )
        label_name, definition = RECODE_VALUE_LABELS[target]
        _attach_value_labels(metadata, target, label_name, definition)

    for source, prefix in (
        ("encounter_type", "encounter_type_dummy"),
        ("sex", "sex_dummy"),
        ("race", "race_dummy"),
        ("ethnicity", "ethnicity_dummy"),
        ("location", "location_dummy"),
    ):
        _tabulate_generate(frame, metadata, source, prefix)

    metadata.sort_variables = ("patient_id",)
    metadata.characteristics = (
        ("_dta", "knots", " ".join(f"{value:g}" for value in abg_knots)),
        ("_dta", "oldvar", "abg_po2"),
        ("_dta", "rcsplines", "rc1 rc2 rc3 rc4 rc5"),
    )
    return PipelineResult(frame, metadata)

"""Accepted encounter assembly, without model execution or DTA publication."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np
import pandas as pd

from .per_file_cleaning import (
    CleaningMetadata,
    CompletePerFileCleaningResult,
    RfsFamily,
)

SETTINGS = ("AMBULATORY", "EMERGENCY", "INPATIENT")


SETTING_CODES = {
    "AMBULATORY": "AMB",
    "EMERGENCY": "EMER",
    "INPATIENT": "INPAT",
}


FAMILY_MERGE_ORDER = tuple(RfsFamily)


class PreprocessingPipelineError(RuntimeError):
    """Raised when an in-memory pipeline boundary is not exact."""


class FirstEncounterOrderError(PreprocessingPipelineError):
    """Raised when the frozen Stata order cannot select one first encounter."""


def _first_encounter_order(frame: pd.DataFrame) -> pd.Index:
    """Return the authorized total order used to select each first encounter."""

    order_columns = ["patient_id", "encounter_date", "pat_enc_hash"]
    if (
        any(name not in frame for name in order_columns)
        or frame["pat_enc_hash"].isna().any()
        or frame["pat_enc_hash"].eq("").any()
        or frame.duplicated(order_columns, keep=False).any()
    ):
        raise FirstEncounterOrderError("first-encounter ordering is not unique")
    return frame.sort_values(
        order_columns,
        kind="mergesort",
        na_position="last",
    ).index


@dataclass(frozen=True, slots=True)
class PipelineResult:
    frame: pd.DataFrame
    metadata: CleaningMetadata


def _is_missing(series: pd.Series) -> pd.Series:
    if series.dtype == object:
        return series.eq("") | series.isna()
    return series.isna()


def _copy_metadata(metadata: CleaningMetadata) -> CleaningMetadata:
    return CleaningMetadata(
        variable_labels=dict(metadata.variable_labels),
        value_label_definitions={
            name: dict(values)
            for name, values in metadata.value_label_definitions.items()
        },
        variable_value_labels=dict(metadata.variable_value_labels),
        display_formats=dict(metadata.display_formats),
        storage_types=dict(metadata.storage_types),
        string_widths=dict(metadata.string_widths),
        sort_variables=tuple(metadata.sort_variables),
        characteristics=tuple(metadata.characteristics),
    )


def _merge_metadata(
    master: CleaningMetadata,
    using: CleaningMetadata,
    *,
    using_columns: tuple[str, ...],
    merge_name: str,
) -> CleaningMetadata:
    result = _copy_metadata(master)
    for name in using_columns:
        if name in result.storage_types:
            continue
        result.storage_types[name] = using.storage_types[name]
        result.display_formats[name] = using.display_formats[name]
        if name in using.string_widths:
            result.string_widths[name] = using.string_widths[name]
        if name in using.variable_labels:
            result.variable_labels[name] = using.variable_labels[name]
        if name in using.variable_value_labels:
            label_name = using.variable_value_labels[name]
            result.variable_value_labels[name] = label_name
            result.value_label_definitions[label_name] = dict(
                using.value_label_definitions[label_name]
            )
    result.storage_types[merge_name] = "byte"
    result.display_formats[merge_name] = "%23.0g"
    result.variable_labels[merge_name] = "Matching result from merge"
    result.variable_value_labels[merge_name] = "_merge"
    result.value_label_definitions["_merge"] = {
        1: "Master only (1)",
        2: "Using only (2)",
        3: "Matched (3)",
        4: "Missing updated (4)",
        5: "Nonmissing conflict (5)",
    }
    result.sort_variables = ("pat_enc_hash",)
    return result


def _stata_update_merge(
    master: PipelineResult,
    using: PipelineResult,
    *,
    merge_name: str,
) -> PipelineResult:
    key = "pat_enc_hash"
    for label, frame in (("master", master.frame), ("using", using.frame)):
        if (
            key not in frame
            or frame[key].isna().any()
            or frame[key].eq("").any()
            or frame[key].duplicated().any()
        ):
            raise PreprocessingPipelineError(
                f"{label} merge key is absent, blank, or nonunique"
            )
    if merge_name in master.frame or merge_name in using.frame:
        raise PreprocessingPipelineError(
            f"merge result variable already exists: {merge_name}"
        )

    master_keys = pd.Index(master.frame[key].to_numpy(copy=False), name=key)
    using_keys = pd.Index(using.frame[key].to_numpy(copy=False), name=key)
    keys = pd.Index(sorted(set(master_keys) | set(using_keys)), name=key)
    master_positions = master_keys.get_indexer(keys)
    using_positions = using_keys.get_indexer(keys)
    result = master.frame.set_axis(master_keys, axis=0, copy=False).reindex(
        keys, copy=True
    )
    master_present = master_positions >= 0
    using_present = using_positions >= 0
    matched = master_present & using_present
    updated = np.zeros(len(result), dtype=bool)
    conflicted = np.zeros(len(result), dtype=bool)

    common_columns = [
        name for name in master.frame.columns if name in using.frame.columns
    ]
    for name in common_columns:
        using_values = using.frame[name].set_axis(using_keys, copy=False).reindex(keys)
        master_missing = _is_missing(result[name])
        using_missing = _is_missing(using_values)
        fill = (master_missing & ~using_missing).to_numpy(dtype=bool)
        updated |= fill & matched
        if name != key:
            equal = result[name].eq(using_values) | (master_missing & using_missing)
            conflicted |= (
                matched
                & ~master_missing.to_numpy(dtype=bool)
                & ~using_missing.to_numpy(dtype=bool)
                & ~equal.to_numpy(dtype=bool, na_value=False)
            )
        result.loc[fill, name] = using_values.loc[fill]

    unique_using = [
        name for name in using.frame.columns if name not in master.frame.columns
    ]
    for name in unique_using:
        result[name] = using.frame[name].set_axis(using_keys, copy=False).reindex(keys)

    codes = np.where(
        ~using_present,
        1,
        np.where(~master_present, 2, np.where(conflicted, 5, np.where(updated, 4, 3))),
    )
    result[merge_name] = pd.Series(codes, index=keys, dtype=np.int8)
    result.reset_index(drop=True, inplace=True)
    metadata = _merge_metadata(
        master.metadata,
        using.metadata,
        using_columns=tuple(unique_using),
        merge_name=merge_name,
    )
    return PipelineResult(result, metadata)


def _result_from_cleaner(result: CompletePerFileCleaningResult) -> PipelineResult:
    if not result.complete:
        raise PreprocessingPipelineError("per-file cleaner result is incomplete")
    # A result is consumed only once by the exact merge matrix.  The merge
    # implementation constructs a new result and never mutates this frame.
    return PipelineResult(result.frame, _copy_metadata(result.metadata))


def _within_setting(
    cleaned: Mapping[tuple[RfsFamily, str], CompletePerFileCleaningResult],
    setting: str,
) -> PipelineResult:
    result = _result_from_cleaner(cleaned[(RfsFamily.ABG, setting)])
    suffixes = {
        RfsFamily.OBESITY: "obes",
        RfsFamily.PREDISPOSITION: "predisp",
        RfsFamily.RESPFAIL: "respfail",
        RfsFamily.VBG: "vbg",
        RfsFamily.VENTSUPPORT: "ventsupp",
    }
    setting_code = SETTING_CODES[setting].lower()
    for family in FAMILY_MERGE_ORDER[1:]:
        result = _stata_update_merge(
            result,
            _result_from_cleaner(cleaned[(family, setting)]),
            merge_name=f"_merge_{setting_code}_{suffixes[family]}",
        )
    return result


def _compressed_integer_storage(series: pd.Series) -> str:
    values = series.dropna()
    if values.empty:
        return "byte"
    minimum = int(values.min())
    maximum = int(values.max())
    if -127 <= minimum and maximum <= 100:
        return "byte"
    if -32767 <= minimum and maximum <= 32740:
        return "int"
    return "long"


def _compress_metadata(frame: pd.DataFrame, metadata: CleaningMetadata) -> None:
    """Reproduce Stata ``compress`` storage choices for an assembled frame."""

    for name in frame:
        series = frame[name]
        if metadata.storage_types[name] == "string":
            observed = series.dropna().astype(str)
            width = max((len(value.encode("utf-8")) for value in observed), default=1)
            metadata.string_widths[name] = max(1, width)
            continue

        observed = series.dropna().to_numpy(dtype=np.float64)
        if not len(observed):
            metadata.storage_types[name] = "byte"
            continue
        if np.equal(observed, np.trunc(observed)).all():
            minimum = int(observed.min())
            maximum = int(observed.max())
            if -127 <= minimum and maximum <= 100:
                compressed_type = "byte"
            elif -32767 <= minimum and maximum <= 32740:
                compressed_type = "int"
            elif -2147483647 <= minimum and maximum <= 2147483620:
                compressed_type = "long"
            else:
                continue
            if not (
                metadata.storage_types[name] == "float" and compressed_type == "long"
            ):
                metadata.storage_types[name] = compressed_type
            continue
        if np.equal(
            observed,
            observed.astype(np.float32).astype(np.float64),
        ).all():
            metadata.storage_types[name] = "float"
        else:
            metadata.storage_types[name] = "double"


def _set_binary_metadata(
    metadata: CleaningMetadata,
    *,
    variable: str,
    variable_label: str,
    label_name: str,
    zero: str,
    one: str,
) -> None:
    metadata.storage_types[variable] = "byte"
    metadata.display_formats[variable] = f"%{max(9, len(zero), len(one))}.0g"
    metadata.variable_labels[variable] = variable_label
    metadata.variable_value_labels[variable] = label_name
    metadata.value_label_definitions[label_name] = {0: zero, 1: one}


def assemble_analysis_base(
    cleaned: Mapping[tuple[RfsFamily, str], CompletePerFileCleaningResult],
) -> PipelineResult:
    """Reproduce frozen merges and shared post-merge identifiers and flags."""

    expected = {(family, setting) for family in RfsFamily for setting in SETTINGS}
    if set(cleaned) != expected:
        raise PreprocessingPipelineError(
            "cleaned input inventory is not the exact 18-file variant"
        )
    result = _within_setting(cleaned, SETTINGS[0])
    result = _stata_update_merge(
        result,
        _within_setting(cleaned, SETTINGS[1]),
        merge_name="_merge_emer",
    )
    result = _stata_update_merge(
        result,
        _within_setting(cleaned, SETTINGS[2]),
        merge_name="_merge_inpat",
    )
    frame = result.frame
    metadata = result.metadata

    original_ids = frame["patient_id"].astype(str)
    patient_levels = {
        value: index + 1 for index, value in enumerate(sorted(set(original_ids)))
    }
    frame.drop(columns=["patient_id"], inplace=True)
    frame["patient_id"] = original_ids.map(patient_levels).astype(np.int32)
    metadata.storage_types["patient_id"] = _compressed_integer_storage(
        frame["patient_id"]
    )
    metadata.display_formats["patient_id"] = "%12.0g"
    metadata.variable_labels["patient_id"] = "group(id)"
    metadata.variable_value_labels.pop("patient_id", None)
    metadata.string_widths.pop("patient_id", None)

    for family in RfsFamily:
        flag = f"{family.value}_rfs"
        frame[flag] = frame[flag].fillna(0)
    multiple = sum(frame[f"{family.value}_rfs"] for family in RfsFamily) > 1
    frame.loc[multiple, "rfs"] = "MULTIPLE"
    rfs_levels = {
        value: index + 1 for index, value in enumerate(sorted(set(frame["rfs"])))
    }
    frame["rfsgroup"] = frame["rfs"].map(rfs_levels).astype(np.int8)
    metadata.storage_types["rfsgroup"] = "byte"
    metadata.display_formats["rfs"] = "%14s"
    metadata.display_formats["rfsgroup"] = (
        f"%{max(9, *(len(value) for value in rfs_levels))}.0g"
    )
    metadata.variable_labels["rfsgroup"] = (
        "Reason for Suspicion of Possible Hypercapnia"
    )
    metadata.variable_value_labels["rfsgroup"] = "rfsgroup"
    metadata.value_label_definitions["rfsgroup"] = {
        code: value for value, code in rfs_levels.items()
    }

    frame.rename(
        columns={"AMB_enc": "is_amb", "EMER_enc": "is_emer", "INPAT_enc": "is_inp"},
        inplace=True,
    )
    for old, new in (
        ("AMB_enc", "is_amb"),
        ("EMER_enc", "is_emer"),
        ("INPAT_enc", "is_inp"),
    ):
        metadata.storage_types[new] = metadata.storage_types.pop(old)
        metadata.display_formats[new] = metadata.display_formats.pop(old)
    metadata.variable_labels["is_amb"] = "Ambulatory Encounter"
    metadata.variable_labels["is_emer"] = "Emergency Encounter"
    frame["is_amb"] = frame["is_amb"].fillna(0)
    frame["is_emer"] = frame["is_emer"].fillna(0)

    original_encounter_type = frame.pop("encounter_type")
    encounter_levels = {
        value: index + 1
        for index, value in enumerate(sorted(set(original_encounter_type)))
    }
    frame["encounter_type"] = original_encounter_type.map(encounter_levels).astype(
        np.int8
    )
    frame.loc[frame["is_emer"].eq(1), "encounter_type"] = 2
    frame.loc[frame["is_inp"].eq(1), "encounter_type"] = 3
    metadata.storage_types["encounter_type"] = "byte"
    metadata.display_formats["encounter_type"] = "%20.0g"
    metadata.variable_labels["encounter_type"] = "Encounter Type?"
    metadata.variable_value_labels["encounter_type"] = "encounter_type_val"
    metadata.value_label_definitions["encounter_type_val"] = {
        1: "Ambulatory Encounter",
        2: "Emergency Encounter",
        3: "Inpatient Encounter",
    }
    metadata.string_widths.pop("encounter_type", None)

    order = _first_encounter_order(frame)
    frame = frame.loc[order].reset_index(drop=True)
    frame["first_encounter"] = (
        frame.groupby("patient_id", sort=False).cumcount().eq(0).astype(np.int8)
    )
    _set_binary_metadata(
        metadata,
        variable="first_encounter",
        variable_label="First Encounter?",
        label_name="is_first_lab",
        zero="Not First Encounter",
        one="First Encounter",
    )

    frame["has_abg"] = frame["paco2"].notna().astype(np.int8)
    _set_binary_metadata(
        metadata,
        variable="has_abg",
        variable_label="Received ABG Verification of CO2 Status?",
        label_name="has_abg_lab",
        zero="No ABG Obtained",
        one="ABG Obtained",
    )
    frame["has_vbg"] = frame["vbg_co2"].notna().astype(np.int8)
    _set_binary_metadata(
        metadata,
        variable="has_vbg",
        variable_label="Received VBG Assessment of CO2 Status?",
        label_name="has_vbg_lab",
        zero="No VBG Obtained",
        one="VBG Obtained",
    )
    frame["has_neither_abg_vbg"] = (
        (frame["has_abg"] + frame["has_vbg"]).eq(0).astype(np.int8)
    )
    _set_binary_metadata(
        metadata,
        variable="has_neither_abg_vbg",
        variable_label="Received Neither ABG nor VBG Assessment of CO2 Status in 1st day?",
        label_name="has_neither_abg_vbg_lab",
        zero="Either ABG or VBG Obtained (first day)",
        one="Neither ABG or VBG Obtained (first day)",
    )
    metadata.variable_labels["is_inp"] = "Inpatient Encounter"
    metadata.variable_value_labels["is_inp"] = "is_inp_lab"
    metadata.value_label_definitions["is_inp_lab"] = {
        0: "Not Inpatient Encounter",
        1: "Inpatient Encounter",
    }
    metadata.storage_types["is_inp"] = "byte"
    metadata.display_formats["is_inp"] = "%23.0g"
    metadata.sort_variables = ("patient_id",)
    return PipelineResult(frame, metadata)

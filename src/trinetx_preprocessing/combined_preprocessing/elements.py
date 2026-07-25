"""Unified source-element catalog and bounded source capture helpers."""

from __future__ import annotations

import re
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pandas as pd

from ..config import Config, ConfigError
from ..glp1_eligibility.concept_sets import (
    ConceptSetCatalog,
    load_concept_sets,
)
from ..pipeline.final_output_schema import FINAL_OUTPUT_COLUMNS
from ..storage import WorkTableWriter

CONCEPT_DOMAIN_BY_PIPELINE_DOMAIN = {
    "labs": "lab",
    "vitals": "vital",
    "diagnosis": "diagnosis",
    "procedure": "procedure",
    "medications": "medication",
}

SOURCE_TABLE_BY_DOMAIN = {
    "labs": "source_lab_measurement",
    "vitals": "source_vital_measurement",
    "diagnosis": "source_diagnosis",
    "procedure": "source_procedure",
    "medications": "source_medication",
    "encounter": "source_encounter",
    "patient": "source_patient",
}

SOURCE_EVENT_COLUMNS = (
    "source_record_id",
    "logical_domain",
    "source_file",
    "source_row_number",
    "observed_order",
    "patient_id",
    "encounter_id",
    "unique_id",
    "code_system_raw",
    "code_system",
    "code_raw",
    "code",
    "date",
    "event_datetime",
    "timestamp_precision",
    "start_date",
    "start_datetime",
    "start_timestamp_precision",
    "end_date",
    "end_datetime",
    "end_timestamp_precision",
    "start_date_derived_by_TriNetX",
    "end_date_derived_by_TriNetX",
    "lab_result_num_val",
    "lab_result_text_val",
    "value",
    "text_value",
    "numeric_value",
    "units_of_measure_raw",
    "units_of_measure",
    "specimen",
    "specimen_id",
    "panel_id",
    "principal_diagnosis_indicator",
    "admitting_diagnosis",
    "reason_for_visit",
    "principal_procedure_indicator",
    "medication_text",
    "order_status",
    "status",
    "route",
    "brand",
    "strength",
    "type",
    "sex",
    "race",
    "ethnicity",
    "year_of_birth",
    "patient_regional_location",
    "month_year_death",
    "derived_by_TriNetX",
    "source_id",
)

SOURCE_EVENT_DUCKDB_TYPES = {
    column: (
        "UBIGINT"
        if column in {"source_row_number", "observed_order"}
        else "TIMESTAMP"
        if column in {"event_datetime", "start_datetime", "end_datetime"}
        else "DOUBLE"
        if column == "numeric_value"
        else "VARCHAR"
    )
    for column in SOURCE_EVENT_COLUMNS
}

MEMBERSHIP_COLUMNS = (
    "source_record_id",
    "element_id",
    "logical_domain",
    "include",
    "match_type",
    "code_system",
    "matched_code",
)

OBSERVABILITY_COLUMNS = (
    "patient_id",
    "logical_domain",
    "event_datetime",
    "timestamp_precision",
    "event_count",
)

GAS_CANDIDATE_COLUMNS = ("patient_id", "encounter_id")
ENCOUNTER_FLOW_COLUMNS = (
    "patient_id",
    "encounter_id",
    "start_datetime",
    "type",
)
ENCOUNTER_FLOW_DUCKDB_TYPES = {
    "patient_id": "VARCHAR",
    "encounter_id": "VARCHAR",
    "start_datetime": "TIMESTAMP",
    "type": "VARCHAR",
}
GAS_ELEMENT_IDS = {
    "source.arterial_pco2",
    "source.venous_pco2",
    "source.unspecified_blood_pco2",
}

COMBINED_MEDICATION_REQUIRED_COLUMNS = (
    "patient_id",
    "code_system",
    "code",
    "start_date",
)

_MEDICATION_INGREDIENT_STEM = re.compile(
    r"medication_ingredients?(?:_?\d+)?",
    re.IGNORECASE,
)


def is_medication_ingredient_export(path: Path) -> bool:
    """Return whether ``path`` belongs to the medication-ingredient family."""

    return _MEDICATION_INGREDIENT_STEM.fullmatch(path.stem) is not None

OPTIONAL_SOURCE_COLUMNS = {
    "labs": ("specimen", "specimen_id", "panel_id"),
    "medications": (
        "encounter_id",
        "unique_id",
        "medication_text",
        "end_date",
        "order_status",
        "status",
        "route",
        "brand",
        "strength",
        "derived_by_TriNetX",
        "source_id",
    ),
    "patient": ("source_id",),
}

_STRING_COLUMNS = tuple(
    column
    for column in SOURCE_EVENT_COLUMNS
    if column
    not in {
        "source_row_number",
        "observed_order",
        "event_datetime",
        "start_datetime",
        "end_datetime",
        "numeric_value",
    }
)


def resolve_concept_sets_dir(config: Config) -> Path:
    """Resolve the catalog used by the unified preprocessing build."""

    configured = config.combined.concept_sets_dir
    if configured is not None:
        root = configured
    else:
        root = Path(__file__).resolve().parents[3] / "config" / "concept_sets"
    if not root.is_dir():
        raise ConfigError(
            "Combined preprocessing requires 'combined.concept_sets_dir'; "
            f"concept catalog not found at {root}."
        )
    return root


def load_combined_catalog(config: Config) -> ConceptSetCatalog:
    """Load the single versioned source-element catalog."""

    return load_concept_sets(resolve_concept_sets_dir(config))


def catalog_rows(catalog: ConceptSetCatalog) -> list[dict[str, Any]]:
    """Return source and derived elements for the database catalog table."""

    rows: list[dict[str, Any]] = []
    for concept in catalog.concepts:
        row = asdict(concept)
        row.update(
            {
                "element_id": f"source.{concept.concept_set_id}",
                "element_kind": "source_concept",
                "value_kind": "event",
                "legacy_column": None,
            }
        )
        rows.append(row)
    rows.extend(
        {
            "element_id": f"historical.final.{column}",
            "element_kind": "historical_derived",
            "value_kind": "column",
            "legacy_column": column,
            "concept_set_id": None,
            "domain": "final",
            "code_system": None,
            "code": None,
            "match_type": None,
            "include": True,
            "description": f"Historical final-output column: {column}",
            "source_authority": "refactor-milestone-2",
            "source_version": "0.2.0",
            "effective_start": None,
            "effective_end": None,
            "notes": "Compatibility element retained in the 534-column contract.",
            "source_file": "pipeline/final_output_schema.py",
            "source_row": index,
        }
        for index, column in enumerate(FINAL_OUTPUT_COLUMNS, start=1)
    )
    return rows


def available_source_columns(
    path: Path,
    required: list[str] | tuple[str, ...],
    *,
    domain: str,
) -> list[str]:
    """Return required plus available optional source columns in stable order."""

    required_columns = tuple(required)
    header = tuple(pd.read_csv(path, nrows=0).columns)
    missing = [column for column in required_columns if column not in header]
    if missing:
        raise ValueError(f"{path} is missing required columns: {', '.join(missing)}")
    optional = OPTIONAL_SOURCE_COLUMNS.get(domain, ())
    return [
        *required_columns,
        *(
            column
            for column in optional
            if column in header and column not in required_columns
        ),
    ]


class ElementCaptureWriter:
    """Capture source rows matching the shared element registry during one scan."""

    def __init__(
        self,
        config: Config,
        domain: str,
        *,
        include_all: bool = False,
        catalog: ConceptSetCatalog | None = None,
    ) -> None:
        if domain not in SOURCE_TABLE_BY_DOMAIN:
            raise ValueError(f"Unsupported combined source domain: {domain}")
        self.config = config
        self.domain = domain
        self.include_all = include_all
        self.enabled = config.combined.enabled
        self.catalog = catalog
        self._source_writer = WorkTableWriter(
            config,
            f"combined_{SOURCE_TABLE_BY_DOMAIN[domain]}.csv",
            enabled=self.enabled,
        )
        self._membership_writer = WorkTableWriter(
            config,
            f"combined_element_membership_{domain}.csv",
            enabled=self.enabled,
        )
        self._observability_writer = WorkTableWriter(
            config,
            f"combined_observability_{domain}.csv",
            enabled=self.enabled and domain in CONCEPT_DOMAIN_BY_PIPELINE_DOMAIN,
        )
        self._gas_candidate_writer = WorkTableWriter(
            config,
            "combined_gas_candidate_id.csv",
            enabled=self.enabled and domain == "labs",
        )
        self._rows_seen = 0
        self._source_rows_seen: dict[str, int] = {}
        self._rows_written = 0
        self._membership_rows_written = 0
        self._observability_rows_written = 0
        self._gas_candidate_rows_written = 0

    @property
    def written_paths(self) -> list[Path]:
        """Return all physical work tables emitted by this writer."""

        return [
            *self._source_writer.written_paths,
            *self._membership_writer.written_paths,
            *self._observability_writer.written_paths,
            *self._gas_candidate_writer.written_paths,
        ]

    def __enter__(self) -> "ElementCaptureWriter":
        self._source_writer.__enter__()
        self._membership_writer.__enter__()
        self._observability_writer.__enter__()
        self._gas_candidate_writer.__enter__()
        if self.enabled and not self.include_all and self.catalog is None:
            self.catalog = load_combined_catalog(self.config)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self.enabled and exc_type is None:
            if self._rows_written == 0:
                self._source_writer.write(_empty_source_frame())
            if self._membership_rows_written == 0:
                self._membership_writer.write(_empty_membership_frame())
            if (
                self.domain in CONCEPT_DOMAIN_BY_PIPELINE_DOMAIN
                and self._observability_rows_written == 0
            ):
                self._observability_writer.write(_empty_observability_frame())
            if self.domain == "labs" and self._gas_candidate_rows_written == 0:
                self._gas_candidate_writer.write(_empty_gas_candidate_frame())
        self._gas_candidate_writer.__exit__(exc_type, exc, tb)
        self._observability_writer.__exit__(exc_type, exc, tb)
        self._membership_writer.__exit__(exc_type, exc, tb)
        self._source_writer.__exit__(exc_type, exc, tb)

    def add_chunk(
        self,
        frame: pd.DataFrame,
        *,
        source_path: Path,
        retain_mask: pd.Series | None = None,
    ) -> None:
        """Capture one raw chunk while preserving source position and duplicates."""

        if not self.enabled or frame.empty:
            self._rows_seen += len(frame)
            return

        relative_source = _relative_source_path(source_path, self.config.data_dir)
        source_rows_seen = self._source_rows_seen.get(relative_source, 0)
        row_numbers = pd.Series(
            range(source_rows_seen + 1, source_rows_seen + len(frame) + 1),
            index=frame.index,
            dtype="int64",
        )
        observed_order = pd.Series(
            range(self._rows_seen, self._rows_seen + len(frame)),
            index=frame.index,
            dtype="int64",
        )
        self._rows_seen += len(frame)
        self._source_rows_seen[relative_source] = source_rows_seen + len(frame)
        observability = _observability_rows(frame, domain=self.domain)
        if not observability.empty:
            self._observability_writer.write(observability)
            self._observability_rows_written += len(observability)
        record_ids = (
            pd.Series(relative_source, index=frame.index, dtype="string")
            + "#"
            + row_numbers.astype("string")
        )

        if self.include_all:
            retained_index = (
                frame.index
                if retain_mask is None
                else frame.index[retain_mask.fillna(False).astype(bool)]
            )
            memberships = _empty_membership_frame()
        else:
            memberships = _classify_memberships(
                frame,
                domain=self.domain,
                record_ids=record_ids,
                catalog=self.catalog,
            )
            included_memberships = memberships.loc[
                memberships["include"].fillna(False).astype(bool)
            ]
            retained_ids = set(
                included_memberships["source_record_id"].astype(str)
            )
            retained_index = frame.index[record_ids.astype(str).isin(retained_ids)]
            memberships = memberships.loc[
                memberships["source_record_id"].astype(str).isin(retained_ids)
            ].copy()

        if self.domain == "labs" and not memberships.empty:
            gas_ids = set(
                memberships.loc[
                    memberships["include"].fillna(False).astype(bool)
                    & memberships["element_id"].isin(GAS_ELEMENT_IDS),
                    "source_record_id",
                ].astype(str)
            )
            gas_mask = record_ids.astype(str).isin(gas_ids)
            gas_candidates = frame.loc[
                gas_mask,
                ["patient_id", "encounter_id"],
            ].copy()
            gas_candidates = gas_candidates.drop_duplicates(keep="first")
            if not gas_candidates.empty:
                gas_candidates["patient_id"] = gas_candidates["patient_id"].astype(
                    "string"
                )
                gas_candidates["encounter_id"] = gas_candidates["encounter_id"].astype(
                    "string"
                )
                self._gas_candidate_writer.write(
                    gas_candidates.loc[:, GAS_CANDIDATE_COLUMNS]
                )
                self._gas_candidate_rows_written += len(gas_candidates)

        if len(retained_index) == 0:
            return
        records = _source_records(
            frame.loc[retained_index],
            domain=self.domain,
            source_file=relative_source,
            record_ids=record_ids.loc[retained_index],
            row_numbers=row_numbers.loc[retained_index],
            observed_order=observed_order.loc[retained_index],
        )
        self._source_writer.write(records)
        self._rows_written += len(records)
        if not memberships.empty:
            self._membership_writer.write(memberships)
            self._membership_rows_written += len(memberships)


def _classify_memberships(
    frame: pd.DataFrame,
    *,
    domain: str,
    record_ids: pd.Series,
    catalog: ConceptSetCatalog | None,
) -> pd.DataFrame:
    concept_domain = CONCEPT_DOMAIN_BY_PIPELINE_DOMAIN.get(domain)
    if concept_domain is None or catalog is None:
        return _empty_membership_frame()
    if "code" not in frame or "code_system" not in frame:
        return _empty_membership_frame()

    keys = pd.DataFrame(
        {
            "code_system": _normalize_code_system(frame["code_system"]),
            "code": frame["code"].astype("string").str.strip().str.upper(),
        },
        index=frame.index,
    )
    unique_keys = keys.drop_duplicates().reset_index(drop=True)
    rules = [
        concept for concept in catalog.concepts if concept.domain == concept_domain
    ]
    matched_keys: list[pd.DataFrame] = []
    for concept in rules:
        matches = unique_keys["code_system"].eq(concept.code_system)
        if concept.match_type == "exact":
            matches &= unique_keys["code"].eq(concept.code)
        elif concept.match_type == "prefix":
            matches &= unique_keys["code"].str.startswith(concept.code, na=False)
        else:
            matches &= unique_keys["code"].str.contains(
                concept.code,
                regex=True,
                na=False,
            )
        if not matches.any():
            continue
        matched = unique_keys.loc[matches].copy()
        matched["element_id"] = f"source.{concept.concept_set_id}"
        matched["logical_domain"] = domain
        matched["include"] = concept.include
        matched["match_type"] = concept.match_type
        matched["matched_code"] = concept.code
        matched_keys.append(matched)
    if not matched_keys:
        return _empty_membership_frame()

    mapping = pd.concat(matched_keys, ignore_index=True)
    source_keys = keys.copy()
    source_keys["source_record_id"] = record_ids.astype("string")
    memberships = source_keys.merge(
        mapping,
        on=["code_system", "code"],
        how="inner",
        sort=False,
    )
    memberships = memberships.rename(columns={"code": "source_code"})
    return memberships.loc[:, MEMBERSHIP_COLUMNS].reset_index(drop=True)


def _source_records(
    frame: pd.DataFrame,
    *,
    domain: str,
    source_file: str,
    record_ids: pd.Series,
    row_numbers: pd.Series,
    observed_order: pd.Series,
) -> pd.DataFrame:
    records = pd.DataFrame(index=frame.index)
    records["source_record_id"] = record_ids.astype("string")
    records["logical_domain"] = domain
    records["source_file"] = source_file
    records["source_row_number"] = row_numbers.astype("Int64")
    records["observed_order"] = observed_order.astype("Int64")

    raw_mapping = {
        "patient_id": "patient_id",
        "encounter_id": "encounter_id",
        "unique_id": "unique_id",
        "date": "date",
        "start_date": "start_date",
        "end_date": "end_date",
        "start_date_derived_by_TriNetX": "start_date_derived_by_TriNetX",
        "end_date_derived_by_TriNetX": "end_date_derived_by_TriNetX",
        "lab_result_num_val": "lab_result_num_val",
        "lab_result_text_val": "lab_result_text_val",
        "value": "value",
        "text_value": "text_value",
        "specimen": "specimen",
        "specimen_id": "specimen_id",
        "panel_id": "panel_id",
        "principal_diagnosis_indicator": "principal_diagnosis_indicator",
        "admitting_diagnosis": "admitting_diagnosis",
        "reason_for_visit": "reason_for_visit",
        "principal_procedure_indicator": "principal_procedure_indicator",
        "medication_text": "medication_text",
        "order_status": "order_status",
        "status": "status",
        "route": "route",
        "brand": "brand",
        "strength": "strength",
        "type": "type",
        "sex": "sex",
        "race": "race",
        "ethnicity": "ethnicity",
        "year_of_birth": "year_of_birth",
        "patient_regional_location": "patient_regional_location",
        "month_year_death": "month_year_death",
        "derived_by_TriNetX": "derived_by_TriNetX",
        "source_id": "source_id",
    }
    for output_column, input_column in raw_mapping.items():
        records[output_column] = _string_values(frame, input_column)

    records["code_system_raw"] = _string_values(frame, "code_system")
    records["code_system"] = _normalize_code_system(records["code_system_raw"])
    records["code_raw"] = _string_values(frame, "code")
    records["code"] = records["code_raw"].str.strip().str.upper()
    records["units_of_measure_raw"] = _string_values(frame, "units_of_measure")
    records["units_of_measure"] = (
        records["units_of_measure_raw"].str.strip().str.lower()
    )

    event_source = "date"
    if domain == "medications":
        event_source = "start_date"
    elif domain == "encounter":
        event_source = "start_date"
    records["event_datetime"] = _parse_timestamps(records[event_source])
    records["timestamp_precision"] = _timestamp_precision(records[event_source])
    records["start_datetime"] = _parse_timestamps(records["start_date"])
    records["start_timestamp_precision"] = _timestamp_precision(records["start_date"])
    records["end_datetime"] = _parse_timestamps(records["end_date"])
    records["end_timestamp_precision"] = _timestamp_precision(records["end_date"])

    numeric_source = None
    if domain == "labs":
        numeric_source = "lab_result_num_val"
    elif domain == "vitals":
        numeric_source = "value"
    if numeric_source is None:
        records["numeric_value"] = pd.Series(
            pd.NA,
            index=records.index,
            dtype="Float64",
        )
    else:
        records["numeric_value"] = pd.to_numeric(
            records[numeric_source], errors="coerce"
        ).astype("Float64")

    for column in _STRING_COLUMNS:
        records[column] = records[column].astype("string")
    return records.loc[:, SOURCE_EVENT_COLUMNS].reset_index(drop=True)


def _empty_source_frame() -> pd.DataFrame:
    frame = pd.DataFrame(index=pd.RangeIndex(0))
    for column in SOURCE_EVENT_COLUMNS:
        if column in {"source_row_number", "observed_order"}:
            frame[column] = pd.Series(dtype="Int64")
        elif column in {"event_datetime", "start_datetime", "end_datetime"}:
            frame[column] = pd.Series(dtype="datetime64[ns]")
        elif column == "numeric_value":
            frame[column] = pd.Series(dtype="Float64")
        else:
            frame[column] = pd.Series(dtype="string")
    return frame.loc[:, SOURCE_EVENT_COLUMNS]


def _empty_membership_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "source_record_id": pd.Series(dtype="string"),
            "element_id": pd.Series(dtype="string"),
            "logical_domain": pd.Series(dtype="string"),
            "include": pd.Series(dtype="boolean"),
            "match_type": pd.Series(dtype="string"),
            "code_system": pd.Series(dtype="string"),
            "matched_code": pd.Series(dtype="string"),
        },
        columns=MEMBERSHIP_COLUMNS,
    )


def _empty_observability_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "patient_id": pd.Series(dtype="string"),
            "logical_domain": pd.Series(dtype="string"),
            "event_datetime": pd.Series(dtype="datetime64[ns]"),
            "timestamp_precision": pd.Series(dtype="string"),
            "event_count": pd.Series(dtype="Int64"),
        },
        columns=OBSERVABILITY_COLUMNS,
    )


def _empty_gas_candidate_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "patient_id": pd.Series(dtype="string"),
            "encounter_id": pd.Series(dtype="string"),
        },
        columns=GAS_CANDIDATE_COLUMNS,
    )


def _observability_rows(frame: pd.DataFrame, *, domain: str) -> pd.DataFrame:
    if domain not in CONCEPT_DOMAIN_BY_PIPELINE_DOMAIN or "patient_id" not in frame:
        return _empty_observability_frame()
    event_column = "start_date" if domain == "medications" else "date"
    if event_column not in frame:
        return _empty_observability_frame()
    rows = pd.DataFrame(
        {
            "patient_id": frame["patient_id"].astype("string"),
            "logical_domain": domain,
            "event_datetime": _parse_timestamps(frame[event_column]),
            "timestamp_precision": _timestamp_precision(frame[event_column]),
        }
    )
    rows = rows.loc[rows["patient_id"].notna()].copy()
    if rows.empty:
        return _empty_observability_frame()
    grouped = (
        rows.groupby(
            [
                "patient_id",
                "logical_domain",
                "event_datetime",
                "timestamp_precision",
            ],
            dropna=False,
            sort=False,
        )
        .size()
        .rename("event_count")
        .reset_index()
    )
    grouped["event_count"] = grouped["event_count"].astype("Int64")
    grouped["patient_id"] = grouped["patient_id"].astype("string")
    grouped["logical_domain"] = grouped["logical_domain"].astype("string")
    grouped["timestamp_precision"] = grouped["timestamp_precision"].astype("string")
    return grouped.loc[:, OBSERVABILITY_COLUMNS]


def _string_values(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame:
        return pd.Series(pd.NA, index=frame.index, dtype="string")
    return frame[column].astype("string")


def _normalize_code_system(series: pd.Series) -> pd.Series:
    return (
        series.astype("string")
        .str.strip()
        .str.upper()
        .str.replace(r"[^A-Z0-9]", "", regex=True)
    )


def _parse_timestamps(series: pd.Series) -> pd.Series:
    text = series.astype("string").str.strip()
    parsed = pd.Series(pd.NaT, index=series.index, dtype="datetime64[ns]")
    compact_date = text.str.fullmatch(r"\d{8}", na=False)
    compact_timestamp = text.str.fullmatch(r"\d{14}", na=False)
    parsed.loc[compact_date] = pd.to_datetime(
        text.loc[compact_date], format="%Y%m%d", errors="coerce"
    )
    parsed.loc[compact_timestamp] = pd.to_datetime(
        text.loc[compact_timestamp], format="%Y%m%d%H%M%S", errors="coerce"
    )
    other = ~(compact_date | compact_timestamp) & text.notna() & text.ne("")
    parsed.loc[other] = pd.to_datetime(
        text.loc[other],
        format="mixed",
        errors="coerce",
    )
    return parsed


def _timestamp_precision(series: pd.Series) -> pd.Series:
    text = series.astype("string").str.strip()
    date_only = text.str.fullmatch(r"\d{8}|\d{4}-\d{2}-\d{2}", na=False)
    present = text.notna() & text.ne("")
    result = pd.Series(pd.NA, index=series.index, dtype="string")
    result.loc[present] = "timestamp"
    result.loc[date_only] = "date_only"
    return result


def _relative_source_path(path: Path, data_dir: Path) -> str:
    source = Path(path).resolve()
    try:
        return source.relative_to(Path(data_dir).resolve()).as_posix()
    except ValueError:
        return source.name

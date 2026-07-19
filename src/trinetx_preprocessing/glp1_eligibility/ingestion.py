"""Out-of-core source ingestion for the GLP-1 eligibility database."""

from __future__ import annotations

import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import duckdb
import pyarrow as pa

from ..filesystem import remove_tree_strict
from .config import GLP1Config
from .monitoring import RunStateWriter
from .provenance import InputInventory
from .sql_helpers import timestamp_precision_sql

_PATIENT_CONCEPT_INGEST_BUCKET_COUNT = 32
_VITAL_INGEST_BUCKET_COUNT = _PATIENT_CONCEPT_INGEST_BUCKET_COUNT
_VITAL_INGEST_SCRATCH_PREFIX = ".trinetx-glp1-vital-ingest-"
_PATIENT_CONCEPT_INGEST_SCRATCH_PREFIX = ".trinetx-glp1-concept-ingest-"
_RAW_OBSERVABILITY_SCRATCH_PREFIX = ".trinetx-glp1-observability-scan-"
_RAW_OBSERVABILITY_BATCH_ROW_TARGET = 1_000_000
_RAW_OBSERVABILITY_SCAN_MEMORY_MIB = 512


@dataclass(frozen=True)
class _PatientConceptSourceSpec:
    """Describe one patient-keyed, concept-filtered source table."""

    concept_domain: str
    source_domains: tuple[str, ...]
    table_name: str
    event_column: str
    source_columns: tuple[str, ...]
    extra_datetime_columns: tuple[tuple[str, str], ...] = ()
    scratch_prefix: str = _PATIENT_CONCEPT_INGEST_SCRATCH_PREFIX


def ingest_core_sources(
    connection: duckdb.DuckDBPyConnection,
    *,
    input_root: Path,
    inventory: InputInventory,
    config: GLP1Config,
    state: RunStateWriter | None = None,
) -> dict[str, int]:
    """Ingest gas-related measurements and candidate patient context once.

    Clinical domains are filtered to configured concepts while DuckDB scans the
    CSV inputs. Encounter and patient rows are retained only for patients with a
    gas candidate, which bounds the database independently of raw export size.
    """

    root = Path(input_root).resolve()
    _load_source_path_map(connection, root, inventory)
    if state is not None:
        state.update(
            phase="source_cohort_flow",
            current_domain="encounter",
            message="Aggregating source-patient and adult encounter flow counts.",
        )
    _create_source_cohort_flow_base(connection, root, inventory, config)
    rows: dict[str, int] = {}

    if state is not None:
        state.update(phase="source_ingestion", current_domain="labs")
    _create_lab_measurements(connection, root, inventory)
    rows["source_lab_measurement"] = _row_count(
        connection, "source_lab_measurement"
    )
    _create_gas_candidate_ids(connection)
    rows["gas_candidate_id"] = _row_count(connection, "gas_candidate_id")
    _create_candidate_membership_tables(connection)

    if state is not None:
        state.update(
            phase="source_ingestion",
            current_domain="encounter",
            rows_processed=sum(rows.values()),
        )
    _create_encounters(connection, root, inventory)
    rows["source_encounter"] = _row_count(connection, "source_encounter")

    if state is not None:
        state.update(
            phase="source_ingestion",
            current_domain="patient",
            rows_processed=sum(rows.values()),
        )
    _create_patients(connection, root, inventory)
    rows["source_patient"] = _row_count(connection, "source_patient")

    if state is not None:
        state.update(
            phase="source_ingestion",
            current_domain="vitals",
            rows_processed=sum(rows.values()),
        )
    _create_vital_measurements(connection, root, inventory)
    rows["source_vital_measurement"] = _row_count(
        connection, "source_vital_measurement"
    )

    for domain, table_name, builder in (
        ("diagnosis", "source_diagnosis", _create_diagnoses),
        ("procedure", "source_procedure", _create_procedures),
        ("medication", "source_medication", _create_medications),
    ):
        if state is not None:
            state.update(
                phase="source_ingestion",
                current_domain=domain,
                rows_processed=sum(rows.values()),
            )
        builder(connection, root, inventory)
        rows[table_name] = _row_count(connection, table_name)

    _update_retained_date_coverage(connection)

    if state is not None:
        state.update(
            phase="source_ingestion_complete",
            current_domain=None,
            rows_processed=sum(rows.values()),
            message="Core source ingestion completed.",
        )
    return rows


def build_raw_observability_summaries(
    connection: duckdb.DuckDBPyConnection,
    *,
    input_root: Path,
    inventory: InputInventory,
    state: RunStateWriter | None = None,
) -> None:
    """Aggregate all candidate-patient source history without concept filtering."""

    root = Path(input_root).resolve()
    if _row_count(connection, "analysis_glp1_eligibility") == 0:
        for domain in ("diagnosis", "labs", "vitals", "procedure", "medication"):
            _create_empty_raw_observability(connection, domain)
        return

    connection.execute(
        """
        CREATE OR REPLACE TEMP TABLE raw_observability_index AS
        SELECT
            index_event_id,
            patient_id,
            index_date
        FROM analysis_glp1_eligibility
        WHERE patient_id IS NOT NULL
        """
    )
    connection.execute(
        """
        CREATE OR REPLACE TEMP TABLE raw_observability_patient AS
        SELECT DISTINCT patient_id
        FROM raw_observability_index
        """
    )
    try:
        specifications = (
            ("diagnosis", ("diagnosis",), "date", 730),
            ("labs", ("labs",), "date", 365),
            ("vitals", ("vitals",), "date", None),
            ("procedure", ("procedure",), "date", None),
            (
                "medication",
                ("medication", "medication_ingredient"),
                "start_date",
                730,
            ),
        )
        for domain, source_domains, event_column, lookback_days in specifications:
            if state is not None:
                state.update(
                    phase="raw_observability",
                    current_domain=domain,
                    message=f"Aggregating unfiltered {domain} history.",
                )
            _create_raw_observability(
                connection,
                root=root,
                inventory=inventory,
                table_domain=domain,
                source_domains=source_domains,
                event_column=event_column,
                lookback_days=lookback_days,
            )
    finally:
        connection.execute("DROP TABLE IF EXISTS raw_observability_patient")
        connection.execute("DROP TABLE IF EXISTS raw_observability_index")


def _update_retained_date_coverage(
    connection: duckdb.DuckDBPyConnection,
) -> None:
    """Record date coverage for rows retained by the analytic source filters."""

    connection.execute(
        """
        CREATE OR REPLACE TEMP TABLE retained_source_date_coverage AS
        WITH events AS (
            SELECT source_file, event_datetime FROM source_lab_measurement
            UNION ALL
            SELECT source_file, encounter_start FROM source_encounter
            UNION ALL
            SELECT source_file, event_datetime FROM source_vital_measurement
            UNION ALL
            SELECT source_file, event_datetime FROM source_diagnosis
            UNION ALL
            SELECT source_file, event_datetime FROM source_procedure
            UNION ALL
            SELECT source_file, event_datetime FROM source_medication
        )
        SELECT source_file, min(event_datetime) AS min_event_date,
               max(event_datetime) AS max_event_date
        FROM events
        WHERE event_datetime IS NOT NULL
        GROUP BY source_file
        """
    )
    connection.execute(
        """
        UPDATE source_file_inventory AS inventory
        SET min_event_date = coverage.min_event_date,
            max_event_date = coverage.max_event_date
        FROM retained_source_date_coverage AS coverage
        WHERE inventory.source_file = coverage.source_file
        """
    )
    connection.execute(
        """
        UPDATE run_manifest
        SET source_min_date = (
                SELECT min(min_event_date) FROM retained_source_date_coverage
            ),
            source_max_date = (
                SELECT max(max_event_date) FROM retained_source_date_coverage
            )
        """
    )
    connection.execute("DROP TABLE retained_source_date_coverage")


def _create_source_cohort_flow_base(
    connection: duckdb.DuckDBPyConnection,
    root: Path,
    inventory: InputInventory,
    config: GLP1Config,
) -> None:
    patient_files = _domain_files(root, inventory, "patient")
    encounter_files = _domain_files(root, inventory, "encounter")
    encounter_types = ", ".join(
        _sql_string(value) for value in config.study.index_encounter_types
    )
    start_condition = (
        "TRUE"
        if config.study.study_start is None
        else (
            "encounter_start::DATE >= DATE "
            + _sql_string(config.study.study_start.isoformat())
        )
    )
    end_condition = (
        "TRUE"
        if config.study.study_end is None
        else (
            "encounter_start::DATE <= DATE "
            + _sql_string(config.study.study_end.isoformat())
        )
    )
    connection.execute(
        f"""
        CREATE OR REPLACE TABLE source_cohort_flow_base AS
        WITH patient_raw AS (
            SELECT patient_id, try_cast(year_of_birth AS INTEGER) AS year_of_birth
            FROM {_read_csv_sql(patient_files)}
        ), patient AS (
            SELECT patient_id, min(year_of_birth) AS year_of_birth
            FROM patient_raw
            WHERE patient_id IS NOT NULL
            GROUP BY patient_id
        ), encounter_raw AS (
            SELECT
                encounter_id,
                patient_id,
                {_timestamp_sql("start_date")} AS encounter_start,
                type
            FROM {_read_csv_sql(encounter_files)}
        ), adult_candidate AS (
            SELECT encounter.encounter_id, encounter.patient_id
            FROM encounter_raw AS encounter
            JOIN patient USING (patient_id)
            WHERE encounter.encounter_id IS NOT NULL
              AND encounter.encounter_start IS NOT NULL
              AND year(encounter.encounter_start) - patient.year_of_birth
                    >= {config.study.adult_age_min}
              AND upper(trim(encounter.type)) IN ({encounter_types})
              AND {start_condition}
              AND {end_condition}
        )
        SELECT
            1 AS stage_order,
            count(*)::BIGINT AS row_count,
            count(*)::BIGINT AS unique_patient_count
        FROM patient
        UNION ALL
        SELECT
            2,
            count(DISTINCT encounter_id)::BIGINT,
            count(DISTINCT patient_id)::BIGINT
        FROM adult_candidate
        """
    )


def _load_source_path_map(
    connection: duckdb.DuckDBPyConnection,
    root: Path,
    inventory: InputInventory,
) -> None:
    connection.execute(
        """
        CREATE OR REPLACE TABLE source_path_map (
            absolute_path VARCHAR PRIMARY KEY,
            source_file VARCHAR NOT NULL,
            logical_domain VARCHAR NOT NULL
        )
        """
    )
    connection.executemany(
        "INSERT INTO source_path_map VALUES (?, ?, ?)",
        [
            (
                str((root / item.source_file).resolve()),
                item.source_file,
                item.logical_domain,
            )
            for item in inventory.files
        ],
    )


def _create_lab_measurements(
    connection: duckdb.DuckDBPyConnection,
    root: Path,
    inventory: InputInventory,
) -> None:
    files = _domain_files(root, inventory, "labs")
    columns = _domain_columns(inventory, "labs")
    raw = _read_csv_sql(files)
    projections = _source_projection(
        columns,
        (
            "patient_id",
            "encounter_id",
            "date",
            "code_system",
            "code",
            "lab_result_num_val",
            "lab_result_text_val",
            "units_of_measure",
            "specimen",
            "specimen_id",
            "panel_id",
            "derived_by_TriNetX",
            "source_id",
        ),
    )
    hash_values = _hash_value_sql(
        columns,
        (
            "patient_id",
            "encounter_id",
            "date",
            "code_system",
            "code",
            "lab_result_num_val",
            "lab_result_text_val",
            "units_of_measure",
            "specimen",
            "specimen_id",
            "panel_id",
            "derived_by_TriNetX",
            "source_id",
        ),
    )
    connection.execute(
        f"""
        CREATE OR REPLACE TABLE source_lab_measurement AS
        SELECT
            {projections},
            {_timestamp_sql('raw."date"')} AS event_datetime,
            paths.source_file,
            sha256(concat_ws(chr(31), paths.source_file, {hash_values}))
                AS source_record_hash
        FROM {raw} AS raw
        JOIN source_path_map AS paths
          ON raw.filename = paths.absolute_path
        WHERE {_concept_membership_sql(connection, "lab")}
        """
    )


def _create_gas_candidate_ids(connection: duckdb.DuckDBPyConnection) -> None:
    connection.execute(
        f"""
        CREATE OR REPLACE TABLE gas_candidate_id AS
        SELECT DISTINCT lab.patient_id, lab.encounter_id
        FROM source_lab_measurement AS lab
        WHERE EXISTS (
            SELECT 1
            FROM concept_set AS concept
            WHERE concept.concept_set_id IN (
                'arterial_pco2', 'venous_pco2', 'unspecified_blood_pco2'
            )
              AND concept.domain = 'lab'
              AND concept.include
              AND {_normalized_code_system_sql('lab.code_system')}
                    = concept.code_system
              AND (
                    (concept.match_type = 'exact'
                     AND upper(trim(lab.code)) = concept.code)
                 OR (concept.match_type = 'prefix'
                     AND starts_with(upper(trim(lab.code)), concept.code))
                 OR (concept.match_type = 'regex'
                     AND regexp_matches(upper(trim(lab.code)), concept.code))
              )
        )
        """
    )


def _create_candidate_membership_tables(
    connection: duckdb.DuckDBPyConnection,
) -> None:
    """Materialize compact membership keys once for downstream source scans."""

    connection.execute(
        """
        CREATE OR REPLACE TEMP TABLE gas_candidate_patient AS
        SELECT DISTINCT patient_id
        FROM gas_candidate_id
        WHERE patient_id IS NOT NULL
        """
    )
    connection.execute(
        """
        CREATE OR REPLACE TEMP TABLE gas_candidate_encounter AS
        SELECT DISTINCT encounter_id
        FROM gas_candidate_id
        WHERE encounter_id IS NOT NULL
        """
    )


def _create_encounters(
    connection: duckdb.DuckDBPyConnection,
    root: Path,
    inventory: InputInventory,
) -> None:
    files = _domain_files(root, inventory, "encounter")
    columns = _domain_columns(inventory, "encounter")
    raw = _read_csv_sql(files)
    names = (
        "encounter_id",
        "patient_id",
        "start_date",
        "end_date",
        "type",
        "start_date_derived_by_TriNetX",
        "end_date_derived_by_TriNetX",
        "derived_by_TriNetX",
        "source_id",
    )
    connection.execute(
        f"""
        CREATE OR REPLACE TABLE source_encounter AS
        SELECT
            {_source_projection(columns, names)},
            {_timestamp_sql('raw."start_date"')} AS encounter_start,
            {_timestamp_sql('raw."end_date"')} AS encounter_end,
            {timestamp_precision_sql('raw."end_date"')}
                AS encounter_end_precision,
            paths.source_file,
            sha256(concat_ws(
                chr(31), paths.source_file, {_hash_value_sql(columns, names)}
            )) AS source_record_hash
        FROM {raw} AS raw
        JOIN source_path_map AS paths
          ON raw.filename = paths.absolute_path
        WHERE {_encounter_membership_sql()}
        """
    )


def _encounter_membership_sql(raw_alias: str = "raw") -> str:
    """Return bounded hash-membership predicates for candidate encounters."""

    return f"""(
        {raw_alias}."patient_id" IN (SELECT patient_id FROM gas_candidate_patient)
        OR {raw_alias}."encounter_id" IN (
            SELECT encounter_id FROM gas_candidate_encounter
        )
    )"""


def _patient_membership_sql(raw_alias: str = "raw") -> str:
    """Return bounded membership against unique gas-candidate patients."""

    return (
        f'{raw_alias}."patient_id" IN '
        "(SELECT patient_id FROM gas_candidate_patient)"
    )


def _create_patients(
    connection: duckdb.DuckDBPyConnection,
    root: Path,
    inventory: InputInventory,
) -> None:
    files = _domain_files(root, inventory, "patient")
    columns = _domain_columns(inventory, "patient")
    raw = _read_csv_sql(files)
    names = (
        "patient_id",
        "sex",
        "race",
        "ethnicity",
        "year_of_birth",
        "month_year_death",
        "patient_regional_location",
        "source_id",
    )
    connection.execute(
        f"""
        CREATE OR REPLACE TABLE source_patient AS
        SELECT
            {_source_projection(columns, names)},
            paths.source_file,
            sha256(concat_ws(
                chr(31), paths.source_file, {_hash_value_sql(columns, names)}
            )) AS source_record_hash
        FROM {raw} AS raw
        JOIN source_path_map AS paths
          ON raw.filename = paths.absolute_path
        WHERE {_patient_membership_sql()}
        """
    )


def _create_vital_measurements(
    connection: duckdb.DuckDBPyConnection,
    root: Path,
    inventory: InputInventory,
) -> None:
    _create_partitioned_patient_concept_source(
        connection,
        root=root,
        inventory=inventory,
        spec=_PatientConceptSourceSpec(
            concept_domain="vital",
            source_domains=("vitals",),
            table_name="source_vital_measurement",
            event_column="date",
            source_columns=(
                "patient_id",
                "encounter_id",
                "date",
                "code_system",
                "code",
                "value",
                "text_value",
                "units_of_measure",
                "derived_by_TriNetX",
                "source_id",
            ),
            scratch_prefix=_VITAL_INGEST_SCRATCH_PREFIX,
        ),
    )


def _partition_parquet_files(partition_directory: Path) -> tuple[Path, ...]:
    """Return data files while excluding macOS AppleDouble sidecars."""

    return tuple(
        sorted(
            path
            for path in partition_directory.rglob("*.parquet")
            if not path.name.startswith("._")
        )
    )


def _create_diagnoses(
    connection: duckdb.DuckDBPyConnection,
    root: Path,
    inventory: InputInventory,
) -> None:
    _create_partitioned_patient_concept_source(
        connection,
        root=root,
        inventory=inventory,
        spec=_PatientConceptSourceSpec(
            concept_domain="diagnosis",
            source_domains=("diagnosis",),
            table_name="source_diagnosis",
            event_column="date",
            source_columns=(
                "patient_id",
                "encounter_id",
                "date",
                "code_system",
                "code",
                "principal_diagnosis_indicator",
                "admitting_diagnosis",
                "reason_for_visit",
                "derived_by_TriNetX",
                "source_id",
            ),
        ),
    )


def _create_procedures(
    connection: duckdb.DuckDBPyConnection,
    root: Path,
    inventory: InputInventory,
) -> None:
    _create_partitioned_patient_concept_source(
        connection,
        root=root,
        inventory=inventory,
        spec=_PatientConceptSourceSpec(
            concept_domain="procedure",
            source_domains=("procedure",),
            table_name="source_procedure",
            event_column="date",
            source_columns=(
                "patient_id",
                "encounter_id",
                "date",
                "code_system",
                "code",
                "principal_procedure_indicator",
                "derived_by_TriNetX",
                "source_id",
            ),
        ),
    )


def _create_medications(
    connection: duckdb.DuckDBPyConnection,
    root: Path,
    inventory: InputInventory,
) -> None:
    _create_partitioned_patient_concept_source(
        connection,
        root=root,
        inventory=inventory,
        spec=_PatientConceptSourceSpec(
            concept_domain="medication",
            source_domains=("medication", "medication_ingredient"),
            table_name="source_medication",
            event_column="start_date",
            source_columns=(
                "patient_id",
                "encounter_id",
                "unique_id",
                "code_system",
                "code",
                "medication_text",
                "start_date",
                "end_date",
                "order_status",
                "status",
                "route",
                "brand",
                "strength",
                "derived_by_TriNetX",
                "source_id",
            ),
            extra_datetime_columns=(("end_date", "end_datetime"),),
        ),
    )


def _create_partitioned_patient_concept_source(
    connection: duckdb.DuckDBPyConnection,
    *,
    root: Path,
    inventory: InputInventory,
    spec: _PatientConceptSourceSpec,
) -> None:
    """Build one concept source with a bounded patient-partitioned join."""

    files = _domain_files_for_domains(root, inventory, spec.source_domains)
    columns = _domain_columns_for_domains(inventory, spec.source_domains)
    raw = _read_csv_sql(files)
    _create_empty_patient_concept_table(connection, spec)

    temp_directory_setting = connection.execute(
        "SELECT current_setting('temp_directory')"
    ).fetchone()[0]
    temp_directory = Path(str(temp_directory_setting)).resolve()
    temp_directory.mkdir(parents=True, exist_ok=True)
    scratch = Path(
        tempfile.mkdtemp(
            prefix=f"{spec.scratch_prefix}{spec.concept_domain}-",
            dir=temp_directory,
        )
    )
    try:
        partition_root = scratch / "patient_rows"
        connection.execute(
            f"""
            COPY (
                SELECT
                    {_source_projection(columns, spec.source_columns)},
                    paths.source_file,
                    hash(raw."patient_id") % {_PATIENT_CONCEPT_INGEST_BUCKET_COUNT}
                        AS patient_bucket
                FROM {raw} AS raw
                JOIN source_path_map AS paths
                  ON raw.filename = paths.absolute_path
                WHERE raw."patient_id" IS NOT NULL
                  AND {_concept_membership_sql(connection, spec.concept_domain)}
            ) TO {_sql_string(str(partition_root))} (
                FORMAT PARQUET,
                PARTITION_BY (patient_bucket),
                COMPRESSION SNAPPY,
                ROW_GROUP_SIZE 250000
            )
            """
        )
        _append_candidate_patient_partitions(
            connection,
            partition_root=partition_root,
            spec=spec,
        )
    finally:
        remove_tree_strict(
            scratch,
            context=f"GLP-1 {spec.concept_domain} ingestion scratch",
        )


def _create_empty_patient_concept_table(
    connection: duckdb.DuckDBPyConnection,
    spec: _PatientConceptSourceSpec,
) -> None:
    source_columns = ",\n            ".join(
        f"{_identifier(name)} VARCHAR" for name in spec.source_columns
    )
    extra_datetimes = "".join(
        f",\n            {_identifier(output_column)} TIMESTAMP"
        for _, output_column in spec.extra_datetime_columns
    )
    connection.execute(
        f"""
        CREATE OR REPLACE TABLE {_identifier(spec.table_name)} (
            {source_columns},
            event_datetime TIMESTAMP{extra_datetimes},
            source_file VARCHAR,
            source_record_hash VARCHAR
        )
        """
    )


def _append_candidate_patient_partitions(
    connection: duckdb.DuckDBPyConnection,
    *,
    partition_root: Path,
    spec: _PatientConceptSourceSpec,
) -> None:
    available_columns = frozenset(spec.source_columns)
    datetime_projections = (
        f"{_timestamp_sql(f'raw.{_identifier(spec.event_column)}')} "
        "AS event_datetime",
        *(
            f"{_timestamp_sql(f'raw.{_identifier(source_column)}')} "
            f"AS {_identifier(output_column)}"
            for source_column, output_column in spec.extra_datetime_columns
        ),
    )
    datetime_sql = ",\n                ".join(datetime_projections)
    for bucket in range(_PATIENT_CONCEPT_INGEST_BUCKET_COUNT):
        partition_directory = partition_root / f"patient_bucket={bucket}"
        files = _partition_parquet_files(partition_directory)
        if not files:
            continue
        connection.execute(
            f"""
            INSERT INTO {_identifier(spec.table_name)}
            SELECT
                {_source_projection(available_columns, spec.source_columns)},
                {datetime_sql},
                raw.source_file,
                sha256(concat_ws(
                    chr(31), raw.source_file,
                    {_hash_value_sql(available_columns, spec.source_columns)}
                )) AS source_record_hash
            FROM {_read_parquet_sql(files)} AS raw
            WHERE raw."patient_id" IN (
                SELECT patient_id
                FROM gas_candidate_patient
                WHERE hash(patient_id)
                    % {_PATIENT_CONCEPT_INGEST_BUCKET_COUNT} = {bucket}
            )
            """
        )


def _domain_files(
    root: Path, inventory: InputInventory, domain: str
) -> tuple[Path, ...]:
    files = tuple(
        root / item.source_file
        for item in inventory.files
        if item.logical_domain == domain
    )
    if not files:
        raise ValueError(f"No inventoried source files for required domain: {domain}")
    return files


def _domain_files_for_domains(
    root: Path,
    inventory: InputInventory,
    domains: tuple[str, ...],
) -> tuple[Path, ...]:
    files = tuple(
        root / item.source_file
        for item in inventory.files
        if item.logical_domain in domains
    )
    if not files:
        raise ValueError(
            "No inventoried source files for required domain(s): "
            + ", ".join(domains)
        )
    return files


def _domain_columns(inventory: InputInventory, domain: str) -> frozenset[str]:
    return frozenset(
        column
        for item in inventory.files
        if item.logical_domain == domain
        for column in item.column_names
    )


def _domain_columns_for_domains(
    inventory: InputInventory,
    domains: tuple[str, ...],
) -> frozenset[str]:
    return frozenset(
        column
        for item in inventory.files
        if item.logical_domain in domains
        for column in item.column_names
    )


def _create_raw_observability(
    connection: duckdb.DuckDBPyConnection,
    *,
    root: Path,
    inventory: InputInventory,
    table_domain: str,
    source_domains: tuple[str, ...],
    event_column: str,
    lookback_days: int | None,
) -> None:
    files = _domain_files_for_domains(root, inventory, source_domains)
    output_table = _identifier(f"raw_{table_domain}_observability")
    _create_empty_raw_observability(connection, table_domain)
    event_datetime_expression = _timestamp_sql("raw.event_value")
    count_expression = (
        "NULL::BIGINT AS event_count"
        if lookback_days is None
        else (
            f"count(*) FILTER (WHERE {event_datetime_expression} BETWEEN "
            f"analysis.index_date - INTERVAL {lookback_days} DAY "
            "AND analysis.index_date) AS event_count"
        )
    )
    merged_count_expression = (
        "NULL::BIGINT AS event_count"
        if lookback_days is None
        else "sum(event_count)::BIGINT AS event_count"
    )
    selected_patient_ids = pa.array(
        tuple(
            row[0]
            for row in connection.execute(
                "SELECT patient_id FROM raw_observability_patient"
            ).fetchall()
        ),
        type=pa.string(),
    )
    connection.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE raw_observability_accumulator AS
        SELECT * FROM {output_table} WHERE FALSE
        """
    )
    try:
        temp_directory_setting = connection.execute(
            "SELECT current_setting('temp_directory')"
        ).fetchone()[0]
        with _raw_observability_batch_reader(
            files,
            event_column=event_column,
            selected_patient_ids=selected_patient_ids,
            temp_directory=Path(str(temp_directory_setting)).resolve(),
        ) as reader:
            for batch in reader:
                connection.register(
                    "raw_observability_batch",
                    pa.Table.from_batches([batch]),
                )
                try:
                    connection.execute(
                        f"""
                        CREATE OR REPLACE TEMP TABLE raw_observability_partial AS
                        SELECT
                            analysis.index_event_id,
                            min({event_datetime_expression}) FILTER (
                                WHERE {event_datetime_expression}
                                    <= analysis.index_date
                            ) AS first_observed_event_date,
                            {count_expression}
                        FROM raw_observability_index AS analysis
                        JOIN raw_observability_batch AS raw USING (patient_id)
                        GROUP BY analysis.index_event_id
                        """
                    )
                finally:
                    connection.unregister("raw_observability_batch")
                connection.execute(
                    f"""
                    CREATE OR REPLACE TEMP TABLE raw_observability_merged AS
                    SELECT
                        index_event_id,
                        min(first_observed_event_date)
                            AS first_observed_event_date,
                        {merged_count_expression}
                    FROM (
                        SELECT * FROM raw_observability_accumulator
                        UNION ALL
                        SELECT * FROM raw_observability_partial
                    )
                    GROUP BY index_event_id
                    """
                )
                connection.execute("DELETE FROM raw_observability_accumulator")
                connection.execute(
                    """
                    INSERT INTO raw_observability_accumulator
                    SELECT * FROM raw_observability_merged
                    """
                )
        connection.execute(
            f"INSERT INTO {output_table} SELECT * FROM raw_observability_accumulator"
        )
    finally:
        connection.execute("DROP TABLE IF EXISTS raw_observability_merged")
        connection.execute("DROP TABLE IF EXISTS raw_observability_partial")
        connection.execute("DROP TABLE IF EXISTS raw_observability_accumulator")


@contextmanager
def _raw_observability_batch_reader(
    files: tuple[Path, ...],
    *,
    event_column: str,
    selected_patient_ids: pa.Array,
    temp_directory: Path,
    row_target: int = _RAW_OBSERVABILITY_BATCH_ROW_TARGET,
) -> Iterator[pa.RecordBatchReader]:
    """Stream selected raw patient/date rows through a bounded connection."""

    if row_target < 1:
        raise ValueError("row_target must be at least 1")
    temp_directory.mkdir(parents=True, exist_ok=True)
    scratch = Path(
        tempfile.mkdtemp(
            prefix=_RAW_OBSERVABILITY_SCRATCH_PREFIX,
            dir=temp_directory,
        )
    )
    scan_connection = duckdb.connect()
    reader: pa.RecordBatchReader | None = None
    try:
        scan_connection.execute("SET preserve_insertion_order = false")
        scan_connection.execute(
            f"SET memory_limit = '{_RAW_OBSERVABILITY_SCAN_MEMORY_MIB}MiB'"
        )
        scan_connection.execute("SET threads = 1")
        scan_connection.execute("SET temp_directory = ?", [str(scratch)])
        scan_connection.register(
            "raw_observability_patient",
            pa.table({"patient_id": selected_patient_ids}),
        )
        raw = _read_csv_sql(files)
        reader = scan_connection.execute(
            f"""
            SELECT
                raw."patient_id" AS patient_id,
                raw.{_identifier(event_column)} AS event_value
            FROM {raw} AS raw
            WHERE raw."patient_id" IS NOT NULL
              AND raw."patient_id" IN (
                  SELECT patient_id FROM raw_observability_patient
              )
            """
        ).to_arrow_reader(row_target)
        yield reader
    finally:
        if reader is not None:
            reader.close()
        try:
            scan_connection.unregister("raw_observability_patient")
        except duckdb.InvalidInputException:
            pass
        scan_connection.close()
        remove_tree_strict(
            scratch,
            context="GLP-1 raw observability scan scratch",
        )


def _create_empty_raw_observability(
    connection: duckdb.DuckDBPyConnection,
    domain: str,
) -> None:
    connection.execute(
        f"""
        CREATE OR REPLACE TABLE {_identifier(f"raw_{domain}_observability")} AS
        SELECT
            NULL::VARCHAR AS index_event_id,
            NULL::TIMESTAMP AS first_observed_event_date,
            NULL::BIGINT AS event_count
        WHERE FALSE
        """
    )


def _read_csv_sql(files: tuple[Path, ...]) -> str:
    paths = ", ".join(_sql_string(str(path.resolve())) for path in files)
    return (
        "read_csv(["
        + paths
        + "], header=true, all_varchar=true, union_by_name=true, "
        "filename=true, null_padding=true)"
    )


def _read_parquet_sql(files: tuple[Path, ...]) -> str:
    paths = ", ".join(_sql_string(str(path.resolve())) for path in files)
    return (
        "read_parquet(["
        + paths
        + "], union_by_name=true, hive_partitioning=false)"
    )


def _source_projection(columns: frozenset[str], names: tuple[str, ...]) -> str:
    return ",\n            ".join(
        f'raw."{name}" AS "{name}"'
        if name in columns
        else f'NULL::VARCHAR AS "{name}"'
        for name in names
    )


def _hash_value_sql(columns: frozenset[str], names: tuple[str, ...]) -> str:
    return ", ".join(
        f'coalesce(raw."{name}", \'\')' if name in columns else "''"
        for name in names
    )


def _concept_membership_sql(
    connection: duckdb.DuckDBPyConnection,
    domain: str,
    raw_alias: str = "raw",
) -> str:
    """Compile concept membership without generic correlation for exact rules."""

    rules = connection.execute(
        """
        SELECT code_system, code, match_type
        FROM concept_set
        WHERE domain = ? AND include
        ORDER BY code_system, code, match_type
        """,
        [domain],
    ).fetchall()
    code_system = _normalized_code_system_sql(f'{raw_alias}."code_system"')
    code = f'upper(trim({raw_alias}."code"))'
    predicates: list[str] = []
    exact_by_system: dict[str, set[str]] = {}
    for rule_system, rule_code, match_type in rules:
        if str(match_type) == "exact":
            exact_by_system.setdefault(str(rule_system), set()).add(str(rule_code))
    for rule_system in sorted(exact_by_system):
        rule_codes = ", ".join(
            _sql_string(rule_code) for rule_code in sorted(exact_by_system[rule_system])
        )
        predicates.append(
            f"({code_system} = {_sql_string(rule_system)} AND {code} IN ({rule_codes}))"
        )
    predicates.extend(
        f"({code_system} = {_sql_string(str(rule_system))} "
        f"AND starts_with({code}, {_sql_string(str(rule_code))}))"
        for rule_system, rule_code, match_type in rules
        if str(match_type) == "prefix"
    )
    predicates.extend(
        f"({code_system} = {_sql_string(str(rule_system))} "
        f"AND regexp_matches({code}, {_sql_string(str(rule_code))}))"
        for rule_system, rule_code, match_type in rules
        if str(match_type) == "regex"
    )
    if not predicates:
        return "FALSE"
    return "(\n" + "\nOR ".join(predicates) + "\n)"


def _normalized_code_system_sql(expression: str) -> str:
    return (
        f"regexp_replace(upper(trim({expression})), "
        "'[^A-Z0-9]', '', 'g')"
    )


def _timestamp_sql(expression: str) -> str:
    """Parse ISO values and compact TriNetX dates without failed first casts."""

    trimmed = f"trim({expression})"
    return (
        f"CASE length({trimmed}) "
        f"WHEN 8 THEN try_strptime({trimmed}, '%Y%m%d') "
        f"WHEN 14 THEN try_strptime({trimmed}, '%Y%m%d%H%M%S') "
        f"ELSE try_cast({trimmed} AS TIMESTAMP) END"
    )


def _sql_string(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _row_count(connection: duckdb.DuckDBPyConnection, table: str) -> int:
    return int(connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])

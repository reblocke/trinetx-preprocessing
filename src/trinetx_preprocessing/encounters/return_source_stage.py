"""Verified patient partitions of unchanged raw history for return execution.

No clinical eligibility, outcome, horizon or encounter-setting filter is applied.
The stage retains required typed source fields and duplicate multiplicity. Its
trusted manifest is prerequisite evidence, never product acceptance.
"""

from __future__ import annotations

import json
import shutil
import time
import uuid
from pathlib import Path

import duckdb
import pyarrow.parquet as pq

from ..combined_preprocessing.builder import require_safe_output_location
from ..filesystem import fsync_directory_strict, fsync_file_strict, write_text_atomic
from .builder import VARIANTS, literal, sha256
from .compatibility import no_symlinks

STAGE_VERSION = "1.0"
REQUIRED_MEMBERSHIP_ELEMENTS = (
    "source.arterial_pco2",
    "source.venous_pco2",
    "source.unspecified_blood_pco2",
)
COLUMNS = {
    "source_encounter": (
        "patient_id",
        "encounter_id",
        "source_record_id",
        "source_file",
        "source_row_number",
        "source_id",
        "type",
        "start_datetime",
        "end_datetime",
        "start_timestamp_precision",
        "end_timestamp_precision",
        "start_date_derived_by_TriNetX",
        "end_date_derived_by_TriNetX",
    ),
    "source_diagnosis": (
        "patient_id",
        "encounter_id",
        "source_record_id",
        "source_file",
        "source_row_number",
        "source_id",
        "code_system",
        "code",
        "event_datetime",
        "timestamp_precision",
    ),
    "source_lab_measurement": (
        "patient_id",
        "encounter_id",
        "source_record_id",
        "source_file",
        "source_row_number",
        "source_id",
        "code_system",
        "code",
        "event_datetime",
        "timestamp_precision",
        "specimen",
        "specimen_id",
        "panel_id",
        "numeric_value",
        "units_of_measure",
    ),
    "source_patient": ("patient_id", "month_year_death"),
    "patient_observability": ("patient_id", "last_event_datetime"),
    "element_membership": ("source_record_id", "element_id", "include"),
}


def _connect(database, parent_bundle, work_dir, partitions):
    no_symlinks(work_dir).mkdir(mode=0o700, parents=True, exist_ok=False)
    db = duckdb.connect()
    db.execute("SET threads=1")
    db.execute("SET memory_limit='3072MiB'")
    db.execute("SET temp_directory=?", [str(work_dir)])
    db.execute(f"ATTACH {literal(no_symlinks(database))} AS canonical (READ_ONLY)")
    files = [
        no_symlinks(parent_bundle / f"encounter_features_{v.lower()}.parquet")
        for v in VARIANTS
    ]
    paths = "[" + ",".join(literal(p) for p in files) + "]"
    db.execute(
        "CREATE TEMP TABLE original_patients AS SELECT DISTINCT "
        f"patient_id::VARCHAR patient_id FROM read_parquet({paths})"
    )
    if db.execute(
        "SELECT count(*) FROM original_patients WHERE patient_id IS NULL"
    ).fetchone()[0]:
        db.close()
        raise ValueError("Parent contains a null original patient key")
    # A source record may legitimately occur more than once. This mapping is
    # distinct; it routes memberships without multiplying their multiplicity.
    # Only required memberships consume this map. Keep unrelated laboratory
    # history in the raw laboratory stage without materializing its routing here.
    # Materialization gives the optimizer the actual required-key cardinality;
    # correlated EXISTS can otherwise build a delimiter table of all lab IDs.
    # No include predicate: false/null memberships are required evidence too.
    elements = ",".join(literal(e) for e in REQUIRED_MEMBERSHIP_ELEMENTS)
    db.execute(
        "CREATE TEMP TABLE required_lab_records AS SELECT DISTINCT source_record_id "
        "FROM canonical.element_membership "
        f"WHERE element_id IN ({elements})"
    )
    db.execute(
        "CREATE TEMP TABLE lab_patient_buckets AS SELECT DISTINCT "
        "s.source_record_id,"
        f"hash(s.patient_id::VARCHAR)%{partitions} AS _return_bucket "
        "FROM canonical.source_lab_measurement s SEMI JOIN original_patients p "
        "ON s.patient_id=p.patient_id "
        "SEMI JOIN required_lab_records m ON m.source_record_id=s.source_record_id"
    )
    db.execute("DROP TABLE required_lab_records")
    return db


def _expected(db, table, partitions):
    # Verifier uses the full canonical relation and original patient membership.
    # It never derives expected source values or membership from staged rows.
    fields = ",".join(f's."{c}"' for c in COLUMNS[table])
    if table == "element_membership":
        elements = ",".join(literal(e) for e in REQUIRED_MEMBERSHIP_ELEMENTS)
        return (
            f"SELECT {fields},p._return_bucket FROM canonical.{table} s "
            "JOIN lab_patient_buckets p USING (source_record_id) "
            f"WHERE s.element_id IN ({elements})"
        )
    return (
        f"SELECT {fields}, hash(s.patient_id::VARCHAR)%{partitions} AS _return_bucket "
        f"FROM canonical.{table} s WHERE EXISTS (SELECT 1 FROM original_patients p "
        "WHERE p.patient_id=s.patient_id)"
    )


def _read_manifest(stage, expected_manifest_sha256, identity):
    stage = no_symlinks(stage)
    path = no_symlinks(stage / "manifest.json")
    if sha256(path) != expected_manifest_sha256:
        raise ValueError("Source-stage manifest differs from trusted digest")
    manifest = json.loads(path.read_text())
    n = manifest.get("partitions")
    if (
        manifest.get("stage_contract_version") != STAGE_VERSION
        or manifest.get("status") != "verified"
        or manifest.get("identity") != identity
        or manifest.get("required_membership_elements")
        != list(REQUIRED_MEMBERSHIP_ELEMENTS)
        or type(n) is not int
        or not 1 <= n <= 1024
    ):
        raise ValueError("Unsupported or mismatched source-stage contract")
    names = {f"{b:04d}_{table}.parquet" for b in range(n) for table in COLUMNS}
    if set(manifest.get("outputs", {})) != names:
        raise ValueError("Source-stage inventory differs")
    if {p.name for p in stage.iterdir() if not p.name.startswith("._")} != names | {
        "manifest.json"
    }:
        raise ValueError("Source-stage directory inventory differs")
    return manifest


def _verify_file(stage, manifest, name):
    p = no_symlinks(stage / name)
    info = manifest["outputs"][name]
    if (
        not p.is_file()
        or p.stat().st_size != info["bytes"]
        or sha256(p) != info["sha256"]
    ):
        raise ValueError(f"Source-stage artifact differs: {name}")
    return p


def verify_source_stage(
    stage: Path,
    *,
    expected_manifest_sha256: str,
    identity: dict,
    database: Path | None = None,
    parent_bundle: Path | None = None,
    work_dir: Path | None = None,
) -> dict:
    """Rehash every file; optionally repeat independent exact canonical proof."""
    manifest = _read_manifest(stage, expected_manifest_sha256, identity)
    for name in manifest["outputs"]:
        _verify_file(stage, manifest, name)
    if database is not None:
        if parent_bundle is None or work_dir is None:
            raise ValueError(
                "Canonical stage proof requires parent and external work location"
            )
        require_safe_output_location(
            work_dir, artifact_label="source-stage verification"
        )
        if any(
            work_dir.is_relative_to(p) or p.is_relative_to(work_dir)
            for p in (stage, parent_bundle, database.parent)
        ):
            raise ValueError("Source-stage verification work overlaps an input")
        with _connect(database, parent_bundle, work_dir, manifest["partitions"]) as db:
            _reconcile(db, stage, manifest)
    if sha256(stage / "manifest.json") != expected_manifest_sha256:
        raise ValueError("Source-stage manifest changed during verification")
    return manifest


def _reconcile(db, stage, manifest, events=None):
    n = manifest["partitions"]
    for table, columns in COLUMNS.items():
        if events:
            events.emit("source_stage", "reconciliation_start", table=table)
        selection = ",".join(f'"{c}"' for c in columns)
        canonical_schema = [
            [r[0], r[1]]
            for r in db.execute(
                f"DESCRIBE SELECT {selection} FROM canonical.{table}"
            ).fetchall()
        ]
        if manifest["schemas"].get(table) != canonical_schema:
            raise ValueError(
                f"Source-stage types differ from canonical source: {table}"
            )
        parts = []
        for bucket in range(n):
            name = f"{bucket:04d}_{table}.parquet"
            path = stage / name
            schema = [
                [row[0], row[1]]
                for row in db.execute(
                    f"DESCRIBE SELECT * FROM read_parquet({literal(path)})"
                ).fetchall()
            ]
            if schema != manifest["schemas"][table] or [c[0] for c in schema] != list(
                columns
            ):
                raise ValueError(f"Source-stage schema differs: {name}")
            parts.append(
                f"SELECT *,{bucket}::UBIGINT _return_bucket "
                f"FROM read_parquet({literal(path)})"
            )
        actual = " UNION ALL ".join(parts)
        expected = _expected(db, table, n)
        db.execute("CREATE TEMP TABLE independently_expected AS " + expected)
        different = db.execute(
            "SELECT count(*) FROM (("
            + "SELECT * FROM independently_expected"
            + " EXCEPT ALL ("
            + actual
            + ")) UNION ALL (("
            + actual
            + ") EXCEPT ALL "
            + "SELECT * FROM independently_expected"
            + "))"
        ).fetchone()[0]
        if different:
            raise ValueError(f"Source-stage exact typed multiset differs: {table}")
        expected_schema = [
            [row[0], row[1]] for row in db.execute("DESCRIBE " + expected).fetchall()
        ][:-1]
        db.execute("DROP TABLE independently_expected")
        if expected_schema != manifest["schemas"][table]:
            raise ValueError(f"Source-stage canonical types differ: {table}")
        if events:
            events.emit("source_stage", "reconciliation_complete", table=table)


def _complete_partition(db, *, pieces, target, columns, empty_source):
    """Normalize one bucket using bounded reads; count completed Parquet metadata."""
    target = no_symlinks(target)
    if target.exists():
        raise FileExistsError(f"Source-stage partition already exists: {target.name}")
    selection = ",".join(f'"{column}"' for column in columns)
    pieces = [no_symlinks(piece) for piece in pieces]
    if not pieces:
        db.execute(
            f"COPY (SELECT {selection} FROM {empty_source} WHERE FALSE) "
            f"TO {literal(target)} (FORMAT PARQUET, COMPRESSION ZSTD)"
        )
    elif len(pieces) == 1:
        pieces[0].replace(target)
    else:
        paths = "[" + ",".join(literal(piece) for piece in pieces) + "]"
        db.execute(
            f"COPY (SELECT {selection} FROM "
            f"read_parquet({paths}, hive_partitioning=false)) "
            f"TO {literal(target)} (FORMAT PARQUET, COMPRESSION ZSTD)"
        )
    fsync_file_strict(target)
    return pq.ParquetFile(target).metadata.num_rows


def create_source_stage(
    *,
    database: Path,
    parent_bundle: Path,
    output_dir: Path,
    work_dir: Path,
    partitions: int = 32,
    identity: dict,
    events=None,
) -> dict:
    """Scan canonical history into reusable shards, then prove all typed rows."""
    if type(partitions) is not int or not 1 <= partitions <= 1024:
        raise ValueError("Invalid patient partition count")
    output_dir, work_dir = no_symlinks(output_dir), no_symlinks(work_dir)
    for path in (output_dir, work_dir):
        require_safe_output_location(path, artifact_label="return source stage")
        for source in (database.parent, parent_bundle):
            if path.is_relative_to(source) or source.is_relative_to(path):
                raise ValueError("Source-stage location overlaps immutable inputs")
    if output_dir.is_relative_to(work_dir) or work_dir.is_relative_to(output_dir):
        raise ValueError("Source-stage output and work must be separate")
    if output_dir.exists():
        raise FileExistsError("Source-stage destination exists")
    staging = output_dir.with_name(f".{output_dir.name}.staging-{uuid.uuid4().hex}")
    staging.mkdir(mode=0o700, parents=True)
    manifest = {
        "stage_contract_version": STAGE_VERSION,
        "status": "building",
        "partitions": partitions,
        "identity": identity,
        "required_membership_elements": list(REQUIRED_MEMBERSHIP_ELEMENTS),
        "outputs": {},
        "schemas": {},
    }
    if events:
        events.emit("source_stage", "patient_routing_start")
    with _connect(database, parent_bundle, work_dir, partitions) as db:
        if events:
            events.emit("source_stage", "patient_routing_complete")
        for table, columns in COLUMNS.items():
            if events:
                events.emit("source_stage", "table_scan_start", table=table)
            table_started = time.monotonic()
            # Preserve the canonical selection, original-patient scope and
            # duplicate multiplicity; change only its physical write plan.
            fields = ",".join(f's."{c}"' for c in columns)
            if table == "element_membership":
                elements = ",".join(literal(e) for e in REQUIRED_MEMBERSHIP_ELEMENTS)
                query = (
                    f"SELECT {fields},p._return_bucket FROM canonical.{table} s "
                    "JOIN lab_patient_buckets p "
                    "ON s.source_record_id=p.source_record_id "
                    f"WHERE s.element_id IN ({elements})"
                )
            else:
                query = (
                    f"SELECT {fields},"
                    f"hash(s.patient_id::VARCHAR)%{partitions} AS _return_bucket "
                    f"FROM canonical.{table} s "
                    "SEMI JOIN original_patients p USING (patient_id)"
                )
            selection = ",".join(f'"{c}"' for c in columns)
            manifest["schemas"][table] = [
                [r[0], r[1]]
                for r in db.execute(
                    f"DESCRIBE SELECT {selection} FROM canonical.{table}"
                ).fetchall()
            ]
            partition_root = no_symlinks(staging / f".partitioned-{table}")
            if events:
                events.emit("source_stage", "table_write_start", table=table)
            db.execute(
                f"COPY ({query}) TO {literal(partition_root)} "
                "(FORMAT PARQUET, COMPRESSION ZSTD, "
                "PARTITION_BY (_return_bucket), WRITE_PARTITION_COLUMNS FALSE)"
            )
            if events:
                events.emit(
                    "source_stage",
                    "table_partitioned",
                    table=table,
                    seconds=time.monotonic() - table_started,
                )
            expected_directories = {
                f"_return_bucket={bucket}" for bucket in range(partitions)
            }
            no_symlinks(partition_root)
            if partition_root.exists():
                for child in partition_root.iterdir():
                    if (
                        child.name not in expected_directories
                        or child.is_symlink()
                        or not child.is_dir()
                    ):
                        raise ValueError(
                            f"Unexpected source-stage partition directory: {table}"
                        )
            table_rows = 0
            for bucket in range(partitions):
                name = f"{bucket:04d}_{table}.parquet"
                path = staging / name
                bucket_dir = partition_root / f"_return_bucket={bucket}"
                pieces = []
                if bucket_dir.exists():
                    if bucket_dir.is_symlink() or not bucket_dir.is_dir():
                        raise ValueError(f"Invalid source-stage partition: {name}")
                    pieces = sorted(bucket_dir.iterdir())
                    if any(
                        piece.is_symlink()
                        or not piece.is_file()
                        or piece.suffix != ".parquet"
                        for piece in pieces
                    ):
                        raise ValueError(f"Invalid source-stage piece: {name}")
                started = time.monotonic()
                count = _complete_partition(
                    db,
                    pieces=pieces,
                    target=path,
                    columns=columns,
                    empty_source=f"canonical.{table}",
                )
                fsync_directory_strict(staging)
                manifest["outputs"][name] = {
                    "bytes": path.stat().st_size,
                    "sha256": sha256(path),
                    "rows": count,
                }
                table_rows += count
                if events:
                    events.emit(
                        "source_stage",
                        "partition_written",
                        table=table,
                        bucket=bucket,
                        pieces=len(pieces),
                        bytes=manifest["outputs"][name]["bytes"],
                        rows=count,
                        seconds=time.monotonic() - started,
                    )
            if partition_root.exists():
                shutil.rmtree(partition_root)
                fsync_directory_strict(staging)
            if events:
                events.emit(
                    "source_stage",
                    "table_write_complete",
                    table=table,
                    rows=table_rows,
                    partitions=partitions,
                    seconds=time.monotonic() - table_started,
                )
        _reconcile(db, staging, manifest, events=events)
    manifest["status"] = "verified"
    write_text_atomic(
        staging / "manifest.json", json.dumps(manifest, sort_keys=True, indent=2) + "\n"
    )
    fsync_directory_strict(staging)
    staging.replace(output_dir)
    fsync_directory_strict(output_dir.parent)
    if events:
        events.emit(
            "source_stage",
            "complete",
            manifest_sha256=sha256(output_dir / "manifest.json"),
        )
    return manifest


def attach_source_partition(db, stage, *, bucket, expected_manifest_sha256, identity):
    """Attach only verified shard files under the unchanged SQL source namespace."""
    manifest = _read_manifest(stage, expected_manifest_sha256, identity)
    if type(bucket) is not int or not 0 <= bucket < manifest["partitions"]:
        raise ValueError("Invalid source-stage bucket")
    db.execute("CREATE SCHEMA preprocessed")
    for table in COLUMNS:
        path = _verify_file(stage, manifest, f"{bucket:04d}_{table}.parquet")
        db.execute(
            f"CREATE VIEW preprocessed.{table} AS "
            f"SELECT * FROM read_parquet({literal(path)})"
        )
    return manifest

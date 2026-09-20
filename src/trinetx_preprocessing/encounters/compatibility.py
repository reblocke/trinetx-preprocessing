"""Authenticated, text-preserving legacy snapshot import; routine reads use DuckDB.

The CSV options are those of the accepted Python reference loader. No clinical
coercion happens here: the unchanged per-file cleaner owns those decisions.
"""

from __future__ import annotations

import csv
import datetime
import hashlib
import json
import os
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from ..combined_preprocessing.builder import require_safe_output_location
from ..combined_preprocessing.contract import compatibility_outputs
from .legacy.raw_schema import load_schema

COMPANION_VERSION = "1.0"
CSV_OPTIONS = dict(
    dtype=str, keep_default_na=False, na_filter=False, encoding="utf-8-sig"
)


def ident(value):
    return '"' + str(value).replace('"', '""') + '"'


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def file_identity(path):
    stat = Path(path).stat()
    return (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns)


def no_symlinks(path):
    path = Path(path).absolute()
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError("Source and artifact locations cannot contain symlinks")
    return path


def read_frame(connection, key, *, chunk_rows=25000):
    """Bound the wide SQL sort while delivering the exact accepted full frame.

    A single ORDER BY over 534 text columns can exceed the reader's memory cap.
    Logical ordinal ranges preserve every row and duplicate without that sort.
    Fill the final column arrays directly: retaining chunks and concatenating
    them would temporarily duplicate a multi-gigabyte object-pointer matrix.
    Reuse equal strings per column, matching the accepted CSV parser's value
    sharing rather than keeping a new Python string for every DuckDB cell.
    The per-file cleaner still receives its original complete pandas frame.
    """
    if chunk_rows < 1:
        raise ValueError("Compatibility read chunk size must be positive")
    names = [c.raw_name for c in load_schema().columns]
    columns = ",".join(ident(c) for c in names)
    rows = connection.execute(
        "SELECT count(*) FROM compatibility_input WHERE compatibility_output_key=?",
        [key],
    ).fetchone()[0]
    values = {name: np.empty(rows, dtype=object) for name in names}
    shared_strings = {name: {} for name in names}
    for offset in range(0, rows, chunk_rows):
        stop = min(rows, offset + chunk_rows)
        chunk = connection.execute(
            f"SELECT {columns} FROM compatibility_input "
            "WHERE compatibility_output_key=? AND source_row_order>=? "
            "AND source_row_order<? ORDER BY source_row_order",
            [key, offset, stop],
        ).fetchdf()
        if len(chunk) != stop - offset:
            raise ValueError("Compatibility row ordinals are incomplete")
        for name in names:
            cache = shared_strings[name]
            values[name][offset:stop] = [
                cache.setdefault(value, value) for value in chunk[name]
            ]
        del chunk
    return pd.DataFrame(values, columns=names, copy=False)


def validate_companion(database):
    database = no_symlinks(database)
    sidecar = database.with_suffix(".json")
    before = file_identity(database)
    receipt = json.loads(sidecar.read_text())
    if (
        receipt.get("schema_version") != COMPANION_VERSION
        or receipt.get("status") != "complete"
        or receipt.get("database_sha256") != digest(database)
        or set(receipt.get("partitions", {}))
        != {o.key for o in compatibility_outputs()}
    ):
        raise ValueError("Invalid compatibility companion identity or inventory")
    with duckdb.connect(str(database), read_only=True) as db:
        columns = [r[0] for r in db.execute("DESCRIBE compatibility_input").fetchall()]
        expected = ["compatibility_output_key", "output_variant", "source_row_order"]
        expected += [c.raw_name for c in load_schema().columns]
        if columns != expected:
            raise ValueError("Compatibility companion schema mismatch")
        rows = db.execute(
            "SELECT compatibility_output_key,count(*),count(DISTINCT source_row_order),"
            "min(source_row_order),max(source_row_order) "
            "FROM compatibility_input GROUP BY 1"
        ).fetchall()
        observed = {r[0]: r[1:] for r in rows}
        for key, info in receipt["partitions"].items():
            n = info["rows"]
            if (
                observed.get(key, (0, 0, None, None))
                != (n, n, 0 if n else None, n - 1 if n else None)
                or not info["frame_parity"]
            ):
                raise ValueError("Compatibility row order or frame parity is invalid")
    if file_identity(database) != before:
        raise ValueError("Compatibility companion changed during validation")
    return receipt


def import_compatibility(*, input_root, identity_receipt, database, chunk_rows=25000):
    """Import exactly 36 authenticated files and prove every delivered text cell.

    Hash before and after parsing, retain explicit logical order and duplicates,
    and compare each imported frame chunk to the accepted CSV parser exactly.
    Failed companions remain at the new destination for private diagnosis.
    """
    root = no_symlinks(input_root)
    receipt_path = no_symlinks(identity_receipt)
    output = no_symlinks(database)
    require_safe_output_location(output, artifact_label="compatibility companion")
    if output.exists() or output.with_suffix(".json").exists():
        raise FileExistsError("Compatibility destination already exists")
    if output.is_relative_to(root):
        raise ValueError("Companion cannot be written inside immutable inputs")
    receipt_hash = digest(receipt_path)
    importer_hash = digest(Path(__file__))
    receipt = json.loads(receipt_path.read_text())
    outputs = compatibility_outputs()
    if set(receipt["inputs"]) != {o.key for o in outputs}:
        raise ValueError("Authenticated receipt must contain exactly 36 partitions")
    if Path(receipt["input_root"]).absolute() != root:
        raise ValueError("Authenticated input root differs")
    headers = [c.raw_name for c in load_schema().columns]
    snapshots = {}
    for part in outputs:
        path = no_symlinks(root / part.relative_path)
        info = receipt["inputs"][part.key]
        before = file_identity(path)
        if not info["accepted_match"] or not info["unchanged"]:
            raise ValueError("Input receipt does not authenticate accepted inputs")
        if digest(path) != info["sha256"] or before != file_identity(path):
            raise ValueError("Input differs from accepted identity")
        with path.open(encoding="utf-8-sig", newline="") as stream:
            if next(csv.reader(stream)) != headers:
                raise ValueError("Compatibility header differs from accepted schema")
        snapshots[part.key] = before
    output.parent.mkdir(parents=True, exist_ok=True)
    partitions = {}
    with duckdb.connect(str(output)) as db:
        db.execute("SET threads=1")
        db.execute("SET memory_limit='1024MiB'")
        db.execute(
            "SET temp_directory=?", [str(output.parent / (output.stem + ".spill"))]
        )
        db.execute(
            "CREATE TABLE compatibility_input (compatibility_output_key VARCHAR, "
            "output_variant VARCHAR, source_row_order BIGINT, "
            + ",".join(ident(c) + " VARCHAR" for c in headers)
            + ")"
        )
        os.chmod(output, 0o600)
        for part in outputs:
            path = root / part.relative_path
            offset = 0
            with pd.read_csv(path, chunksize=chunk_rows, **CSV_OPTIONS) as chunks:
                for frame in chunks:
                    frame = frame.reset_index(drop=True)
                    if frame.columns.tolist() != headers or frame.isna().any().any():
                        raise ValueError(
                            "CSV loader changed header or introduced missing objects"
                        )
                    imported = frame.copy(deep=False)
                    imported.insert(
                        0, "source_row_order", np.arange(offset, offset + len(frame))
                    )
                    imported.insert(0, "output_variant", part.variant)
                    imported.insert(0, "compatibility_output_key", part.key)
                    db.register("_import", imported)
                    db.execute("INSERT INTO compatibility_input SELECT * FROM _import")
                    db.unregister("_import")
                    returned = db.execute(
                        "SELECT "
                        + ",".join(ident(c) for c in headers)
                        + " FROM compatibility_input WHERE compatibility_output_key=? "
                        "AND source_row_order>=? AND source_row_order<? "
                        "ORDER BY source_row_order",
                        [part.key, offset, offset + len(frame)],
                    ).fetchdf()
                    # No assertion output can expose restricted values.
                    if not frame.equals(returned):
                        raise ValueError(
                            "Imported text frame differs from accepted CSV loader"
                        )
                    offset += len(frame)
            if (
                file_identity(path) != snapshots[part.key]
                or digest(path) != receipt["inputs"][part.key]["sha256"]
            ):
                raise ValueError("Authenticated input changed during import")
            partitions[part.key] = {
                "rows": offset,
                "sha256": receipt["inputs"][part.key]["sha256"],
                "file_identity": snapshots[part.key],
                "frame_parity": True,
            }
        db.execute("CHECKPOINT")
    if digest(receipt_path) != receipt_hash or any(
        file_identity(root / p.relative_path) != snapshots[p.key] for p in outputs
    ):
        raise ValueError("Source identities changed during import")
    manifest = {
        "schema_version": COMPANION_VERSION,
        "status": "complete",
        "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "importer_sha256": importer_hash,
        "database_sha256": digest(output),
        "source_identity_receipt_sha256": receipt_hash,
        "partitions": partitions,
        "loader": {**CSV_OPTIONS, "dtype": "str"},
        "schema_sha256": digest(Path(__file__).parent / "legacy/raw_schema.json"),
        "limitation": "Preserves accepted legacy inputs; bypasses incompatible "
        "canonical population projections without explaining their mismatch",
    }
    output.with_suffix(".json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest

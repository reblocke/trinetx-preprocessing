"""Exact multiset comparison using bounded, full-value hash partitions.

Hashes only route rows. Every comparison groups complete typed rows and sums
signed multiplicities; hash collisions never establish equality.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from ..combined_preprocessing.builder import require_safe_output_location
from ..filesystem import remove_tree_strict

PARTITION_THRESHOLD = 200_000
PARTITION_COUNT = 64
PARTITION_ROW_GROUP_SIZE = 8192
_BUCKET = "__verification_bucket"
_WEIGHT = "__verification_weight"


def _identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def exact_difference_counts(
    connection,
    left,
    right,
    *,
    scratch_root=None,
    progress=None,
    threshold=None,
    bucket_count=PARTITION_COUNT,
):
    """Return exact excess-row counts, including NULLs and duplicates."""
    if threshold is None:
        threshold = PARTITION_THRESHOLD
    if bucket_count < 1 or bucket_count & (bucket_count - 1):
        raise ValueError("Partition count must be a positive power of two")
    left_schema = [r[:2] for r in connection.execute("DESCRIBE " + left).fetchall()]
    right_schema = [r[:2] for r in connection.execute("DESCRIBE " + right).fetchall()]
    if left_schema != right_schema:
        raise ValueError("Exact comparison requires identical typed schemas")
    sizes = [
        int(connection.execute(f"SELECT count(*) FROM ({q})").fetchone()[0])
        for q in (left, right)
    ]
    if max(sizes) <= threshold:
        return {
            "left_only": int(
                connection.execute(
                    f"SELECT count(*) FROM (({left}) EXCEPT ALL ({right}))"
                ).fetchone()[0]
            ),
            "right_only": int(
                connection.execute(
                    f"SELECT count(*) FROM (({right}) EXCEPT ALL ({left}))"
                ).fetchone()[0]
            ),
        }
    if scratch_root is None:
        raise ValueError("Large exact comparisons require an external scratch root")
    scratch_root = Path(scratch_root)
    require_safe_output_location(
        scratch_root, artifact_label="Exact comparison scratch"
    )
    scratch_root.mkdir(parents=True, exist_ok=True)
    columns = [name for name, _ in left_schema]
    if _BUCKET in columns or _WEIGHT in columns:
        raise ValueError("Input uses reserved verification column names")
    projection = ", ".join(map(_identifier, columns))
    directory = Path(tempfile.mkdtemp(prefix=".glp1-multiset-", dir=scratch_root))
    old_open_files = connection.execute(
        "SELECT current_setting('partitioned_write_max_open_files')"
    ).fetchone()[0]
    try:
        connection.execute(f"SET partitioned_write_max_open_files = {bucket_count}")
        if progress:
            progress(
                {
                    "phase": "partition_write",
                    "total_rows": sum(sizes),
                    "completed_units": 0,
                    "total_units": bucket_count,
                }
            )
        connection.execute(f"""
            COPY (
                SELECT {projection}, {_identifier(_WEIGHT)},
                       hash({projection}) % {bucket_count} AS {_identifier(_BUCKET)}
                FROM (
                    SELECT *, 1::BIGINT AS {_identifier(_WEIGHT)} FROM ({left})
                    UNION ALL
                    SELECT *, -1::BIGINT AS {_identifier(_WEIGHT)} FROM ({right})
                )
            ) TO {_literal(str(directory))}
            (FORMAT PARQUET, PARTITION_BY ({_identifier(_BUCKET)}),
             COMPRESSION ZSTD, ROW_GROUP_SIZE {PARTITION_ROW_GROUP_SIZE})
        """)
        if progress:
            progress(
                {
                    "phase": "partition_compare",
                    "completed_units": 0,
                    "total_units": bucket_count,
                }
            )
        result = {"left_only": 0, "right_only": 0}
        observed = [0, 0]
        for bucket in range(bucket_count):
            files = sorted(
                p
                for p in (directory / f"{_BUCKET}={bucket}").glob("*.parquet")
                if not p.name.startswith("._")
            )
            if files:
                paths = "[" + ", ".join(_literal(str(p)) for p in files) + "]"
                relation = f"read_parquet({paths}, hive_partitioning=false)"
                schema = [
                    r[:2]
                    for r in connection.execute(
                        f"DESCRIBE SELECT {projection} FROM {relation}"
                    ).fetchall()
                ]
                if schema != left_schema:
                    raise ValueError("Partition serialization changed a typed schema")
                counts = connection.execute(f"""
                    SELECT count(*) FILTER (WHERE {_identifier(_WEIGHT)}=1),
                           count(*) FILTER (WHERE {_identifier(_WEIGHT)}=-1)
                    FROM {relation}
                """).fetchone()
                observed = [a + int(b) for a, b in zip(observed, counts, strict=True)]
                excess = connection.execute(f"""
                    SELECT coalesce(sum(greatest(delta, 0)), 0),
                           coalesce(sum(greatest(-delta, 0)), 0)
                    FROM (
                        SELECT sum({_identifier(_WEIGHT)}) AS delta
                        FROM {relation} GROUP BY {projection}
                    )
                """).fetchone()
                result["left_only"] += int(excess[0])
                result["right_only"] += int(excess[1])
            if progress:
                progress(
                    {
                        "phase": "partition_compare",
                        "completed_units": bucket + 1,
                        "total_units": bucket_count,
                    }
                )
        if observed != sizes:
            raise ValueError("Partition row coverage disagrees with input relations")
        return result
    finally:
        connection.execute(
            f"SET partitioned_write_max_open_files = {int(old_open_files)}"
        )
        remove_tree_strict(directory, context="Exact comparison partition scratch")

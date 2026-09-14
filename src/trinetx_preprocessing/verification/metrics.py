"""Small scientific summaries for review; never substitute these for exact parity."""

from __future__ import annotations

import hashlib
from pathlib import Path

from ..combined_preprocessing.database import open_combined_database
from ..glp1_eligibility.outputs import OUTPUT_TABLES


def scientific_metrics(database: Path) -> dict:
    metrics = {}
    with open_combined_database(database, read_only=True, memory_limit_mib=2048) as con:
        for table in OUTPUT_TABLES:
            columns = con.execute(
                "SELECT column_name, data_type FROM information_schema.columns "
                "WHERE table_name=? ORDER BY ordinal_position",
                [table],
            ).fetchall()
            projections = ["count(*)"]
            labels = [table + ".rows"]
            for name, dtype in columns:
                quoted = '"' + name.replace('"', '""') + '"'
                # Fixed controlled domains only; never emit identifiers/free text.
                if dtype == "BOOLEAN" or name.endswith("_status"):
                    projections.append(f"count(*) FILTER (WHERE {quoted} IS NULL)")
                    labels.append(f"{table}.{name}.missing")
                    values = (
                        ("true", "false")
                        if dtype == "BOOLEAN"
                        else (
                            "'met'",
                            "'not_met'",
                            "'indeterminate'",
                            "'included'",
                            "'excluded'",
                        )
                    )
                    for value in values:
                        projections.append(f"count(*) FILTER (WHERE {quoted}={value})")
                        labels.append(f"{table}.{name}.{value.strip(chr(39))}")
            values = con.execute(
                f"SELECT {', '.join(projections)} FROM {table}"
            ).fetchone()
            metrics.update(zip(labels, values, strict=True))
            metrics[table + ".content_sha256"] = table_fingerprint(con, table, columns)
        flow = con.execute(
            "SELECT stage, row_count, unique_patient_count "
            "FROM cohort_flow ORDER BY stage"
        ).fetchall()
        for stage, rows, patients in flow:
            metrics[f"cohort_flow.{stage}.rows"] = rows
            metrics[f"cohort_flow.{stage}.patients"] = patients
    return metrics


def drift_report(before: dict, after: dict) -> dict:
    return {
        k: {"before": before.get(k), "after": after.get(k)}
        for k in sorted(before.keys() | after.keys())
        if k not in before or k not in after or before[k] != after[k]
    }


def table_fingerprint(connection, table: str, columns: list[tuple[str, str]]) -> str:
    """Stream sorted row SHA256s; preserve multiplicity, types and NULLs.

    Only an aggregate digest leaves this function. The engine can spill sorting
    externally; Python retains at most 4096 hashes. Run IDs are operational.
    """
    stable = [(name, dtype) for name, dtype in columns if name != "run_id"]
    from .policy import sha

    digest = hashlib.sha256(sha(stable).encode())
    fields = ", ".join('"' + name.replace('"', '""') + '"' for name, _ in stable)
    identifier = '"' + table.replace('"', '""') + '"'
    cursor = connection.execute(
        f"SELECT sha256(to_json(struct_pack({fields}))) AS row_hash "
        f"FROM {identifier} ORDER BY row_hash"
    )
    while rows := cursor.fetchmany(4096):
        for (row_hash,) in rows:
            digest.update(row_hash.encode())
    return digest.hexdigest()

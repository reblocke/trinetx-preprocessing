"""Atomic, input-bound checkpoints for expensive encounter materialization."""

from __future__ import annotations

import hashlib
import json
import logging

LOGGER = logging.getLogger(__name__)
CACHE_FINGERPRINT_VERSION = "duckdb-json-multiset-v1"


class StageCache:
    """Keep a stage's tables and its completion receipt in one transaction.

    Only tool-owned databases with matching source/configuration/code bindings
    may resume. A database left by an older implementation needs a separately
    validated recovery import; table existence alone never authorizes reuse.
    """

    def __init__(self, connection, binding):
        self.connection = connection
        encoded = json.dumps(binding, sort_keys=True)
        names = {
            row[0]
            for row in connection.execute(
                "SELECT table_name FROM duckdb_tables() "
                "WHERE database_name=current_database() AND NOT internal"
            ).fetchall()
        }
        if "encounter_cache_binding" not in names:
            if names:
                raise ValueError("Unbound encounter cache requires validated recovery")
            connection.execute("BEGIN")
            try:
                connection.execute(
                    "CREATE TABLE encounter_cache_binding (binding VARCHAR)"
                )
                connection.execute(
                    "INSERT INTO encounter_cache_binding VALUES (?)", [encoded]
                )
                connection.execute(
                    "CREATE TABLE encounter_stage_checkpoint "
                    "(stage VARCHAR PRIMARY KEY, receipt VARCHAR)"
                )
                connection.execute("COMMIT")
            except BaseException:
                connection.execute("ROLLBACK")
                raise
        rows = connection.execute(
            "SELECT binding FROM encounter_cache_binding"
        ).fetchall()
        if rows != [(encoded,)]:
            raise ValueError(
                "Encounter cache source/configuration/code binding changed"
            )

    def _table_receipts(self, tables):
        result = {}
        for table in tables:
            quoted = '"' + table.replace('"', '""') + '"'
            result[table] = {
                "rows": self.connection.execute(
                    f"SELECT count(*) FROM {quoted}"
                ).fetchone()[0],
                "schema": [
                    list(row[:2])
                    for row in self.connection.execute(f"DESCRIBE {quoted}").fetchall()
                ],
                "fingerprint_version": CACHE_FINGERPRINT_VERSION,
                "content_sha256": self._content_fingerprint(quoted),
            }
        return result

    def _content_fingerprint(self, quoted_table):
        """Hash the sorted multiset of complete rows using bounded fetch batches.

        DuckDB serializes each row as an ordered JSON object. Sorting the
        serialized row strings supplies a canonical order; duplicate rows
        are emitted repeatedly, so multiplicity is part of the digest. Dates,
        nulls, strings and numeric values use DuckDB's logical JSON rendering.
        """
        cursor = self.connection.execute(
            f"SELECT to_json(t) AS row_json FROM {quoted_table} AS t ORDER BY 1"
        )
        digest = hashlib.sha256(CACHE_FINGERPRINT_VERSION.encode() + b"\0")
        while rows := cursor.fetchmany(2048):
            for (row,) in rows:
                encoded = row.encode("utf-8")
                digest.update(len(encoded).to_bytes(8, "big"))
                digest.update(encoded)
        return digest.hexdigest()

    def run(self, stage, tables, operation):
        row = self.connection.execute(
            "SELECT receipt FROM encounter_stage_checkpoint WHERE stage=?", [stage]
        ).fetchone()
        if row:
            receipt = json.loads(row[0])
            if any(
                details.get("fingerprint_version") != CACHE_FINGERPRINT_VERSION
                or not details.get("content_sha256")
                for details in receipt.get("tables", {}).values()
            ):
                raise ValueError(
                    "Legacy encounter checkpoint needs verified adoption or rebuild"
                )
            if receipt["tables"] != self._table_receipts(tables):
                raise ValueError("Encounter checkpoint content integrity changed")
            LOGGER.info("Reusing completed encounter stage %s", stage)
            return receipt["result"]
        LOGGER.info("Starting encounter stage %s", stage)
        self.connection.execute("BEGIN")
        try:
            result = operation()
            receipt = {"tables": self._table_receipts(tables), "result": result}
            self.connection.execute(
                "INSERT INTO encounter_stage_checkpoint VALUES (?, ?)",
                [stage, json.dumps(receipt, sort_keys=True)],
            )
            self.connection.execute("COMMIT")
        except BaseException:
            self.connection.execute("ROLLBACK")
            raise
        self.connection.execute("CHECKPOINT")
        LOGGER.info("Committed encounter stage %s", stage)
        return result

    def receipts(self):
        return {
            stage: json.loads(receipt)
            for stage, receipt in self.connection.execute(
                "SELECT stage, receipt FROM encounter_stage_checkpoint ORDER BY stage"
            ).fetchall()
        }

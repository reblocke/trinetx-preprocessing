"""Atomic, input-bound checkpoints for expensive encounter materialization."""

from __future__ import annotations

import json
import logging

LOGGER = logging.getLogger(__name__)


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
            }
        return result

    def run(self, stage, tables, operation):
        row = self.connection.execute(
            "SELECT receipt FROM encounter_stage_checkpoint WHERE stage=?", [stage]
        ).fetchone()
        if row:
            receipt = json.loads(row[0])
            if receipt["tables"] != self._table_receipts(tables):
                raise ValueError("Encounter checkpoint table integrity changed")
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

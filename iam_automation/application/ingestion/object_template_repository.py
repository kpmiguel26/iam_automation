"""Persistence for versioned, configuration-only object templates."""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


class ObjectTemplateRepository:
    """Store object-template snapshots in the existing template history table."""

    # Keep the legacy key so existing version history remains linked and auditable.
    TEMPLATE_KEY = "EMPLOYEE_PROFILE"

    def __init__(self, database_path: Path):
        self.database_path = Path(database_path)

    def latest(self) -> dict[str, Any] | None:
        with self._connection() as connection:
            approvals_table = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'engine_v2_object_template_approvals'"
            ).fetchone()
            approval_join = (
                "LEFT JOIN engine_v2_object_template_approvals a "
                "ON a.object_template_version_id = v.employee_template_version_id"
                if approvals_table else ""
            )
            approval_columns = (
                "a.approved_by, a.approved_at_utc"
                if approvals_table else "NULL AS approved_by, NULL AS approved_at_utc"
            )
            row = connection.execute(
                f"""SELECT v.employee_template_version_id, v.template_key, v.version_number,
                          v.status, v.definition_json, v.created_by, v.created_at_utc,
                          v.updated_by, v.updated_at_utc, {approval_columns}
                   FROM employee_template_versions v
                   {approval_join}
                   WHERE v.template_key = ?
                   ORDER BY v.version_number DESC LIMIT 1""",
                (self.TEMPLATE_KEY,),
            ).fetchone()
        result = self._decode(row) if row else None
        if result is not None:
            result["is_approved"] = bool(result.get("approved_at_utc"))
        return result

    def save_draft(self, definition: dict[str, Any], actor: str) -> dict[str, Any]:
        now = datetime.now(timezone.utc).isoformat()
        payload = json.dumps(definition, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        with self._connection() as connection:
            latest = connection.execute(
                """SELECT version_number, created_by, status
                   FROM employee_template_versions
                   WHERE template_key = ? ORDER BY version_number DESC LIMIT 1""",
                (self.TEMPLATE_KEY,),
            ).fetchone()
            version = int(latest[0]) + 1 if latest else 1
            creator = str(latest[1]) if latest else actor
            version_id = str(uuid.uuid4())
            connection.execute(
                """INSERT INTO employee_template_versions
                   (employee_template_version_id, template_key, version_number, status,
                    definition_json, created_by, created_at_utc, updated_by, updated_at_utc)
                   VALUES (?, ?, ?, 'DRAFT', ?, ?, ?, ?, ?)""",
                (version_id, self.TEMPLATE_KEY, version, payload, creator, now, actor, now),
            )
        return {
            "employee_template_version_id": version_id,
            "template_key": self.TEMPLATE_KEY,
            "version_number": version,
            "status": "DRAFT",
            "definition": definition,
            "created_by": creator,
            "created_at_utc": now,
            "updated_by": actor,
            "updated_at_utc": now,
        }

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=5)
        connection.row_factory = sqlite3.Row
        return connection

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    @staticmethod
    def _decode(row: sqlite3.Row) -> dict[str, Any]:
        result = dict(row)
        result["definition"] = json.loads(result.pop("definition_json"))
        return result

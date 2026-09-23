"""SQLite persistence for draft and approved ingestion template versions."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


class TemplateRepository:
    def __init__(self, database_path: Path):
        self.database_path = Path(database_path)

    def list_versions(self) -> tuple[dict[str, Any], ...]:
        with self._connection() as connection:
            rows = connection.execute(
                """SELECT definition_version_id, source_id, version_number, status,
                          definition_json, created_by, created_at_utc, updated_by,
                          updated_at_utc, approved_by, approved_at_utc
                   FROM source_definition_versions
                   ORDER BY updated_at_utc DESC, source_id, version_number DESC"""
            ).fetchall()
        return tuple(self._decode_row(row) for row in rows)

    def get(self, definition_version_id: str) -> dict[str, Any] | None:
        with self._connection() as connection:
            row = connection.execute(
                """SELECT definition_version_id, source_id, version_number, status,
                          definition_json, created_by, created_at_utc, updated_by,
                          updated_at_utc, approved_by, approved_at_utc
                   FROM source_definition_versions WHERE definition_version_id = ?""",
                (definition_version_id,),
            ).fetchone()
        return self._decode_row(row) if row else None

    def save_draft(self, definition: dict[str, Any], actor: str, version_id: str | None = None) -> dict[str, Any]:
        source_id = str(definition.get("source_id", "")).strip()
        if not source_id:
            raise ValueError("A source key is required before saving a template.")
        now = datetime.now(timezone.utc).isoformat()
        payload = json.dumps(definition, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        with self._connection() as connection:
            if version_id:
                row = connection.execute(
                    "SELECT status, source_id FROM source_definition_versions WHERE definition_version_id = ?",
                    (version_id,),
                ).fetchone()
                if row is None or row[0] != "DRAFT":
                    raise ValueError("Only a saved draft can be changed. Start a new version for an approved template.")
                if row[1] != source_id:
                    raise ValueError("The internal source key cannot change inside a saved version. Start a new template instead.")
                connection.execute(
                    """UPDATE source_definition_versions
                       SET definition_json = ?, content_sha256 = ?, updated_by = ?, updated_at_utc = ?
                       WHERE definition_version_id = ? AND status = 'DRAFT'""",
                    (payload, digest, actor, now, version_id),
                )
                saved_id = version_id
            else:
                version = connection.execute(
                    "SELECT COALESCE(MAX(version_number), 0) + 1 FROM source_definition_versions WHERE source_id = ?",
                    (source_id,),
                ).fetchone()[0]
                saved_id = str(uuid.uuid4())
                connection.execute(
                    """INSERT INTO source_definition_versions
                       (definition_version_id, source_id, version_number, status, definition_json,
                        content_sha256, created_by, created_at_utc, updated_by, updated_at_utc)
                       VALUES (?, ?, ?, 'DRAFT', ?, ?, ?, ?, ?, ?)""",
                    (saved_id, source_id, version, payload, digest, actor, now, actor, now),
                )
        result = self.get(saved_id)
        assert result is not None
        return result

    def approve(self, version_id: str, actor: str) -> dict[str, Any]:
        now = datetime.now(timezone.utc).isoformat()
        with self._connection() as connection:
            cursor = connection.execute(
                """UPDATE source_definition_versions
                   SET status = 'APPROVED', approved_by = ?, approved_at_utc = ?, updated_by = ?, updated_at_utc = ?
                   WHERE definition_version_id = ? AND status = 'DRAFT'""",
                (actor, now, actor, now, version_id),
            )
            if cursor.rowcount != 1:
                raise ValueError("This version is no longer a draft and cannot be approved.")
        result = self.get(version_id)
        assert result is not None
        return result

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
    def _decode_row(row: sqlite3.Row) -> dict[str, Any]:
        result = dict(row)
        result["definition"] = json.loads(result.pop("definition_json"))
        return result

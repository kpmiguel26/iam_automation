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

    def list_template_cards(self) -> tuple[dict[str, Any], ...]:
        """Return the latest active version per source with history and order."""
        with self._connection() as connection:
            rows = connection.execute(
                """SELECT v.definition_version_id, v.source_id, v.version_number, v.status,
                          v.definition_json, v.created_by, v.created_at_utc, v.updated_by,
                          v.updated_at_utc, v.approved_by, v.approved_at_utc,
                          COALESCE(o.ingestion_order, 2147483647) AS ingestion_order
                   FROM source_definition_versions v
                   LEFT JOIN source_ingestion_orders o ON o.source_id = v.source_id
                   WHERE NOT EXISTS (
                       SELECT 1 FROM source_template_lifecycle_events d
                       WHERE d.source_id = v.source_id AND d.restored_at_utc IS NULL
                   )
                   ORDER BY v.source_id, v.version_number DESC"""
            ).fetchall()
            history_rows = connection.execute(
                """SELECT definition_version_id, source_id, version_number, status,
                          definition_json, created_by, created_at_utc, updated_by,
                          updated_at_utc, approved_by, approved_at_utc
                   FROM source_definition_versions
                   WHERE NOT EXISTS (
                       SELECT 1 FROM source_template_lifecycle_events d
                       WHERE d.source_id = source_definition_versions.source_id AND d.restored_at_utc IS NULL
                   )
                   ORDER BY source_id, version_number DESC"""
            ).fetchall()
        versions: dict[str, list[dict[str, Any]]] = {}
        for row in history_rows:
            versions.setdefault(str(row["source_id"]), []).append(self._decode_row(row))
        latest_by_source: dict[str, dict[str, Any]] = {}
        for row in rows:
            source_id = str(row["source_id"])
            if source_id in latest_by_source:
                continue
            item = self._decode_row(row)
            item["ingestion_order"] = int(row["ingestion_order"])
            item["versions"] = versions.get(source_id, [])
            latest_by_source[source_id] = item
        cards = sorted(latest_by_source.values(), key=lambda item: (item["ingestion_order"], item["source_id"].casefold()))
        for index, card in enumerate(cards, start=1):
            if card["ingestion_order"] == 2147483647:
                card["ingestion_order"] = index
        return tuple(cards)

    def move_template(self, source_id: str, direction: int, actor: str) -> tuple[dict[str, Any], ...]:
        """Move a source template one position while keeping positions contiguous."""
        if direction not in (-1, 1):
            raise ValueError("Template order direction must be -1 or 1.")
        now = datetime.now(timezone.utc).isoformat()
        with self._connection() as connection:
            sources = [str(row[0]) for row in connection.execute(
                """SELECT v.source_id, MIN(COALESCE(o.ingestion_order, 2147483647)) AS sort_order
                   FROM source_definition_versions v
                   LEFT JOIN source_ingestion_orders o ON o.source_id = v.source_id
                   WHERE NOT EXISTS (
                       SELECT 1 FROM source_template_lifecycle_events d
                       WHERE d.source_id = v.source_id AND d.restored_at_utc IS NULL
                   )
                   GROUP BY v.source_id ORDER BY sort_order, v.source_id COLLATE NOCASE"""
            ).fetchall()]
            if source_id not in sources:
                raise ValueError("Template not found.")
            current = sources.index(source_id)
            target = max(0, min(len(sources) - 1, current + direction))
            if target != current:
                sources.insert(target, sources.pop(current))
                for position, item_source_id in enumerate(sources, start=1):
                    connection.execute(
                        """INSERT INTO source_ingestion_orders(source_id, ingestion_order, updated_by, updated_at_utc)
                           VALUES (?, ?, ?, ?)
                           ON CONFLICT(source_id) DO UPDATE SET ingestion_order = excluded.ingestion_order,
                               updated_by = excluded.updated_by, updated_at_utc = excluded.updated_at_utc""",
                        (item_source_id, position, actor, now),
                    )
        return self.list_template_cards()

    def delete_template(self, source_id: str, actor: str) -> None:
        """Hide a report template while retaining its versions and source lineage."""
        now = datetime.now(timezone.utc).isoformat()
        with self._connection() as connection:
            exists = connection.execute(
                "SELECT 1 FROM source_definition_versions WHERE source_id = ? LIMIT 1",
                (source_id,),
            ).fetchone()
            if exists is None:
                raise ValueError("Report template not found.")
            deleted = connection.execute(
                """SELECT 1 FROM source_template_lifecycle_events
                   WHERE source_id = ? AND restored_at_utc IS NULL LIMIT 1""",
                (source_id,),
            ).fetchone()
            if deleted is not None:
                raise ValueError("Report template is already removed from the active library.")
            connection.execute(
                """INSERT INTO source_template_lifecycle_events
                   (lifecycle_event_id, source_id, deleted_by, deleted_at_utc)
                   VALUES (?, ?, ?, ?)""",
                (str(uuid.uuid4()), source_id, actor, now),
            )
            active_sources = [str(row[0]) for row in connection.execute(
                """SELECT v.source_id, MIN(COALESCE(o.ingestion_order, 2147483647)) AS sort_order
                   FROM source_definition_versions v
                   LEFT JOIN source_ingestion_orders o ON o.source_id = v.source_id
                   WHERE NOT EXISTS (
                       SELECT 1 FROM source_template_lifecycle_events d
                       WHERE d.source_id = v.source_id AND d.restored_at_utc IS NULL
                   )
                   GROUP BY v.source_id ORDER BY sort_order, v.source_id COLLATE NOCASE"""
            ).fetchall()]
            for position, active_source_id in enumerate(active_sources, start=1):
                connection.execute(
                    """INSERT INTO source_ingestion_orders(source_id, ingestion_order, updated_by, updated_at_utc)
                       VALUES (?, ?, ?, ?)
                       ON CONFLICT(source_id) DO UPDATE SET ingestion_order = excluded.ingestion_order,
                           updated_by = excluded.updated_by, updated_at_utc = excluded.updated_at_utc""",
                    (active_source_id, position, actor, now),
                )

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
        reactivated = False
        with self._connection() as connection:
            if version_id:
                deleted = connection.execute(
                    """SELECT 1 FROM source_template_lifecycle_events
                       WHERE source_id = ? AND restored_at_utc IS NULL LIMIT 1""",
                    (source_id,),
                ).fetchone()
                if deleted is not None:
                    raise ValueError("This report template was removed. Start a new report draft to restore it.")
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
                deleted = connection.execute(
                    """SELECT lifecycle_event_id FROM source_template_lifecycle_events
                       WHERE source_id = ? AND restored_at_utc IS NULL
                       ORDER BY deleted_at_utc DESC LIMIT 1""",
                    (source_id,),
                ).fetchone()
                if deleted is not None:
                    connection.execute(
                        """UPDATE source_template_lifecycle_events
                           SET restored_by = ?, restored_at_utc = ?
                           WHERE lifecycle_event_id = ? AND restored_at_utc IS NULL""",
                        (actor, now, deleted[0]),
                    )
                    reactivated = True
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
                if reactivated:
                    active_sources = [str(row[0]) for row in connection.execute(
                        """SELECT v.source_id, MIN(COALESCE(o.ingestion_order, 2147483647)) AS sort_order
                           FROM source_definition_versions v
                           LEFT JOIN source_ingestion_orders o ON o.source_id = v.source_id
                           WHERE v.source_id != ? AND NOT EXISTS (
                               SELECT 1 FROM source_template_lifecycle_events d
                               WHERE d.source_id = v.source_id AND d.restored_at_utc IS NULL
                           )
                           GROUP BY v.source_id ORDER BY sort_order, v.source_id COLLATE NOCASE""",
                        (source_id,),
                    ).fetchall()]
                    active_sources.append(source_id)
                    for position, active_source_id in enumerate(active_sources, start=1):
                        connection.execute(
                            """INSERT INTO source_ingestion_orders(source_id, ingestion_order, updated_by, updated_at_utc)
                               VALUES (?, ?, ?, ?)
                               ON CONFLICT(source_id) DO UPDATE SET ingestion_order = excluded.ingestion_order,
                                   updated_by = excluded.updated_by, updated_at_utc = excluded.updated_at_utc""",
                            (active_source_id, position, actor, now),
                        )
        result = self.get(saved_id)
        assert result is not None
        result["reactivated"] = reactivated
        return result

    def approve(self, version_id: str, actor: str) -> dict[str, Any]:
        now = datetime.now(timezone.utc).isoformat()
        with self._connection() as connection:
            cursor = connection.execute(
                """UPDATE source_definition_versions
                   SET status = 'APPROVED', approved_by = ?, approved_at_utc = ?, updated_by = ?, updated_at_utc = ?
                   WHERE definition_version_id = ? AND status = 'DRAFT'
                     AND NOT EXISTS (
                         SELECT 1 FROM source_template_lifecycle_events d
                         WHERE d.source_id = source_definition_versions.source_id AND d.restored_at_utc IS NULL
                     )""",
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

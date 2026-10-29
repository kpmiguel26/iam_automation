"""SQLite persistence for draft and approved ingestion template versions."""

from __future__ import annotations

import hashlib
import json
import sqlite3
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
            card["is_validated"] = self.is_validated(card["definition_version_id"])
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
        """Physically remove a report template and cascade its locally owned data."""
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
            impact = self._deletion_impact(connection, source_id)
            if impact["object_references"]:
                names = ", ".join(dict.fromkeys(impact["object_references"]))
                raise ValueError(
                    f"This report is still linked to {names}. Unlink it, save, and approve the Object Template before removing it."
                )
            self._cascade_source_data(connection, source_id)
            connection.execute("DELETE FROM source_ingestion_orders WHERE source_id = ?", (source_id,))
            # These lifecycle tables implement archival. A physical removal must
            # not leave a hidden template row that can be reactivated later.
            for table in ("source_template_lifecycle_events", "source_template_deletions"):
                if self._table_exists(connection, table):
                    connection.execute(f"DELETE FROM {table} WHERE source_id = ?", (source_id,))
            connection.execute("DELETE FROM source_definition_versions WHERE source_id = ?", (source_id,))
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

    @staticmethod
    def _table_exists(connection: sqlite3.Connection, table_name: str) -> bool:
        return connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table_name,)
        ).fetchone() is not None

    @classmethod
    def _cascade_source_data(cls, connection: sqlite3.Connection, source_id: str) -> None:
        """Delete source-owned runtime rows while retaining objects shared by other reports."""
        def ids(sql: str, params: tuple[Any, ...]) -> list[str]:
            return [str(row[0]) for row in connection.execute(sql, params).fetchall()]

        def delete_in(table: str, column: str, values: list[str]) -> None:
            if not values or not cls._table_exists(connection, table):
                return
            columns = {str(row[1]) for row in connection.execute(f"PRAGMA table_info({table})")}
            if column not in columns:
                return
            for offset in range(0, len(values), 500):
                chunk = values[offset:offset + 500]
                marks = ",".join("?" for _ in chunk)
                connection.execute(f"DELETE FROM {table} WHERE {column} IN ({marks})", chunk)

        batch_ids = (
            ids("SELECT batch_id FROM engine_v2_batches WHERE source_id = ?", (source_id,))
            if cls._table_exists(connection, "engine_v2_batches") else []
        )
        evidence_ids = []
        if batch_ids and cls._table_exists(connection, "engine_v2_evidence"):
            marks = ",".join("?" for _ in batch_ids)
            evidence_ids = ids(f"SELECT evidence_id FROM engine_v2_evidence WHERE batch_id IN ({marks})", tuple(batch_ids))
        object_ids: list[str] = []
        if batch_ids and cls._table_exists(connection, "engine_v2_object_evidence"):
            marks = ",".join("?" for _ in batch_ids)
            object_ids = ids(
                f"""SELECT DISTINCT oe.object_id FROM engine_v2_object_evidence oe
                    JOIN engine_v2_evidence e ON e.evidence_id = oe.evidence_id
                    WHERE e.batch_id IN ({marks})""",
                tuple(batch_ids),
            )
        orphan_ids = []
        if object_ids and cls._table_exists(connection, "engine_v2_object_evidence"):
            for object_id in object_ids:
                other = connection.execute(
                    """SELECT 1 FROM engine_v2_object_evidence oe
                       JOIN engine_v2_evidence e ON e.evidence_id = oe.evidence_id
                       JOIN engine_v2_batches b ON b.batch_id = e.batch_id
                       WHERE oe.object_id = ? AND b.source_id <> ? LIMIT 1""",
                    (object_id, source_id),
                ).fetchone()
                if other is None:
                    orphan_ids.append(object_id)

        facts = []
        if cls._table_exists(connection, "engine_v2_source_facts"):
            facts = ids("SELECT fact_id FROM engine_v2_source_facts WHERE source_id = ?", (source_id,))
        delete_in("engine_v2_object_property_values", "fact_id", facts)
        delete_in("engine_v2_rule_findings", "batch_id", batch_ids)
        delete_in("engine_v2_strong_identifiers", "source_id", [source_id])
        delete_in("engine_v2_source_facts", "fact_id", facts)
        delete_in("engine_v2_object_evidence", "evidence_id", evidence_ids)
        delete_in("engine_v2_evidence", "evidence_id", evidence_ids)
        delete_in("engine_v2_batches", "batch_id", batch_ids)

        # Remove any remaining dependent rows before deleting objects that became
        # source-exclusive. Other-source evidence and its objects remain intact.
        delete_in("engine_v2_rule_findings", "object_id", orphan_ids)
        delete_in("engine_v2_object_property_values", "object_id", orphan_ids)
        delete_in("engine_v2_strong_identifiers", "object_id", orphan_ids)
        delete_in("engine_v2_source_facts", "object_id", orphan_ids)
        delete_in("engine_v2_object_evidence", "object_id", orphan_ids)
        delete_in("engine_v2_objects", "object_id", orphan_ids)

        delete_in("engine_v2_file_analyses", "source_id", [source_id])
        delete_in("engine_v2_file_observations", "source_id", [source_id])
        version_ids = ids("SELECT definition_version_id FROM source_definition_versions WHERE source_id = ?", (source_id,))
        delete_in("source_template_validation_events", "definition_version_id", version_ids)

    def deletion_impact(self, source_id: str) -> dict[str, Any]:
        """Preview active object-template dependencies without changing stored data."""
        with self._connection() as connection:
            exists = connection.execute(
                "SELECT 1 FROM source_definition_versions WHERE source_id = ? LIMIT 1",
                (source_id,),
            ).fetchone()
            if exists is None:
                raise ValueError("Report template not found.")
            return self._deletion_impact(connection, source_id)

    @staticmethod
    def _deletion_impact(connection: sqlite3.Connection, source_id: str) -> dict[str, Any]:
        references: list[str] = []
        linked_templates: list[dict[str, Any]] = []
        table = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'employee_template_versions'"
        ).fetchone()
        if table is not None:
            deletion_table = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'engine_v2_object_template_deletions'"
            ).fetchone()
            active_versions_only = (
                "AND NOT EXISTS (SELECT 1 FROM engine_v2_object_template_deletions d "
                "WHERE d.object_template_version_id = v.employee_template_version_id)"
                if deletion_table else ""
            )
            rows = connection.execute(
                f"""SELECT v.employee_template_version_id, v.definition_json, v.version_number
                   FROM employee_template_versions v
                   WHERE v.template_key = 'EMPLOYEE_PROFILE'
                     {active_versions_only}
                   ORDER BY v.version_number DESC"""
            ).fetchall()
            approved_ids: set[str] = set()
            approval_table = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'engine_v2_object_template_approvals'"
            ).fetchone()
            if approval_table is not None:
                approved_ids = {
                    str(row[0]) for row in connection.execute(
                        "SELECT object_template_version_id FROM engine_v2_object_template_approvals"
                    ).fetchall()
                }
            active_ids = {str(rows[0]["employee_template_version_id"])} if rows else set()
            latest_approved = next((str(row["employee_template_version_id"]) for row in rows if str(row["employee_template_version_id"]) in approved_ids), None)
            if latest_approved:
                active_ids.add(latest_approved)
            for row in rows:
                version_id = str(row["employee_template_version_id"])
                if version_id not in active_ids:
                    continue
                try:
                    definition = json.loads(row["definition_json"] or "{}")
                except (TypeError, json.JSONDecodeError):
                    definition = {}
                source_templates = [
                    source for source in definition.get("source_templates", ())
                    if isinstance(source, dict) and str(source.get("source_id", ""))
                ]
                if not any(str(source.get("source_id", "")) == source_id for source in source_templates):
                    continue
                object_name = str(definition.get("object_name") or "Current Object Template")
                references.append(object_name)
                reference_types = []
                if any(str(source.get("source_id", "")) == source_id for source in source_templates):
                    reference_types.append("selected as a report source")
                if any(str(prop.get("source_id", "")) == source_id for prop in definition.get("properties", ()) if isinstance(prop, dict)):
                    reference_types.append("provides object properties")
                if any(str(identifier.get("source_id", "")) == source_id for identifier in definition.get("identifiers", ()) if isinstance(identifier, dict)):
                    reference_types.append("provides matching identifiers")
                if any(
                    str(endpoint.get("source_id", "")) == source_id
                    for match in definition.get("matches", ()) if isinstance(match, dict)
                    for endpoint in (match.get("left", {}), match.get("right", {})) if isinstance(endpoint, dict)
                ):
                    reference_types.append("participates in cross-report matching")
                linked_templates.append({
                    "object_name": object_name,
                    "version_number": int(row["version_number"]),
                    "source_count": len(source_templates),
                    "sole_source": len(source_templates) == 1,
                    "reference_types": reference_types,
                })

        def table_exists(table_name: str) -> bool:
            return connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table_name,)
            ).fetchone() is not None

        def has_columns(table_name: str, *expected: str) -> bool:
            if not table_exists(table_name):
                return False
            columns = {str(row[1]) for row in connection.execute(f"PRAGMA table_info({table_name})")}
            return set(expected).issubset(columns)

        observation_count = 0
        template_version_count = int(connection.execute(
            "SELECT COUNT(*) FROM source_definition_versions WHERE source_id = ?", (source_id,)
        ).fetchone()[0])
        if has_columns("engine_v2_file_observations", "source_id"):
            observation_count = int(connection.execute(
                "SELECT COUNT(*) FROM engine_v2_file_observations WHERE source_id = ?", (source_id,)
            ).fetchone()[0])
        batch_count = 0
        if has_columns("engine_v2_batches", "source_id", "batch_id"):
            batch_count = int(connection.execute(
                "SELECT COUNT(*) FROM engine_v2_batches WHERE source_id = ?", (source_id,)
            ).fetchone()[0])
        evidence_count = object_link_count = objects_with_evidence = orphaned_objects = 0
        shared_objects = 0
        if has_columns("engine_v2_evidence", "evidence_id", "batch_id") and has_columns("engine_v2_batches", "batch_id", "source_id"):
            evidence_count = int(connection.execute(
                "SELECT COUNT(*) FROM engine_v2_evidence e JOIN engine_v2_batches b ON b.batch_id = e.batch_id WHERE b.source_id = ?",
                (source_id,),
            ).fetchone()[0])
        if (
            has_columns("engine_v2_object_evidence", "object_id", "evidence_id")
            and has_columns("engine_v2_evidence", "evidence_id", "batch_id")
            and has_columns("engine_v2_batches", "batch_id", "source_id")
        ):
            relation = """FROM engine_v2_object_evidence oe
                          JOIN engine_v2_evidence e ON e.evidence_id = oe.evidence_id
                          JOIN engine_v2_batches b ON b.batch_id = e.batch_id
                          WHERE b.source_id = ?"""
            object_link_count = int(connection.execute(
                "SELECT COUNT(*) " + relation, (source_id,)
            ).fetchone()[0])
            objects_with_evidence = int(connection.execute(
                "SELECT COUNT(DISTINCT oe.object_id) " + relation, (source_id,)
            ).fetchone()[0])
            orphaned_objects = int(connection.execute(
                """SELECT COUNT(DISTINCT oe.object_id) FROM engine_v2_object_evidence oe
                   JOIN engine_v2_evidence e ON e.evidence_id = oe.evidence_id
                   JOIN engine_v2_batches b ON b.batch_id = e.batch_id
                   WHERE b.source_id = ? AND NOT EXISTS (
                     SELECT 1 FROM engine_v2_object_evidence other_oe
                     JOIN engine_v2_evidence other_e ON other_e.evidence_id = other_oe.evidence_id
                     JOIN engine_v2_batches other_b ON other_b.batch_id = other_e.batch_id
                     WHERE other_oe.object_id = oe.object_id AND other_b.source_id <> ?
                   )""",
                (source_id, source_id),
            ).fetchone()[0])
            shared_objects = max(0, objects_with_evidence - orphaned_objects)
        counts = {
            "engine_v2_file_observations": observation_count,
            "engine_v2_batches": batch_count,
            "engine_v2_evidence": evidence_count,
        }
        return {
            "source_id": source_id,
            "template_versions": template_version_count,
            "shared_objects_retained": shared_objects,
            "object_references": tuple(references),
            "linked_object_templates": linked_templates,
            "requires_object_detach": bool(linked_templates),
            "sole_source_objects": orphaned_objects,
            "objects_to_remove_if_orphaned": orphaned_objects,
            "objects_with_source_evidence": objects_with_evidence,
            "object_evidence_links": object_link_count,
            "import_batches": batch_count,
            "evidence_rows": evidence_count,
            "engine_data_counts": counts,
        }

    def get(self, definition_version_id: str) -> dict[str, Any] | None:
        with self._connection() as connection:
            row = connection.execute(
                """SELECT definition_version_id, source_id, version_number, status,
                          definition_json, created_by, created_at_utc, updated_by,
                          updated_at_utc, approved_by, approved_at_utc
                   FROM source_definition_versions WHERE definition_version_id = ?""",
                (definition_version_id,),
            ).fetchone()
        if row is None:
            return None
        result = self._decode_row(row)
        result["is_validated"] = self.is_validated(definition_version_id)
        return result

    def is_validated(self, definition_version_id: str) -> bool:
        with self._connection() as connection:
            table = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'source_template_validation_events'"
            ).fetchone()
            if table is None:
                return False
            return connection.execute(
                """SELECT 1 FROM source_template_validation_events e
                   JOIN source_definition_versions v
                     ON v.definition_version_id = e.definition_version_id
                    AND v.content_sha256 = e.content_sha256
                   WHERE e.definition_version_id = ? LIMIT 1""",
                (definition_version_id,),
            ).fetchone() is not None

    def save_draft(
        self,
        definition: dict[str, Any],
        actor: str,
        version_id: str | None = None,
        *,
        mark_validated: bool = False,
    ) -> dict[str, Any]:
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
                else:
                    # Persist an initial position as soon as a new template is
                    # saved. Backfill older templates that predate the order
                    # table first, preserving their currently displayed order,
                    # then append the newly created template.
                    missing_order = connection.execute(
                        """SELECT 1 FROM source_definition_versions v
                           LEFT JOIN source_ingestion_orders o ON o.source_id = v.source_id
                           WHERE o.source_id IS NULL AND NOT EXISTS (
                               SELECT 1 FROM source_template_lifecycle_events d
                               WHERE d.source_id = v.source_id AND d.restored_at_utc IS NULL
                           ) LIMIT 1"""
                    ).fetchone()
                    if missing_order is not None:
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
                        active_sources = [item for item in active_sources if item != source_id]
                        active_sources.append(source_id)
                        for position, active_source_id in enumerate(active_sources, start=1):
                            connection.execute(
                                """INSERT INTO source_ingestion_orders
                                   (source_id, ingestion_order, updated_by, updated_at_utc)
                                   VALUES (?, ?, ?, ?)
                                   ON CONFLICT(source_id) DO UPDATE SET ingestion_order = excluded.ingestion_order,
                                       updated_by = excluded.updated_by, updated_at_utc = excluded.updated_at_utc""",
                                (active_source_id, position, actor, now),
                            )
            if mark_validated:
                validation_table = connection.execute(
                    "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'source_template_validation_events'"
                ).fetchone()
                if validation_table is None:
                    raise RuntimeError("Template validation schema is unavailable; apply database migrations before saving validated settings.")
                connection.execute(
                    """INSERT INTO source_template_validation_events
                       (validation_event_id, definition_version_id, content_sha256, validated_by, validated_at_utc)
                       VALUES (?, ?, ?, ?, ?)""",
                    (str(uuid.uuid4()), saved_id, digest, actor, now),
                )
        result = self.get(saved_id)
        assert result is not None
        result["reactivated"] = reactivated
        result["is_validated"] = self.is_validated(saved_id)
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
        connection.execute("PRAGMA foreign_keys = ON")
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

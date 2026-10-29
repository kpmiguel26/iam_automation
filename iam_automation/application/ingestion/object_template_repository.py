"""Persistence for versioned, configuration-only object templates."""

from __future__ import annotations

import hashlib
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
            deletion_table = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'engine_v2_object_template_deletions'"
            ).fetchone()
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
            deletion_join = (
                "LEFT JOIN engine_v2_object_template_deletions d "
                "ON d.object_template_version_id = v.employee_template_version_id"
                if deletion_table else ""
            )
            deletion_filter = "AND d.object_template_version_id IS NULL" if deletion_table else ""
            row = connection.execute(
                f"""SELECT v.employee_template_version_id, v.template_key, v.version_number,
                          v.status, v.definition_json, v.created_by, v.created_at_utc,
                          v.updated_by, v.updated_at_utc, {approval_columns}
                   FROM employee_template_versions v
                   {approval_join}
                   {deletion_join}
                   WHERE v.template_key = ? {deletion_filter}
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

    def deletion_impact(self, version_id: str) -> dict[str, int]:
        """Count data owned by the current Object Template before confirmation."""
        with self._connection() as connection:
            versions = self._active_version_ids(connection)
            if version_id not in versions:
                raise ValueError("The Object Template changed. Refresh the library and review the current version.")
            return self._deletion_impact(connection, versions)

    def delete(
        self, version_id: str, actor: str, *, expected_impact_token: str,
    ) -> dict[str, int]:
        """Remove all runtime-v2 data for the singleton object type, retaining version tombstones."""
        now = datetime.now(timezone.utc).isoformat()
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            versions = self._active_version_ids(connection)
            if not versions or version_id not in versions:
                raise ValueError("The Object Template changed. Refresh the library and review the current version.")
            impact = self._deletion_impact(connection, versions)
            if not expected_impact_token or expected_impact_token != self.impact_token(impact):
                raise ValueError("The affected data changed after the preview. Review the updated impact and confirm again.")
            if impact["external_object_links"]:
                raise ValueError(
                    "This Object Template has evidence linked to another object type. Resolve those links before deleting it."
                )

            version_marks = ",".join("?" for _ in versions)
            type_ids = [str(row[0]) for row in connection.execute(
                f"""SELECT DISTINCT object_type_id FROM engine_v2_object_template_types
                    WHERE object_template_version_id IN ({version_marks})""", versions,
            ).fetchall()]
            type_row = connection.execute(
                "SELECT object_type_id FROM engine_v2_object_types WHERE object_type_key = 'EMPLOYEE_PROFILE'"
            ).fetchone()
            if type_row is not None and str(type_row[0]) not in type_ids:
                type_ids.append(str(type_row[0]))

            object_conditions = [f"object_template_version_id IN ({version_marks})"]
            object_params: list[object] = list(versions)
            if type_ids:
                type_marks = ",".join("?" for _ in type_ids)
                object_conditions.append(f"object_type_id IN ({type_marks})")
                object_params.extend(type_ids)
            object_ids = [str(row[0]) for row in connection.execute(
                "SELECT object_id FROM engine_v2_objects WHERE " + " OR ".join(object_conditions), object_params,
            ).fetchall()]
            batch_ids = [str(row[0]) for row in connection.execute(
                f"SELECT batch_id FROM engine_v2_batches WHERE object_template_version_id IN ({version_marks})",
                versions,
            ).fetchall()]
            evidence_ids: list[str] = []
            if batch_ids:
                batch_marks = ",".join("?" for _ in batch_ids)
                evidence_ids = [str(row[0]) for row in connection.execute(
                    f"SELECT evidence_id FROM engine_v2_evidence WHERE batch_id IN ({batch_marks})", batch_ids,
                ).fetchall()]

            def marks_and_ids(values: list[str]) -> tuple[str, list[str]]:
                return (",".join("?" for _ in values), values)

            object_marks, object_params = marks_and_ids(object_ids)
            batch_marks, batch_params = marks_and_ids(batch_ids)
            evidence_marks, evidence_params = marks_and_ids(evidence_ids)
            if object_ids or batch_ids or type_ids:
                finding_conditions = []
                finding_params: list[str] = []
                if object_ids:
                    finding_conditions.append(f"object_id IN ({object_marks})")
                    finding_params.extend(object_params)
                if batch_ids:
                    finding_conditions.append(f"batch_id IN ({batch_marks})")
                    finding_params.extend(batch_params)
                if type_ids:
                    type_marks = ",".join("?" for _ in type_ids)
                    finding_conditions.append(f"object_type_id IN ({type_marks})")
                    finding_params.extend(type_ids)
                connection.execute(
                    "DELETE FROM engine_v2_rule_findings WHERE " + " OR ".join(finding_conditions), finding_params,
                )

            if object_ids or type_ids or versions:
                conditions = []
                params: list[str] = []
                if object_ids:
                    conditions.append(f"object_id IN ({object_marks})")
                    params.extend(object_params)
                if type_ids:
                    type_marks = ",".join("?" for _ in type_ids)
                    conditions.append(f"object_type_id IN ({type_marks})")
                    params.extend(type_ids)
                conditions.append(f"object_template_version_id IN ({version_marks})")
                params.extend(versions)
                connection.execute(
                    "DELETE FROM engine_v2_strong_identifiers WHERE " + " OR ".join(conditions), params,
                )

            if object_ids or versions:
                conditions = []
                params = []
                if object_ids:
                    conditions.append(f"object_id IN ({object_marks})")
                    params.extend(object_params)
                conditions.append(f"object_template_version_id IN ({version_marks})")
                params.extend(versions)
                connection.execute(
                    "DELETE FROM engine_v2_object_property_values WHERE " + " OR ".join(conditions), params,
                )
                connection.execute(
                    "DELETE FROM engine_v2_source_facts WHERE " + " OR ".join(conditions), params,
                )

            if object_ids or evidence_ids:
                conditions = []
                params = []
                if object_ids:
                    conditions.append(f"object_id IN ({object_marks})")
                    params.extend(object_params)
                if evidence_ids:
                    conditions.append(f"evidence_id IN ({evidence_marks})")
                    params.extend(evidence_params)
                connection.execute(
                    "DELETE FROM engine_v2_object_evidence WHERE " + " OR ".join(conditions), params,
                )

            if evidence_ids:
                connection.execute(
                    f"DELETE FROM engine_v2_evidence WHERE evidence_id IN ({evidence_marks})", evidence_params,
                )
            if batch_ids:
                connection.execute(
                    f"DELETE FROM engine_v2_batches WHERE batch_id IN ({batch_marks})", batch_params,
                )
            if object_ids:
                connection.execute(
                    f"DELETE FROM engine_v2_objects WHERE object_id IN ({object_marks})", object_params,
                )
            connection.execute(
                f"DELETE FROM engine_v2_object_template_approvals WHERE object_template_version_id IN ({version_marks})",
                versions,
            )
            connection.execute(
                f"DELETE FROM engine_v2_object_template_types WHERE object_template_version_id IN ({version_marks})",
                versions,
            )
            for removed_version_id in versions:
                connection.execute(
                    """INSERT INTO engine_v2_object_template_deletions
                       (object_template_version_id, deleted_by, deleted_at_utc, removal_impact_json)
                       VALUES (?, ?, ?, ?)""",
                    (removed_version_id, actor, now, json.dumps(impact, ensure_ascii=False, sort_keys=True)),
                )
            connection.commit()
            return impact
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def _active_version_ids(connection: sqlite3.Connection) -> list[str]:
        return [str(row[0]) for row in connection.execute(
            """SELECT v.employee_template_version_id FROM employee_template_versions v
               LEFT JOIN engine_v2_object_template_deletions d
                 ON d.object_template_version_id = v.employee_template_version_id
               WHERE v.template_key = ? AND d.object_template_version_id IS NULL
               ORDER BY v.version_number""",
            (ObjectTemplateRepository.TEMPLATE_KEY,),
        ).fetchall()]

    @staticmethod
    def impact_token(impact: dict[str, int]) -> str:
        canonical = json.dumps(impact, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @staticmethod
    def _deletion_impact(connection: sqlite3.Connection, versions: list[str]) -> dict[str, int]:
        version_marks = ",".join("?" for _ in versions)
        type_ids = [str(row[0]) for row in connection.execute(
            f"""SELECT DISTINCT object_type_id FROM engine_v2_object_template_types
                WHERE object_template_version_id IN ({version_marks})""", versions,
        ).fetchall()]
        type_row = connection.execute(
            "SELECT object_type_id FROM engine_v2_object_types WHERE object_type_key = 'EMPLOYEE_PROFILE'"
        ).fetchone()
        if type_row is not None and str(type_row[0]) not in type_ids:
            type_ids.append(str(type_row[0]))
        type_filter = ""
        type_params: list[str] = []
        if type_ids:
            type_marks = ",".join("?" for _ in type_ids)
            type_filter = f" OR object_type_id IN ({type_marks})"
            type_params = type_ids
        object_ids = [str(row[0]) for row in connection.execute(
            f"""SELECT object_id FROM engine_v2_objects WHERE
                object_template_version_id IN ({version_marks}){type_filter}""",
            [*versions, *type_params],
        ).fetchall()]
        batch_ids = [str(row[0]) for row in connection.execute(
            f"SELECT batch_id FROM engine_v2_batches WHERE object_template_version_id IN ({version_marks})",
            versions,
        ).fetchall()]
        evidence_ids = []
        if batch_ids:
            batch_marks = ",".join("?" for _ in batch_ids)
            evidence_ids = [str(row[0]) for row in connection.execute(
                f"SELECT evidence_id FROM engine_v2_evidence WHERE batch_id IN ({batch_marks})", batch_ids,
            ).fetchall()]
        external_links = 0
        if evidence_ids:
            evidence_marks = ",".join("?" for _ in evidence_ids)
            object_filter = ""
            object_params: list[str] = []
            if object_ids:
                object_marks = ",".join("?" for _ in object_ids)
                object_filter = f" AND oe.object_id NOT IN ({object_marks})"
                object_params = object_ids
            external_links = int(connection.execute(
                f"""SELECT COUNT(*) FROM engine_v2_object_evidence oe
                    WHERE oe.evidence_id IN ({evidence_marks}){object_filter}""",
                [*evidence_ids, *object_params],
            ).fetchone()[0])

        def count(table: str, conditions: list[str], params: list[str]) -> int:
            if not conditions:
                return 0
            where = " OR ".join(conditions)
            return int(connection.execute(f"SELECT COUNT(*) FROM {table} WHERE {where}", params).fetchone()[0])

        def ownership_conditions(*, include_object: bool = True, include_batch: bool = True,
                                 include_type: bool = False, include_version: bool = True) -> tuple[list[str], list[str]]:
            conditions: list[str] = []
            params: list[str] = []
            if include_object and object_ids:
                conditions.append(f"object_id IN ({','.join('?' for _ in object_ids)})")
                params.extend(object_ids)
            if include_batch and batch_ids:
                conditions.append(f"batch_id IN ({','.join('?' for _ in batch_ids)})")
                params.extend(batch_ids)
            if include_type and type_ids:
                conditions.append(f"object_type_id IN ({','.join('?' for _ in type_ids)})")
                params.extend(type_ids)
            if include_version:
                conditions.append(f"object_template_version_id IN ({version_marks})")
                params.extend(versions)
            return conditions, params

        fact_conditions, fact_params = ownership_conditions()
        property_conditions, property_params = ownership_conditions(include_batch=False)
        identifier_conditions, identifier_params = ownership_conditions(include_batch=False, include_type=True)
        finding_conditions, finding_params = ownership_conditions(include_version=False, include_type=True)
        link_conditions: list[str] = []
        link_params: list[str] = []
        if object_ids:
            link_conditions.append(f"object_id IN ({','.join('?' for _ in object_ids)})")
            link_params.extend(object_ids)
        if evidence_ids:
            link_conditions.append(f"evidence_id IN ({','.join('?' for _ in evidence_ids)})")
            link_params.extend(evidence_ids)

        return {
            "template_versions": len(versions),
            "objects": len(object_ids),
            "batches": len(batch_ids),
            "evidence_rows": len(evidence_ids),
            "source_facts": count("engine_v2_source_facts", fact_conditions, fact_params),
            "property_values": count("engine_v2_object_property_values", property_conditions, property_params),
            "identifiers": count("engine_v2_strong_identifiers", identifier_conditions, identifier_params),
            "object_evidence_links": count("engine_v2_object_evidence", link_conditions, link_params),
            "findings": count("engine_v2_rule_findings", finding_conditions, finding_params),
            "external_object_links": external_links,
        }

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
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

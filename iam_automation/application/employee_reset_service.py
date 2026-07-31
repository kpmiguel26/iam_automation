from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .audit_service import record_audit
from .publication_state import mark_publication_pending


class EmployeeResetService:
    """Safely remove employee/import test data while preserving access control."""

    EMPLOYEE_TABLES = (
        "worker_profile_versions",
        "worker_merge_events",
        "worker_source_lineage",
        "worker_discrepancies",
        "worker_engagements",
        "worker_identifiers",
        "workers",
        "ingestion_records",
        "quarantine_records",
        "import_batches",
        "file_observations",
    )

    def __init__(self, runtime_path: Path, *, audit_path: Path | None = None, backup_directory: Path | None = None):
        self.runtime_path = runtime_path.expanduser().resolve()
        self.audit_path = audit_path
        self.backup_directory = backup_directory or self.runtime_path.parent / "backups"

    def reset(self, actor: str, *, clear_workflow_records: bool = True) -> dict[str, Any]:
        if not self.runtime_path.is_file():
            raise ValueError(f"Runtime SQLite database was not found: {self.runtime_path}")

        backup_path = self._backup_database()
        counts: dict[str, int] = {}
        removed_request_ids: list[str] = []
        connection = sqlite3.connect(self.runtime_path, timeout=30)
        try:
            connection.execute("PRAGMA busy_timeout = 30000")
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("BEGIN IMMEDIATE")
            tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
            for table in self.EMPLOYEE_TABLES:
                if table in tables:
                    counts[table] = int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
                    connection.execute(f"DELETE FROM {table}")

            if clear_workflow_records and "change_requests" in tables:
                request_rows = connection.execute(
                    """
                    SELECT request_id FROM change_requests
                    WHERE lower(entity_type) IN ('employee', 'worker', 'ingestion_record', 'import_batch')
                       OR upper(operation_type) LIKE 'IMPORT_%'
                       OR upper(operation_type) LIKE '%EMPLOYEE%'
                    """
                ).fetchall()
                removed_request_ids = [str(row[0]) for row in request_rows]
                if removed_request_ids:
                    placeholders = ",".join("?" for _ in removed_request_ids)
                    for table in ("publication_queue", "approval_assignments"):
                        if table in tables:
                            counts[table] = int(connection.execute(f"SELECT COUNT(*) FROM {table} WHERE request_id IN ({placeholders})", removed_request_ids).fetchone()[0])
                            connection.execute(f"DELETE FROM {table} WHERE request_id IN ({placeholders})", removed_request_ids)
                    counts["change_requests"] = len(removed_request_ids)
                    connection.execute(f"DELETE FROM change_requests WHERE request_id IN ({placeholders})", removed_request_ids)
                    if "notifications" in tables:
                        notification_conditions = [f"entity_id IN ({placeholders})"]
                        notification_parameters: list[str] = list(removed_request_ids)
                        notification_conditions.append("lower(entity_type) IN ('employee', 'worker', 'ingestion_record', 'import_batch')")
                        notification_conditions.append("upper(notification_type) LIKE 'IMPORT_%'")
                        notification_conditions.append("upper(notification_type) LIKE '%EMPLOYEE%'")
                        notification_where = " OR ".join(notification_conditions)
                        counts["employee_notifications"] = int(
                            connection.execute(
                                f"SELECT COUNT(*) FROM notifications WHERE {notification_where}",
                                notification_parameters,
                            ).fetchone()[0]
                        )
                        connection.execute(
                            f"DELETE FROM notifications WHERE {notification_where}",
                            notification_parameters,
                        )

            connection.commit()
            connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

        result = {"backup": str(backup_path), "counts": counts, "removed_request_count": len(removed_request_ids), "clear_workflow_records": clear_workflow_records}
        mark_publication_pending(self.runtime_path, actor=actor, reason="Employee test data reset")
        record_audit(self.audit_path, actor, "EMPLOYEE_TEST_DATA_RESET", "runtime_database", self.runtime_path.name, new_values=result)
        return result

    def _backup_database(self) -> Path:
        self.backup_directory.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        destination = self.backup_directory / f"test-reset-before-{stamp}.sqlite"
        source = sqlite3.connect(self.runtime_path, timeout=30)
        target = sqlite3.connect(destination)
        try:
            source.execute("PRAGMA busy_timeout = 30000")
            source.backup(target)
            target.commit()
        finally:
            target.close()
            source.close()
        return destination

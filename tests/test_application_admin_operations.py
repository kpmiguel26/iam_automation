"""
File: tests/test_application_admin_operations.py
Purpose: Provides automated regression tests for test application admin operations.
Responsibilities: Exposes or coordinates: ApplicationAdminOperationsTests.
Dependencies: unittest, iam_automation
Inputs/outputs: Inputs: temporary databases, fixtures, and test doubles. Outputs: assertions and test results.
Author / implementation: Miguel Fernandez.
Developed for: Kaiser Permanente NSES GWFM.
Project implementation and integration: Miguel Fernandez.
Third-party source, libraries, and dependencies retain their original licenses.
Estimated implementation effort: 1.25 h (Git-derived heuristic; see docs/file-effort-history.md).
"""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from iam_automation.application.delegation_service import DelegationService
from iam_automation.application.file_watch_service import FileWatchService, load_watcher_health
from iam_automation.application.import_service import ImportService
from iam_automation.application.notification_service import NotificationService
from iam_automation.application.request_service import RequestService
from iam_automation.application.roster_lock_ingestion_service import RosterLockIngestionService
from iam_automation.application.user_service import UserService
from iam_automation.database.runtime_schema import initialize_runtime_database
from iam_automation.identity import CurrentUser, ROLE_REQUESTER


class ApplicationAdminOperationsTests(unittest.TestCase):
    def test_rehire_notifications_reconcile_when_alert_is_gone(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = initialize_runtime_database(Path(tmp) / "runtime.sqlite")
            UserService(database).create_user("admin", "Admin", "secret", ["APPLICATION_ADMIN"])
            service = NotificationService(database)
            alert = {"alert_id": "roster:access", "worker_name": "Ada Lovelace", "status": "TERMINATED", "business_days_remaining": 10}
            self.assertEqual(service.notify_rehire_alerts([alert]), 1)
            self.assertEqual(service.notify_rehire_alerts([]), 0)
            notifications = service.list_for_user("admin")
            self.assertEqual(len(notifications), 1)
            self.assertEqual(notifications[0].status, "EXPIRED")

    def test_notifications_can_expire_and_resolve(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = initialize_runtime_database(Path(tmp) / "runtime.sqlite")
            service = NotificationService(database)
            past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
            expired_id = service.create("admin", "TEST", "Expired", "Expired event", expires_at_utc=past)
            active_id = service.create("admin", "TEST", "Active", "Active event")
            self.assertEqual(service.unread_count("admin"), 1)
            service.resolve("admin", active_id)
            statuses = {item.notification_id: item.status for item in service.list_for_user("admin")}
            self.assertEqual(statuses[expired_id], "EXPIRED")
            self.assertEqual(statuses[active_id], "RESOLVED")

    def test_notifications_can_be_marked_read_in_bulk(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = initialize_runtime_database(Path(tmp) / "runtime.sqlite")
            service = NotificationService(database)
            first_id = service.create("admin", "TEST", "First", "First event")
            second_id = service.create("admin", "TEST", "Second", "Second event")
            self.assertEqual(service.mark_all_read("admin"), 2)
            self.assertEqual(service.unread_count("admin"), 0)
            statuses = {item.notification_id: item.status for item in service.list_for_user("admin")}
            self.assertEqual(statuses[first_id], "READ")
            self.assertEqual(statuses[second_id], "READ")

    def test_retrying_a_stable_notification_does_not_reset_read_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = initialize_runtime_database(Path(tmp) / "runtime.sqlite")
            service = NotificationService(database)

            notification_id = service.create("admin", "TEST", "First", "First event", notification_id="stable-event")
            service.mark_read("admin", notification_id)
            service.create("admin", "TEST", "Updated", "Updated event", notification_id="stable-event")

            notification = service.list_for_user("admin")[0]
            self.assertEqual(notification.title, "Updated")
            self.assertEqual(notification.status, "READ")

    def test_normal_notifications_stay_local_when_sharepoint_root_is_configured(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            database = initialize_runtime_database(base / "runtime.sqlite")
            service = NotificationService(database, sharepoint_root=base / "sharepoint")

            notification_id = service.create("admin", "TEST", "Local", "Local event")

            self.assertEqual(service.list_for_user("admin")[0].notification_id, notification_id)
            self.assertFalse((base / "sharepoint" / "notifications").exists())
            self.assertTrue((base / ".iam_notifications").is_dir())
            with sqlite3.connect(database) as connection:
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM notifications").fetchone()[0], 0)

    def test_only_database_publication_is_written_to_shared_notifications(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            database = initialize_runtime_database(base / "runtime.sqlite")
            service = NotificationService(database, sharepoint_root=base / "sharepoint")

            notification_id = service.publish_database_snapshot(
                "checksum-001",
                actor="admin",
                recipients=["admin", "reviewer"],
                reconciled_count=2,
            )

            self.assertTrue((base / "sharepoint" / "notifications" / f"{notification_id}.json").exists())
            notification = service.list_for_user("admin")[0]
            self.assertEqual(notification.notification_type, "DATABASE_SNAPSHOT_PUBLISHED")
            self.assertEqual(notification.severity, "CRITICAL")

            throttled_id = service.publish_database_snapshot(
                "checksum-002",
                actor="admin",
                recipients=["admin", "reviewer"],
            )
            self.assertEqual(throttled_id, notification_id)

            service.create("admin", "TEST", "Local", "Local event")
            self.assertEqual(len(list((base / "sharepoint" / "notifications").glob("*.json"))), 1)

    def test_republishing_request_review_does_not_reset_read_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = initialize_runtime_database(Path(tmp) / "runtime.sqlite")
            UserService(database).create_user("admin", "Admin", "secret", ["APPLICATION_ADMIN"])
            service = NotificationService(database)
            self.assertEqual(service.notify_request_reviewers("request-001", "CREATE_EMPLOYEE", "requester"), 1)
            notification = service.list_for_user("admin")[0]
            service.mark_read("admin", notification.notification_id)
            service.notify_request_reviewers("request-001", "CREATE_EMPLOYEE", "requester")
            self.assertEqual(service.unread_count("admin"), 0)
            self.assertEqual(service.list_for_user("admin")[0].status, "READ")

    def test_republishing_source_update_does_not_reset_read_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = initialize_runtime_database(Path(tmp) / "runtime.sqlite")
            UserService(database).create_user("admin", "Admin", "secret", ["APPLICATION_ADMIN"])
            service = NotificationService(database)
            self.assertEqual(service.notify_source_update_available("request-001", "IMPORT_ROSTER_LOCK", 2), 1)
            notification = service.list_for_user("admin")[0]
            service.mark_read("admin", notification.notification_id)
            service.notify_source_update_available("request-001", "IMPORT_ROSTER_LOCK", 2)
            self.assertEqual(service.unread_count("admin"), 0)
            self.assertEqual(service.list_for_user("admin")[0].status, "READ")

    def test_expired_delegations_are_retained_for_administration(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = initialize_runtime_database(Path(tmp) / "runtime.sqlite")
            service = DelegationService(database)
            UserService(database).create_user("reviewer.test", "Reviewer", "secret", ["REVIEWER"])
            start = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
            end = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
            created = service.create("admin", "reviewer.test", "APPROVALS", start, end, "Absence test", "admin")
            self.assertEqual(service.expire_due(), 1)
            delegation = next(item for item in service.list_all() if item.delegation_id == created.delegation_id)
            self.assertEqual(delegation.status, "EXPIRED")

    def test_import_quarantines_invalid_rows_and_can_resolve_them(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = initialize_runtime_database(Path(tmp) / "runtime.sqlite")
            service = ImportService(database)
            batch = service.import_bytes("employees.csv", b"employee_id,job_title\nE100,Analyst\n,Missing ID\n", "admin")
            self.assertEqual((batch.total_rows, batch.valid_rows, batch.quarantine_rows), (2, 1, 1))
            records = service.list_quarantine(open_only=True)
            self.assertEqual(len(records), 1)
            service.resolve_quarantine(records[0]["quarantine_id"], "admin")
            self.assertEqual(service.list_quarantine(open_only=True), [])

    def test_application_admin_can_assign_reviewer(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = initialize_runtime_database(Path(tmp) / "runtime.sqlite")
            service = RequestService(database)
            request_item = service.create(CurrentUser("requester.test", "pc", (ROLE_REQUESTER,)), "CREATE_EMPLOYEE", "E100", {"first_name": "Test"}, "Coverage test")
            assigned = service.assign(request_item.request_id, "reviewer.test", "admin", "Manual reviewer assignment")
            self.assertEqual(assigned.assigned_to, "reviewer.test")
            self.assertEqual(assigned.status, "UNDER_REVIEW")

    def test_file_watcher_notifies_once_for_new_pending_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            database = initialize_runtime_database(base / "runtime.sqlite")
            UserService(database).create_user("admin", "Admin", "secret", ["APPLICATION_ADMIN"])
            pending = base / "requests" / "pending"
            pending.mkdir(parents=True)
            request_file = pending / "request-001.json"
            request_file.write_text('{"request_id":"request-001"}', encoding="utf-8")
            watcher = FileWatchService(database, base)
            self.assertEqual(watcher.scan_once(), 1)
            self.assertEqual(watcher.scan_once(), 0)
            notifications = watcher.notifications.list_for_user("admin")
            self.assertEqual(len(notifications), 1)
            self.assertEqual(notifications[0].notification_type, "FILE_DETECTED")

    def test_file_watcher_retry_does_not_duplicate_existing_file_notification(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            database = initialize_runtime_database(base / "runtime.sqlite")
            UserService(database).create_user("admin", "Admin", "secret", ["APPLICATION_ADMIN"])
            pending = base / "requests" / "pending"
            pending.mkdir(parents=True)
            request_file = pending / "request-001.json"
            request_file.write_text('{"request_id":"request-001"}', encoding="utf-8")

            watcher = FileWatchService(database, base)
            self.assertEqual(watcher.scan_once(), 1)
            notification = watcher.notifications.list_for_user("admin")[0]
            watcher.notifications.mark_read("admin", notification.notification_id)

            # Simulate a retry after the observation write was interrupted,
            # while the notification row was already committed.
            from iam_automation.infrastructure.sqlite.orm import FileObservationModel, orm_session
            with orm_session(database) as session:
                session.delete(session.get(FileObservationModel, str(request_file)))

            self.assertEqual(watcher.scan_once(), 1)
            notifications = watcher.notifications.list_for_user("admin")
            self.assertEqual(len(notifications), 1)
            self.assertEqual(notifications[0].status, "READ")

    def test_file_watcher_health_alert_resolves_after_recovery(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = initialize_runtime_database(Path(tmp) / "runtime.sqlite")
            UserService(database).create_user("admin", "Admin", "secret", ["APPLICATION_ADMIN"])
            watcher = FileWatchService(database, Path(tmp))
            watcher.record_watcher_failure(OSError("provider unavailable"), 3)
            notification = watcher.notifications.list_for_user("admin")[0]
            self.assertEqual(notification.notification_type, "WATCHER_CYCLE_FAILURE")
            self.assertEqual(notification.severity, "CRITICAL")
            watcher.record_watcher_recovery()
            self.assertEqual(watcher.notifications.list_for_user("admin")[0].status, "RESOLVED")

    def test_file_watcher_health_is_persisted_outside_runtime_database(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = initialize_runtime_database(Path(tmp) / "runtime.sqlite")
            watcher = FileWatchService(database, Path(tmp))
            watcher.record_watcher_health(status="DEGRADED", consecutive_failures=3, error=OSError("sync unavailable"))
            degraded = load_watcher_health(database)
            self.assertEqual(degraded["status"], "DEGRADED")
            self.assertEqual(degraded["consecutive_failures"], 3)
            self.assertIn("OSError: sync unavailable", degraded["last_error"])

            watcher.record_watcher_health(status="HEALTHY", consecutive_failures=0, processed_count=2)
            healthy = load_watcher_health(database)
            self.assertEqual(healthy["status"], "HEALTHY")
            self.assertEqual(healthy["last_processed_count"], 2)
            self.assertEqual(healthy["last_error"], "")
            self.assertTrue(healthy["last_success_at_utc"])

    def test_file_watcher_detects_published_runtime_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            database = initialize_runtime_database(base / "runtime.sqlite")
            UserService(database).create_user("admin", "Admin", "secret", ["MASTER_ADMIN"])
            snapshots = base / "database" / "snapshots"
            snapshots.mkdir(parents=True)
            (snapshots / "iam_runtime.sqlite").write_bytes(b"published-v1")
            watcher = FileWatchService(database, base)
            self.assertEqual(watcher.scan_once(), 1)
            notification = watcher.notifications.list_for_user("admin")[0]
            self.assertEqual(notification.title, "New database snapshot published")
            self.assertEqual(notification.target_route, "/dashboard")

    def test_roster_lock_ingestion_stages_rows_and_quarantines_invalid_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            database = initialize_runtime_database(base / "runtime.sqlite")
            source = base / "roster.xlsx"
            from openpyxl import Workbook
            workbook = Workbook()
            sheet = workbook.active
            sheet.append(["Vendor Name", "Vendor employee ID", "Employee first name"])
            sheet.append(["TTEC", "E100", "Valid"])
            sheet.append(["TTEC", "", "Missing ID"])
            workbook.save(source)
            result = RosterLockIngestionService(database).ingest_file(source)
            self.assertEqual((result.total_rows, result.staged_rows, result.quarantine_rows), (2, 1, 1))


if __name__ == "__main__":
    unittest.main()
#endfile

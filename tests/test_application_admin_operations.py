from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from iam_automation.application.delegation_service import DelegationService
from iam_automation.application.file_watch_service import FileWatchService
from iam_automation.application.import_service import ImportService
from iam_automation.application.notification_service import NotificationService
from iam_automation.application.request_service import RequestService
from iam_automation.application.user_service import UserService
from iam_automation.database.runtime_schema import initialize_runtime_database
from iam_automation.identity import CurrentUser, ROLE_REQUESTER


class ApplicationAdminOperationsTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()

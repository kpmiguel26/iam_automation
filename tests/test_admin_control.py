"""
File: tests/test_admin_control.py
Purpose: Provides automated regression tests for test admin control.
Responsibilities: Exposes or coordinates: AdminControlTests.
Dependencies: unittest, iam_automation
Inputs/outputs: Inputs: temporary databases, fixtures, and test doubles. Outputs: assertions and test results.
Author: Miguel Fernandez.
Copyright: © Miguel Fernandez. Developed for Kaiser Permanente NSES IAM Automation.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from iam_automation import webapp
from iam_automation.application.shared_request_service import SharedRequestService
from iam_automation.database.runtime_schema import initialize_runtime_database
from iam_automation.identity import CurrentUser, ROLE_APPLICATION_ADMIN, ROLE_REQUESTER, ROLE_SUPER_OPERATOR
from iam_automation.startup import PreflightResult, StartupSettings, StartupState


class AdminControlTests(unittest.TestCase):
    def make_result(self, database: Path) -> PreflightResult:
        root = database.parent / "sharepoint"
        settings = StartupSettings(root, root / "database.accdb", root / "published.sqlite", database, root / "workspace", root / "backups", root / "audit")
        return PreflightResult(StartupState.READY, True, "ready", settings)

    def test_application_admin_can_open_control_center(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = initialize_runtime_database(Path(tmp) / "runtime.sqlite")
            admin = CurrentUser("app.admin", "PC01", (ROLE_APPLICATION_ADMIN,))
            app = webapp.create_app(self.make_result(database), app_authenticator=lambda _u, _p: admin)
            client = app.test_client()
            with client.session_transaction() as session:
                session["iam_user"] = admin.username
                session["iam_roles"] = list(admin.roles)
            self.assertEqual(client.get("/admin").status_code, 200)
            self.assertEqual(client.get("/admin/users").status_code, 200)

    def test_requester_cannot_open_control_center(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = initialize_runtime_database(Path(tmp) / "runtime.sqlite")
            app = webapp.create_app(self.make_result(database))
            client = app.test_client()
            with client.session_transaction() as session:
                session["iam_user"] = "requester"
                session["iam_roles"] = [ROLE_REQUESTER]
            self.assertEqual(client.get("/admin").status_code, 403)
            self.assertEqual(client.get("/admin/users").status_code, 403)

    def test_temporary_super_operator_cannot_manage_master_security_or_publish_access(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = initialize_runtime_database(Path(tmp) / "runtime.sqlite")
            operator = CurrentUser("operator", "PC01", (ROLE_SUPER_OPERATOR,))
            client = webapp.create_app(self.make_result(database), app_authenticator=lambda _u, _p: operator).test_client()
            with client.session_transaction() as session:
                session["iam_user"] = operator.username
                session["iam_roles"] = list(operator.roles)
            self.assertEqual(client.get("/admin/master/settings").status_code, 403)
            with client.session_transaction() as session:
                csrf_token = session["iam_csrf_token"]
            self.assertEqual(client.post("/admin/governance/publish", headers={"X-CSRF-Token": csrf_token}).status_code, 403)

    def test_automatic_source_request_is_reviewed_only_in_source_updates(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = initialize_runtime_database(Path(tmp) / "runtime.sqlite")
            root = database.parent / "sharepoint"
            SharedRequestService(root).create(
                CurrentUser("workspace-watcher", "test-pc", (ROLE_APPLICATION_ADMIN,)),
                "IMPORT_ROSTER_LOCK",
                "batch-1",
                {"record_count": 1},
                "New source file detected",
            )
            client = self.client_for_admin(database)
            response = client.get("/admin/approvals")
            self.assertEqual(response.status_code, 200)
            self.assertNotIn(b"Roster Lock import", response.data)
            self.assertIn(b"Source Updates", response.data)

    def test_imports_page_hides_automatic_source_batches(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = initialize_runtime_database(Path(tmp) / "runtime.sqlite")
            from iam_automation.infrastructure.sqlite.orm import ImportBatchModel, orm_session

            with orm_session(database) as session:
                session.add(ImportBatchModel(
                    batch_id="auto-batch",
                    filename="roster.xlsx",
                    source_type="ROSTER_LOCK",
                    status="COMPLETED",
                    total_rows=1,
                    valid_rows=1,
                    quarantine_rows=0,
                    created_by="workspace-watcher",
                    created_at_utc="2026-07-31T12:00:00+00:00",
                    completed_at_utc="2026-07-31T12:00:00+00:00",
                ))
            response = self.client_for_admin(database).get("/admin/imports")
            self.assertEqual(response.status_code, 200)
            self.assertNotIn(b"roster.xlsx", response.data)
            self.assertIn(b"automatic updates", response.data)

    def client_for_admin(self, database: Path):
        admin = CurrentUser("app.admin", "PC01", (ROLE_APPLICATION_ADMIN,))
        client = webapp.create_app(self.make_result(database)).test_client()
        with client.session_transaction() as session:
            session["iam_user"] = admin.username
            session["iam_roles"] = list(admin.roles)
            session["is_admin"] = True
        return client


if __name__ == "__main__":
    unittest.main()

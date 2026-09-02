"""
File: tests/test_webapp.py
Purpose: Provides automated regression tests for test webapp.
Responsibilities: Exposes or coordinates: WebAppTests.
Dependencies: unittest, iam_automation
Inputs/outputs: Inputs: temporary databases, fixtures, and test doubles. Outputs: assertions and test results.
Author / implementation: Miguel Fernandez.
Developed for: Kaiser Permanente NSES GWFM.
Project implementation and integration: Miguel Fernandez.
Third-party source, libraries, and dependencies retain their original licenses.
Estimated implementation effort: 1.25 h (Git-derived heuristic; see docs/file-effort-history.md).
"""

from __future__ import annotations

import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from iam_automation import webapp
from iam_automation.application.employee_service import EmployeeService
from iam_automation.application.notification_service import NotificationService
from iam_automation.database.runtime_schema import initialize_runtime_database
from iam_automation.identity import CurrentUser, ROLE_APPLICATION_ADMIN
from iam_automation.startup import PreflightResult, StartupSettings, StartupState


@unittest.skipIf(webapp.Flask is None, "Flask is optional in the development environment")
class WebAppTests(unittest.TestCase):
    def make_result(self, ok: bool) -> PreflightResult:
        root = Path("/tmp/OneDrive - Test/IAMAutomation")
        settings = StartupSettings(root, root / "iam.accdb", root / "iam_runtime.sqlite", root / "runtime.sqlite", Path("/tmp/IAMAutomation/workspace"), root / "backups", root / "audit", approved_users_path=Path("/tmp/users.csv"))
        return PreflightResult(StartupState.READY if ok else StartupState.INVALID_PATH, ok, "test", settings)

    def test_blocked_preflight_cannot_reach_login(self):
        app = webapp.create_app(self.make_result(False))
        self.assertEqual(app.test_client().get("/login").status_code, 503)

    def test_raw_iso_timestamps_are_humanized_in_templates(self):
        app = webapp.create_app(self.make_result(True))
        rendered = app.jinja_env.from_string("{{ timestamp }}").render(timestamp="2026-08-14T00:00:00")
        self.assertEqual(rendered, "Aug 14, 2026, 12:00 AM UTC")

    def test_web_login_creates_local_session_and_opens_dashboard(self):
        user = type("User", (), {"username": "DOMAIN\\user", "roles": ("REQUESTER",)})()
        app = webapp.create_app(self.make_result(True), app_authenticator=lambda username, password: user)
        client = app.test_client()
        self.assertEqual(client.get("/login").status_code, 200)
        with client.session_transaction() as session:
            csrf_token = session["iam_csrf_token"]
        response = client.post("/login", data={"username": "app-user", "password": "secret", "csrf_token": csrf_token}, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Workspace overview", response.data)
        self.assertIn(b"DOMAIN\\user", response.data)
        self.assertIn(b"Workspace actions", response.data)
        self.assertIn(b"according to your role", response.data)
        dashboard = client.get("/dashboard")
        self.assertIn(b"Workspace overview", dashboard.data)
        self.assertEqual(client.get("/logout").status_code, 302)
        self.assertEqual(client.get("/dashboard").status_code, 302)

    def test_testing_help_requires_login_and_is_available_in_session(self):
        user = type("User", (), {"username": "tester", "roles": ("REQUESTER",)})()
        app = webapp.create_app(self.make_result(True), app_authenticator=lambda username, password: user)
        client = app.test_client()
        self.assertEqual(client.get("/help/testing").status_code, 302)
        with client.session_transaction() as session:
            csrf_token = session["iam_csrf_token"]
        client.post("/login", data={"username": "tester", "password": "secret", "csrf_token": csrf_token})
        response = client.get("/help/testing")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Testing &amp; Help Center", response.data)
        self.assertIn(b"PRE-001", response.data)
        self.assertIn(b"Report a bug", response.data)

    def test_workspace_status_requires_login(self):
        app = webapp.create_app(self.make_result(True))
        self.assertEqual(app.test_client().get("/workspace/status").status_code, 401)

    def test_reports_requires_login(self):
        app = webapp.create_app(self.make_result(True))
        self.assertEqual(app.test_client().get("/reports").status_code, 302)

    def test_employee_directory_stays_empty_until_user_requests_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = initialize_runtime_database(Path(tmp) / "runtime.sqlite")
            settings = StartupSettings(
                database.parent / "sharepoint",
                database.parent / "database.accdb",
                database.parent / "published.sqlite",
                database,
                database.parent / "workspace",
                database.parent / "backups",
                database.parent / "audit",
            )
            app = webapp.create_app(PreflightResult(StartupState.READY, True, "ready", settings))
            client = app.test_client()
            with client.session_transaction() as session:
                session["iam_user"] = "directory.user"
                session["iam_roles"] = ["REQUESTER"]

            blocked_query = {"side_effect": AssertionError("empty directory request must not load employee rows")}
            with patch.object(EmployeeService, "filter_values", return_value=(["ACTIVE"], ["Vendor A"], ["ACCESSNOW"])), \
                patch.object(EmployeeService, "list_workers_page", **blocked_query), \
                patch.object(EmployeeService, "rehire_alerts", return_value=[]), \
                patch.object(EmployeeService, "pending_source_update_count", return_value=0):
                response = client.get("/employees")
                self.assertEqual(response.status_code, 200)
                self.assertIn(b"Search to view employees", response.data)
                self.assertIn(b"Vendor A", response.data)
                long_empty_url = "/employees?q=&status=ALL&vendor=ALL&source=ALL&updated=ALL&sort=UPDATED_DESC&engagement=&review="
                canonical = client.get(long_empty_url)
                self.assertEqual(canonical.status_code, 302)
                self.assertEqual(canonical.headers["Location"], "/employees")

    def test_source_updates_has_operational_inbox_and_separate_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = initialize_runtime_database(Path(tmp) / "runtime.sqlite")
            settings = StartupSettings(
                database.parent / "sharepoint",
                database.parent / "database.accdb",
                database.parent / "published.sqlite",
                database,
                database.parent / "workspace",
                database.parent / "backups",
                database.parent / "audit",
            )
            app = webapp.create_app(PreflightResult(StartupState.READY, True, "ready", settings))
            client = app.test_client()
            with client.session_transaction() as session:
                session["iam_user"] = "directory.user"
                session["iam_roles"] = ["REQUESTER"]

            inbox = client.get("/employees/source-updates")
            self.assertEqual(inbox.status_code, 200)
            self.assertIn(b"Needs attention", inbox.data)
            self.assertIn(b"Review history", inbox.data)
            self.assertIn(b"No files need attention right now", inbox.data)

            history = client.get("/employees/source-updates/history")
            self.assertEqual(history.status_code, 200)
            self.assertIn(b"Review history", history.data)
            self.assertIn(b"Filter file history", history.data)

    def test_notification_pages_use_one_canonical_center(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = initialize_runtime_database(Path(tmp) / "runtime.sqlite")
            NotificationService(database).create(
                "app.admin",
                "TEST",
                "Test notification",
                "Review this local event.",
                severity="WARNING",
            )
            settings = StartupSettings(
                database.parent / "sharepoint",
                database.parent / "database.accdb",
                database.parent / "published.sqlite",
                database,
                database.parent / "workspace",
                database.parent / "backups",
                database.parent / "audit",
            )
            app = webapp.create_app(PreflightResult(StartupState.READY, True, "ready", settings))
            client = app.test_client()
            with client.session_transaction() as session:
                session["iam_user"] = "app.admin"
                session["iam_roles"] = [ROLE_APPLICATION_ADMIN]
                session["is_admin"] = True

            legacy = client.get("/admin/notifications?status=UNREAD&severity=WARNING")
            self.assertEqual(legacy.status_code, 302)
            self.assertIn("/notifications?status=UNREAD&severity=WARNING", legacy.headers["Location"])
            response = client.get(legacy.headers["Location"])
            self.assertEqual(response.status_code, 200)
            self.assertIn(b"Local workspace inbox", response.data)
            self.assertIn(b"Test notification", response.data)
            self.assertIn(b"Mark all as read", response.data)

    def test_notification_toast_is_transient_and_can_clear_inbox(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = initialize_runtime_database(Path(tmp) / "runtime.sqlite")
            service = NotificationService(database)
            service.create("app.admin", "TEST", "One", "First event")
            service.create("app.admin", "TEST", "Two", "Second event")
            settings = StartupSettings(
                database.parent / "sharepoint",
                database.parent / "database.accdb",
                database.parent / "published.sqlite",
                database,
                database.parent / "workspace",
                database.parent / "backups",
                database.parent / "audit",
            )
            app = webapp.create_app(PreflightResult(StartupState.READY, True, "ready", settings))
            client = app.test_client()
            with client.session_transaction() as session:
                session["iam_user"] = "app.admin"
                session["iam_roles"] = [ROLE_APPLICATION_ADMIN]
                session["is_admin"] = True
            client.get("/notifications")
            with client.session_transaction() as session:
                csrf_token = session["iam_csrf_token"]

            response = client.get("/notifications?notice=Saved&notice_type=success")
            self.assertIn(b'id="iamToast"', response.data)
            self.assertIn(b"history.replaceState", response.data)
            cleared = client.post("/notifications/read-all", data={"csrf_token": csrf_token}, follow_redirects=False)
            self.assertEqual(cleared.status_code, 302)
            self.assertEqual(service.unread_count("app.admin"), 0)

    def test_local_server_uses_loopback_and_ephemeral_port(self):
        app = webapp.create_app(self.make_result(True))
        server = webapp.LocalWebAppServer(app)
        try:
            try:
                url = server.start()
            except PermissionError as exc:
                self.skipTest(f"loopback sockets are unavailable in this environment: {exc}")
            self.assertTrue(url.startswith("http://127.0.0.1:"))
            self.assertGreater(server.port, 0)
        finally:
            server.stop()


if __name__ == "__main__":
    unittest.main()
#endfile

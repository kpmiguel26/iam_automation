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
from iam_automation.application.workspace_refresh_service import record_published_source_checksum
from iam_automation.database.runtime_schema import initialize_runtime_database
from iam_automation.identity import CurrentUser, ROLE_APPLICATION_ADMIN, validate_app_user_from_sqlite
from iam_automation.application.user_service import UserService
from iam_automation.runtime_sync import sha256_file
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

    def test_first_master_admin_sets_password_and_publishes_initial_account(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / "OneDrive - Test" / "IAMAutomation"
            published = initialize_runtime_database(root / "database" / "snapshots" / "iam_runtime.sqlite")
            local = initialize_runtime_database(base / "runtime.sqlite")
            record_published_source_checksum(local, sha256_file(published))
            service = UserService(local)
            service.create_user("DOMAIN\\user", "DOMAIN\\user", "old-password-for-bootstrap", ["MASTER_ADMIN"])
            settings = StartupSettings(
                root,
                None,
                published,
                local,
                base / "workspace",
                root / "backups",
                root / "audit",
            )
            result = PreflightResult(StartupState.READY, True, "ready", settings)
            app = webapp.create_app(result)
            client = app.test_client()

            with patch("iam_automation.webapp.windows_username", return_value="DOMAIN\\user"):
                response = client.get("/login")
                self.assertEqual(response.status_code, 302)
                self.assertIn("/first-run/admin", response.headers["Location"])
                with client.session_transaction() as session:
                    csrf_token = session["iam_csrf_token"]
                response = client.post(
                    "/first-run/admin",
                    data={
                        "csrf_token": csrf_token,
                        "application_username": "migue",
                        "display_name": "Miguel Fernandez",
                        "password": "a-long-first-password",
                        "confirm_password": "a-long-first-password",
                    },
                )

            self.assertEqual(response.status_code, 200)
            self.assertIn(b"Miguel Fernandez is ready as MASTER_ADMIN", response.data)
            self.assertIn(b"Sign in with this application username: <code>migue</code>", response.data)
            user = validate_app_user_from_sqlite(published, "migue", "a-long-first-password")
            self.assertEqual(user.roles, ("MASTER_ADMIN",))
            published_user = UserService(published).get_user("migue")
            self.assertIsNotNone(published_user)
            self.assertEqual(published_user.display_name, "Miguel Fernandez")
            self.assertIsNone(UserService(published).get_user("DOMAIN\\user"))
            self.assertFalse((local.with_name("runtime.publish-pending.json")).exists())

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

    def test_business_rules_help_requires_login_and_contains_main_sections(self):
        app = webapp.create_app(self.make_result(True))
        client = app.test_client()
        self.assertEqual(client.get("/help/business-rules").status_code, 302)
        with client.session_transaction() as session:
            session["iam_user"] = "tester"
            session["iam_roles"] = ["REQUESTER"]

        response = client.get("/help/business-rules")

        self.assertEqual(response.status_code, 200)
        for anchor in ("what-it-does", "before-after", "creating-rule", "operands", "operators", "composite", "business-days", "rule-lifecycle", "finding-lifecycle", "troubleshooting"):
            self.assertIn(f'id="{anchor}"'.encode(), response.data)
        self.assertIn(b"advisory-only", response.data)
        self.assertIn(b"Example: rehire review window", response.data)
        self.assertIn(b"user must decide and configure", response.data)
        self.assertIn(b"Rules do not block imports", response.data)

    def test_business_rules_contextual_help_links_point_to_help_anchors(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = initialize_runtime_database(Path(tmp) / "runtime.sqlite")
            admin = CurrentUser("app.admin", "PC01", (ROLE_APPLICATION_ADMIN,))
            root = database.parent / "sharepoint"
            settings = StartupSettings(root, root / "database.accdb", root / "published.sqlite", database, root / "workspace", root / "backups", root / "audit")
            app = webapp.create_app(PreflightResult(StartupState.READY, True, "ready", settings), app_authenticator=lambda _u, _p: admin)
            client = app.test_client()
            with client.session_transaction() as session:
                session["iam_user"] = admin.username
                session["iam_roles"] = list(admin.roles)

            business_rules = client.get("/admin/business-rules")
            self.assertEqual(business_rules.status_code, 200)
            self.assertIn(b'href="/help/business-rules"', business_rules.data)

            wizard = client.get("/admin/business-rules/wizard/phase")
            self.assertEqual(wizard.status_code, 200)
            self.assertIn(b"/help/business-rules#before-after", wizard.data)

            with client.session_transaction() as session:
                csrf_token = session["iam_csrf_token"]
            headers = {"X-CSRF-Token": csrf_token}
            source = client.post("/admin/business-rules/wizard/source", data={"phase": "AFTER"}, headers=headers)
            self.assertIn(b"/help/business-rules#creating-rule", source.data)
            details = client.post("/admin/business-rules/wizard/details", data={"phase": "AFTER", "source_system": "MASTER_ROSTER"}, headers=headers)
            for anchor in ("composite", "operands", "operators"):
                self.assertIn(f"/help/business-rules#{anchor}".encode(), details.data)
            condition = client.post("/admin/business-rules/wizard/condition", data={"phase": "AFTER", "source_system": "MASTER_ROSTER", "field": "email", "operator": "missing", "value": ""}, headers=headers)
            self.assertIn(b"/help/business-rules#creating-rule", condition.data)
            review = client.post("/admin/business-rules/wizard/review", data={"phase": "AFTER", "source_system": "MASTER_ROSTER", "field": "email", "operator": "missing", "value": "", "rule_number": "1", "name": "Missing email", "description": "Review missing email.", "generated_name": "AFTER - MR - 001 - email - Missing email"}, headers=headers)
            self.assertIn(b"/help/business-rules#rule-lifecycle", review.data)

            help_page = client.get("/help/business-rules")
            for anchor in ("before-after", "creating-rule", "composite", "operands", "operators", "rule-lifecycle"):
                self.assertIn(f'id="{anchor}"'.encode(), help_page.data)

    def test_workspace_refresh_guard_is_loaded_on_every_authenticated_page(self):
        user = type("User", (), {"username": "tester", "roles": ("REQUESTER",)})()
        app = webapp.create_app(self.make_result(True), app_authenticator=lambda username, password: user)
        client = app.test_client()
        with client.session_transaction() as session:
            session["iam_user"] = "tester"
            session["iam_roles"] = ["REQUESTER"]
            session["iam_session_started_at"] = "2026-09-04T12:00:00+00:00"

        profile = client.get("/profile")
        self.assertEqual(profile.status_code, 200)
        self.assertIn(b'id="workspaceUpdateModal"', profile.data)
        self.assertIn(b"/workspace/status", profile.data)

        dashboard = client.get("/dashboard")
        self.assertEqual(dashboard.status_code, 200)
        self.assertEqual(dashboard.data.count(b'id="workspaceUpdateModal"'), 1)

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

    def test_partial_source_import_does_not_block_next_stage(self):
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

            files_by_source = {
                "ROSTER_LOCK": [{
                    "source_system": "ROSTER_LOCK",
                    "source_file": "roster.xlsx",
                    "source_path": "roster.xlsx",
                    "source_checksum": "roster-checksum",
                    "record_count": 15,
                    "staged_count": 1,
                    "pending_count": 1,
                    "linked_count": 14,
                    "ambiguous_count": 0,
                    "conflict_count": 0,
                    "imported": False,
                    "latest_at": "2026-09-17T21:28:20+00:00",
                    "source_modified_at": "2026-07-31T20:08:53+00:00",
                }],
                "MASTER_ROSTER": [],
                "RSR_SUPPLIER_WORKER_DETAILS": [],
                "ACCESSNOW": [{
                    "source_system": "ACCESSNOW",
                    "source_file": "access.csv",
                    "source_path": "access.csv",
                    "source_checksum": "access-checksum",
                    "record_count": 2,
                    "staged_count": 2,
                    "pending_count": 2,
                    "linked_count": 0,
                    "ambiguous_count": 0,
                    "conflict_count": 0,
                    "imported": False,
                    "latest_at": "2026-09-17T21:31:00+00:00",
                    "source_modified_at": "2026-09-17T21:31:00+00:00",
                }],
            }

            with patch.object(EmployeeService, "list_source_systems", return_value=[]), patch.object(EmployeeService, "list_source_files", side_effect=lambda source: [dict(item) for item in files_by_source[source]]):
                response = client.get("/employees/source-updates")

            self.assertEqual(response.status_code, 200)
            self.assertIn(b"Imported with warnings", response.data)
            self.assertIn(b"access.csv", response.data)
            self.assertIn(b"Import file", response.data)
            self.assertNotIn(b"Waiting for previous stage", response.data)

            files_by_source["ROSTER_LOCK"][0]["staged_count"] = 15
            with patch.object(EmployeeService, "list_source_systems", return_value=[]), patch.object(EmployeeService, "list_source_files", side_effect=lambda source: [dict(item) for item in files_by_source[source]]):
                blocked_response = client.get("/employees/source-updates")

            self.assertIn(b"Waiting for previous stage", blocked_response.data)

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

    def test_local_server_drains_waitress_workers_before_closing(self):
        events = []

        class FakeDispatcher:
            def shutdown(self, *, timeout):
                events.append(("dispatcher.shutdown", timeout))

        class FakeServer:
            task_dispatcher = FakeDispatcher()

            def close(self):
                events.append(("server.close",))

        class FakeThread:
            def join(self, *, timeout):
                events.append(("thread.join", timeout))

        server = webapp.LocalWebAppServer(object())
        server._server = FakeServer()
        server._thread = FakeThread()

        server.stop()

        self.assertEqual(
            events,
            [("dispatcher.shutdown", 2), ("server.close",), ("thread.join", 2)],
        )


if __name__ == "__main__":
    unittest.main()
#endfile

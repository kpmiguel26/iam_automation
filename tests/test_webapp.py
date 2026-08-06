from __future__ import annotations

import unittest
from pathlib import Path

from iam_automation import webapp
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

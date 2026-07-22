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

    def test_local_server_uses_loopback_and_ephemeral_port(self):
        app = webapp.create_app(self.make_result(True), identity_validator=lambda _: type("User", (), {"username": "DOMAIN\\user", "roles": ("REQUESTER",)})())
        server = webapp.LocalWebAppServer(app)
        try:
            url = server.start()
            self.assertTrue(url.startswith("http://127.0.0.1:"))
            self.assertGreater(server.port, 0)
        finally:
            server.stop()


if __name__ == "__main__":
    unittest.main()

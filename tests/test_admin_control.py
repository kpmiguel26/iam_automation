from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from iam_automation import webapp
from iam_automation.database.runtime_schema import initialize_runtime_database
from iam_automation.identity import CurrentUser, ROLE_APPLICATION_ADMIN, ROLE_REQUESTER
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


if __name__ == "__main__":
    unittest.main()

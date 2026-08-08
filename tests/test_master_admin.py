"""
File: tests/test_master_admin.py
Purpose: Provides automated regression tests for test master admin.
Responsibilities: Exposes or coordinates: MasterAdminTests.
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
from iam_automation.database.runtime_schema import initialize_runtime_database
from iam_automation.identity import CurrentUser, ROLE_APPLICATION_ADMIN, ROLE_MASTER_ADMIN
from iam_automation.startup import PreflightResult, StartupSettings, StartupState
from iam_automation.application.user_service import UserService


class MasterAdminTests(unittest.TestCase):
    def make_result(self, database: Path) -> PreflightResult:
        root = database.parent / "sharepoint"
        settings = StartupSettings(root, root / "database.accdb", root / "published.sqlite", database, root / "workspace", root / "backups", root / "audit")
        settings.audit_folder_path.mkdir(parents=True, exist_ok=True)
        return PreflightResult(StartupState.READY, True, "ready", settings)

    def client_for(self, database: Path, user: CurrentUser):
        app = webapp.create_app(self.make_result(database), app_authenticator=lambda _u, _p: user)
        client = app.test_client()
        with client.session_transaction() as session:
            session["iam_user"] = user.username
            session["iam_roles"] = list(user.roles)
        return client

    def test_master_routes_are_backend_protected(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = initialize_runtime_database(Path(tmp) / "runtime.sqlite")
            self.assertEqual(self.client_for(database, CurrentUser("app", "pc", (ROLE_APPLICATION_ADMIN,))).get("/admin/master/administrators").status_code, 403)
            client = self.client_for(database, CurrentUser("master", "pc", (ROLE_MASTER_ADMIN,)))
            self.assertEqual(client.get("/admin/master/administrators").status_code, 200)

    def test_master_can_save_settings_and_break_glass_requires_reason(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = initialize_runtime_database(Path(tmp) / "runtime.sqlite")
            client = self.client_for(database, CurrentUser("master", "pc", (ROLE_MASTER_ADMIN,)))
            client.get("/admin/master/settings")
            with client.session_transaction() as session:
                csrf_token = session["iam_csrf_token"]
            response = client.post("/admin/master/settings", data={"sla_create": "12", "sla_update": "8", "sla_deactivate": "4", "break_glass_enabled": "1", "csrf_token": csrf_token})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(client.post("/admin/master/break-glass", data={"operation": "recover queue", "reason": "", "csrf_token": csrf_token}).status_code, 400)
            self.assertEqual(client.post("/admin/master/break-glass", data={"operation": "recover queue", "reason": "Approved test recovery", "csrf_token": csrf_token}).status_code, 302)
            self.assertEqual(client.get("/admin/master/audit").status_code, 200)

    def test_last_master_admin_cannot_lose_master_role(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = initialize_runtime_database(Path(tmp) / "runtime.sqlite")
            service = UserService(database)
            service.create_user("master", "Master", "secret", [ROLE_MASTER_ADMIN])
            with self.assertRaisesRegex(ValueError, "last active administrator"):
                service.update_user("master", display_name="Master", password="", roles=[ROLE_APPLICATION_ADMIN], active=True)


if __name__ == "__main__":
    unittest.main()

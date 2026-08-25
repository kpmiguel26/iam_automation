"""
File: tests/test_user_service.py
Purpose: Provides automated regression tests for test user service.
Responsibilities: Exposes or coordinates: UserServiceTests.
Dependencies: unittest, werkzeug, iam_automation
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
import sqlite3
from pathlib import Path

from werkzeug.security import check_password_hash

from iam_automation.application.user_service import UserService
from iam_automation.database.runtime_schema import initialize_runtime_database
from iam_automation.domain.users import ACCOUNT_STATUS_PASSWORD_RESET_REQUIRED, ACCOUNT_STATUS_SUSPENDED


class UserServiceTests(unittest.TestCase):
    def test_create_and_update_application_user(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = initialize_runtime_database(Path(tmp) / "runtime.sqlite")
            service = UserService(database)

            service.create_user("iam.admin", "IAM Admin", "secret", ["ADMINISTRATOR"])
            created = service.list_users()[0]
            self.assertEqual(created.username, "iam.admin")
            self.assertEqual(created.roles, ("APPLICATION_ADMIN",))
            self.assertTrue(created.active)

            service.create_user("master.admin", "Master Admin", "master-secret", ["MASTER_ADMIN"])

            service.update_user(
                "iam.admin",
                display_name="Updated Admin",
                password="new-secret",
                roles=["AUDITOR"],
                active=False,
            )
            updated = service.list_users()[0]
            self.assertEqual(updated.display_name, "Updated Admin")
            self.assertEqual(updated.roles, ("AUDITOR",))
            self.assertFalse(updated.active)
            connection = sqlite3.connect(database)
            try:
                row = connection.execute("SELECT password_hash FROM app_users WHERE username = ?", ("iam.admin",)).fetchone()
            finally:
                connection.close()
            self.assertTrue(check_password_hash(row[0], "new-secret"))

    def test_cannot_remove_last_active_administrator(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = initialize_runtime_database(Path(tmp) / "runtime.sqlite")
            service = UserService(database)
            service.create_user("master.admin", "Master Admin", "secret", ["MASTER_ADMIN"])
            with self.assertRaisesRegex(ValueError, "last active administrator"):
                service.update_user("master.admin", display_name="Master Admin", password="", roles=["AUDITOR"], active=False)

    def test_account_lifecycle_uses_controlled_statuses(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = initialize_runtime_database(Path(tmp) / "runtime.sqlite")
            service = UserService(database)
            service.create_user("iam.user", "IAM User", "secret", ["REQUESTER"])

            service.update_user(
                "iam.user",
                display_name="IAM User",
                password="",
                roles=["REQUESTER"],
                active=False,
                status=ACCOUNT_STATUS_SUSPENDED,
            )
            suspended = service.list_users()[0]
            self.assertEqual(suspended.status, ACCOUNT_STATUS_SUSPENDED)
            self.assertFalse(suspended.active)

            service.update_user(
                "iam.user",
                display_name="IAM User",
                password="",
                roles=["REQUESTER"],
                active=False,
                status=ACCOUNT_STATUS_PASSWORD_RESET_REQUIRED,
            )
            self.assertEqual(service.list_users()[0].status, ACCOUNT_STATUS_PASSWORD_RESET_REQUIRED)

    def test_rejects_unknown_account_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = initialize_runtime_database(Path(tmp) / "runtime.sqlite")
            service = UserService(database)
            service.create_user("iam.user", "IAM User", "secret", ["REQUESTER"])
            with self.assertRaisesRegex(ValueError, "Status must be selected"):
                service.update_user("iam.user", display_name="IAM User", password="", roles=["REQUESTER"], active=False, status="UNKNOWN")

if __name__ == "__main__":
    unittest.main()
#endfile

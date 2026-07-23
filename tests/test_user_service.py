from __future__ import annotations

import tempfile
import unittest
import sqlite3
from pathlib import Path

from werkzeug.security import check_password_hash

from iam_automation.application.user_service import UserService
from iam_automation.database.runtime_schema import initialize_runtime_database


class UserServiceTests(unittest.TestCase):
    def test_create_and_update_application_user(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = initialize_runtime_database(Path(tmp) / "runtime.sqlite")
            service = UserService(database)

            service.create_user("iam.admin", "IAM Admin", "secret", ["ADMINISTRATOR"])
            created = service.list_users()[0]
            self.assertEqual(created.username, "iam.admin")
            self.assertEqual(created.roles, ("ADMINISTRATOR",))
            self.assertTrue(created.active)

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

            row = sqlite3.connect(database).execute("SELECT password_hash FROM app_users").fetchone()
            self.assertTrue(check_password_hash(row[0], "new-secret"))


if __name__ == "__main__":
    unittest.main()

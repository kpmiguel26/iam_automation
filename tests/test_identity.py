"""
File: tests/test_identity.py
Purpose: Provides automated regression tests for test identity.
Responsibilities: Exposes or coordinates: IdentityTests.
Dependencies: unittest, iam_automation, werkzeug
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
from unittest.mock import patch

from iam_automation.database import initialize_runtime_database
from iam_automation.identity import load_approved_users, validate_app_user_from_sqlite, validate_current_user
from iam_automation.application.user_service import UserService
from werkzeug.security import generate_password_hash


class IdentityTests(unittest.TestCase):
    def test_loads_active_users_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "users.csv"
            path.write_text(
                "username,roles,active\nDOMAIN\\user,\"Administrator,IAM Analyst\",true\nDOMAIN\\inactive,Auditor,false\n",
                encoding="utf-8",
            )
            users = load_approved_users(path)
        self.assertIn("domain\\user", users)
        self.assertNotIn("domain\\inactive", users)

    def test_rejects_unapproved_current_user(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "users.csv"
            path.write_text("username,roles,active\nDOMAIN\\other,Auditor,true\n", encoding="utf-8")
            with patch("iam_automation.identity.windows_username", return_value="DOMAIN\\user"):
                with self.assertRaises(PermissionError):
                    validate_current_user(path)

    def test_application_login_is_separate_from_windows_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = initialize_runtime_database(Path(tmp) / "runtime.sqlite")
            connection = sqlite3.connect(path)
            try:
                connection.execute(
                    "INSERT INTO app_users (username, display_name, password_hash) VALUES (?, ?, ?)",
                    ("app.admin", "Application Admin", generate_password_hash("secret")),
                )
                connection.execute("INSERT OR IGNORE INTO roles (role_name) VALUES (?)", ("ADMINISTRATOR",))
                connection.execute("INSERT INTO user_roles (username, role_name) VALUES (?, ?)", ("app.admin", "ADMINISTRATOR"))
                connection.commit()
            finally:
                connection.close()
            user = validate_app_user_from_sqlite(path, "app.admin", "secret")
            self.assertEqual(user.username, "app.admin")
            self.assertEqual(user.roles, ("APPLICATION_ADMIN",))

    def test_non_active_application_account_cannot_login(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = initialize_runtime_database(Path(tmp) / "runtime.sqlite")
            service = UserService(path)
            service.create_user("app.user", "Application User", "secret", ["REQUESTER"])
            service.update_user(
                "app.user",
                display_name="Application User",
                password="",
                roles=["REQUESTER"],
                active=False,
                status="SUSPENDED",
            )
            with self.assertRaisesRegex(PermissionError, "Invalid application username or password"):
                validate_app_user_from_sqlite(path, "app.user", "secret")


if __name__ == "__main__":
    unittest.main()
#endfile

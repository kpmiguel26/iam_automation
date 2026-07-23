from __future__ import annotations

import tempfile
import unittest
import sqlite3
from pathlib import Path
from unittest.mock import patch

from iam_automation.database import initialize_runtime_database
from iam_automation.identity import load_approved_users, validate_app_user_from_sqlite, validate_current_user
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


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from iam_automation.database import initialize_runtime_database


class RuntimeSchemaTests(unittest.TestCase):
    def test_runtime_database_is_created_idempotently(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "runtime.sqlite"
            initialize_runtime_database(path)
            initialize_runtime_database(path)
            connection = sqlite3.connect(path)
            tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
            connection.close()
            self.assertTrue({"app_metadata", "approved_users", "app_users", "roles", "user_roles"}.issubset(tables))


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from iam_automation.database import applied_migrations, apply_pending_migrations, initialize_runtime_database


class MigrationTests(unittest.TestCase):
    def test_existing_runtime_is_registered_and_migrations_are_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = initialize_runtime_database(Path(tmp) / "runtime.sqlite")
            first = applied_migrations(database)
            second = apply_pending_migrations(database, actor="test")

            self.assertEqual(first, ("v001_initial_schema", "v002_notification_indexes", "v003_ingestion_records", "v004_worker_domain", "v005_rsr_worker_details"))
            self.assertEqual(second, ())
            connection = sqlite3.connect(database)
            try:
                index_names = {row[1] for row in connection.execute("PRAGMA index_list(notifications)")}
            finally:
                connection.close()
            self.assertIn("idx_notifications_recipient_status", index_names)


if __name__ == "__main__":
    unittest.main()

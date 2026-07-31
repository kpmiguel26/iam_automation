from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from iam_automation.database import applied_migrations, apply_pending_migrations, initialize_runtime_database
from iam_automation.database.migration_runner import current_database_revision


class MigrationTests(unittest.TestCase):
    def test_existing_runtime_is_registered_and_migrations_are_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = initialize_runtime_database(Path(tmp) / "runtime.sqlite")
            first = applied_migrations(database)
            second = apply_pending_migrations(database, actor="test")

            self.assertEqual(first, ("v001_initial_schema", "v002_notification_indexes", "v003_ingestion_records", "v004_worker_domain", "v005_rsr_worker_details", "v006_worker_history"))
            self.assertEqual(second, ())
            connection = sqlite3.connect(database)
            try:
                index_names = {row[1] for row in connection.execute("PRAGMA index_list(notifications)")}
                table_names = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
                worker_columns = {row[1] for row in connection.execute("PRAGMA table_info(workers)")}
                alembic_revision = connection.execute("SELECT version_num FROM alembic_version").fetchone()[0]
            finally:
                connection.close()
            self.assertIn("idx_notifications_recipient_status", index_names)
            self.assertIn("worker_profile_versions", table_names)
            self.assertIn("worker_merge_events", table_names)
            self.assertIn("superseded_by_worker_id", worker_columns)
            self.assertEqual(alembic_revision, "0006_worker_history")
            self.assertEqual(current_database_revision(database), "0006_worker_history")


if __name__ == "__main__":
    unittest.main()

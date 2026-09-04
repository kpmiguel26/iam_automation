"""
File: tests/test_migrations.py
Purpose: Provides automated regression tests for test migrations.
Responsibilities: Exposes or coordinates: MigrationTests.
Dependencies: unittest, iam_automation
Inputs/outputs: Inputs: temporary databases, fixtures, and test doubles. Outputs: assertions and test results.
Author / implementation: Miguel Fernandez.
Developed for: Kaiser Permanente NSES GWFM.
Project implementation and integration: Miguel Fernandez.
Third-party source, libraries, and dependencies retain their original licenses.
Estimated implementation effort: 1.25 h (Git-derived heuristic; see docs/file-effort-history.md).
"""

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

            self.assertEqual(first, ("v001_initial_schema", "v002_notification_indexes", "v003_ingestion_records", "v004_worker_domain", "v005_rsr_worker_details", "v006_worker_history", "v007_source_observations", "v008_source_file_timestamps", "v009_local_notification_store", "v010_accessnow_match_indexes", "v011_business_rules", "v012_compact_employee_fields", "v013_star_schema", "v014_worker_field_history"))
            self.assertEqual(second, ())
            connection = sqlite3.connect(database)
            try:
                index_names = {row[1] for row in connection.execute("PRAGMA index_list(notifications)")}
                worker_identifier_indexes = {row[1] for row in connection.execute("PRAGMA index_list(worker_identifiers)")}
                worker_indexes = {row[1] for row in connection.execute("PRAGMA index_list(workers)")}
                table_names = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
                worker_columns = {row[1] for row in connection.execute("PRAGMA table_info(workers)")}
                alembic_revision = connection.execute("SELECT version_num FROM alembic_version").fetchone()[0]
            finally:
                connection.close()
            self.assertIn("idx_notifications_recipient_status", index_names)
            self.assertIn("worker_profile_versions", table_names)
            self.assertIn("worker_merge_events", table_names)
            self.assertIn("worker_source_profiles", table_names)
            self.assertIn("business_rules", table_names)
            self.assertIn("business_rule_versions", table_names)
            self.assertIn("rule_findings", table_names)
            self.assertIn("field_catalog", table_names)
            self.assertIn("employee_field_values", table_names)
            self.assertIn("fact_source_snapshot", table_names)
            self.assertIn("fact_termination", table_names)
            self.assertIn("fact_assignment", table_names)
            self.assertIn("fact_worker_field_history", table_names)
            self.assertIn("dim_source", table_names)
            self.assertIn("dim_field", table_names)
            self.assertIn("dim_date", table_names)
            self.assertIn("dim_vendor", table_names)
            self.assertIn("superseded_by_worker_id", worker_columns)
            self.assertIn("idx_worker_identifiers_match", worker_identifier_indexes)
            self.assertIn("idx_workers_canonical_email", worker_indexes)
            self.assertIn("idx_workers_canonical_name", worker_indexes)
            self.assertEqual(alembic_revision, "0014_worker_field_history")
            self.assertEqual(current_database_revision(database), "0014_worker_field_history")


if __name__ == "__main__":
    unittest.main()
#endfile

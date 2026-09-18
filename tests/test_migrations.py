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
from iam_automation.infrastructure.sqlite.orm import BusinessRuleModel, BusinessRuleVersionModel, orm_session


class MigrationTests(unittest.TestCase):
    def test_existing_runtime_is_registered_and_migrations_are_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = initialize_runtime_database(Path(tmp) / "runtime.sqlite")
            first = applied_migrations(database)
            second = apply_pending_migrations(database, actor="test")

            self.assertEqual(first, ("v001_initial_schema", "v002_notification_indexes", "v003_ingestion_records", "v004_worker_domain", "v005_rsr_worker_details", "v006_worker_history", "v007_source_observations", "v008_source_file_timestamps", "v009_local_notification_store", "v010_accessnow_match_indexes", "v011_business_rules", "v012_compact_employee_fields", "v013_star_schema", "v014_worker_field_history", "v015_source_separated_write_model", "v016_allow_fact_linking", "v017_rule_execution_phase", "v018_fact_quarantine", "v019_rule_configuration", "v020_rule_context_binding", "v021_pin_rule_calendar_version", "v022_source_rule_catalog"))
            self.assertEqual(second, ())
            connection = sqlite3.connect(database)
            try:
                index_names = {row[1] for row in connection.execute("PRAGMA index_list(notifications)")}
                worker_identifier_indexes = {row[1] for row in connection.execute("PRAGMA index_list(worker_identifiers)")}
                worker_indexes = {row[1] for row in connection.execute("PRAGMA index_list(workers)")}
                table_names = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
                trigger_names = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'trigger'")}
                worker_columns = {row[1] for row in connection.execute("PRAGMA table_info(workers)")}
                field_columns = {row[1] for row in connection.execute("PRAGMA table_info(dim_field)")}
                rule_version_columns = {row[1] for row in connection.execute("PRAGMA table_info(business_rule_versions)")}
                context_version_columns = {row[1] for row in connection.execute("PRAGMA table_info(rule_context_versions)")}
                pinned_calendar_version = connection.execute(
                    "SELECT default_calendar_version_id FROM rule_context_versions WHERE context_version_id = 'context:default:1'"
                ).fetchone()[0]
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
            self.assertIn("dim_employee", table_names)
            self.assertIn("bridge_employee_identifier", table_names)
            self.assertIn("source_field_mapping", table_names)
            self.assertIn("field_ownership", table_names)
            self.assertIn("employee_identity_rule", table_names)
            self.assertIn("fact_accessnow_employee", table_names)
            self.assertIn("fact_master_roster_employee", table_names)
            self.assertIn("fact_roster_lock_assignment", table_names)
            self.assertIn("fact_rsr_assignment", table_names)
            self.assertIn("fact_employee_status_event", table_names)
            self.assertIn("fact_source_field_value", table_names)
            self.assertIn("fact_employee_field_history", table_names)
            self.assertIn("trg_status_event_accessnow_source", trigger_names)
            self.assertIn("trg_fact_accessnow_employee_immutable_update", trigger_names)
            self.assertIn("superseded_by_worker_id", worker_columns)
            self.assertIn("idx_worker_identifiers_match", worker_identifier_indexes)
            self.assertIn("idx_workers_canonical_email", worker_indexes)
            self.assertIn("idx_workers_canonical_name", worker_indexes)
            self.assertIn("fact_quarantine", table_names)
            self.assertIn("rule_calendars", table_names)
            self.assertIn("rule_calendar_versions", table_names)
            self.assertIn("rule_calendar_holidays", table_names)
            self.assertIn("rule_contexts", table_names)
            self.assertIn("rule_context_versions", table_names)
            self.assertIn("semantic_type", field_columns)
            self.assertIn("allowed_operators_json", field_columns)
            self.assertIn("context_version_id", rule_version_columns)
            self.assertIn("default_calendar_version_id", context_version_columns)
            self.assertEqual(pinned_calendar_version, "calendar:standard:1")
            self.assertEqual(alembic_revision, "0022_source_rule_catalog")
            self.assertEqual(current_database_revision(database), "0022_source_rule_catalog")

    def test_calendar_binding_migration_pins_legacy_rule_versions(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = initialize_runtime_database(Path(tmp) / "runtime.sqlite")
            with orm_session(database) as session:
                session.add(BusinessRuleModel(
                    rule_id="legacy-rule", name="Legacy rule", status="ACTIVE",
                    current_version=1, created_at_utc="now", updated_at_utc="now",
                ))
                session.add(BusinessRuleVersionModel(
                    rule_version_id="legacy-rule:1", rule_id="legacy-rule", version=1,
                    condition_json='{"field":"email","operator":"missing"}',
                    scope_json="{}", status="ACTIVE", created_at_utc="now",
                ))

            connection = sqlite3.connect(database)
            try:
                connection.execute("UPDATE alembic_version SET version_num = '0020_rule_context_binding'")
                connection.commit()
            finally:
                connection.close()

            self.assertEqual(apply_pending_migrations(database), ("v021_pin_rule_calendar_version", "v022_source_rule_catalog"))
            with orm_session(database) as session:
                version = session.get(BusinessRuleVersionModel, "legacy-rule:1")
                self.assertEqual(version.context_version_id, "context:default:1")


if __name__ == "__main__":
    unittest.main()
#endfile

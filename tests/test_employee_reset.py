"""
File: tests/test_employee_reset.py
Purpose: Provides automated regression tests for test employee reset.
Responsibilities: Exposes or coordinates: EmployeeResetTests.
Dependencies: unittest, iam_automation
Inputs/outputs: Inputs: temporary databases, fixtures, and test doubles. Outputs: assertions and test results.
Author / implementation: Miguel Fernandez.
Developed for: Kaiser Permanente NSES GWFM.
Project implementation and integration: Miguel Fernandez.
Third-party source, libraries, and dependencies retain their original licenses.
Estimated implementation effort: 1.25 h (Git-derived heuristic; see docs/file-effort-history.md).
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from iam_automation.application.employee_reset_service import EmployeeResetService
from iam_automation.application.publication_state import publication_pending
from iam_automation.database.runtime_schema import initialize_runtime_database


class EmployeeResetTests(unittest.TestCase):
    def test_reset_preserves_users_and_clears_employee_test_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            database = initialize_runtime_database(root / "runtime.sqlite")
            connection = sqlite3.connect(database)
            connection.executescript(
                """
                INSERT INTO app_users(username, display_name, password_hash) VALUES ('admin', 'Admin', 'hash');
                INSERT INTO user_roles(username, role_name) VALUES ('admin', 'MASTER_ADMIN');
                INSERT INTO approved_users(username, display_name) VALUES ('admin', 'Admin');
                INSERT INTO workers(worker_id, first_name, last_name, display_name) VALUES ('worker-1', 'Ada', 'Lovelace', 'Ada Lovelace');
                INSERT INTO worker_identifiers(identifier_id, worker_id, source_system, identifier_type, identifier_value, normalized_value) VALUES ('identifier-1', 'worker-1', 'ROSTER_LOCK', 'VENDOR_ID', '123', '123');
                INSERT INTO worker_engagements(engagement_id, worker_id, vendor_name) VALUES ('engagement-1', 'worker-1', 'TTEC');
                INSERT INTO worker_profile_versions(version_id, worker_id, version_number, snapshot_json) VALUES ('version-1', 'worker-1', 1, '{}');
                INSERT INTO worker_merge_events(merge_id, survivor_worker_id, duplicate_worker_id, reason) VALUES ('merge-1', 'worker-1', 'worker-1', 'test');
                INSERT INTO worker_source_lineage(lineage_id, worker_id, batch_id, source_system, source_file, source_checksum, row_number, field_name) VALUES ('lineage-1', 'worker-1', 'batch-1', 'ROSTER_LOCK', 'input.xlsx', 'checksum', 1, 'first_name');
                INSERT INTO worker_discrepancies(discrepancy_id, worker_id, source_system, source_record_key, field_name) VALUES ('discrepancy-1', 'worker-1', 'ROSTER_LOCK', '123', 'last_name');
                INSERT INTO import_batches(batch_id, filename, source_type, created_by) VALUES ('batch-1', 'input.xlsx', 'ROSTER_LOCK', 'admin');
                INSERT INTO ingestion_records(record_id, batch_id, source_system, source_file, source_checksum, row_number, source_record_key, normalized_json, payload_json) VALUES ('record-1', 'batch-1', 'ROSTER_LOCK', 'input.xlsx', 'checksum', 1, '123', '{}', '{}');
                INSERT INTO fact_master_roster_employee(master_roster_fact_id, batch_id, source_id, source_record_key) VALUES ('source-fact-1', 'batch-1', (SELECT source_id FROM dim_source WHERE source_system = 'ROSTER_LOCK'), '123');
                INSERT INTO fact_quarantine(quarantine_fact_id, finding_id, worker_id, batch_id, source_system, source_record_key, rule_id, rule_version_id) VALUES ('quarantine-fact-1', 'finding-1', 'worker-1', 'batch-1', 'ROSTER_LOCK', '123', 'rule-1', 'rule-1:1');
                INSERT INTO business_rules(rule_id, name, description, status, current_version, created_by, created_at_utc, updated_at_utc) VALUES ('rule-1', 'Missing email', '', 'ACTIVE', 1, 'admin', 'now', 'now');
                INSERT INTO business_rule_versions(rule_version_id, rule_id, version, phase, scope_json, condition_json, severity, status, created_by, created_at_utc) VALUES ('rule-1:1', 'rule-1', 1, 'BEFORE', '{}', '{}', 'WARNING', 'ACTIVE', 'admin', 'now');
                INSERT INTO quarantine_records(quarantine_id, batch_id, row_number, reason, payload_json) VALUES ('quarantine-1', 'batch-1', 2, 'missing', '{}');
                INSERT INTO file_observations(path, file_kind, signature) VALUES ('input.xlsx', 'ROSTER_LOCK', 'checksum');
                INSERT INTO change_requests(request_id, created_at_utc, created_by, computer_name, application_version, operation_type, entity_type, entity_id, payload_json, reason) VALUES ('request-1', 'now', 'admin', 'test', 'local', 'IMPORT_ROSTER_LOCK', 'import_batch', 'batch-1', '{}', 'test');
                INSERT INTO approval_assignments(assignment_id, request_id, assigned_to, assigned_by, reason) VALUES ('assignment-1', 'request-1', 'admin', 'admin', 'test');
                INSERT INTO publication_queue(publication_id, request_id, queued_by, queued_at_utc) VALUES ('publication-1', 'request-1', 'admin', 'now');
                """
            )
            connection.commit()
            connection.close()

            result = EmployeeResetService(database, audit_path=root / "audit").reset("admin")

            self.assertTrue(Path(result["backup"]).is_file())
            self.assertTrue(publication_pending(database))
            connection = sqlite3.connect(database)
            for table in EmployeeResetService.EMPLOYEE_TABLES:
                self.assertEqual(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0], 0, table)
            trigger_names = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'trigger'")}
            self.assertIn("trg_fact_master_roster_employee_immutable_delete", trigger_names)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM app_users").fetchone()[0], 1)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM user_roles").fetchone()[0], 1)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM business_rules").fetchone()[0], 1)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM business_rule_versions").fetchone()[0], 1)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM change_requests").fetchone()[0], 0)
            connection.close()
            audit_lines = list((root / "audit").glob("audit_*.jsonl"))[0].read_text(encoding="utf-8").splitlines()
            self.assertEqual(json.loads(audit_lines[-1])["action"], "EMPLOYEE_TEST_DATA_RESET")

            result = EmployeeResetService(database, audit_path=root / "audit").reset("admin", clear_business_rules=True)
            self.assertTrue(result["clear_business_rules"])
            connection = sqlite3.connect(database)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM business_rule_versions").fetchone()[0], 0)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM business_rules").fetchone()[0], 0)
            connection.close()


if __name__ == "__main__":
    unittest.main()
#endfile

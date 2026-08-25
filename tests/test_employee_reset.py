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
                INSERT INTO quarantine_records(quarantine_id, batch_id, row_number, reason, payload_json) VALUES ('quarantine-1', 'batch-1', 2, 'missing', '{}');
                INSERT INTO file_observations(path, file_kind, signature) VALUES ('input.xlsx', 'ROSTER_LOCK', 'checksum');
                INSERT INTO change_requests(request_id, created_at_utc, created_by, computer_name, application_version, operation_type, entity_type, entity_id, payload_json, reason) VALUES ('request-1', 'now', 'admin', 'test', 'local', 'IMPORT_ROSTER_LOCK', 'import_batch', 'batch-1', '{}', 'test');
                INSERT INTO approval_assignments(assignment_id, request_id, assigned_to, assigned_by, reason) VALUES ('assignment-1', 'request-1', 'admin', 'admin', 'test');
                INSERT INTO publication_queue(publication_id, request_id, queued_by, queued_at_utc) VALUES ('publication-1', 'request-1', 'admin', 'now');
                INSERT INTO notifications(notification_id, recipient_username, notification_type, title, message, entity_type, entity_id) VALUES ('notification-1', 'admin', 'IMPORT_READY', 'Import', 'Review', 'import_batch', 'request-1');
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
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM app_users").fetchone()[0], 1)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM user_roles").fetchone()[0], 1)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM change_requests").fetchone()[0], 0)
            connection.close()
            audit_lines = list((root / "audit").glob("audit_*.jsonl"))[0].read_text(encoding="utf-8").splitlines()
            self.assertEqual(json.loads(audit_lines[-1])["action"], "EMPLOYEE_TEST_DATA_RESET")


if __name__ == "__main__":
    unittest.main()
#endfile

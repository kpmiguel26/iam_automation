"""
File: tests/test_database_schema.py
Purpose: Provides automated regression tests for test database schema.
Responsibilities: Exposes or coordinates: DatabaseSchemaTests.
Dependencies: unittest, iam_automation
Inputs/outputs: Inputs: temporary databases, fixtures, and test doubles. Outputs: assertions and test results.
Author / implementation: Miguel Fernandez.
Developed for: Kaiser Permanente NSES GWFM.
Project implementation and integration: Miguel Fernandez.
Third-party source, libraries, and dependencies retain their original licenses.
Estimated implementation effort: 1.25 h (Git-derived heuristic; see docs/file-effort-history.md).
"""

from __future__ import annotations

import unittest

from iam_automation.database import ACCESS_TABLES, access_schema_statements


class DatabaseSchemaTests(unittest.TestCase):
    def test_schema_has_all_initial_business_tables(self):
        statements = "\n".join(access_schema_statements())
        for table in ACCESS_TABLES:
            self.assertIn(f"CREATE TABLE {table}", statements)

    def test_schema_contains_request_audit_and_export_controls(self):
        statements = "\n".join(access_schema_statements())
        for table in ("tbl_ChangeRequests", "tbl_RequestDecisions", "tbl_AuditEvents", "tbl_ExportRuns", "tbl_DatabaseVersions"):
            self.assertIn(table, statements)


if __name__ == "__main__":
    unittest.main()
#endfile

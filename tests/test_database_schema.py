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

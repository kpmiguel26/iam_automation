"""
File: tests/test_admin_control.py
Purpose: Provides automated regression tests for test admin control.
Responsibilities: Exposes or coordinates: AdminControlTests.
Dependencies: unittest, iam_automation
Inputs/outputs: Inputs: temporary databases, fixtures, and test doubles. Outputs: assertions and test results.
Author / implementation: Miguel Fernandez.
Developed for: Kaiser Permanente NSES GWFM.
Project implementation and integration: Miguel Fernandez.
Third-party source, libraries, and dependencies retain their original licenses.
Estimated implementation effort: 1.25 h (Git-derived heuristic; see docs/file-effort-history.md).
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from iam_automation import webapp
from iam_automation.application.shared_request_service import SharedRequestService
from iam_automation.application.business_rule_service import BusinessRuleService
from iam_automation.database.runtime_schema import initialize_runtime_database
from iam_automation.identity import CurrentUser, ROLE_APPLICATION_ADMIN, ROLE_REQUESTER, ROLE_SUPER_OPERATOR
from iam_automation.startup import PreflightResult, StartupSettings, StartupState


class AdminControlTests(unittest.TestCase):
    def make_result(self, database: Path) -> PreflightResult:
        root = database.parent / "sharepoint"
        settings = StartupSettings(root, root / "database.accdb", root / "published.sqlite", database, root / "workspace", root / "backups", root / "audit")
        return PreflightResult(StartupState.READY, True, "ready", settings)

    def test_application_admin_can_open_control_center(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = initialize_runtime_database(Path(tmp) / "runtime.sqlite")
            admin = CurrentUser("app.admin", "PC01", (ROLE_APPLICATION_ADMIN,))
            app = webapp.create_app(self.make_result(database), app_authenticator=lambda _u, _p: admin)
            client = app.test_client()
            with client.session_transaction() as session:
                session["iam_user"] = admin.username
                session["iam_roles"] = list(admin.roles)
            self.assertEqual(client.get("/admin").status_code, 200)
            self.assertEqual(client.get("/admin/users").status_code, 200)

    def test_quarantine_page_replaces_rule_findings_page(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = initialize_runtime_database(Path(tmp) / "runtime.sqlite")
            client = self.client_for_admin(database)
            response = client.get("/admin/quarantine")
            self.assertEqual(response.status_code, 200)
            self.assertIn(b"Quarantine", response.data)
            self.assertIn(b'hx-get="/admin/quarantine"', response.data)
            self.assertIn(b'name="rule_id"', response.data)
            legacy = client.get("/admin/business-rule-findings")
            self.assertEqual(legacy.status_code, 302)
            self.assertIn(b"/admin/quarantine", legacy.headers["Location"].encode())

    def test_quarantine_filters_return_htmx_findings_panel(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = initialize_runtime_database(Path(tmp) / "runtime.sqlite")
            client = self.client_for_admin(database)
            response = client.get(
                "/admin/quarantine?status=ALL&severity=WARNING&rule_id=rule-example",
                headers={"HX-Request": "true"},
            )
            self.assertEqual(response.status_code, 200)
            self.assertIn(b'id="quarantine-findings-region"', response.data)
            self.assertIn(b'hx-target="#quarantine-findings-region"', response.data)
            self.assertNotIn(b"<!doctype html", response.data.lower())

    def test_business_rule_wizard_filters_master_roster_fields_and_contains_operator(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = initialize_runtime_database(Path(tmp) / "runtime.sqlite")
            client = self.client_for_admin(database)
            client.get("/admin/business-rules/wizard/phase")
            with client.session_transaction() as session:
                csrf_token = session["iam_csrf_token"]
            headers = {"X-CSRF-Token": csrf_token}
            source = client.post("/admin/business-rules/wizard/source", data={"phase": "AFTER"}, headers=headers)
            self.assertEqual(source.status_code, 200)
            self.assertIn(b"Master Roster", source.data)
            self.assertIn(b"rule-accordion", source.data)
            self.assertIn(b"Execution phase", source.data)
            details = client.post(
                "/admin/business-rules/wizard/details",
                data={"phase": "AFTER", "source_system": "MASTER_ROSTER"},
                headers=headers,
            )
            self.assertEqual(details.status_code, 200)
            self.assertIn(b"npn_login_id", details.data)
            self.assertIn(b"Data to check", details.data)
            condition = client.post(
                "/admin/business-rules/wizard/condition",
                data={"phase": "AFTER", "source_system": "MASTER_ROSTER", "field": "npn_login_id", "operator": "contains", "value": "|RECORD|"},
                headers=headers,
            )
            self.assertEqual(condition.status_code, 200)
            self.assertIn(b"Rule naming", condition.data)
            review = client.post(
                "/admin/business-rules/wizard/review",
                data={"phase": "AFTER", "source_system": "MASTER_ROSTER", "field": "npn_login_id", "operator": "contains", "value": "|RECORD|", "rule_number": "7", "name": "Composite NPN", "description": "Review composite values.", "generated_name": "AFTER - MR - 007 - npn_login_id - Composite NPN"},
                headers=headers,
            )
            self.assertEqual(review.status_code, 200)
            self.assertIn(b"contains", review.data)
            self.assertIn(b"Review and create", review.data)
            self.assertIn(b"rule-accordion-item", review.data)
            start = client.get("/admin/business-rules/wizard/start")
            self.assertEqual(start.status_code, 200)
            self.assertIn(b"Create a rule", start.data)

    def test_business_rule_catalog_can_test_a_draft_rule(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = initialize_runtime_database(Path(tmp) / "runtime.sqlite")
            rule_id = BusinessRuleService(database).create_rule(
                name="Draft status test", description="Preview this rule.", field="status",
                operator="equals", value="TERMINATED", severity="WARNING", actor="test",
            )
            client = self.client_for_admin(database)
            client.get("/admin/business-rules")
            with client.session_transaction() as session:
                csrf_token = session["iam_csrf_token"]
            response = client.post(
                f"/admin/business-rules/{rule_id}/test",
                headers={"X-CSRF-Token": csrf_token, "HX-Request": "true"},
            )
            self.assertEqual(response.status_code, 200)
            self.assertIn(b"Rule test", response.data)
            self.assertIn(b"No records matched this rule", response.data)

    def test_requester_cannot_open_control_center(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = initialize_runtime_database(Path(tmp) / "runtime.sqlite")
            app = webapp.create_app(self.make_result(database))
            client = app.test_client()
            with client.session_transaction() as session:
                session["iam_user"] = "requester"
                session["iam_roles"] = [ROLE_REQUESTER]
            self.assertEqual(client.get("/admin").status_code, 403)
            self.assertEqual(client.get("/admin/users").status_code, 403)

    def test_temporary_super_operator_cannot_manage_master_security_or_publish_access(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = initialize_runtime_database(Path(tmp) / "runtime.sqlite")
            operator = CurrentUser("operator", "PC01", (ROLE_SUPER_OPERATOR,))
            client = webapp.create_app(self.make_result(database), app_authenticator=lambda _u, _p: operator).test_client()
            with client.session_transaction() as session:
                session["iam_user"] = operator.username
                session["iam_roles"] = list(operator.roles)
            self.assertEqual(client.get("/admin/master/settings").status_code, 403)
            with client.session_transaction() as session:
                csrf_token = session["iam_csrf_token"]
            self.assertEqual(client.post("/admin/governance/publish", headers={"X-CSRF-Token": csrf_token}).status_code, 403)

    def test_automatic_source_request_is_reviewed_only_in_source_updates(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = initialize_runtime_database(Path(tmp) / "runtime.sqlite")
            root = database.parent / "sharepoint"
            SharedRequestService(root).create(
                CurrentUser("workspace-watcher", "test-pc", (ROLE_APPLICATION_ADMIN,)),
                "IMPORT_ROSTER_LOCK",
                "batch-1",
                {"record_count": 1},
                "New source file detected",
            )
            client = self.client_for_admin(database)
            response = client.get("/admin/approvals")
            self.assertEqual(response.status_code, 200)
            self.assertNotIn(b"Roster Lock import", response.data)
            self.assertIn(b"Source Updates", response.data)

    def test_imports_page_hides_automatic_source_batches(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = initialize_runtime_database(Path(tmp) / "runtime.sqlite")
            from iam_automation.infrastructure.sqlite.orm import ImportBatchModel, orm_session

            with orm_session(database) as session:
                session.add(ImportBatchModel(
                    batch_id="auto-batch",
                    filename="roster.xlsx",
                    source_type="ROSTER_LOCK",
                    status="COMPLETED",
                    total_rows=1,
                    valid_rows=1,
                    quarantine_rows=0,
                    created_by="workspace-watcher",
                    created_at_utc="2026-07-31T12:00:00+00:00",
                    completed_at_utc="2026-07-31T12:00:00+00:00",
                ))
            response = self.client_for_admin(database).get("/admin/imports")
            self.assertEqual(response.status_code, 200)
            self.assertNotIn(b"roster.xlsx", response.data)
            self.assertIn(b"automatic updates", response.data)

    def client_for_admin(self, database: Path):
        admin = CurrentUser("app.admin", "PC01", (ROLE_APPLICATION_ADMIN,))
        client = webapp.create_app(self.make_result(database)).test_client()
        with client.session_transaction() as session:
            session["iam_user"] = admin.username
            session["iam_roles"] = list(admin.roles)
            session["is_admin"] = True
        return client


if __name__ == "__main__":
    unittest.main()
#endfile

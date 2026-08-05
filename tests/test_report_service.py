from __future__ import annotations

import tempfile
import unittest
import json
from datetime import datetime, timezone
from pathlib import Path

from iam_automation.application.report_service import ReportService
from iam_automation.application.report_template_service import ReportTemplateService
from iam_automation.application.employee_service import EmployeeService
from iam_automation.application.user_service import UserService
from iam_automation.database.runtime_schema import initialize_runtime_database
from iam_automation.infrastructure.sqlite.orm import (
    IngestionRecordModel,
    WorkerDiscrepancyModel,
    WorkerEngagementModel,
    WorkerModel,
    WorkerSourceProfileModel,
    orm_session,
)
from iam_automation import webapp
from iam_automation.startup import PreflightResult, StartupSettings, StartupState


class ReportServiceTests(unittest.TestCase):
    def test_report_template_folders_scope_private_and_shared_templates(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = ReportTemplateService(Path(tmp))
            private_folder = service.save_folder(name="My Queries", created_by="alice")
            shared_folder = service.save_folder(name="Team Queries", created_by="alice", shared=True)
            service.save(name="Private", definition={"columns": []}, created_by="alice", folder_id=private_folder.folder_id)
            shared = service.save(name="Shared", definition={"columns": []}, created_by="alice", folder_id=shared_folder.folder_id, shared=True)

            self.assertEqual({item.name for item in service.list_for_user("alice")}, {"Private", "Shared"})
            self.assertEqual([item.name for item in service.list_for_user("bob")], ["Shared"])
            self.assertEqual([item.name for item in service.list_folders("bob")], ["Team Queries"])
            private = next(item for item in service.list_for_user("alice") if item.name == "Private")
            self.assertIsNone(service.get_for_user(private.template_id, "bob"))
            self.assertEqual(service.get_for_user(shared.template_id, "bob").name, "Shared")

    def test_studio_field_catalog_is_limited_by_source_and_all_unlocks_catalog(self):
        service = ReportService(Path("/missing/runtime.sqlite"))
        roster_keys = {field.key for field in service.field_catalog("ROSTER_LOCK")}
        accessnow_keys = {field.key for field in service.field_catalog("ACCESSNOW")}
        all_keys = {field.key for field in service.field_catalog("ALL")}
        self.assertIn("engagement.onboarding_date", roster_keys)
        self.assertNotIn("engagement.statement_of_work", roster_keys)
        self.assertNotIn("engagement.vendor_name", accessnow_keys)
        self.assertIn("engagement.statement_of_work", all_keys)
        self.assertGreater(len(all_keys), len(roster_keys))

    def test_studio_catalog_and_preview_include_all_normalized_source_columns(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = initialize_runtime_database(Path(tmp) / "runtime.sqlite")
            with orm_session(database) as session:
                session.add(WorkerModel(worker_id="one", display_name="Ada Lovelace", status="ACTIVE"))
                session.add(WorkerSourceProfileModel(
                    profile_id="profile-1",
                    worker_id="one",
                    source_system="ROSTER_LOCK",
                    source_record_key="TTEC:100",
                    snapshot_json=json.dumps({"vendor_employee_id": "100", "custom_roster_column": "Priority"}),
                ))
                session.add(IngestionRecordModel(
                    record_id="record-1",
                    batch_id="batch-1",
                    source_system="ROSTER_LOCK",
                    source_file="roster.xlsx",
                    source_checksum="checksum",
                    row_number=2,
                    source_record_key="TTEC:100",
                    normalized_json=json.dumps({"vendor_employee_id": "100", "custom_roster_column": "Priority"}),
                    payload_json=json.dumps({"Custom Roster Column": "Priority"}),
                    status="APPLIED",
                    matched_worker_id="one",
                ))
            service = ReportService(database)
            keys = {field.key for field in service.field_catalog("ROSTER_LOCK")}
            self.assertIn("raw.ROSTER_LOCK.custom_roster_column", keys)
            preview = service.studio_preview(source="ROSTER_LOCK", columns=["employee.display_name", "raw.ROSTER_LOCK.custom_roster_column"])
            self.assertEqual(preview.rows[0]["raw.ROSTER_LOCK.custom_roster_column"], "Priority")

    def test_studio_catalog_preview_filters_and_excludes_superseded_workers(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = initialize_runtime_database(Path(tmp) / "runtime.sqlite")
            with orm_session(database) as session:
                session.add_all([
                    WorkerModel(worker_id="one", display_name="Ada Lovelace", status="ACTIVE"),
                    WorkerModel(worker_id="two", display_name="Grace Hopper", status="PENDING"),
                    WorkerModel(worker_id="old", display_name="Old Record", status="ACTIVE", superseded_by_worker_id="one"),
                ])
                session.add_all([
                    WorkerEngagementModel(engagement_id="one-roster", worker_id="one", source_system="ROSTER_LOCK", vendor_name="TTEC", onboarding_date="2026-08-04"),
                    WorkerEngagementModel(engagement_id="one-access", worker_id="one", source_system="ACCESSNOW", vendor_name="TTEC"),
                    WorkerEngagementModel(engagement_id="two-roster", worker_id="two", source_system="ROSTER_LOCK", vendor_name="Concentrix", onboarding_date="2026-07-01"),
                ])
            preview = ReportService(database).studio_preview(
                source="ROSTER_LOCK",
                columns=["employee.display_name", "engagement.vendor_name", "engagement.onboarding_date"],
                filter_field="engagement.onboarding_date",
                filter_operator="greater_than",
                filter_value="2026-08-01",
                sort_field="engagement.onboarding_date",
            )
            self.assertEqual(preview.total_rows, 1)
            self.assertEqual(preview.rows[0]["employee.display_name"], "Ada Lovelace")
            self.assertEqual(preview.definition["sources"], ["ROSTER_LOCK"])
            self.assertIn("ACTIVE", preview.filter_options["employee.status"])

    def test_studio_empty_filters_do_not_require_a_filter_value(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = initialize_runtime_database(Path(tmp) / "runtime.sqlite")
            with orm_session(database) as session:
                session.add_all([
                    WorkerModel(worker_id="has-email", display_name="Has Email", canonical_email="has@example.com"),
                    WorkerModel(worker_id="no-email", display_name="No Email", canonical_email=""),
                ])

            preview = ReportService(database).studio_preview(
                source="CANONICAL",
                columns=["employee.display_name", "employee.email"],
                filter_field="employee.email",
                filter_operator="is_empty",
            )

            self.assertEqual(preview.total_rows, 1)
            self.assertEqual(preview.rows[0]["employee.display_name"], "No Email")
            self.assertEqual(preview.definition["filters"][0]["operator"], "is_empty")

    def test_studio_date_filters_accept_common_date_formats(self):
        self.assertTrue(ReportService._matches("12/31/2025", "greater_than", "01/01/2025", "date"))
        self.assertTrue(ReportService._matches("31/12/2025", "less_than", "01/01/2026", "date"))
        self.assertFalse(ReportService._matches("2026-08-10", "last_days", "5", "date"))

    def test_studio_multi_value_filters_apply_before_unlimited_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = initialize_runtime_database(Path(tmp) / "runtime.sqlite")
            with orm_session(database) as session:
                session.add_all([
                    WorkerModel(worker_id="active", display_name="Active", status="ACTIVE"),
                    WorkerModel(worker_id="pending", display_name="Pending", status="PENDING"),
                    WorkerModel(worker_id="terminated", display_name="Terminated", status="TERMINATED"),
                ])

            preview = ReportService(database).studio_preview(
                source="CANONICAL",
                columns=["employee.display_name", "employee.status"],
                filters=[{"field": "employee.status", "operator": "in", "value": ["ACTIVE", "PENDING"]}],
                limit="all",
            )

            self.assertEqual(preview.total_rows, 2)
            self.assertEqual(preview.definition["limit"], None)
            self.assertEqual({row["employee.status"] for row in preview.rows}, {"ACTIVE", "PENDING"})

    def test_studio_all_source_returns_one_row_per_employee(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = initialize_runtime_database(Path(tmp) / "runtime.sqlite")
            with orm_session(database) as session:
                session.add(WorkerModel(worker_id="one", display_name="One", status="ACTIVE"))
                session.add_all([
                    WorkerEngagementModel(engagement_id="one-roster", worker_id="one", source_system="ROSTER_LOCK", vendor_name="TTEC"),
                    WorkerEngagementModel(engagement_id="one-rsr", worker_id="one", source_system="RSR_SUPPLIER_WORKER_DETAILS", job_title="Developer"),
                ])

            preview = ReportService(database).studio_preview(
                source="ALL",
                columns=["employee.worker_id", "engagement.vendor_name", "engagement.job_title"],
                limit="all",
            )

            self.assertEqual(preview.total_rows, 1)
            self.assertEqual(preview.rows[0]["employee.worker_id"], "one")

    def test_new_hire_readiness_uses_roster_start_date_and_missing_source_coverage(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = initialize_runtime_database(Path(tmp) / "runtime.sqlite")
            with orm_session(database) as session:
                session.add_all([
                    WorkerModel(worker_id="newest", display_name="Newest Worker", canonical_email="new@example.com", status="ACTIVE"),
                    WorkerModel(worker_id="covered", display_name="Covered Worker", status="ACTIVE"),
                    WorkerModel(worker_id="old", display_name="Old Worker", status="ACTIVE"),
                    WorkerModel(worker_id="superseded", display_name="Superseded Worker", status="ACTIVE", superseded_by_worker_id="newest"),
                ])
                session.add_all([
                    WorkerEngagementModel(engagement_id="new-roster", worker_id="newest", source_system="ROSTER_LOCK", vendor_name="TTEC", onboarding_date="2026-08-04"),
                    WorkerEngagementModel(engagement_id="covered-roster", worker_id="covered", source_system="ROSTER_LOCK", vendor_name="TTEC", onboarding_date="2026-08-03"),
                    WorkerEngagementModel(engagement_id="covered-rsr", worker_id="covered", source_system="RSR_SUPPLIER_WORKER_DETAILS", vendor_name="TTEC"),
                    WorkerEngagementModel(engagement_id="covered-access", worker_id="covered", source_system="ACCESSNOW", vendor_name="TTEC"),
                    WorkerEngagementModel(engagement_id="old-roster", worker_id="old", source_system="ROSTER_LOCK", vendor_name="TTEC", onboarding_date="2026-07-01"),
                    WorkerEngagementModel(engagement_id="superseded-roster", worker_id="superseded", source_system="ROSTER_LOCK", vendor_name="TTEC", onboarding_date="2026-08-05"),
                ])
            rows = ReportService(database).new_hire_readiness()
            self.assertEqual([row.worker_id for row in rows], ["newest", "old"])
            self.assertEqual(rows[0].work_start_date, "2026-08-04")
            self.assertTrue(rows[0].missing_fieldglass)
            self.assertTrue(rows[0].missing_accessnow)

    def test_empty_database_returns_zeroed_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            snapshot = ReportService(Path(tmp) / "missing.sqlite").snapshot()
            self.assertEqual(snapshot.total_employees, 0)
            self.assertEqual(snapshot.vendors, ())
            self.assertTrue(snapshot.as_of_utc)

    def test_snapshot_counts_unique_workers_across_historical_vendor_engagements(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = initialize_runtime_database(Path(tmp) / "runtime.sqlite")
            with orm_session(database) as session:
                session.add_all([
                    WorkerModel(worker_id="active", display_name="Active Worker", status="ACTIVE"),
                    WorkerModel(worker_id="pending", display_name="Pending Worker", status="PENDING"),
                    WorkerModel(worker_id="no-vendor", display_name="No Vendor", status="INACTIVE"),
                    WorkerModel(worker_id="superseded", display_name="Old Worker", status="ACTIVE", superseded_by_worker_id="active"),
                ])
                session.add_all([
                    WorkerEngagementModel(engagement_id="a-1", worker_id="active", vendor_name="TTEC"),
                    WorkerEngagementModel(engagement_id="a-2", worker_id="active", vendor_name="Concentrix"),
                    WorkerEngagementModel(engagement_id="p-1", worker_id="pending", vendor_name="TTEC"),
                    WorkerEngagementModel(engagement_id="old-1", worker_id="superseded", vendor_name="TTEC"),
                ])
                session.add_all([
                    WorkerDiscrepancyModel(discrepancy_id="open", worker_id="active", source_system="TEST", source_record_key="a", field_name="vendor", status="OPEN"),
                    WorkerDiscrepancyModel(discrepancy_id="closed", worker_id="pending", source_system="TEST", source_record_key="p", field_name="vendor", status="RESOLVED"),
                ])

            snapshot = ReportService(database).snapshot()
            self.assertEqual((snapshot.total_employees, snapshot.active_employees, snapshot.pending_inactive_employees), (3, 1, 2))
            self.assertEqual((snapshot.total_vendors, snapshot.employees_without_vendor, snapshot.open_discrepancies, snapshot.total_vendor_engagements), (2, 1, 1, 3))
            rows = {row.vendor_name: row for row in snapshot.vendors}
            self.assertEqual(rows["TTEC"].employee_count, 2)
            self.assertEqual(rows["TTEC"].engagement_count, 2)
            self.assertEqual(rows["TTEC"].active_count, 1)
            self.assertEqual(rows["TTEC"].pending_inactive_count, 1)
            self.assertEqual(rows["TTEC"].open_discrepancy_count, 1)
            self.assertEqual(rows["Concentrix"].employee_count, 1)

    def test_directory_supports_report_card_filters(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = initialize_runtime_database(Path(tmp) / "runtime.sqlite")
            with orm_session(database) as session:
                session.add_all([
                    WorkerModel(worker_id="active", display_name="Active", status="ACTIVE"),
                    WorkerModel(worker_id="inactive", display_name="Inactive", status="INACTIVE"),
                    WorkerModel(worker_id="missing", display_name="Missing", status="PENDING"),
                ])
                session.add(WorkerEngagementModel(engagement_id="active-vendor", worker_id="active", vendor_name="TTEC"))
                session.add(WorkerDiscrepancyModel(discrepancy_id="active-discrepancy", worker_id="active", source_system="TEST", source_record_key="a", field_name="status", status="OPEN"))

            service = EmployeeService(database)
            _, total_non_active = service.list_workers_page(status="NON_ACTIVE")
            _, total_without_vendor = service.list_workers_page(vendor="NONE")
            _, total_with_discrepancy = service.list_workers_page(review="OPEN")
            self.assertEqual(total_non_active, 2)
            self.assertEqual(total_without_vendor, 2)
            self.assertEqual(total_with_discrepancy, 1)

    def test_authenticated_report_page_renders_vendor_link(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            database = initialize_runtime_database(root / "runtime.sqlite")
            UserService(database).create_user("reporter", "Reporter", "secret", ["REQUESTER"])
            with orm_session(database) as session:
                session.add(WorkerModel(worker_id="worker-1", display_name="Ada Lovelace", status="ACTIVE"))
                session.add(WorkerEngagementModel(engagement_id="engagement-1", worker_id="worker-1", vendor_name="TTEC"))
            settings = StartupSettings(
                root,
                root / "iam.accdb",
                root / "published.sqlite",
                database,
                root / "workspace",
                root / "backups",
                root / "audit",
            )
            app = webapp.create_app(PreflightResult(StartupState.READY, True, "test", settings))
            client = app.test_client()
            with client.session_transaction() as flask_session:
                flask_session["iam_user"] = "reporter"
                flask_session["iam_roles"] = ["REQUESTER"]
                flask_session["iam_session_started_at"] = datetime.now(timezone.utc).isoformat()
            response = client.get("/reports")
            self.assertEqual(response.status_code, 200)
            self.assertIn(b"<h1>Reports</h1>", response.data)
            self.assertIn(b"/reports/vendors", response.data)
            self.assertIn(b"all=1", response.data)
            self.assertIn(b"status=NON_ACTIVE", response.data)
            self.assertIn(b"vendor=NONE", response.data)
            self.assertIn(b"review=OPEN", response.data)
            duplicate_response = client.get("/reports?duplicates=1")
            self.assertEqual(duplicate_response.status_code, 200)
            self.assertIn(b"No duplicate signals were found", duplicate_response.data)
            self.assertEqual(client.get("/reports/vendors").status_code, 200)
            self.assertIn(b"Vendor report", client.get("/reports/vendors").data)
            self.assertEqual(client.get("/reports/duplicates").status_code, 200)
            self.assertIn(b"Duplicate search", client.get("/reports/duplicates").data)
            new_hire_response = client.get("/reports/new-hires")
            self.assertEqual(new_hire_response.status_code, 200)
            self.assertIn(b"New hire readiness", new_hire_response.data)
            studio_response = client.get("/reports/studio")
            self.assertEqual(studio_response.status_code, 200)
            self.assertIn(b"Report Studio", studio_response.data)
            filter_options_response = client.get("/reports/studio/filter-options?source=CANONICAL&field=employee.status")
            self.assertEqual(filter_options_response.status_code, 200)
            self.assertIn(b"ACTIVE", filter_options_response.data)
            saved_template = client.post("/reports/studio/templates", json={
                "name": "Active employees",
                "definition": {"sources": ["CANONICAL"], "columns": ["employee.display_name"], "filters": [], "sort": [], "limit": None},
            })
            self.assertEqual(saved_template.status_code, 200)
            template_id = saved_template.get_json()["template_id"]
            loaded_template = client.get(f"/reports/studio?template_id={template_id}")
            self.assertEqual(loaded_template.status_code, 200)
            self.assertIn(b"Active employees", loaded_template.data)
            folder_response = client.post("/reports/studio/folders", json={"name": "My team queries", "shared": True})
            self.assertEqual(folder_response.status_code, 200)
            folder_id = folder_response.get_json()["folder_id"]
            shared_template = client.post("/reports/studio/templates", json={
                "name": "Shared active employees",
                "folder_id": folder_id,
                "shared": True,
                "definition": {"sources": ["CANONICAL"], "columns": ["employee.display_name"], "filters": [], "sort": [], "limit": None},
            })
            self.assertEqual(shared_template.status_code, 200)
            self.assertIn(b"Shared active employees", client.get("/reports/studio").data)
            self.assertIn(b"vendor/datatables/js/dataTables.min.js", studio_response.data)
            self.assertIn(b"vendor/datatables/js/jquery.min.js", studio_response.data)
            self.assertIn(b"vendor/datatables/js/buttons.html5.min.js", studio_response.data)
            studio_preview = client.post("/reports/studio", data={
                "source": "CANONICAL",
                "columns": ["employee.display_name", "employee.status"],
                "filter_field": "employee.display_name",
                "filter_operator": "contains",
                "filter_value": "Ada",
                "sort_field": "employee.display_name",
                "sort_direction": "asc",
                "limit": "25",
            })
            self.assertEqual(studio_preview.status_code, 200)
            self.assertIn(b"Ada Lovelace", studio_preview.data)


if __name__ == "__main__":
    unittest.main()

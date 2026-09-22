from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path

from openpyxl import Workbook

from iam_automation import webapp
from iam_automation.application.ingestion.configuration_contracts import DraftFieldDefinition, DraftSourceDefinition
from iam_automation.application.ingestion.configuration_service import DraftConfigurationService
from iam_automation.database.runtime_schema import initialize_runtime_database
from iam_automation.identity import CurrentUser, ROLE_APPLICATION_ADMIN
from iam_automation.infrastructure.sqlite.orm import ImportBatchModel, IngestionRecordModel, orm_session
from iam_automation.startup import PreflightResult, StartupSettings, StartupState


class IngestionConfigurationTests(unittest.TestCase):
    def make_app(self, database: Path):
        root = database.parent / "sharepoint"
        settings = StartupSettings(root, root / "database.accdb", root / "published.sqlite", database, root / "workspace", root / "backups", root / "audit")
        admin = CurrentUser("app.admin", "PC01", (ROLE_APPLICATION_ADMIN,))
        app = webapp.create_app(PreflightResult(StartupState.READY, True, "ready", settings), app_authenticator=lambda _u, _p: admin)
        client = app.test_client()
        with client.session_transaction() as session:
            session["iam_user"] = admin.username
            session["iam_roles"] = list(admin.roles)
            session["is_admin"] = True
        client.get("/admin/ingestion-sources")
        return client

    def csrf(self, client):
        with client.session_transaction() as session:
            return session["iam_csrf_token"]

    def test_configuration_page_loads_for_application_admin(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = initialize_runtime_database(Path(tmp) / "runtime.sqlite")
            response = self.make_app(database).get("/admin/ingestion-sources")
            self.assertEqual(response.status_code, 200)
            self.assertIn(b"Ingestion source configuration", response.data)
            self.assertIn(b"Draft only", response.data)
            self.assertIn(b"READ", response.data)
            self.assertIn(b"Read sample", response.data)
            self.assertIn(b"hx-indicator=\"#read-sample-button\"", response.data)
            self.assertIn(b"Reading report", response.data)

    def test_draft_contract_preserves_identifier_as_string(self):
        draft = DraftSourceDefinition(
            source_id="sample",
            display_name="Sample",
            fields=(DraftFieldDefinition("Employee ID", "employee_id", identifier=True),),
        )
        restored = DraftSourceDefinition.from_dict(draft.to_dict())
        self.assertEqual(restored.fields[0].data_type, "string")
        self.assertTrue(restored.fields[0].identifier)

    def test_csv_inspection_preserves_leading_zeroes_and_suggests_string(self):
        inspection = DraftConfigurationService.inspect_sample("sample.csv", b"Employee ID,Status\n001234,Active\n000007,Inactive\n")
        self.assertEqual(inspection["rows_detected"], 2)
        self.assertEqual(inspection["rows"][0]["Employee ID"], "001234")
        suggestions = {item["source_name"]: item["suggested_type"] for item in inspection["type_suggestions"]}
        self.assertEqual(suggestions["Employee ID"], "string")

    def test_excel_inspection_detects_sheets_headers_and_rows(self):
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "Roster"
        sheet.append(["Employee ID", "Hire Date"])
        sheet.append(["001234", "2026-09-22"])
        stream = io.BytesIO()
        workbook.save(stream)
        inspection = DraftConfigurationService.inspect_sample("sample.xlsx", stream.getvalue(), sheet_name="Roster")
        self.assertEqual(inspection["sheet_names"], ("Roster",))
        self.assertEqual(inspection["headers"], ("Employee ID", "Hire Date"))
        self.assertEqual(inspection["rows"][0]["Employee ID"], "001234")

    def test_master_roster_composes_nuid_and_npn_multiline_headers(self):
        path = Path(__file__).parent / "fixtures" / "sharepoint_simulated" / "master_roster" / "Kaiser_Master_Roster_2026-09-22T0610.xlsx"
        structure = DraftConfigurationService.inspect_structure(path.name, path.read_bytes())
        sheet = structure["sheets"][0]
        self.assertEqual(sheet["recommended_header_row"], 4)
        self.assertEqual(sheet["recommended_header_rows"], (1, 2, 3, 4))

        inspection = DraftConfigurationService.inspect_sample(
            path.name,
            path.read_bytes(),
            sheet_name="sheet1",
            header_row=4,
            header_rows=(1, 2, 3, 4),
        )
        self.assertEqual(inspection["rows_detected"], 1017)
        self.assertEqual(inspection["headers"][-2:], ("CLIENT · Kaiser Systems · NUID · LogonID", "OPERATIONS · Healthcare Systems · NPN · LogonID"))
        self.assertEqual(inspection["rows"][0]["CLIENT · Kaiser Systems · NUID · LogonID"], "O625432")
        self.assertEqual(inspection["rows"][0]["OPERATIONS · Healthcare Systems · NPN · LogonID"], "")

    def test_fields_can_be_added_and_removed_without_database_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = initialize_runtime_database(Path(tmp) / "runtime.sqlite")
            client = self.make_app(database)
            headers = {"X-CSRF-Token": self.csrf(client)}
            base = {"source_id": "sample", "display_name": "Sample", "field_source_name": ["Employee ID"], "field_key_0": "employee_id", "field_type_0": "string", "field_nullable_0": "on", "action": "add_field"}
            added = client.post("/admin/ingestion-sources", data=base, headers=headers)
            self.assertEqual(added.status_code, 302)
            self.assertIn(b"Employee ID", client.get("/admin/ingestion-sources").data)
            removed = client.post("/admin/ingestion-sources", data={**base, "remove_field_index": "0"}, headers=headers)
            self.assertEqual(removed.status_code, 302)
            self.assertIn(b"Your report preview will appear here", client.get("/admin/ingestion-sources").data)
            with orm_session(database) as session:
                self.assertEqual(session.query(ImportBatchModel).count(), 0)
                self.assertEqual(session.query(IngestionRecordModel).count(), 0)

    def test_preview_isolated_from_production_persistence(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = initialize_runtime_database(Path(tmp) / "runtime.sqlite")
            client = self.make_app(database)
            headers = {"X-CSRF-Token": self.csrf(client)}
            response = client.post(
                "/admin/ingestion-sources",
                data={
                    "source_id": "sample",
                    "display_name": "Sample",
                    "format": "CSV",
                    "field_source_name": ["Employee ID", "Status"],
                    "field_key_0": "employee_id",
                    "field_type_0": "string",
                    "field_identifier_0": "on",
                    "field_nullable_0": "on",
                    "field_key_1": "status",
                    "field_type_1": "string",
                    "field_nullable_1": "on",
                    "mapping_target_0": "employee_id",
                    "mapping_transform_0": "normalize_id",
                    "sample_file": (io.BytesIO(b"Employee ID,Status\n001234,Active\n"), "sample.csv"),
                    "action": "preview",
                },
                headers=headers,
                content_type="multipart/form-data",
            )
            self.assertEqual(response.status_code, 200)
            self.assertIn(b"Preview completed in memory", response.data)
            self.assertIn(b"001234", response.data)
            self.assertIn(b"No production ingestion objects were created", response.data)
            with orm_session(database) as session:
                self.assertEqual(session.query(ImportBatchModel).count(), 0)
                self.assertEqual(session.query(IngestionRecordModel).count(), 0)

    def test_invalid_draft_returns_useful_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = initialize_runtime_database(Path(tmp) / "runtime.sqlite")
            client = self.make_app(database)
            response = client.post(
                "/admin/ingestion-sources",
                data={"source_id": "bad key", "display_name": "", "action": "save"},
                headers={"X-CSRF-Token": self.csrf(client)},
            )
            self.assertEqual(response.status_code, 400)
            self.assertIn(b"Source key may contain only", response.data)
            self.assertIn(b"Display name is required", response.data)

    def test_htmx_flow_reads_file_selects_header_and_then_selects_source_schema(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = initialize_runtime_database(Path(tmp) / "runtime.sqlite")
            client = self.make_app(database)
            csrf = self.csrf(client)
            response = client.post(
                "/admin/ingestion-sources/sample/inspect",
                data={
                    "source_id": "roster",
                    "display_name": "Roster report",
                    "sample_file": (io.BytesIO(b"Report generated: today\nEmployee ID,Status\n001234,Active\n"), "roster.csv"),
                },
                headers={"X-CSRF-Token": csrf, "HX-Request": "true"},
                content_type="multipart/form-data",
            )
            self.assertEqual(response.status_code, 200)
            self.assertNotIn(b"<!doctype html>", response.data.lower())
            self.assertIn(b"Which rows make up the column headers?", response.data)
            self.assertIn(b"Employee ID", response.data)
            artifact_id = next(
                value.split('"', 1)[0]
                for value in response.data.decode().split('value="')[1:]
                if value and len(value.split('"', 1)[0]) == 32
            )

            selected = client.post(
                "/admin/ingestion-sources/sample/select",
                data={"artifact_id": artifact_id, "sheet_name": "", "header_row": "2"},
                headers={"X-CSRF-Token": csrf, "HX-Request": "true"},
            )
            self.assertEqual(selected.status_code, 200)
            self.assertIn(b"Review the data before selecting columns", selected.data)
            self.assertIn(b"001234", selected.data)
            self.assertIn(b"Choose what to import and how it may be used", selected.data)
            self.assertIn(b"Import this column", selected.data)
            self.assertIn(b"Data type", selected.data)

            role_changed = client.post(
                "/admin/ingestion-sources/draft/mapping",
                data={
                    "identity_role": "IDENTITY_SEED",
                    "field_include_0": "on",
                    "field_include_1": "on",
                    "field_key_0": "employee_id",
                    "field_type_0": "string",
                    "field_transform_0": "normalize_id",
                    "field_key_1": "status",
                    "field_type_1": "string",
                    "field_transform_1": "identity",
                },
                headers={"X-CSRF-Token": csrf, "HX-Request": "true"},
            )
            self.assertEqual(role_changed.status_code, 200)
            self.assertIn(b"Only a strong identifier may be allowed to create identity.", role_changed.data)
            switch_attributes = role_changed.data.decode().split('id="identity-can-create"', 1)[1].split(">", 1)[0]
            self.assertNotIn("disabled", switch_attributes)

            mapped = client.post(
                "/admin/ingestion-sources/draft/mapping",
                data={
                    "display_name": "Roster report",
                    "source_id": "roster",
                    "field_include_0": "on",
                    "field_key_0": "employee_id",
                    "field_type_0": "string",
                    "field_transform_0": "normalize_id",
                    "field_key_1": "status",
                    "field_type_1": "string",
                    "field_transform_1": "identity",
                    "identity_role": "IDENTITY_SEED",
                    "identity_can_create_employee": "on",
                    "identity_field_0_match": "on",
                    "identity_field_0_strength": "STRONG",
                    "identity_field_0_create": "on",
                    "identity_field_1_match": "on",
                    "identity_field_1_strength": "SUPPORTING",
                    "identity_field_1_create": "on",
                },
                headers={"X-CSRF-Token": csrf, "HX-Request": "true"},
            )
            self.assertEqual(mapped.status_code, 200)
            self.assertIn(b"Source schema saved in this browser session", mapped.data)

            preview = client.post(
                "/admin/ingestion-sources/sample/preview",
                headers={"X-CSRF-Token": csrf, "HX-Request": "true"},
            )
            self.assertEqual(preview.status_code, 200)
            self.assertIn(b"Preview completed in memory", preview.data)
            self.assertIn(b"001234", preview.data)

            with client.session_transaction() as session:
                saved = DraftSourceDefinition.from_dict(session["ingestion_configuration_draft"])
            self.assertEqual(tuple(field.source_name for field in saved.fields if field.include), ("Employee ID",))
            self.assertEqual(saved.fields[0].data_type, "string")
            self.assertEqual(saved.identity_governance.role, "IDENTITY_SEED")
            self.assertTrue(saved.identity_governance.can_create_employee)
            self.assertEqual(saved.identity_governance.identifiers[0].field_key, "employee_id")
            self.assertTrue(saved.identity_governance.identifiers[0].can_create_identity)
            self.assertEqual(len(saved.identity_governance.identifiers), 1)

            with orm_session(database) as session:
                self.assertEqual(session.query(ImportBatchModel).count(), 0)
                self.assertEqual(session.query(IngestionRecordModel).count(), 0)

    def test_htmx_master_roster_flow_suggests_and_composes_context_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = initialize_runtime_database(Path(tmp) / "runtime.sqlite")
            client = self.make_app(database)
            csrf = self.csrf(client)
            path = Path(__file__).parent / "fixtures" / "sharepoint_simulated" / "master_roster" / "Kaiser_Master_Roster_2026-09-22T0610.xlsx"
            response = client.post(
                "/admin/ingestion-sources/sample/inspect",
                data={"sample_file": (io.BytesIO(path.read_bytes()), path.name)},
                headers={"X-CSRF-Token": csrf, "HX-Request": "true"},
                content_type="multipart/form-data",
            )
            self.assertEqual(response.status_code, 200)
            self.assertIn(b"Suggested: rows 1, 2, 3, 4", response.data)
            self.assertIn(b"System Type Name", response.data)
            artifact_id = next(
                value.split('"', 1)[0]
                for value in response.data.decode().split('value="')[1:]
                if value and len(value.split('"', 1)[0]) == 32
            )
            selected = client.post(
                "/admin/ingestion-sources/sample/select",
                data={"artifact_id": artifact_id, "sheet_name": "sheet1", "header_rows": ["1", "2", "3", "4"], "header_row": "4"},
                headers={"X-CSRF-Token": csrf, "HX-Request": "true"},
            )
            self.assertEqual(selected.status_code, 200)
            self.assertIn(b"nuid", selected.data)
            self.assertIn(b"npn", selected.data)
            self.assertIn(b"CLIENT \xc2\xb7 Kaiser Systems \xc2\xb7 NUID \xc2\xb7 LogonID", selected.data)
            self.assertIn(b"1017 row(s) detected", selected.data)


if __name__ == "__main__":
    unittest.main()

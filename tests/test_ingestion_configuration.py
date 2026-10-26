from __future__ import annotations

import io
import sqlite3
import tempfile
import unittest
from pathlib import Path

from openpyxl import Workbook

from iam_automation import webapp
from iam_automation.application.ingestion.configuration_contracts import DraftFieldDefinition, DraftIdentityGovernance, DraftIdentityIdentifier, DraftRecognitionSettings, DraftSourceDefinition
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

    def test_identity_matching_is_limited_to_three_fields(self):
        draft = DraftSourceDefinition(
            source_id="sample",
            display_name="Sample",
            identity_governance=DraftIdentityGovernance(
                identifiers=tuple(
                    DraftIdentityIdentifier(field_key=f"identifier_{index}", can_match=True)
                    for index in range(4)
                )
            ),
        )
        errors = DraftConfigurationService.validate(draft)
        self.assertIn("Choose no more than 3 fields for identity matching.", errors)

    def test_htmx_mapping_shows_runtime_recognition_controls(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = initialize_runtime_database(Path(tmp) / "runtime.sqlite")
            client = self.make_app(database)
            csrf = self.csrf(client)
            inspected = client.post(
                "/admin/ingestion-sources/sample/inspect",
                data={"sample_file": (io.BytesIO(b"Employee ID,NUID,Logon ID,Email\n001,ABC,LOG001,a@example.com\n"), "signals.csv")},
                headers={"X-CSRF-Token": csrf, "HX-Request": "true"},
                content_type="multipart/form-data",
            )
            artifact_id = next(
                value.split('"', 1)[0]
                for value in inspected.data.decode().split('value="')[1:]
                if value and len(value.split('"', 1)[0]) == 32
            )
            selected = client.post(
                "/admin/ingestion-sources/sample/select",
                data={"artifact_id": artifact_id, "header_row": "1"},
                headers={"X-CSRF-Token": csrf, "HX-Request": "true"},
            )
            selected_body = selected.data.decode()
            recognition_index = selected_body.index('id="recognition-header-0"')
            settings_index = selected_body.index('id="field-settings-0"')
            self.assertLess(recognition_index, settings_index)
            recognition_control = selected_body.split('id="recognition-header-0"', 1)[1].split(">", 1)[0]
            self.assertNotIn("checked", recognition_control)
            self.assertIn("Choose 2–3 distinctive headers", selected_body)
            response = client.post(
                "/admin/ingestion-sources/draft/mapping",
                data={
                    "source_id": "signals",
                    "display_name": "Signals",
                    **{f"field_include_{index}": "on" for index in range(4)},
                    **{f"field_key_{index}": key for index, key in enumerate(("employee_id", "nuid", "logon_id", "email"))},
                    **{f"field_type_{index}": "string" for index in range(4)},
                    **{f"field_transform_{index}": "identity" for index in range(4)},
                    "recognition_headers_present": "1",
                    "recognition_header_0": "on",
                },
                headers={"X-CSRF-Token": csrf, "HX-Request": "true"},
            )
            self.assertEqual(response.status_code, 200)
            body = response.data.decode()
            self.assertIn("Required to recognize this report", body)
            self.assertIn("Validate template", body)

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

    def test_runtime_compatible_preview_checks_date_values_and_recognition_headers(self):
        draft = DraftSourceDefinition(
            source_id="roster",
            display_name="Roster",
            recognition_settings=DraftRecognitionSettings(required_headers=("Submission Date", "FG Status")),
            fields=(
                DraftFieldDefinition(source_name="Submission Date", field_key="submission_date", data_type="date"),
                DraftFieldDefinition(source_name="FG Status", field_key="fg_status", data_type="string"),
            ),
        )
        inspection = {
            "headers": ("Submission Date",),
            "rows_detected": 1,
            "rows": ({"Submission Date": "2026-09-30T17:15:00"},),
        }

        preview = DraftConfigurationService.preview(draft, inspection)

        self.assertEqual(preview["normalized_rows"][0]["submission_date"], "2026-09-30")
        self.assertEqual(preview["missing_recognition_headers"], ("FG Status",))
        diagnostics = [(item["severity"], item["message"]) for item in preview["diagnostics"]]
        self.assertTrue(any(severity == "BLOCKING" and "recognize this report: FG Status" in message for severity, message in diagnostics))
        self.assertTrue(any(severity == "WARNING" and "optional fields are also required" in message for severity, message in diagnostics))
        self.assertTrue(any(severity == "INFO" and "normalized to calendar dates" in message for severity, message in diagnostics))

    def test_runtime_compatible_preview_blocks_invalid_date_sample(self):
        draft = DraftSourceDefinition(
            source_id="roster",
            display_name="Roster",
            fields=(DraftFieldDefinition(source_name="Start Date", field_key="start_date", data_type="date"),),
        )
        preview = DraftConfigurationService.preview(draft, {
            "headers": ("Start Date",),
            "rows_detected": 1,
            "rows": ({"Start Date": "next Friday"},),
        })
        self.assertEqual(len(preview["invalid_rows"]), 1)
        self.assertTrue(any(item["severity"] == "BLOCKING" and "fails runtime validation" in item["message"] for item in preview["diagnostics"]))

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
            self.assertIn(b"Required to recognize this report", selected.data)
            self.assertIn(b"Which source fields should be included?", selected.data)
            self.assertIn(b"Name in this template", selected.data)
            self.assertIn(b"Data type", selected.data)
            self.assertIn(b"Identity and matching settings live in the Template Library", selected.data)

            mapping_data = {
                "display_name": "Roster report",
                "source_id": "roster",
                "field_include_0": "on",
                "field_key_0": "employee_id",
                "field_type_0": "string",
                "field_transform_0": "normalize_id",
                "field_key_1": "status",
                "field_type_1": "string",
                "field_transform_1": "identity",
                "recognition_headers_present": "1",
                "recognition_header_0": "on",
            }
            mapped = client.post(
                "/admin/ingestion-sources/draft/mapping",
                data=mapping_data,
                headers={"X-CSRF-Token": csrf, "HX-Request": "true"},
            )
            self.assertEqual(mapped.status_code, 200)
            self.assertIn(b"Validation passed. Review the checks", mapped.data)
            self.assertIn(b"Save template", mapped.data)
            with sqlite3.connect(database) as connection:
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM source_definition_versions").fetchone()[0], 0)

            saved_response = client.post(
                "/admin/ingestion-sources/draft/mapping",
                data={**mapping_data, "action": "save"},
                headers={"X-CSRF-Token": csrf, "HX-Request": "true"},
            )
            self.assertEqual(saved_response.status_code, 200)
            self.assertIn(b"Source schema saved in this browser session", saved_response.data)

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
            self.assertEqual(saved.identity_governance.role, "EVIDENCE_ONLY")
            self.assertFalse(saved.identity_governance.can_create_employee)
            self.assertEqual(len(saved.identity_governance.identifiers), 0)
            self.assertEqual(saved.recognition_settings.required_headers, ("Employee ID",))

            with orm_session(database) as session:
                self.assertEqual(session.query(ImportBatchModel).count(), 0)
                self.assertEqual(session.query(IngestionRecordModel).count(), 0)

    def test_saving_template_is_blocked_when_sample_fails_runtime_field_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = initialize_runtime_database(Path(tmp) / "runtime.sqlite")
            client = self.make_app(database)
            csrf = self.csrf(client)
            inspected = client.post(
                "/admin/ingestion-sources/sample/inspect",
                data={"sample_file": (io.BytesIO(b"Start Date\nnot a date\n"), "dates.csv")},
                headers={"X-CSRF-Token": csrf, "HX-Request": "true"},
                content_type="multipart/form-data",
            )
            self.assertEqual(inspected.status_code, 200)
            artifact_id = next(
                value.split('"', 1)[0]
                for value in inspected.data.decode().split('value="')[1:]
                if value and len(value.split('"', 1)[0]) == 32
            )
            selected = client.post(
                "/admin/ingestion-sources/sample/select",
                data={"artifact_id": artifact_id, "sheet_name": "", "header_row": "1"},
                headers={"X-CSRF-Token": csrf, "HX-Request": "true"},
            )
            self.assertEqual(selected.status_code, 200)
            response = client.post(
                "/admin/ingestion-sources/draft/mapping",
                data={
                    "recognition_headers_present": "1",
                    "recognition_header_0": "on",
                    "field_include_0": "on",
                    "field_key_0": "start_date",
                    "field_type_0": "date",
                    "field_transform_0": "identity",
                },
                headers={"X-CSRF-Token": csrf, "HX-Request": "true"},
            )
            self.assertEqual(response.status_code, 200)
            self.assertIn(b"fails runtime checks", response.data)
            self.assertIn(b"BLOCKING", response.data)
            with sqlite3.connect(database) as connection:
                saved_count = connection.execute("SELECT COUNT(*) FROM source_definition_versions").fetchone()[0]
            self.assertEqual(saved_count, 0)

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

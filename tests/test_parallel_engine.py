from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from dataclasses import replace

from openpyxl import Workbook

from iam_automation.application.parallel_engine.contracts import SourceTemplate
from werkzeug.test import Client
from werkzeug.wrappers import Response

from iam_automation.application.parallel_engine.database import initialize_engine_schema
from iam_automation.application.parallel_engine.engine import ParallelIngestionEngine
from iam_automation.application.parallel_engine.reader import parse_source_rows
from iam_automation.application.parallel_engine.templates import RuntimeTemplateCatalog
from iam_automation.application.parallel_engine.watcher import ParallelFileWatcher
from iam_automation.interfaces.web.parallel_engine_app import create_parallel_engine_app
from iam_automation.interfaces.web.parallel_host import LegacyReadOnlyGateway, create_parallel_host
from iam_automation.startup import PreflightResult, StartupSettings, StartupState


class ParallelEngineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "sharepoint"
        self.root.mkdir()
        (self.root / "source-a").mkdir()
        (self.root / "source-b").mkdir()
        self.database = Path(self.temp.name) / "runtime.sqlite"
        self._create_configuration_schema()
        self.source_a_id = self._save_source("SOURCE_A", "source-a", "Employee ID", "employee_id", "Account", "account_id")
        self.source_b_id = self._save_source("SOURCE_B", "source-b", "Vendor ID", "vendor_id", "Account", "account_id")
        self.object_version_id = "object-v1"
        self._save_object_template()
        initialize_engine_schema(self.database)

    def tearDown(self):
        self.temp.cleanup()

    def _create_configuration_schema(self):
        with sqlite3.connect(self.database) as connection:
            connection.executescript(
                """CREATE TABLE source_definition_versions (
                     definition_version_id TEXT PRIMARY KEY, source_id TEXT, version_number INTEGER,
                     status TEXT, definition_json TEXT);
                   CREATE TABLE source_ingestion_orders(source_id TEXT PRIMARY KEY, ingestion_order INTEGER);
                   CREATE TABLE source_template_lifecycle_events(source_id TEXT, restored_at_utc TEXT);
                   CREATE TABLE employee_template_versions (
                     employee_template_version_id TEXT PRIMARY KEY, template_key TEXT,
                     version_number INTEGER, status TEXT, definition_json TEXT,
                     created_by TEXT, created_at_utc TEXT, updated_by TEXT, updated_at_utc TEXT);
                   CREATE TABLE employees(employee_id TEXT PRIMARY KEY);"""
            )

    def _save_source(self, source_id, folder, id_header, id_key, account_header, account_key):
        version_id = f"{source_id.lower()}-v1"
        identity = {
            "role": "IDENTITY_SEED",
            "can_create_employee": True,
            "identifiers": [
                {"field_key": id_key, "strength": "STRONG", "can_match": True, "can_create_identity": True},
                {"field_key": account_key, "strength": "STRONG", "can_match": True, "can_create_identity": True},
            ],
            "max_matching_fields": 3,
        }
        definition = {
            "source_id": source_id,
            "display_name": source_id.replace("_", " "),
            "watched_subfolder": folder,
            "reader_settings": {"format": "CSV", "header_row": 1, "header_rows": [1], "csv_delimiter": ",", "filename_pattern": "*.csv"},
            "recognition_settings": {"extension": ".csv", "filename_pattern": "*.csv", "required_headers": [id_header]},
            "fields": [
                {"source_name": id_header, "field_key": id_key, "include": True, "data_type": "string", "transform_name": "identity", "required": True, "nullable": False},
                {"source_name": account_header, "field_key": account_key, "include": True, "data_type": "string", "transform_name": "trim", "required": True, "nullable": False},
            ],
            "identity_governance": identity,
            "validations": [],
            "schema_drift_policy": "WARNING",
        }
        with sqlite3.connect(self.database) as connection:
            connection.execute("INSERT INTO source_definition_versions VALUES (?, ?, 1, 'APPROVED', ?)", (version_id, source_id, json.dumps(definition)))
            connection.execute("INSERT INTO source_ingestion_orders VALUES (?, ?)", (source_id, 1 if source_id == "SOURCE_A" else 2))
        return version_id

    def _save_object_template(self):
        definition = {
            "object_name": "Person Evidence",
            "allow_object_creation": True,
            "source_templates": [
                {"source_id": "SOURCE_A", "source_definition_version_id": self.source_a_id},
                {"source_id": "SOURCE_B", "source_definition_version_id": self.source_b_id},
            ],
            "properties": [],
            "identifiers": [
                {"source_id": "SOURCE_A", "field_key": "employee_id", "strength": "STRONG", "can_create_identity": True, "source_can_create_object": True},
                {"source_id": "SOURCE_A", "field_key": "account_id", "strength": "STRONG", "can_create_identity": True, "source_can_create_object": True},
                {"source_id": "SOURCE_B", "field_key": "vendor_id", "strength": "STRONG", "can_create_identity": True, "source_can_create_object": True},
                {"source_id": "SOURCE_B", "field_key": "account_id", "strength": "STRONG", "can_create_identity": True, "source_can_create_object": True},
            ],
            "matches": [{"strength": "STRONG", "left": {"source_id": "SOURCE_A", "field_key": "employee_id"}, "right": {"source_id": "SOURCE_B", "field_key": "vendor_id"}}],
        }
        with sqlite3.connect(self.database) as connection:
            connection.execute(
                "INSERT INTO employee_template_versions VALUES (?, 'EMPLOYEE_PROFILE', 1, 'DRAFT', ?, 'author', 'now', 'author', 'now')",
                (self.object_version_id, json.dumps(definition)),
            )

    def _approve_object(self):
        catalog = RuntimeTemplateCatalog(self.database, self.root)
        catalog.approve_object_template(self.object_version_id, "approver")
        return catalog

    def test_object_template_requires_approval_and_load_pins_approved_versions(self):
        catalog = RuntimeTemplateCatalog(self.database, self.root)
        self.assertIsNone(catalog.load())
        catalog.approve_object_template(self.object_version_id, "approver")
        config = catalog.load()
        self.assertEqual(config.object_template.version_id, self.object_version_id)
        self.assertEqual([item.version_id for item in config.sources], [self.source_a_id, self.source_b_id])

    def test_strong_links_create_and_reuse_objects_without_canonical_writes(self):
        self._approve_object()
        engine = ParallelIngestionEngine(self.database, self.root)
        first_file = self.root / "source-a" / "workers.csv"
        first_file.write_text("Employee ID,Account\n00123,A-1\n00124,A-2\n", encoding="utf-8")
        first = engine.ingest_file(first_file)
        self.assertEqual((first.status, first.objects_created, first.evidence_rows), ("COMPLETED", 2, 2))

        second_file = self.root / "source-b" / "vendors.csv"
        second_file.write_text("Vendor ID,Account\n00123,B-1\n", encoding="utf-8")
        second = engine.ingest_file(second_file)
        self.assertEqual(second.objects_created, 0)
        self.assertEqual(second.objects_linked, 1)
        repeated = engine.ingest_file(second_file)
        self.assertEqual(repeated.batch_id, second.batch_id)

        with sqlite3.connect(self.database) as connection:
            objects = connection.execute("SELECT COUNT(*) FROM engine_v2_objects").fetchone()[0]
            links = connection.execute("SELECT COUNT(*) FROM engine_v2_object_evidence").fetchone()[0]
            evidence = connection.execute("SELECT normalized_json FROM engine_v2_evidence WHERE source_key LIKE '%00123%' LIMIT 1").fetchone()[0]
            canonical = connection.execute("SELECT COUNT(*) FROM employees").fetchone()[0]
        self.assertEqual((objects, links, canonical), (2, 3, 0))
        self.assertIn('"employee_id": "00123"', evidence)

    def test_newly_approved_source_version_marks_approved_object_template_stale(self):
        self._approve_object()
        with sqlite3.connect(self.database) as connection:
            original = connection.execute("SELECT definition_json FROM source_definition_versions WHERE definition_version_id=?", (self.source_a_id,)).fetchone()[0]
            connection.execute("INSERT INTO source_definition_versions VALUES (?, 'SOURCE_A', 2, 'APPROVED', ?)", ("source_a-v2", original))
        with self.assertRaisesRegex(ValueError, "stale"):
            RuntimeTemplateCatalog(self.database, self.root).load()

    def test_xlsx_zero_padded_integer_identifier_is_preserved(self):
        self._approve_object()
        source = RuntimeTemplateCatalog(self.database, self.root).load().sources[0]
        definition = dict(source.definition)
        definition["reader_settings"] = {**definition["reader_settings"], "format": "XLSX"}
        definition["recognition_settings"] = {**definition["recognition_settings"], "extension": ".xlsx"}
        source = replace(source, definition=definition)
        workbook = Workbook()
        sheet = workbook.active
        sheet.append(["Employee ID", "Account"])
        sheet.append([123, "A-1"])
        sheet["A2"].number_format = "00000"
        output = Path(self.temp.name) / "padded.xlsx"
        workbook.save(output)
        workbook.close()
        rows, errors, _unknown = parse_source_rows(output, output.read_bytes(), source)
        self.assertEqual(errors, ())
        self.assertEqual(rows[0].normalized_values["employee_id"], "00123")

    def test_date_fields_normalize_iso_datetime_values_before_evidence_staging(self):
        source = SourceTemplate(
            source_id="SOURCE_DATE",
            version_id="source-date-v1",
            version_number=1,
            display_name="Date source",
            definition={
                "reader_settings": {"format": "CSV", "header_row": 1, "header_rows": [1], "csv_delimiter": ","},
                "fields": [
                    {"source_name": "Employee ID", "field_key": "employee_id", "include": True, "data_type": "string", "transform_name": "identity", "required": True, "nullable": False},
                    {"source_name": "Start Date", "field_key": "start_date", "include": True, "data_type": "date", "transform_name": "identity", "required": False, "nullable": True},
                ],
            },
            watched_path=self.root / "source-a",
            ingestion_order=1,
        )
        path = self.root / "source-a" / "dates.csv"

        rows, diagnostics, unknown_headers = parse_source_rows(
            path,
            b"Employee ID,Start Date\n00123,2026-09-30T17:15:00\n",
            source,
        )

        self.assertFalse(diagnostics)
        self.assertFalse(unknown_headers)
        self.assertEqual(rows[0].normalized_values["start_date"], "2026-09-30")
        self.assertFalse(rows[0].issues)

    def test_recognition_ignores_excluded_headers_from_older_drafts(self):
        self._approve_object()
        source = RuntimeTemplateCatalog(self.database, self.root).load().sources[0]
        definition = json.loads(json.dumps(source.definition))
        definition["recognition_settings"]["required_headers"].append("Source Column 1")
        definition["fields"].append({
            "source_name": "Source Column 1", "field_key": "source_column_1",
            "include": False, "data_type": "string", "required": False,
        })
        source = replace(source, definition=definition)
        file_path = self.root / "source-a" / "excluded-header.csv"
        content = b"Employee ID,Account\n00123,A-1\n"
        file_path.write_bytes(content)
        matched, diagnostic = ParallelIngestionEngine._recognition_match(file_path, content, source)
        self.assertTrue(matched, diagnostic)

    def test_unrecognized_file_is_observed_without_creating_a_batch(self):
        self._approve_object()
        file_path = self.root / "source-a" / "wrong.csv"
        file_path.write_text("Unrelated,Header\nvalue,other\n", encoding="utf-8")
        watcher = ParallelFileWatcher(ParallelIngestionEngine(self.database, self.root))
        self.assertEqual(watcher.scan_once(), 0)
        with sqlite3.connect(self.database) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM engine_v2_batches").fetchone()[0], 0)
            self.assertEqual(connection.execute("SELECT status FROM engine_v2_file_observations WHERE path=?", (str(file_path.resolve()),)).fetchone()[0], "UNRECOGNIZED")
            analysis = connection.execute(
                "SELECT recognition_status, detected_headers_json, missing_headers_json, diagnostics_json FROM engine_v2_file_analyses WHERE path=?",
                (str(file_path.resolve()),),
            ).fetchone()
        self.assertEqual(analysis[0], "UNRECOGNIZED")
        self.assertEqual(json.loads(analysis[1]), ["Unrelated", "Header"])
        self.assertEqual(json.loads(analysis[2]), ["Employee ID"])
        self.assertIn("Required recognition headers are absent", analysis[3])

    def test_watcher_persists_recognition_analysis_without_importing_rows(self):
        self._approve_object()
        file_path = self.root / "source-a" / "roster.csv"
        file_path.write_text("Employee ID,Account,Extra\n00123,A-1,unknown\n", encoding="utf-8")
        ParallelFileWatcher(ParallelIngestionEngine(self.database, self.root)).scan_once()
        with sqlite3.connect(self.database) as connection:
            analysis = connection.execute(
                """SELECT source_id, source_order, recognition_status, file_checksum,
                          detected_headers_json, unknown_headers_json, checks_json
                   FROM engine_v2_file_analyses WHERE path=?""",
                (str(file_path.resolve()),),
            ).fetchone()
            counts = (
                connection.execute("SELECT COUNT(*) FROM engine_v2_batches").fetchone()[0],
                connection.execute("SELECT COUNT(*) FROM engine_v2_evidence").fetchone()[0],
                connection.execute("SELECT COUNT(*) FROM engine_v2_objects").fetchone()[0],
            )
        self.assertEqual(analysis[0:3], ("SOURCE_A", 1, "RECOGNIZED"))
        self.assertEqual(len(analysis[3]), 64)
        self.assertEqual(json.loads(analysis[4]), ["Employee ID", "Account", "Extra"])
        self.assertEqual(json.loads(analysis[5]), ["Extra"])
        self.assertTrue(json.loads(analysis[6])["required_headers_present"])
        self.assertEqual(counts, (0, 0, 0))

    def test_watcher_discovers_but_does_not_process_until_file_authorization(self):
        self._approve_object()
        file_path = self.root / "source-a" / "watch.csv"
        file_path.write_text("Employee ID,Account\n00123,A-1\n", encoding="utf-8")
        watcher = ParallelFileWatcher(ParallelIngestionEngine(self.database, self.root), interval_seconds=120)
        self.assertEqual(watcher.scan_once(), 0)
        self.assertEqual(watcher.scan_once(), 0)
        with sqlite3.connect(self.database) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM engine_v2_batches").fetchone()[0], 0)
            observation = connection.execute(
                "SELECT observation_id, status FROM engine_v2_file_observations WHERE path=?",
                (str(file_path.resolve()),),
            ).fetchone()
            health = connection.execute("SELECT status FROM engine_v2_watcher_state WHERE singleton_id=1").fetchone()[0]
        self.assertEqual(health, "HEALTHY")
        self.assertEqual(observation[1], "PENDING_AUTHORIZATION")

        result = watcher.authorize_and_process(observation[0], "approver")
        self.assertEqual((result.status, result.objects_created), ("COMPLETED", 1))
        self.assertEqual(watcher.scan_once(), 0)
        with sqlite3.connect(self.database) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM engine_v2_batches").fetchone()[0], 1)
            authorizer = connection.execute(
                "SELECT authorized_by, authorized_at_utc, status FROM engine_v2_file_observations WHERE path=?",
                (str(file_path.resolve()),),
            ).fetchone()
        self.assertEqual(authorizer[0], "approver")
        self.assertTrue(authorizer[1])
        self.assertEqual(authorizer[2], "PROCESSED")

    def test_processing_authorization_route_requires_approver_csrf_and_disabled_gate(self):
        self._approve_object()
        file_path = self.root / "source-a" / "authorized.csv"
        file_path.write_text("Employee ID,Account\n00123,A-1\n", encoding="utf-8")
        ParallelFileWatcher(ParallelIngestionEngine(self.database, self.root)).scan_once()
        with sqlite3.connect(self.database) as connection:
            observation_id = connection.execute(
                "SELECT observation_id FROM engine_v2_file_observations WHERE path=?",
                (str(file_path.resolve()),),
            ).fetchone()[0]

        app = create_parallel_engine_app(self.database, self.root, shared_secret="test-secret")
        client = app.test_client()
        with client.session_transaction() as session:
            session["iam_user"] = "approver"
            session["iam_roles"] = ["APPLICATION_ADMIN"]
            session["parallel_engine_csrf_token"] = "valid-token"
        url = f"/files/{observation_id}/process"
        self.assertEqual(client.post(url).status_code, 400)
        with client.session_transaction() as session:
            session["iam_roles"] = ["EMPLOYEE"]
        self.assertEqual(client.post(url, data={"csrf_token": "valid-token"}).status_code, 403)
        with client.session_transaction() as session:
            session["iam_roles"] = ["APPLICATION_ADMIN"]
        self.assertEqual(client.post(url, data={"csrf_token": "valid-token"}).status_code, 302)
        with sqlite3.connect(self.database) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM engine_v2_batches").fetchone()[0], 0)
            self.assertEqual(connection.execute("SELECT status FROM engine_v2_file_observations WHERE path=?", (str(file_path.resolve()),)).fetchone()[0], "PENDING_AUTHORIZATION")

    def test_object_template_approval_route_requires_role_and_csrf(self):
        app = create_parallel_engine_app(self.database, self.root, shared_secret="test-secret")
        client = app.test_client()
        with client.session_transaction() as session:
            session["iam_user"] = "approver"
            session["iam_roles"] = ["APPLICATION_ADMIN"]
            session["parallel_engine_csrf_token"] = "valid-token"
        response = client.post(f"/objects/{self.object_version_id}/approve")
        self.assertEqual(response.status_code, 400)
        with client.session_transaction() as session:
            session["iam_roles"] = ["EMPLOYEE"]
        response = client.post(f"/objects/{self.object_version_id}/approve", data={"csrf_token": "valid-token"})
        self.assertEqual(response.status_code, 403)
        with client.session_transaction() as session:
            session["iam_roles"] = ["APPLICATION_ADMIN"]
        response = client.post(f"/objects/{self.object_version_id}/approve", data={"csrf_token": "valid-token"})
        self.assertEqual(response.status_code, 302)

    def test_parallel_host_mounts_engine_and_keeps_legacy_reference_read_only(self):
        settings = StartupSettings(
            sharepoint_root_path=self.root, published_access_db_path=None,
            published_runtime_db_path=self.database, local_runtime_db_path=self.database,
            workspace_path=Path(self.temp.name) / "workspace", backup_folder_path=self.root / "backups",
            audit_folder_path=self.root / "audit",
        )
        preflight = PreflightResult(StartupState.READY, True, "ready", settings)
        host = create_parallel_host(preflight)
        client = Client(host.application, Response)
        self.assertEqual(client.get("/legacy/login").status_code, 200)
        session_cookie = host.engine_app.session_interface.get_signing_serializer(host.engine_app).dumps(
            {"iam_user": "admin", "iam_roles": ["APPLICATION_ADMIN"]}
        )
        client.set_cookie("session", session_cookie)
        self.assertEqual(client.get("/engine/dashboard").status_code, 200)
        self.assertEqual(client.post("/legacy/notifications/read-all").status_code, 405)


if __name__ == "__main__":
    unittest.main()

"""
File: tests/test_rsr_supplier_worker_details.py
Purpose: Provides automated regression tests for test rsr supplier worker details.
Responsibilities: Exposes or coordinates: RsrSupplierWorkerDetailsTests.
Dependencies: unittest, openpyxl, sqlalchemy, iam_automation
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

from openpyxl import Workbook
from sqlalchemy import select

from iam_automation.application.employee_service import EmployeeService
from iam_automation.application.roster_lock_ingestion_service import RosterLockIngestionService
from iam_automation.application.file_watch_service import FileWatchService
from iam_automation.application.shared_request_service import SharedRequestService
from iam_automation.database.runtime_schema import initialize_runtime_database
from iam_automation.infrastructure.sqlite.orm import IngestionRecordModel, WorkerIdentifierModel, WorkerModel, orm_session
from iam_automation.source_adapters.rsr_supplier_worker_details import RsrSupplierWorkerDetailsAdapter


class RsrSupplierWorkerDetailsTests(unittest.TestCase):
    def test_reference_rsr_workbook_stages_as_one_batch(self):
        source = Path(__file__).parent / "fixtures" / "sharepoint_simulated" / "rsrsuplierworkerdetails" / "RSR Supplier Worker Details -- .xlsx"
        self.assertTrue(source.exists())
        with tempfile.TemporaryDirectory() as tmp:
            database = initialize_runtime_database(Path(tmp) / "runtime.sqlite")
            result = RsrSupplierWorkerDetailsAdapter(database).ingest_file(source, "qa")
            self.assertGreater(result.total_rows, 600)
            self.assertEqual(result.staged_rows, 615)
            self.assertEqual(result.quarantined_rows, 0)
            self.assertEqual(len(EmployeeService(database).list_staged_records()), result.staged_rows)

    def _write_roster(self, path: Path) -> None:
        workbook = Workbook()
        sheet = workbook.active
        sheet.append(["Vendor Name", "Vendor employee ID", "Employee first name", "Employee last name", "Vendor Email Address"])
        sheet.append(["TTEC", "V-100", "Ada", "Lovelace", "ada@example.com"])
        workbook.save(path)

    def _write_rsr(self, path: Path, supplier_reference: str = "V-100", worker_id: str = "RSR-1") -> None:
        workbook = Workbook()
        sheet = workbook.active
        sheet.append(["RSR Supplier Worker Details"])
        sheet.append(["Statement of Work", "Worker Status", "Work Order ID", "Supplier Reference", "Worker ID", "Buyer Reference", "Worker", "SOW Worker Role", "Worker Primary Contact", "Worker Start Date", "Worker End Date", "Resident License Number", "LOB", "NPN", "Taxonomy", "Resident License State"])
        sheet.append(["TTEC Contact Center Agent Services SOW 11109", "Open", "WO-1", supplier_reference, worker_id, "BUY-1", "Lovelace, Ada", "Analyst", "Contact", "2026-08-01", "2026-09-01", "LIC-1", "LOB-1", "NPN-1", "TAX-1", "CA"])
        workbook.save(path)

    def test_rsr_matches_existing_worker_and_applies_as_enrichment(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            database = initialize_runtime_database(root / "runtime.sqlite")
            roster = root / "roster.xlsx"
            rsr = root / "rsr.xlsx"
            self._write_roster(roster)
            self._write_rsr(rsr)
            RosterLockIngestionService(database).ingest_file(roster)
            record_id = EmployeeService(database).list_staged_records()[0]["record_id"]
            worker_id = EmployeeService(database).promote_ingestion_record(record_id, "qa")

            result = RsrSupplierWorkerDetailsAdapter(database).ingest_file(rsr, "qa")
            self.assertEqual(result.staged_rows, 1)
            staged = EmployeeService(database).list_staged_records()
            rsr_record = next(item for item in staged if item["source_system"] == "RSR_SUPPLIER_WORKER_DETAILS")
            self.assertEqual(rsr_record["match_status"], "MATCHED")
            self.assertEqual(rsr_record["matched_worker_id"], worker_id)

            applied = EmployeeService(database).apply_approved_import_records([rsr_record["record_id"]], "qa")
            self.assertEqual(applied["processed"], 1)
            self.assertEqual(applied["created"], 0)
            self.assertEqual(applied["reused"], 1)
            detail = EmployeeService(database).get_worker(worker_id)
            self.assertEqual(detail["engagements"][0].work_order_id, "WO-1")
            self.assertEqual(detail["engagements"][0].statement_of_work, "TTEC Contact Center Agent Services SOW 11109")
            self.assertEqual(detail["engagements"][0].vendor_name, "TTEC")
            self.assertEqual(detail["engagements"][0].job_title, "Analyst")

    def test_rsr_same_file_is_idempotent_and_unmatched_is_created_only_after_approval(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            database = initialize_runtime_database(root / "runtime.sqlite")
            rsr = root / "rsr.xlsx"
            self._write_rsr(rsr, supplier_reference="UNKNOWN")
            adapter = RsrSupplierWorkerDetailsAdapter(database)
            first = adapter.ingest_file(rsr, "qa")
            second = adapter.ingest_file(rsr, "qa")
            self.assertFalse(first.already_processed)
            self.assertTrue(second.already_processed)
            record = EmployeeService(database).list_staged_records()[0]
            self.assertEqual(record["match_status"], "UNMATCHED")
            result = adapter.apply_approved_records([record["record_id"]], "qa")
            self.assertEqual(result["processed"], 1)
            self.assertEqual(result["created"], 1)
            self.assertEqual(len(EmployeeService(database).list_workers()), 1)
            with orm_session(database) as session:
                applied_record = session.get(IngestionRecordModel, record["record_id"])
                self.assertIsNotNone(applied_record.matched_worker_id)
                self.assertEqual(applied_record.match_status, "MATCHED")
                self.assertEqual(applied_record.observation_state, "CURRENT")
            repeated = adapter.apply_approved_records([record["record_id"]], "qa")
            self.assertEqual(repeated["failed"], 0)
            self.assertEqual(repeated["reused"], 1)

    def test_rsr_matching_refreshes_after_roster_lock_creates_workers(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            database = initialize_runtime_database(root / "runtime.sqlite")
            roster = root / "roster.xlsx"
            rsr = root / "rsr.xlsx"
            self._write_roster(roster)
            self._write_rsr(rsr)

            RosterLockIngestionService(database).ingest_file(roster)
            roster_record = EmployeeService(database).list_staged_records()[0]["record_id"]
            # RSR arrives first, so it cannot match yet.
            RsrSupplierWorkerDetailsAdapter(database).ingest_file(rsr, "qa")
            before = next(item for item in EmployeeService(database).list_staged_records() if item["source_system"] == "RSR_SUPPLIER_WORKER_DETAILS")
            self.assertEqual(before["match_status"], "UNMATCHED")

            EmployeeService(database).promote_staged_records([roster_record], "qa")
            refreshed = EmployeeService(database).refresh_rsr_matches()
            self.assertEqual(refreshed["matched"], 1)
            after = next(item for item in EmployeeService(database).list_staged_records() if item["source_system"] == "RSR_SUPPLIER_WORKER_DETAILS")
            self.assertEqual(after["match_status"], "MATCHED")

    def test_rsr_approval_revalidates_stale_unmatched_record_before_creating_worker(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            database = initialize_runtime_database(root / "runtime.sqlite")
            roster = root / "roster.xlsx"
            rsr = root / "rsr.xlsx"
            self._write_roster(roster)
            self._write_rsr(rsr)

            RosterLockIngestionService(database).ingest_file(roster)
            rsr_result = RsrSupplierWorkerDetailsAdapter(database).ingest_file(rsr, "qa")
            rsr_record = next(item for item in EmployeeService(database).list_staged_records() if item["source_system"] == "RSR_SUPPLIER_WORKER_DETAILS")
            RsrSupplierWorkerDetailsAdapter(database).match_batch(rsr_result.batch_id)
            roster_record = next(item for item in EmployeeService(database).list_staged_records() if item["source_system"] == "ROSTER_LOCK")
            worker_id = EmployeeService(database).promote_ingestion_record(roster_record["record_id"], "qa")
            with orm_session(database) as session:
                record = session.get(IngestionRecordModel, rsr_record["record_id"])
                record.match_status = "UNMATCHED"
                record.matched_worker_id = None

            result = EmployeeService(database).apply_approved_import_records([rsr_record["record_id"]], "qa")
            self.assertEqual(result["created"], 0)
            self.assertEqual(result["failed"], 0)
            self.assertEqual(len(EmployeeService(database).list_workers()), 1)
            with orm_session(database) as session:
                record = session.get(IngestionRecordModel, rsr_record["record_id"])
                self.assertEqual(record.matched_worker_id, worker_id)
                self.assertEqual(record.match_status, "MATCHED")

    def test_roster_promotion_reuses_rsr_canonical_by_shared_vendor_identifier(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            database = initialize_runtime_database(root / "runtime.sqlite")
            roster = root / "roster.xlsx"
            rsr = root / "rsr.xlsx"
            self._write_roster(roster)
            self._write_rsr(rsr)

            RsrSupplierWorkerDetailsAdapter(database).ingest_file(rsr, "qa")
            rsr_record = next(item for item in EmployeeService(database).list_staged_records() if item["source_system"] == "RSR_SUPPLIER_WORKER_DETAILS")
            rsr_result = RsrSupplierWorkerDetailsAdapter(database).apply_approved_records([rsr_record["record_id"]], "qa")
            self.assertEqual(rsr_result["created"], 1)
            rsr_worker_id = EmployeeService(database).list_workers()[0].worker_id

            RosterLockIngestionService(database).ingest_file(roster)
            roster_record = next(item for item in EmployeeService(database).list_staged_records() if item["source_system"] == "ROSTER_LOCK")
            roster_worker_id = EmployeeService(database).promote_ingestion_record(roster_record["record_id"], "qa")

            self.assertEqual(roster_worker_id, rsr_worker_id)
            self.assertEqual(len(EmployeeService(database).list_workers()), 1)

    def test_vendor_is_derived_from_statement_of_work_not_adapter_name(self):
        self.assertEqual(
            RsrSupplierWorkerDetailsAdapter._derive_vendor_name({
                "statement_of_work": "Concentrix Customer Care SOW 22222",
            }),
            "Concentrix",
        )
        self.assertEqual(
            RsrSupplierWorkerDetailsAdapter._derive_vendor_name({
                "vendor_name": "TTEC",
                "statement_of_work": "Concentrix Customer Care SOW 22222",
            }),
            "TTEC",
        )
        self.assertEqual(
            RsrSupplierWorkerDetailsAdapter._derive_vendor_name({
                "statement_of_work": "TTEC_2020 TRAINING WFD",
            }),
            "TTEC",
        )

    def test_watcher_discovers_rsr_folder_and_stages_without_manual_upload(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            database = initialize_runtime_database(root / "runtime.sqlite")
            source_folder = root / "rsrsuplierworkerdetails"
            source_folder.mkdir()
            self._write_rsr(source_folder / "details.xlsx")
            watcher = FileWatchService(database, root)
            self.assertEqual(watcher.scan_once(), 1)
            with orm_session(database) as session:
                self.assertEqual(session.scalar(select(IngestionRecordModel.source_system).limit(1)), "RSR_SUPPLIER_WORKER_DETAILS")
                self.assertEqual(session.scalar(select(WorkerModel.worker_id).limit(1)), None)
            requests = SharedRequestService(root).list_requests(queue=True)
            self.assertEqual(len(requests), 1)
            self.assertEqual(requests[0].operation_type, "IMPORT_RSR_SUPPLIER_DETAILS")
            self.assertEqual(requests[0].payload["record_count"], 1)
            watcher.scan_once()
            self.assertEqual(len(SharedRequestService(root).list_requests(queue=True)), 1)


if __name__ == "__main__":
    unittest.main()
#endfile

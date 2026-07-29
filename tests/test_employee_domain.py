from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from openpyxl import Workbook

from iam_automation.application.employee_service import EmployeeService
from iam_automation.application.roster_lock_ingestion_service import RosterLockIngestionService
from iam_automation.database.runtime_schema import initialize_runtime_database
from iam_automation.infrastructure.sqlite.orm import IngestionRecordModel, orm_session


class EmployeeDomainTests(unittest.TestCase):
    def test_roster_lock_is_staged_before_explicit_worker_promotion(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            database = initialize_runtime_database(root / "runtime.sqlite")
            source = root / "roster.xlsx"
            workbook = Workbook()
            sheet = workbook.active
            sheet.append(["Vendor Name", "Vendor employee ID", "Employee first name", "Employee last name", "Vendor Email Address", "Job Title", "Program"])
            sheet.append(["TTEC", "E100", "Ada", "Lovelace", "Ada@Example.com", "Analyst", "IAM"])
            workbook.save(source)

            result = RosterLockIngestionService(database).ingest_file(source)
            self.assertEqual(result.staged_rows, 1)
            with orm_session(database) as session:
                record = session.query(IngestionRecordModel).one()
                record_id = record.record_id
            self.assertEqual(EmployeeService(database).list_workers(), [])

            worker_id = EmployeeService(database).promote_ingestion_record(record_id, "admin")
            workers = EmployeeService(database).list_workers()
            self.assertEqual(len(workers), 1)
            self.assertEqual(workers[0].worker_id, worker_id)
            self.assertEqual(workers[0].display_name, "Ada Lovelace")
            self.assertEqual(workers[0].email, "ada@example.com")
            self.assertEqual(workers[0].vendor_name, "TTEC")

    def test_same_vendor_identifier_reuses_worker_and_adds_engagement(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            database = initialize_runtime_database(root / "runtime.sqlite")
            service = EmployeeService(database)
            for index, project in enumerate(("Project A", "Project B"), start=1):
                source = root / f"roster-{index}.xlsx"
                workbook = Workbook()
                sheet = workbook.active
                sheet.append(["Vendor Name", "Vendor employee ID", "Employee first name", "Employee last name", "Project"])
                sheet.append(["TTEC", "E100", "Ada", "Lovelace", project])
                workbook.save(source)
                RosterLockIngestionService(database).ingest_file(source)
                with orm_session(database) as session:
                    record_id = session.query(IngestionRecordModel).order_by(IngestionRecordModel.created_at_utc.desc()).first().record_id
                worker_id = service.promote_ingestion_record(record_id, "admin")
                if index == 1:
                    first_worker = worker_id
            detail = service.get_worker(first_worker)
            self.assertEqual(len(detail["engagements"]), 2)
            self.assertEqual(len(service.list_workers()), 1)

    def test_bulk_promotion_processes_staged_rows_without_one_click_per_worker(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            database = initialize_runtime_database(root / "runtime.sqlite")
            source = root / "roster-bulk.xlsx"
            workbook = Workbook()
            sheet = workbook.active
            sheet.append(["Vendor Name", "Vendor employee ID", "Employee first name", "Employee last name", "Vendor Email Address", "Project"])
            sheet.append(["TTEC", "E100", "Ada", "Lovelace", "ada@example.com", "Project A"])
            sheet.append(["TTEC", "E101", "Grace", "Hopper", "grace@example.com", "Project A"])
            sheet.append(["TTEC", "E102", "Katherine", "Johnson", "katherine@example.com", "Project B"])
            workbook.save(source)

            result = RosterLockIngestionService(database).ingest_file(source)
            self.assertEqual(result.staged_rows, 3)

            promotion = EmployeeService(database).promote_all_staged_records("admin")

            self.assertEqual(promotion["processed"], 3)
            self.assertEqual(promotion["created"], 3)
            self.assertEqual(promotion["reused"], 0)
            self.assertEqual(promotion["failed"], 0)
            self.assertEqual(len(EmployeeService(database).list_workers()), 3)
            with orm_session(database) as session:
                self.assertEqual(session.query(IngestionRecordModel).filter_by(status="MATCHED").count(), 3)


if __name__ == "__main__":
    unittest.main()

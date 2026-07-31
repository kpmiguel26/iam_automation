from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from iam_automation.application.employee_service import EmployeeService
from iam_automation.database.runtime_schema import initialize_runtime_database
from iam_automation.infrastructure.sqlite.orm import IngestionRecordModel, orm_session


class SourceDuplicateSummaryTests(unittest.TestCase):
    def _record(
        self,
        record_id: str,
        payload: dict[str, object],
        *,
        source_system: str = "ROSTER_LOCK",
        source_file: str | None = None,
        matched_worker_id: str | None = None,
    ) -> IngestionRecordModel:
        return IngestionRecordModel(
            record_id=record_id,
            batch_id=f"batch-{record_id}",
            source_system=source_system,
            source_file=source_file or f"{source_system.lower()}.xlsx",
            source_checksum=f"checksum-{record_id}",
            row_number=2,
            source_record_key=record_id,
            normalized_json=json.dumps(payload),
            payload_json=json.dumps(payload),
            status="MATCHED" if matched_worker_id else "STAGED",
            match_status="MATCHED" if matched_worker_id else "UNMATCHED",
            matched_worker_id=matched_worker_id,
            match_reason="",
            created_at_utc="2026-07-31T12:00:00+00:00",
        )

    def test_same_strong_identifier_is_reported_as_possible_duplicate(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = initialize_runtime_database(Path(tmp) / "runtime.sqlite")
            with orm_session(database) as session:
                session.add_all(
                    [
                        self._record("one", {"vendor_employee_id": "E-100", "first_name": "Ada", "last_name": "Lovelace"}),
                        self._record("two", {"vendor_employee_id": "E-100", "first_name": "Ada", "last_name": "Lovelace"}, source_system="RSR_SUPPLIER_WORKER_DETAILS"),
                    ]
                )

            summary = EmployeeService(database).source_duplicate_summary()

            self.assertEqual(summary["group_count"], 1)
            self.assertEqual(summary["record_count"], 2)
            self.assertEqual(summary["groups"][0]["signal"], "Vendor employee ID")
            self.assertEqual(summary["groups"][0]["classification"], "REVIEW_DUPLICATE")

    def test_same_identifier_for_one_worker_is_correlated_source_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = initialize_runtime_database(Path(tmp) / "runtime.sqlite")
            with orm_session(database) as session:
                session.add_all(
                    [
                        self._record("one", {"vendor_employee_id": "E-100", "first_name": "Ada"}, matched_worker_id="worker-1"),
                        self._record("two", {"vendor_employee_id": "E-100", "first_name": "Ada"}, source_system="RSR_SUPPLIER_WORKER_DETAILS", matched_worker_id="worker-1"),
                    ]
                )

            group = EmployeeService(database).source_duplicate_summary()["groups"][0]

            self.assertEqual(group["classification"], "CORROBORATED")
            self.assertEqual(group["record_count"], 2)

    def test_name_and_email_are_used_as_fallback_signal(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = initialize_runtime_database(Path(tmp) / "runtime.sqlite")
            with orm_session(database) as session:
                session.add_all(
                    [
                        self._record("one", {"first_name": "Ada", "last_name": "Lovelace", "email": "ada@example.com"}),
                        self._record("two", {"first_name": "Ada", "last_name": "Lovelace", "email": "ada@example.com"}, source_system="FIELDGLASS"),
                    ]
                )

            groups = EmployeeService(database).source_duplicate_summary()["groups"]

            self.assertEqual(len(groups), 1)
            self.assertEqual(groups[0]["signal"], "Name + email")

    def test_source_file_filter_isolates_review_worklist(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = initialize_runtime_database(Path(tmp) / "runtime.sqlite")
            with orm_session(database) as session:
                session.add_all(
                    [
                        self._record("roster", {"vendor_employee_id": "E-100", "first_name": "Ada"}, source_file="/sharepoint/rosterlocks/roster.xlsx"),
                        self._record("rsr", {"vendor_employee_id": "E-100", "first_name": "Ada"}, source_system="RSR_SUPPLIER_WORKER_DETAILS", source_file=r"C:\sharepoint\rsrsuplierworkerdetails\rsr.xlsx"),
                    ]
                )

            service = EmployeeService(database)
            all_files = service.source_update_overview()
            roster_only = service.source_update_overview(source_file="roster.xlsx")

            self.assertEqual(all_files["source_files"], ["roster.xlsx", "rsr.xlsx"])
            self.assertEqual(len(roster_only["new_employee_records"]), 1)
            self.assertEqual(roster_only["new_employee_records"][0]["record_id"], "roster")
            self.assertEqual(roster_only["duplicate_summary"]["group_count"], 0)


if __name__ == "__main__":
    unittest.main()

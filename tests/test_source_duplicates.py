"""
File: tests/test_source_duplicates.py
Purpose: Provides automated regression tests for test source duplicates.
Responsibilities: Exposes or coordinates: SourceDuplicateSummaryTests.
Dependencies: unittest, iam_automation
Inputs/outputs: Inputs: temporary databases, fixtures, and test doubles. Outputs: assertions and test results.
Author / implementation: Miguel Fernandez.
Developed for: Kaiser Permanente NSES GWFM.
Project implementation and integration: Miguel Fernandez.
Third-party source, libraries, and dependencies retain their original licenses.
Estimated implementation effort: 1.25 h (Git-derived heuristic; see docs/file-effort-history.md).
"""

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
        source_record_key: str | None = None,
        created_at_utc: str = "2026-07-31T12:00:00+00:00",
    ) -> IngestionRecordModel:
        return IngestionRecordModel(
            record_id=record_id,
            batch_id=f"batch-{record_id}",
            source_system=source_system,
            source_file=source_file or f"{source_system.lower()}.xlsx",
            source_checksum=f"checksum-{record_id}",
            row_number=2,
            source_record_key=source_record_key or record_id,
            normalized_json=json.dumps(payload),
            payload_json=json.dumps(payload),
            status="MATCHED" if matched_worker_id else "STAGED",
            match_status="MATCHED" if matched_worker_id else "UNMATCHED",
            matched_worker_id=matched_worker_id,
            match_reason="",
            created_at_utc=created_at_utc,
        )

    def test_same_strong_identifier_from_different_sources_is_not_a_duplicate(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = initialize_runtime_database(Path(tmp) / "runtime.sqlite")
            with orm_session(database) as session:
                session.add_all(
                    [
                        self._record("one", {"vendor_employee_id": "E-100", "first_name": "Ada", "last_name": "Lovelace"}, source_record_key="E-100"),
                        self._record("two", {"vendor_employee_id": "E-100", "first_name": "Ada", "last_name": "Lovelace"}, source_system="RSR_SUPPLIER_WORKER_DETAILS", source_record_key="E-100"),
                    ]
                )

            summary = EmployeeService(database).source_duplicate_summary()

            self.assertEqual(summary["group_count"], 0)
            self.assertEqual(summary["record_count"], 0)

    def test_same_identifier_for_one_worker_is_correlated_source_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = initialize_runtime_database(Path(tmp) / "runtime.sqlite")
            with orm_session(database) as session:
                session.add_all(
                    [
                        self._record("one", {"vendor_employee_id": "E-100", "first_name": "Ada"}, matched_worker_id="worker-1", source_record_key="E-100"),
                        self._record("two", {"vendor_employee_id": "E-100", "first_name": "Ada"}, matched_worker_id="worker-1", source_record_key="E-100"),
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
                        self._record("one", {"first_name": "Ada", "last_name": "Lovelace", "email": "ada@example.com"}, source_record_key="E-100"),
                        self._record("two", {"first_name": "Ada", "last_name": "Lovelace", "email": "ada@example.com"}, source_record_key="E-100"),
                    ]
                )

            groups = EmployeeService(database).source_duplicate_summary()["groups"]

            self.assertEqual(len(groups), 1)
            self.assertEqual(groups[0]["signal"], "Name + email")

    def test_same_source_repetition_creates_worker_from_latest_and_archives_old_row(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = initialize_runtime_database(Path(tmp) / "runtime.sqlite")
            with orm_session(database) as session:
                session.add_all([
                    self._record("old", {"vendor_employee_id": "E-100", "first_name": "Ada", "last_name": "Old"}, source_record_key="E-100", source_file="old.xlsx", created_at_utc="2026-08-01T00:00:00+00:00"),
                    self._record("new", {"vendor_employee_id": "E-100", "first_name": "Ada", "last_name": "New"}, source_record_key="E-100", source_file="new.xlsx", created_at_utc="2026-08-02T00:00:00+00:00"),
                ])

            service = EmployeeService(database)
            result = service.resolve_source_duplicate("old", "admin")

            self.assertEqual(result["current_record_id"], "new")
            self.assertEqual(len(service.list_workers()), 1)
            history = service.get_worker(result["worker_id"])
            self.assertEqual(len(history["source_observations"]), 2)
            self.assertEqual({item["source_file"] for item in history["source_observations"]}, {"old.xlsx", "new.xlsx"})
            self.assertGreaterEqual(len(history["lineage"]), 6)
            with orm_session(database) as session:
                old = session.get(IngestionRecordModel, "old")
                new = session.get(IngestionRecordModel, "new")
                self.assertEqual(old.observation_state, "SUPERSEDED")
                self.assertEqual(new.observation_state, "CURRENT")
                self.assertEqual(new.matched_worker_id, result["worker_id"])

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
#endfile

from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import select

from iam_automation.application.employee_service import EmployeeService
from iam_automation.application.accessnow_ingestion_service import AccessNowIngestionService
from iam_automation.database.runtime_schema import initialize_runtime_database
from iam_automation.infrastructure.sqlite.orm import IngestionRecordModel, WorkerEngagementModel, WorkerIdentifierModel, WorkerModel, orm_session
from iam_automation.application.source_reconciliation import ensure_source_identifiers, find_worker_matches
from iam_automation.application.source_date import parse_source_date
from iam_automation.application.status_catalog import normalize_accessnow_status


class SourceUpdatesTests(unittest.TestCase):
    def test_status_catalog_normalizes_accessnow_aliases(self):
        self.assertEqual(normalize_accessnow_status("termination"), "TERMINATED")
        self.assertEqual(normalize_accessnow_status("disabled"), "DEACTIVATED")

    def test_rehire_alert_matching_uses_worker_and_source_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = initialize_runtime_database(Path(tmp) / "runtime.sqlite")
            access = self._record("access", "ACCESSNOW", "access.csv", "A-100", "2026-08-01T00:00:00+00:00")
            access.matched_worker_id = "worker-1"
            access.normalized_json = json.dumps({"accessnow_employee_id": "A-100", "accessnow_status": "TERMINATED", "terminated_date": "2026-08-03"})
            roster = self._record("roster", "ROSTER_LOCK", "roster.xlsx", "A-100", "2026-08-10T00:00:00+00:00")
            roster.matched_worker_id = "worker-1"
            roster.normalized_json = json.dumps({"vendor_employee_id": "A-100", "onboarding_date": "2026-08-10"})
            with orm_session(database) as session:
                session.add(WorkerModel(worker_id="worker-1", display_name="Ada Lovelace", status="TERMINATED"))
                session.add_all([access, roster])

            self.assertEqual(len(EmployeeService(database).rehire_alerts()), 1)

    def test_accessnow_status_normalization_preserves_deactivated(self):
        self.assertEqual(AccessNowIngestionService._normalize({"Employee Status": "DEACTIVATED"})["accessnow_status"], "DEACTIVATED")
        self.assertEqual(AccessNowIngestionService._worker_status({"accessnow_status": "DEACTIVATION"}), "DEACTIVATED")

    def test_accessnow_deactivated_status_updates_worker_and_engagement(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = initialize_runtime_database(Path(tmp) / "runtime.sqlite")
            record = self._record("access", "ACCESSNOW", "access.csv", "A-100", "2026-08-01T00:00:00+00:00")
            record.matched_worker_id = "worker-1"
            record.match_status = "MATCHED"
            record.normalized_json = json.dumps({
                "accessnow_employee_id": "A-100",
                "first_name": "Ada",
                "last_name": "Lovelace",
                "accessnow_status": "DEACTIVATED",
            })
            with orm_session(database) as session:
                session.add(WorkerModel(worker_id="worker-1", first_name="Ada", last_name="Lovelace", display_name="Ada Lovelace", status="ACTIVE"))
                session.add(record)

            result = AccessNowIngestionService(database).apply_approved_records(["access"], "qa")

            self.assertEqual(result["processed"], 1)
            with orm_session(database) as session:
                worker = session.get(WorkerModel, "worker-1")
                engagement = session.scalar(select(WorkerEngagementModel).where(WorkerEngagementModel.worker_id == "worker-1"))
                self.assertEqual(worker.status, "DEACTIVATED")
                self.assertEqual(engagement.status, "DEACTIVATED")

    def test_source_date_parser_accepts_accessnow_timestamp(self):
        self.assertEqual(parse_source_date("9/9/2025 6:7:0 AM PDT"), date(2025, 9, 9))
        self.assertEqual(parse_source_date("2026-08-03T20:14:31+00:00"), date(2026, 8, 3))
        self.assertIsNone(parse_source_date("not a date"))

    def _record(self, record_id: str, source: str, filename: str, key: str, created: str) -> IngestionRecordModel:
        payload = {"first_name": "Ada", "last_name": "Lovelace", "email": "ada@example.com", "vendor_employee_id": key}
        return IngestionRecordModel(
            record_id=record_id,
            batch_id=f"batch-{record_id}",
            source_system=source,
            source_file=f"/sharepoint/{filename}",
            source_checksum=f"checksum-{record_id}",
            row_number=2,
            source_record_key=key,
            normalized_json=json.dumps(payload),
            payload_json=json.dumps(payload),
            status="STAGED",
            match_status="UNMATCHED",
            created_at_utc=created,
        )

    def test_source_and_file_summaries_do_not_require_payload_deserialization(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = initialize_runtime_database(Path(tmp) / "runtime.sqlite")
            with orm_session(database) as session:
                session.add_all([
                    self._record("one", "ROSTER_LOCK", "roster-old.xlsx", "E-100", "2026-08-01T00:00:00+00:00"),
                    self._record("two", "ROSTER_LOCK", "roster-new.xlsx", "E-100", "2026-08-02T00:00:00+00:00"),
                    self._record("three", "ACCESSNOW", "access.csv", "A-100", "2026-08-03T00:00:00+00:00"),
                ])

            service = EmployeeService(database)
            sources = service.list_source_systems()
            files = service.list_source_files("ROSTER_LOCK")

            self.assertEqual({item["source_system"] for item in sources}, {"ROSTER_LOCK", "ACCESSNOW"})
            self.assertEqual(len(files), 2)
            self.assertEqual(sum(int(item["record_count"]) for item in files), 2)
            self.assertEqual(service.get_source_file_summary("ROSTER_LOCK", "roster-new.xlsx")["record_count"], 1)

    def test_source_rows_are_paginated_and_payload_is_loaded_only_for_page(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = initialize_runtime_database(Path(tmp) / "runtime.sqlite")
            with orm_session(database) as session:
                session.add_all([self._record(str(index), "ROSTER_LOCK", "roster.xlsx", f"E-{index}", f"2026-08-01T00:00:{index:02d}+00:00") for index in range(1, 121)])

            records, total = EmployeeService(database).list_source_records("ROSTER_LOCK", "roster.xlsx", page=3, per_page=50)

            self.assertEqual(total, 120)
            self.assertEqual(len(records), 20)
            self.assertEqual(len({record["source_record_key"] for record in records}), 20)
            self.assertIn("first_name", records[0]["payload"])

    def test_linking_newer_same_source_record_supersedes_previous_observation(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = initialize_runtime_database(Path(tmp) / "runtime.sqlite")
            with orm_session(database) as session:
                session.add(WorkerModel(worker_id="worker-1", first_name="Ada", last_name="Lovelace", display_name="Ada Lovelace", status="ACTIVE"))
                session.add_all([
                    self._record("old", "ROSTER_LOCK", "old.xlsx", "E-100", "2026-08-01T00:00:00+00:00"),
                    self._record("new", "ROSTER_LOCK", "new.xlsx", "E-100", "2026-08-02T00:00:00+00:00"),
                ])

            service = EmployeeService(database)
            service.link_source_record("old", "worker-1")
            service.link_source_record("new", "worker-1")
            with orm_session(database) as session:
                old = session.get(IngestionRecordModel, "old")
                new = session.get(IngestionRecordModel, "new")
                self.assertEqual(old.observation_state, "SUPERSEDED")
                self.assertEqual(old.superseded_by_record_id, "new")
                self.assertEqual(new.observation_state, "CURRENT")

    def test_cross_source_identifier_aliases_resolve_to_one_canonical_worker(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = initialize_runtime_database(Path(tmp) / "runtime.sqlite")
            with orm_session(database) as session:
                session.add(WorkerModel(worker_id="worker-1", first_name="Markisha", last_name="Tharp", display_name="Markisha Tharp", status="ACTIVE"))
                ensure_source_identifiers(session, "worker-1", "ACCESSNOW", {"accessnow_nuid": "L016524", "accessnow_employee_id": "34310430MT"}, "2026-08-04T00:00:00+00:00")
                matches, reason = find_worker_matches(session, "RSR_SUPPLIER_WORKER_DETAILS", {"buyer_reference": "L016524", "supplier_reference": "3431606", "first_name": "Markisha", "last_name": "Tharp"})
                self.assertEqual(matches, ["worker-1"])
                self.assertEqual(reason, "Exact source identifier match")
                ensure_source_identifiers(session, "worker-1", "RSR_SUPPLIER_WORKER_DETAILS", {"buyer_reference": "L016524", "supplier_reference": "3431606", "worker_id": "KAISWK00212840"}, "2026-08-04T00:00:00+00:00")
            with orm_session(database) as session:
                identifiers = session.scalars(select(WorkerIdentifierModel).where(WorkerIdentifierModel.worker_id == "worker-1")).all()
                self.assertEqual({item.source_system for item in identifiers}, {"ACCESSNOW", "RSR_SUPPLIER_WORKER_DETAILS"})

    def test_candidate_dossier_crosses_files_and_keeps_each_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = initialize_runtime_database(Path(tmp) / "runtime.sqlite")
            records = [
                self._record("roster", "ROSTER_LOCK", "roster.xlsx", "TTEC:3431606", "2026-08-01T00:00:00+00:00"),
                self._record("rsr", "RSR_SUPPLIER_WORKER_DETAILS", "rsr.xlsx", "3431606:181", "2026-08-02T00:00:00+00:00"),
                self._record("access", "ACCESSNOW", "access.csv", "34310430MT", "2026-08-03T00:00:00+00:00"),
            ]
            records[0].normalized_json = json.dumps({"first_name": "Markisha", "last_name": "Tharp", "vendor_employee_id": "3431606", "job_title": "Trainer"})
            records[1].normalized_json = json.dumps({"first_name": "Markisha", "last_name": "Tharp", "supplier_reference": "3431606", "worker_id": "KAISWK00212840", "sow_worker_role": "Licensed Agent ENG"})
            records[2].normalized_json = json.dumps({"first_name": "Markisha", "last_name": "Tharp", "accessnow_employee_id": "34310430MT", "accessnow_nuid": "L016524", "accessnow_status": "ACTIVE"})
            with orm_session(database) as session:
                session.add_all(records)
            service = EmployeeService(database)
            dossier = service.source_candidate_preview("rsr")
            self.assertEqual(dossier["source_count"], 3)
            self.assertEqual(dossier["file_count"], 3)
            self.assertEqual({row["record_id"] for row in dossier["records"]}, {"roster", "rsr", "access"})
            self.assertTrue(any("KAISWK00212840" in row["payload"].values() for row in dossier["records"]))
            self.assertEqual(len(service.search_source_people("Markisha")), 1)

    def test_candidate_preparation_assigns_one_worker_to_all_source_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = initialize_runtime_database(Path(tmp) / "runtime.sqlite")
            records = [
                self._record("one", "ACCESSNOW", "access.csv", "A-100", "2026-08-01T00:00:00+00:00"),
                self._record("two", "RSR_SUPPLIER_WORKER_DETAILS", "rsr.xlsx", "R-100", "2026-08-02T00:00:00+00:00"),
                self._record("three", "ROSTER_LOCK", "roster.xlsx", "V-100", "2026-08-03T00:00:00+00:00"),
            ]
            with orm_session(database) as session:
                session.add_all(records)
            service = EmployeeService(database)
            result = service.prepare_source_candidate(["one", "two", "three"], "qa")
            self.assertTrue(result["created"])
            with orm_session(database) as session:
                linked = session.scalars(select(IngestionRecordModel.matched_worker_id).where(IngestionRecordModel.record_id.in_(["one", "two", "three"]))).all()
                self.assertEqual(set(linked), {result["worker_id"]})
                self.assertEqual(session.query(WorkerModel).count(), 1)

    def test_list_source_people_groups_all_files_by_person(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = initialize_runtime_database(Path(tmp) / "runtime.sqlite")
            one = self._record("one", "ACCESSNOW", "access.csv", "A-100", "2026-08-01T00:00:00+00:00")
            two = self._record("two", "RSR_SUPPLIER_WORKER_DETAILS", "rsr.xlsx", "R-100", "2026-08-02T00:00:00+00:00")
            three = self._record("three", "ROSTER_LOCK", "roster.xlsx", "V-200", "2026-08-03T00:00:00+00:00")
            with orm_session(database) as session:
                session.add_all([one, two, three])
            people = EmployeeService(database).list_source_people()
            self.assertEqual(len(people), 1)
            self.assertEqual(people[0]["record_count"], 3)
            self.assertEqual(people[0]["source_count"], 3)

    def test_create_all_source_candidates_creates_one_worker_for_all_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = initialize_runtime_database(Path(tmp) / "runtime.sqlite")
            records = [
                self._record("access", "ACCESSNOW", "access.csv", "A-100", "2026-08-01T00:00:00+00:00"),
                self._record("rsr", "RSR_SUPPLIER_WORKER_DETAILS", "rsr.xlsx", "R-100", "2026-08-02T00:00:00+00:00"),
                self._record("roster", "ROSTER_LOCK", "roster.xlsx", "V-100", "2026-08-03T00:00:00+00:00"),
            ]
            with orm_session(database) as session:
                session.add_all(records)
            result = EmployeeService(database).create_all_source_candidates("admin")
            self.assertEqual(result["created"], 1)
            self.assertEqual(result["processed"], 3)
            with orm_session(database) as session:
                self.assertEqual(session.query(WorkerModel).count(), 1)
                self.assertEqual(session.query(IngestionRecordModel).filter(IngestionRecordModel.matched_worker_id.is_not(None)).count(), 3)

    def test_roster_lock_raises_rehire_alert_for_recent_accessnow_termination(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = initialize_runtime_database(Path(tmp) / "runtime.sqlite")
            access = self._record("access", "ACCESSNOW", "access.csv", "A-100", "2026-08-01T00:00:00+00:00")
            access.matched_worker_id = "worker-1"
            access.status = "APPLIED"
            access.normalized_json = json.dumps({"accessnow_employee_id": "A-100", "first_name": "Ada", "last_name": "Lovelace", "accessnow_status": "TERMINATED", "terminated_date": "8/3/2026 6:7:0 AM PDT"})
            roster = self._record("roster", "ROSTER_LOCK", "roster.xlsx", "A-100", "2026-08-10T00:00:00+00:00")
            roster.matched_worker_id = "worker-1"
            roster.normalized_json = json.dumps({"vendor_employee_id": "A-100", "first_name": "Ada", "last_name": "Lovelace", "onboarding_date": "2026-08-10"})
            with orm_session(database) as session:
                session.add(WorkerModel(worker_id="worker-1", first_name="Ada", last_name="Lovelace", display_name="Ada Lovelace", status="TERMINATED"))
                session.add_all([access, roster])

            alerts = EmployeeService(database).rehire_alerts()

            self.assertEqual(len(alerts), 1)
            self.assertEqual(alerts[0]["status"], "TERMINATED")
            self.assertEqual(alerts[0]["business_days_elapsed"], 5)
            self.assertEqual(alerts[0]["business_days_remaining"], 25)

            result = EmployeeService(database).resolve_rehire_alert("roster", "admin", "Reviewed by management")
            self.assertEqual(result["status"], "RESOLVED")
            self.assertEqual(EmployeeService(database).rehire_alerts(), [])
            with orm_session(database) as session:
                self.assertEqual(session.get(WorkerModel, "worker-1").status, "TERMINATED")
                self.assertEqual(session.get(IngestionRecordModel, "roster").observation_state, "RESOLVED")

    def test_rehire_business_days_exclude_configured_holidays(self):
        with patch.dict(os.environ, {"REHIRE_HOLIDAYS": "2026-07-06"}):
            elapsed = EmployeeService._business_days_between(date(2026, 7, 3), date(2026, 7, 7))

        self.assertEqual(elapsed, 1)


if __name__ == "__main__":
    unittest.main()

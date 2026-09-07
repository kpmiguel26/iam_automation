"""
File: tests/test_worker_history.py
Purpose: Provides automated regression tests for test worker history.
Responsibilities: Exposes or coordinates: WorkerHistoryTests.
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
import uuid
from pathlib import Path

from iam_automation.application.employee_service import EmployeeService
from iam_automation.application.worker_history_service import backfill_missing_worker_versions, record_worker_version
from iam_automation.database.runtime_schema import initialize_runtime_database
from iam_automation.infrastructure.sqlite.orm import FactWorkerFieldHistoryModel, WorkerDiscrepancyModel, WorkerMergeEventModel, WorkerModel, WorkerProfileVersionModel, orm_session


class WorkerHistoryTests(unittest.TestCase):
    def _worker(self, worker_id: str, first_name: str) -> WorkerModel:
        return WorkerModel(
            worker_id=worker_id,
            first_name=first_name,
            last_name="Worker",
            display_name=f"{first_name} Worker",
            canonical_email=f"{first_name.lower()}@example.com",
            status="ACTIVE",
            record_version=1,
            created_at_utc="2026-07-31T00:00:00+00:00",
            updated_at_utc="2026-07-31T00:00:00+00:00",
        )

    def test_existing_worker_gets_idempotent_baseline_and_changes_append_versions(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = initialize_runtime_database(Path(tmp) / "runtime.sqlite")
            worker_id = str(uuid.uuid4())
            with orm_session(database) as session:
                session.add(self._worker(worker_id, "Ada"))

            self.assertEqual(backfill_missing_worker_versions(database), 1)
            self.assertEqual(backfill_missing_worker_versions(database), 0)
            with orm_session(database) as session:
                worker = session.get(WorkerModel, worker_id)
                worker.first_name = "Grace"
                worker.display_name = "Grace Worker"
                record_worker_version(session, worker_id, actor="admin", change_type="ADMIN_UPDATE", changed_fields=["first_name", "display_name"])

                versions = session.query(WorkerProfileVersionModel).filter_by(worker_id=worker_id).order_by(WorkerProfileVersionModel.version_number).all()
                self.assertEqual([item.version_number for item in versions], [1, 2])
                self.assertEqual(versions[0].snapshot_json, "")
                self.assertEqual(versions[1].snapshot_json, "")
                history = session.query(FactWorkerFieldHistoryModel).filter_by(worker_id=worker_id).all()
                values = {(item.version_number, item.field_key): item.value_text for item in history}
                self.assertEqual(values[(1, "first_name")], "Ada")
                self.assertEqual(values[(2, "first_name")], "Grace")
                self.assertEqual(worker.record_version, 2)

    def test_merge_preserves_duplicate_as_superseded_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = initialize_runtime_database(Path(tmp) / "runtime.sqlite")
            survivor_id, duplicate_id = str(uuid.uuid4()), str(uuid.uuid4())
            with orm_session(database) as session:
                session.add(self._worker(survivor_id, "Ada"))
                session.add(self._worker(duplicate_id, "Ada"))

            result = EmployeeService(database).merge_workers(survivor_id, duplicate_id, "Same person imported from two sources", "admin")
            self.assertEqual(result["survivor_worker_id"], survivor_id)
            with orm_session(database) as session:
                duplicate = session.get(WorkerModel, duplicate_id)
                self.assertEqual(duplicate.status, "DUPLICATE_SUPERSEDED")
                self.assertEqual(duplicate.superseded_by_worker_id, survivor_id)
                self.assertEqual(session.query(WorkerMergeEventModel).count(), 1)
                self.assertEqual(session.query(WorkerProfileVersionModel).filter_by(worker_id=survivor_id).count(), 1)
                self.assertEqual(session.query(WorkerProfileVersionModel).filter_by(worker_id=duplicate_id).count(), 1)

            active, total = EmployeeService(database).list_workers_page(page=1, per_page=25)
            self.assertEqual(total, 1)
            self.assertEqual(active[0].worker_id, survivor_id)

    def test_merge_fills_missing_profile_values_and_records_conflicts(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = initialize_runtime_database(Path(tmp) / "runtime.sqlite")
            survivor_id, duplicate_id = str(uuid.uuid4()), str(uuid.uuid4())
            with orm_session(database) as session:
                survivor = self._worker(survivor_id, "Ada")
                survivor.last_name = ""
                survivor.canonical_email = ""
                survivor.display_name = "Ada"
                duplicate = self._worker(duplicate_id, "Ada")
                duplicate.last_name = "Lovelace"
                duplicate.display_name = "Ada Lovelace"
                duplicate.canonical_email = "ada.lovelace@example.com"
                session.add_all([survivor, duplicate])

            EmployeeService(database).merge_workers(survivor_id, duplicate_id, "Same person confirmed", "admin")

            with orm_session(database) as session:
                survivor = session.get(WorkerModel, survivor_id)
                self.assertEqual(survivor.last_name, "Lovelace")
                self.assertEqual(survivor.canonical_email, "ada.lovelace@example.com")
                self.assertEqual(survivor.display_name, "Ada Lovelace")
                self.assertEqual(session.query(WorkerDiscrepancyModel).filter_by(worker_id=survivor_id).count(), 0)

                conflicting_id = str(uuid.uuid4())
                conflicting = self._worker(conflicting_id, "Ada")
                conflicting.canonical_email = "different@example.com"
                session.add(conflicting)

            EmployeeService(database).merge_workers(survivor_id, conflicting_id, "Same person confirmed", "admin")
            with orm_session(database) as session:
                survivor = session.get(WorkerModel, survivor_id)
                self.assertEqual(survivor.canonical_email, "ada.lovelace@example.com")
                discrepancy = session.query(WorkerDiscrepancyModel).filter_by(worker_id=survivor_id, field_name="canonical_email").one()
                self.assertEqual(discrepancy.current_value, "ada.lovelace@example.com")
                self.assertEqual(discrepancy.incoming_value, "different@example.com")

    def test_duplicate_merge_plan_selects_most_complete_profile(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = initialize_runtime_database(Path(tmp) / "runtime.sqlite")
            sparse_id, complete_id = str(uuid.uuid4()), str(uuid.uuid4())
            with orm_session(database) as session:
                sparse = self._worker(sparse_id, "Ada")
                sparse.canonical_email = ""
                sparse.created_at_utc = "2026-07-30T00:00:00+00:00"
                complete = self._worker(complete_id, "Ada")
                complete.canonical_email = "ada.lovelace@example.com"
                complete.status = "INACTIVE"
                complete.created_at_utc = "2026-08-01T00:00:00+00:00"
                session.add_all([sparse, complete])

            plan = EmployeeService(database).canonical_duplicate_merge_plan(sparse_id)
            self.assertIsNotNone(plan)
            self.assertEqual(plan["survivor"]["worker_id"], sparse_id)
            self.assertEqual(plan["duplicates"][0]["worker_id"], complete_id)
            self.assertEqual(plan["selection_reason"], "oldest_canonical_identity")
            self.assertEqual([item["field"] for item in plan["conflicts"]], ["Status"])


if __name__ == "__main__":
    unittest.main()
#endfile
